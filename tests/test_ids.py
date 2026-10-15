from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from labbrain.ids import IdError, is_valid_id, new_id, protocol_version, slugify

NOW = datetime(2026, 10, 13, 14, 20)


def touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n---\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Label smoothing vs. calibration", "label-smoothing-vs-calibration"),
        ("  Curriculum -- by   length!! ", "curriculum-by-length"),
        ("Müller–Ångström", "muller-angstrom"),
        ("straße", "strae"),
        ("李明", "untitled"),
        ("", "untitled"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_slugify_truncates_at_word_boundary() -> None:
    slug = slugify("a very long title about tempered decoding in sequence models today")
    assert slug == "a-very-long-title-about-tempered"


def test_dated_ids(tmp_path: Path) -> None:
    def mint(t: str, title: str) -> str:
        return new_id(t, root=tmp_path, now=NOW, title=title)

    assert mint("experiment", "Label smoothing") == "EXP-20261013-label-smoothing"
    assert mint("claim", "Median AUROC") == "CLM-20261013-median-auroc"
    assert mint("idea", "Curriculum by length") == "IDEA-20261013-curriculum-by-length"
    assert mint("decision", "Tracker choice") == "ADR-20261013-tracker-choice"
    assert mint("dataset", "Main split") == "DS-20261013-main-split"


def test_collision_scans_every_note_folder(tmp_path: Path) -> None:
    touch(tmp_path, "experiments/EXP-20261013-label-smoothing.md")
    touch(tmp_path, "ideas/archive/EXP-20261013-label-smoothing-2.md")
    got = new_id("experiment", root=tmp_path, now=NOW, title="Label smoothing")
    assert got == "EXP-20261013-label-smoothing-3"


def test_collision_suffix_respects_slug_max(tmp_path: Path) -> None:
    slug = "abcdefghij-abcdefghij-abcdefghij-abcdefg"
    assert len(slug) == 40
    touch(tmp_path, f"experiments/EXP-20261013-{slug}.md")
    got = new_id("experiment", root=tmp_path, now=NOW, title=slug)
    assert got == "EXP-20261013-abcdefghij-abcdefghij-abcdefghij-2"
    assert is_valid_id(got, "experiment")


def test_protocol_numbering(tmp_path: Path) -> None:
    assert new_id("protocol", root=tmp_path, now=NOW) == "EVAL-v1"
    touch(tmp_path, "protocols/EVAL-v1.md")
    touch(tmp_path, "protocols/EVAL-v3-masked.md")
    assert new_id("protocol", root=tmp_path, now=NOW) == "EVAL-v4"
    assert new_id("protocol", root=tmp_path, now=NOW, name="Masked AUROC") == "EVAL-v4-masked-auroc"
    assert protocol_version("EVAL-v3-masked") == 3
    assert protocol_version("EXP-20261013-x") is None


def test_literature_ids(tmp_path: Path) -> None:
    got = new_id(
        "literature",
        root=tmp_path,
        now=NOW,
        title="Attention Is All You Need",
        first_author="Vaswani",
        year=2017,
    )
    assert got == "LIT-vaswani2017-attention"
    got = new_id(
        "literature",
        root=tmp_path,
        now=NOW,
        title="On the Rethinking of X",
        first_author="van der Waals",
        year=2016,
    )
    assert got == "LIT-vanderwaals2016-rethinking"
    with pytest.raises(IdError):
        new_id("literature", root=tmp_path, now=NOW, title="x", first_author="a")


def test_handoff_and_concept_ids(tmp_path: Path) -> None:
    assert new_id("handoff", root=tmp_path, now=NOW, agent="claude") == "HO-20261013-1420-claude"
    assert (
        new_id("concept", root=tmp_path, now=NOW, title="Tempered decoding") == "tempered-decoding"
    )


def test_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(IdError):
        new_id("memo", root=tmp_path, now=NOW, title="x")


@pytest.mark.parametrize(
    ("note_id", "note_type", "ok"),
    [
        ("EXP-20261013-label-smoothing", "experiment", True),
        ("EXP-2026101-label", "experiment", False),
        ("EXP-20261013-Label", "experiment", False),
        ("EVAL-v3", "protocol", True),
        ("EVAL-v3-masked", "protocol", True),
        ("EVAL-v0", "protocol", False),
        ("LIT-vaswani2017-attention", "literature", True),
        ("LIT-vaswani17-attention", "literature", False),
        ("HO-20261013-1420-claude", "handoff", True),
        ("tempered-decoding", "concept", True),
        ("Tempered", "concept", False),
        ("DS-20260801-main-split", "dataset", True),
        ("EXP-20261013-" + "a" * 41, "experiment", False),
    ],
)
def test_is_valid_id(note_id: str, note_type: str, ok: bool) -> None:
    assert is_valid_id(note_id, note_type) is ok


def test_custom_prefixes() -> None:
    assert is_valid_id("RUN-20261013-x", "experiment", {"experiment": "RUN"})
    assert not is_valid_id("EXP-20261013-x", "experiment", {"experiment": "RUN"})
