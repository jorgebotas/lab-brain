"""ID formats, slugs and collision-safe ID minting.

IDs are date + slug, never counters, so two lab members on separate branches
cannot mint the same ID. The one exception is protocol versions (EVAL-v<N>),
which are created rarely and by hand; a clash is caught by the duplicate-ID check.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from labbrain.layout import iter_note_files

SLUG_MAX = 40
SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
DEFAULT_PREFIXES: dict[str, str] = {
    "experiment": "EXP",
    "protocol": "EVAL",
    "claim": "CLM",
    "idea": "IDEA",
    "decision": "ADR",
    "literature": "LIT",
    "handoff": "HO",
    "dataset": "DS",
}
DATED_TYPES: frozenset[str] = frozenset({"experiment", "claim", "idea", "decision", "dataset"})
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "on",
        "of",
        "for",
        "in",
        "to",
        "and",
        "with",
        "via",
        "towards",
        "toward",
        "is",
        "are",
        "from",
        "by",
        "at",
    }
)


class IdError(ValueError):
    """An ID cannot be minted from the given inputs."""


def slugify(text: str, max_len: int = SLUG_MAX, fallback: str = "untitled") -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(_fold_char(ch) for ch in decomposed)
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return _truncate(slug, max_len) or fallback


def _fold_char(ch: str) -> str:
    """ASCII stays; non-ASCII marks, letters and digits drop; anything else separates."""
    if ch.isascii():
        return ch
    if unicodedata.category(ch)[0] in "MLN":
        return ""
    return "-"


def _truncate(slug: str, max_len: int) -> str:
    if len(slug) <= max_len:
        return slug
    cut = slug[:max_len]
    if slug[max_len] != "-" and "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-")


def _prefixes(prefixes: Mapping[str, str] | None) -> dict[str, str]:
    return {**DEFAULT_PREFIXES, **(prefixes or {})}


def id_regex(note_type: str, prefixes: Mapping[str, str] | None = None) -> re.Pattern[str]:
    slug = f"(?P<slug>{SLUG_PATTERN})"
    if note_type == "concept":
        return re.compile(rf"\A{slug}\Z")
    try:
        p = re.escape(_prefixes(prefixes)[note_type])
    except KeyError as exc:
        raise IdError(f"unknown note type: {note_type}") from exc
    if note_type in DATED_TYPES:
        pattern = rf"{p}-\d{{8}}-{slug}"
    elif note_type == "protocol":
        pattern = rf"{p}-v[1-9]\d*(?:-{slug})?"
    elif note_type == "literature":
        pattern = rf"{p}-[a-z]+\d{{4}}-{slug}"
    else:  # handoff
        pattern = rf"{p}-\d{{8}}-\d{{4}}-{slug}"
    return re.compile(rf"\A{pattern}\Z")


def is_valid_id(note_id: str, note_type: str, prefixes: Mapping[str, str] | None = None) -> bool:
    match = id_regex(note_type, prefixes).match(note_id)
    return match is not None and len(match.group("slug") or "") <= SLUG_MAX


def existing_ids(root: Path) -> set[str]:
    """Filename stems of every note in the working tree, tracked or not."""
    return {path.stem for path in iter_note_files(root)}


def protocol_version(note_id: str, prefixes: Mapping[str, str] | None = None) -> int | None:
    prefix = re.escape(_prefixes(prefixes)["protocol"])
    match = re.match(rf"\A{prefix}-v([1-9]\d*)(?:-|\Z)", note_id)
    return int(match.group(1)) if match else None


def new_id(
    note_type: str,
    *,
    root: Path,
    now: datetime,
    title: str = "",
    prefixes: Mapping[str, str] | None = None,
    agent: str = "",
    first_author: str = "",
    year: int | None = None,
    name: str = "",
) -> str:
    pre = _prefixes(prefixes)
    taken = existing_ids(root)
    if note_type in DATED_TYPES:
        stamp = now.strftime("%Y%m%d")
        return _first_free(lambda s: f"{pre[note_type]}-{stamp}-{s}", slugify(title), taken)
    if note_type == "protocol":
        return _next_protocol(pre["protocol"], taken, name, prefixes)
    if note_type == "literature":
        if year is None or not 1000 <= year <= 9999:
            raise IdError("literature IDs need a four-digit year")
        author = re.sub(r"[^a-z]", "", slugify(first_author, fallback="")) or "anon"
        word = _first_significant_word(title)
        return _first_free(lambda s: f"{pre['literature']}-{author}{year}-{s}", word, taken)
    if note_type == "handoff":
        stamp = now.strftime("%Y%m%d-%H%M")
        agent_slug = slugify(agent, fallback="agent")
        return _first_free(lambda s: f"{pre['handoff']}-{stamp}-{s}", agent_slug, taken)
    if note_type == "concept":
        return _first_free(lambda s: s, slugify(title), taken)
    raise IdError(f"unknown note type: {note_type}")


def _first_significant_word(title: str) -> str:
    for word in slugify(title, max_len=10_000, fallback="").split("-"):
        if word and word not in _STOPWORDS:
            return word[:SLUG_MAX]
    return "untitled"


def _first_free(compose: Callable[[str], str], slug: str, taken: set[str]) -> str:
    candidate = compose(slug)
    k = 2
    while candidate in taken:
        suffix = f"-{k}"
        candidate = compose(_truncate(slug, SLUG_MAX - len(suffix)) + suffix)
        k += 1
    return candidate


def _next_protocol(
    prefix: str, taken: set[str], name: str, prefixes: Mapping[str, str] | None
) -> str:
    numbers = [n for t in taken if (n := protocol_version(t, prefixes)) is not None]
    base = f"{prefix}-v{max(numbers, default=0) + 1}"
    if not name:
        return base
    return _first_free(lambda s: f"{base}-{s}", slugify(name), taken)
