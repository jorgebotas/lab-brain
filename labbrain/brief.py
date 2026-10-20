"""`labbrain brief`: recent handoffs, open work and vault health in a few lines.

Prints note IDs and titles (what index.md already holds), never body text. Titles pass
through `findings.sanitize`, so PHI-shaped text in a title (digit runs, SSNs, phone numbers,
emails) is redacted: the brief also feeds the SessionStart hook's session context.
"""

from __future__ import annotations

from labbrain import __version__
from labbrain.findings import ERROR, WARNING, Finding, sanitize, strip_controls
from labbrain.notes import Note
from labbrain.vault import Vault

HANDOFF_LIMIT = 3
LIST_LIMIT = 5


def _clean(text: str) -> str:
    return " ".join(strip_controls(text).split())


def _title(note: Note) -> str:
    return sanitize(note.get_str("title") or "")


def _row(note: Note) -> str:
    return f"  {_clean(note.stem)}  {_title(note)}"


def _newest(notes: list[Note]) -> list[Note]:
    return sorted(notes, key=lambda n: n.stem, reverse=True)


def _with_status(vault: Vault, note_type: str, status: str) -> list[Note]:
    return _newest([n for n in vault.of_type(note_type) if n.get_str("status") == status])


def _listing(notes: list[Note], limit: int) -> list[str]:
    if not notes:
        return ["  none"]
    rows = [_row(n) for n in notes[:limit]]
    if len(notes) > limit:
        rows.append(f"  … and {len(notes) - limit} more")
    return rows


def build_brief(vault: Vault, findings: list[Finding], *, short: bool, warning: str | None) -> str:
    head = [f"{_clean(vault.config.project_name)} · engine {__version__}"]
    if warning:
        head.append(f"warning: {_clean(warning)}")
    handoffs = _newest(vault.of_type("handoff"))
    running = _with_status(vault, "experiment", "running")
    planned = _with_status(vault, "experiment", "planned")
    stale = _with_status(vault, "claim", "stale")
    open_ideas = len(_with_status(vault, "idea", "open"))
    errors = sum(1 for f in findings if f.severity == ERROR)
    warnings = sum(1 for f in findings if f.severity == WARNING)
    if short:
        last = f"{_clean(handoffs[0].stem)}  {_title(handoffs[0])}" if handoffs else "none"
        counts = (
            f"Running {len(running)} · Planned {len(planned)} · Stale claims {len(stale)}"
            f" · Open ideas {open_ideas} · Lint errors {errors}"
        )
        return "\n".join([*head, f"Last handoff: {last}", counts]) + "\n"
    lines = [*head, "", "Recent handoffs:"]
    lines += [_row(n) for n in handoffs[:HANDOFF_LIMIT]] or ["  none"]
    lines.append("")
    for label, notes in (
        ("Experiments running", running),
        ("Experiments planned", planned),
        ("Stale claims", stale),
    ):
        lines += [f"{label} ({len(notes)}):", *_listing(notes, LIST_LIMIT)]
    lines += ["", f"Open ideas: {open_ideas} · Lint: {errors} errors, {warnings} warnings"]
    return "\n".join(lines) + "\n"
