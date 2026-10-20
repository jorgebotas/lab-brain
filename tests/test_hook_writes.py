"""PreToolUse write checks: the frozen-file guard and the PHI pre-write scan."""

from __future__ import annotations

import json
import secrets
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from helpers import MIN_CONFIG, commit_all, git, hook_payload, make_vault, note_text, write

from labbrain.hooks import writes
from labbrain.hooks.entry import run_hook
from labbrain.hooks.payload import Denial, parse_payload
from labbrain.hooks.scope import load_scope
from labbrain.phi import line_hash

DONE = "EXP-20261001-done"
DONE_REL = f"experiments/{DONE}.md"
PROTOCOL = "EVAL-draft"
PROTOCOL_REL = f"protocols/{PROTOCOL}.md"
LOOSE = "EVAL-loose"
LOOSE_REL = f"protocols/{LOOSE}.md"
HANDOFF = "HO-20261001-1200-claude"
HANDOFF_REL = f"handoffs/{HANDOFF}.md"
CLAIM = "CLM-20261001-claim"
CLAIM_REL = f"claims/{CLAIM}.md"
RAW_REL = "raw/papers/a.txt"

CANNOT_APPLY = (
    "lab-brain frozen-file guard: could not apply this edit to a protected file; "
    "re-read the file and retry."
)
MANUSCRIPTS = (
    "lab-brain frozen-file guard: manuscripts are edited through proposals; "
    "write under manuscripts/_proposals/ instead."
)
RAW = "lab-brain frozen-file guard: raw/ files are immutable once written; add a new file instead."
BODY_REWRITE = "existing body lines were modified or deleted; only insertions are allowed"
DONE_BODY = "## Plan\n\nPlan.\n\n## Results\n\nDone on 2026-10-01.\n"


def frozen_message(rel: str, note_type: str, *messages: str) -> str:
    return (
        f"lab-brain frozen-file guard: {rel} is a frozen {note_type}; this edit is not "
        f"allowed: {'; '.join(messages)}. Supersede the note instead, or change only the "
        "allowed fields."
    )


def phi_message(rel: str, rules: str, lines: str) -> str:
    return (
        f"lab-brain PHI guard: the proposed content of {rel} matched {rules} (lines {lines}). "
        "Remove individual-level data before writing."
    )


def done_text(**fields: Any) -> str:
    fields.setdefault("status", "done")
    fields.setdefault("protocol", PROTOCOL)
    fields.setdefault("created", date(2026, 9, 1))
    return note_text(DONE, "experiment", fields.pop("body", DONE_BODY), **fields)


def handoff_text(**fields: Any) -> str:
    fields.setdefault("session_goal", "goal")
    return note_text(HANDOFF, "handoff", **fields)


def build_vault(tmp_path: Path, config: str = MIN_CONFIG, *, commit: bool = True) -> Path:
    """A vault with a done experiment, the draft protocol it uses, an unreferenced draft
    protocol, a handoff, a draft claim and a raw file; committed unless `commit` is off."""
    v = make_vault(tmp_path / "v", config)
    write(v, DONE_REL, done_text())
    write(v, PROTOCOL_REL, note_text(PROTOCOL, "protocol", status="draft"))
    write(v, LOOSE_REL, note_text(LOOSE, "protocol", status="draft"))
    write(v, HANDOFF_REL, handoff_text())
    write(v, CLAIM_REL, note_text(CLAIM, "claim"))
    write(v, RAW_REL, "paper\n")
    if commit:
        git(v, "init", "-q", "-b", "main")
        commit_all(v)
    return v


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return build_vault(tmp_path)


def env_for(tmp_path: Path) -> dict[str, str]:
    return {"HOME": str(tmp_path / "home")}


def check(v: Path, data: bytes) -> Denial | None:
    return writes.check_write(parse_payload(data), load_scope(v, env_for(v.parent)))


def write_call(v: Path, rel: str, content: str) -> Denial | None:
    return check(v, hook_payload("write", cwd=v, path=v / rel, content=content))


def call(v: Path, tool_name: str, tool_input: dict[str, Any]) -> Denial | None:
    return check(v, hook_payload("edit", cwd=v, tool_name=tool_name, tool_input=tool_input))


def edit_call(v: Path, rel: str, old: str, new: str, *, replace_all: bool = False) -> Denial | None:
    tool_input = {
        "file_path": str(v / rel),
        "old_string": old,
        "new_string": new,
        "replace_all": replace_all,
    }
    return call(v, "Edit", tool_input)


def denied(denial: Denial | None, rule: str, message: str) -> None:
    assert denial is not None
    assert (denial.rule, denial.message) == (rule, message)


# --- frozen notes ---------------------------------------------------------------------


def test_done_experiment_body_rewrite_denied(vault: Path) -> None:
    proposed = done_text().replace("Done on 2026-10-01.", "Rewritten.")
    denied(
        write_call(vault, DONE_REL, proposed),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", BODY_REWRITE),
    )


def test_done_experiment_append_allowed(vault: Path) -> None:
    assert write_call(vault, DONE_REL, done_text() + "\n## Addendum\n\nMore.\n") is None
    assert edit_call(vault, DONE_REL, "Plan.\n", "Plan.\n\nAn inserted line.\n") is None


def test_done_experiment_status_to_superseded_allowed(vault: Path) -> None:
    proposed = done_text(
        status="superseded", superseded_by="EXP-20261002-next", updated=date(2026, 10, 2)
    )
    assert write_call(vault, DONE_REL, proposed) is None


def test_done_experiment_field_change_denied(vault: Path) -> None:
    denied(
        write_call(vault, DONE_REL, done_text(title="Another title")),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", "frozen field 'title' changed"),
    )


def test_disallowed_status_transition_denied(vault: Path) -> None:
    denied(
        edit_call(vault, DONE_REL, "status: done", "status: running"),
        "frozen-file",
        frozen_message(
            DONE_REL,
            "experiment",
            "status change done → running is not allowed on a frozen experiment",
        ),
    )


def test_handoff_committed_frozen_on_existence(vault: Path) -> None:
    denied(
        edit_call(vault, HANDOFF_REL, "session_goal: goal", "session_goal: other"),
        "frozen-file",
        frozen_message(HANDOFF_REL, "handoff", "frozen field 'session_goal' changed"),
    )


def test_uncommitted_new_handoff_editable(vault: Path) -> None:
    # The skills' flow: `labbrain new` writes the note, then the agent fills in fields.
    rel = "handoffs/HO-20261020-0900-claude.md"
    write(vault, rel, note_text("HO-20261020-0900-claude", "handoff", session_goal="TBD"))
    assert edit_call(vault, rel, "session_goal: TBD", "session_goal: the real goal") is None
    assert write_call(vault, rel, "rewritten entirely\n") is None


def test_protocol_referenced_by_done_experiment_frozen(vault: Path) -> None:
    denied(
        edit_call(vault, PROTOCOL_REL, f"title: {PROTOCOL}", "title: changed"),
        "frozen-file",
        frozen_message(PROTOCOL_REL, "protocol", "frozen field 'title' changed"),
    )
    # A draft protocol that no done experiment uses stays editable.
    assert edit_call(vault, LOOSE_REL, f"title: {LOOSE}", "title: changed") is None


def test_moved_frozen_note_found_by_id(vault: Path) -> None:
    moved = f"experiments/archive/{DONE}.md"
    (vault / moved).parent.mkdir()
    (vault / DONE_REL).rename(vault / moved)
    denied(
        write_call(vault, moved, done_text(title="Changed")),
        "frozen-file",
        frozen_message(moved, "experiment", "frozen field 'title' changed"),
    )


def test_edit_old_string_missing_on_frozen_denied(vault: Path) -> None:
    denied(edit_call(vault, DONE_REL, "not in the file", "x"), "frozen-file", CANNOT_APPLY)


def test_edit_old_string_missing_elsewhere_allowed(vault: Path) -> None:
    assert edit_call(vault, CLAIM_REL, "not in the file", "x") is None
    assert edit_call(vault, LOOSE_REL, "not in the file", "x") is None
    assert edit_call(vault, "notes/missing.md", "not in the file", "x") is None


def test_edit_unreadable_frozen_denied(vault: Path) -> None:
    (vault / DONE_REL).unlink()
    (vault / DONE_REL).mkdir()
    denied(edit_call(vault, DONE_REL, "status: done", "status: done"), "frozen-file", CANNOT_APPLY)


def test_replace_all_applied(vault: Path) -> None:
    # "2026-10-01" is in `updated` (mutable) first, then in a body line.
    assert edit_call(vault, DONE_REL, "2026-10-01", "2026-10-02") is None
    denied(
        edit_call(vault, DONE_REL, "2026-10-01", "2026-10-02", replace_all=True),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", BODY_REWRITE),
    )


def multi(v: Path, rel: str, *edits: tuple[str, str]) -> Denial | None:
    tool_input = {
        "file_path": str(v / rel),
        "edits": [{"old_string": old, "new_string": new} for old, new in edits],
    }
    return call(v, "MultiEdit", tool_input)


def test_multiedit_sequence_applied(vault: Path) -> None:
    # The second edit only matches once the first has been applied.
    first = ("status: done", "status: superseded")
    second = ("status: superseded", "status: superseded\nsuperseded_by: EXP-20261002-next")
    assert multi(vault, DONE_REL, first, second) is None
    denied(
        multi(vault, DONE_REL, first, (f"title: {DONE}", "title: changed")),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", "frozen field 'title' changed"),
    )
    denied(multi(vault, DONE_REL, second, first), "frozen-file", CANNOT_APPLY)
    denied(
        call(vault, "MultiEdit", {"file_path": str(vault / DONE_REL), "edits": "x"}),
        "frozen-file",
        CANNOT_APPLY,
    )


def test_edit_creating_a_file(vault: Path) -> None:
    assert edit_call(vault, "claims/CLM-20261020-new.md", "", "text\n") is None
    denied(edit_call(vault, DONE_REL, "", "x"), "frozen-file", CANNOT_APPLY)


def test_write_without_string_content_on_frozen_denied(vault: Path) -> None:
    tool_input = {"file_path": str(vault / DONE_REL), "content": 3}
    denied(call(vault, "Write", tool_input), "frozen-file", CANNOT_APPLY)


def test_frozen_unparseable_denied(vault: Path) -> None:
    denied(
        write_call(vault, DONE_REL, "no frontmatter at all\n"),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", "frozen note no longer parses"),
    )
    # A non-frozen note may be left unparseable; the post-write validator reports it.
    assert write_call(vault, CLAIM_REL, "no frontmatter at all\n") is None


def test_no_git_nothing_frozen(tmp_path: Path) -> None:
    v = build_vault(tmp_path, commit=False)
    assert write_call(v, DONE_REL, "rewritten\n") is None
    git(v, "init", "-q", "-b", "main")  # a repository without commits: still nothing frozen
    assert write_call(v, DONE_REL, "rewritten\n") is None
    denied(write_call(v, "manuscripts/paper.md", "x\n"), "frozen-file", MANUSCRIPTS)


def test_vault_in_repo_subfolder(tmp_path: Path) -> None:
    repo = tmp_path / "code"
    v = build_vault(repo, commit=False)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    denied(
        write_call(v, DONE_REL, done_text(title="Changed")),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", "frozen field 'title' changed"),
    )


# --- manuscripts and raw --------------------------------------------------------------


def test_manuscripts_outside_proposals_denied(vault: Path) -> None:
    denied(write_call(vault, "manuscripts/paper.md", "x\n"), "frozen-file", MANUSCRIPTS)
    denied(write_call(vault, "manuscripts/_proposals", "x\n"), "frozen-file", MANUSCRIPTS)
    denied(edit_call(vault, "manuscripts/a/b.tex", "x", "y"), "frozen-file", MANUSCRIPTS)


def test_manuscripts_proposals_allowed(vault: Path) -> None:
    assert write_call(vault, "manuscripts/_proposals/p.md", "x\n") is None
    assert write_call(vault, "notes/manuscripts/x.md", "x\n") is None


def test_raw_existing_denied(vault: Path) -> None:
    denied(write_call(vault, RAW_REL, "paper\n"), "frozen-file", RAW)
    denied(edit_call(vault, RAW_REL, "not there", "x"), "frozen-file", RAW)


def test_raw_new_allowed(vault: Path) -> None:
    assert write_call(vault, "raw/papers/b.txt", "new paper\n") is None
    assert write_call(vault, "raw/new/c.txt", "new paper\n") is None


def test_notebook_edit(vault: Path) -> None:
    write(vault, "raw/nb.ipynb", "{}")
    tool_input = {"notebook_path": str(vault / "raw/nb.ipynb"), "new_source": "x"}
    denied(call(vault, "NotebookEdit", tool_input), "frozen-file", RAW)
    tool_input = {"notebook_path": str(vault / "manuscripts/nb.ipynb"), "new_source": "x"}
    denied(call(vault, "NotebookEdit", tool_input), "frozen-file", MANUSCRIPTS)
    tool_input = {"notebook_path": str(vault / DONE_REL), "new_source": "x"}
    denied(call(vault, "NotebookEdit", tool_input), "frozen-file", CANNOT_APPLY)
    tool_input = {"notebook_path": str(vault / "analysis/nb.ipynb"), "new_source": "x"}
    assert call(vault, "NotebookEdit", tool_input) is None


def case_insensitive(directory: Path) -> bool:
    probe = directory / "case-probe"
    probe.write_text("")
    try:
        return (directory / "CASE-PROBE").exists()
    finally:
        probe.unlink()


def test_true_case_rel(vault: Path) -> None:
    insensitive = case_insensitive(vault)
    expected = DONE_REL if insensitive else f"Experiments/{DONE}.md"
    assert writes.vault_rel(vault, vault / f"Experiments/{DONE}.md") == expected
    expected = "raw/papers/NEW/x" if insensitive else "RAW/papers/NEW/x"
    assert writes.vault_rel(vault, vault / "RAW/papers/NEW/x") == expected
    assert writes.vault_rel(vault, vault / "missing/Dir/x.md") == "missing/Dir/x.md"
    assert writes.vault_rel(vault, vault / f"{DONE_REL}/below") == f"{DONE_REL}/below"


def test_fold_classification() -> None:
    assert writes.is_raw("RAW/x") and writes.is_raw("Raw/a/b") and not writes.is_raw("raws/x")
    assert writes.manuscript_outside_proposals("Manuscripts/x.md")
    assert writes.manuscript_outside_proposals("MANUSCRIPTS/_Proposals")
    assert not writes.manuscript_outside_proposals("Manuscripts/_PROPOSALS/x.md")
    assert not writes.manuscript_outside_proposals("notes/manuscripts/x.md")
    assert writes.note_like(f"Experiments/{DONE}.md")
    assert writes.note_like(DONE_REL)
    assert not writes.note_like("Experiments/x.txt")


def test_miscased_paths_guarded(vault: Path) -> None:
    # Fold logic alone: these hold on any filesystem.
    denied(write_call(vault, "Manuscripts/x.md", "x\n"), "frozen-file", MANUSCRIPTS)
    shown = writes.vault_rel(vault, vault / f"Experiments/{DONE}.md")
    denied(
        write_call(vault, f"Experiments/{DONE}.md", done_text(title="Changed")),
        "frozen-file",
        frozen_message(shown, "experiment", "frozen field 'title' changed"),
    )


@pytest.mark.skipif(
    not case_insensitive(Path(__file__).parent), reason="needs a case-insensitive filesystem"
)
def test_miscased_paths_guarded_on_disk(vault: Path) -> None:
    denied(write_call(vault, "RAW/papers/a.txt", "x\n"), "frozen-file", RAW)
    denied(
        edit_call(vault, f"EXPERIMENTS/{DONE}.md", "Done on", "Redone on"),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", BODY_REWRITE),
    )


def test_outside_vault_and_other_tools_ignored(tmp_path: Path, vault: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert write_call(outside, "manuscripts/x.md", "x\n") is None
    assert check(vault, hook_payload("read", cwd=vault, path=vault / RAW_REL)) is None
    assert call(vault, "Write", {"content": "x"}) is None


def test_relative_target_resolved_against_cwd(vault: Path) -> None:
    data = hook_payload("write", cwd=vault, path="manuscripts/x.md", content="x")
    denied(check(vault, data), "frozen-file", MANUSCRIPTS)


def test_target_vault_outside_scope(tmp_path: Path) -> None:
    v = build_vault(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    data = hook_payload("write", cwd=other, path=v / "manuscripts/x.md", content="x")
    denial = writes.check_write(parse_payload(data), load_scope(other, env_for(tmp_path)))
    denied(denial, "frozen-file", MANUSCRIPTS)
    data = hook_payload("write", cwd=other, path=v / CLAIM_REL, content="MRN 12345678\n")
    denial = writes.check_write(parse_payload(data), load_scope(other, env_for(tmp_path)))
    denied(denial, "phi", phi_message(CLAIM_REL, "phi-mrn", "1"))


# --- PHI pre-write scan ---------------------------------------------------------------


def mrn() -> str:
    return str(10**7 + secrets.randbelow(9 * 10**7))


def test_phi_prescan_existing_note_denied(vault: Path) -> None:
    anchor = "## History\n\nText."
    line = (vault / CLAIM_REL).read_text().splitlines().index("## History") + 4
    denied(
        edit_call(vault, CLAIM_REL, anchor, f"{anchor}\nMRN {mrn()}"),
        "phi",
        phi_message(CLAIM_REL, "phi-mrn", str(line)),
    )


def test_phi_prescan_new_file(vault: Path) -> None:
    # Review Focus 3: the target does not exist yet, and is denied before it lands.
    rel = "claims/CLM-20261020-new.md"
    assert not (vault / rel).exists()
    content = f"line one\nPatient MRN {mrn()}\ncall 713-555-0142\n"
    denied(write_call(vault, rel, content), "phi", phi_message(rel, "phi-mrn, phi-phone", "2, 3"))
    rel = "analysis/new/summary.md"
    denied(write_call(vault, rel, content), "phi", phi_message(rel, "phi-mrn, phi-phone", "2, 3"))
    # End to end, through the hook entry point.
    data = hook_payload("write", cwd=vault, path=vault / rel, content=f"MRN {mrn()}")
    code, out, err = run_hook("pre-tool-use", data, env_for(vault.parent))
    assert (code, out, err) == (2, "", phi_message(rel, "phi-mrn", "1"))
    assert not (vault / rel).exists()


def test_phi_out_of_scan_scope_skipped(vault: Path) -> None:
    assert write_call(vault, "scratch/x.md", f"MRN {mrn()}\n") is None
    assert write_call(vault, "index.md", f"MRN {mrn()}\n") is None


def test_phi_allowlisted_line_allowed(vault: Path) -> None:
    rel = "claims/CLM-20261020-new.md"
    line = f"MRN {mrn()}"
    entry = {
        "file": rel,
        "rule": "phi-mrn",
        "line_sha256": line_hash(line),
        "author": "alice",
        "date": "2026-10-20",
    }
    write(vault, ".labbrain/phi-allow.yaml", json.dumps([entry]))
    assert write_call(vault, rel, f"intro\n{line}\n") is None
    other = f"MRN {mrn()}"
    denied(
        write_call(vault, rel, f"intro\n{line}\n{other}\n"),
        "phi",
        phi_message(rel, "phi-mrn", "3"),
    )


def test_phi_unprotected_vault_skipped(tmp_path: Path) -> None:
    v = build_vault(tmp_path, MIN_CONFIG + "protected_data: false\n")
    assert write_call(v, "claims/CLM-20261020-new.md", f"MRN {mrn()}\n") is None


def test_phi_notebook_new_source_scanned(vault: Path) -> None:
    tool_input = {
        "notebook_path": str(vault / "analysis/nb.ipynb"),
        "new_source": f"print('x')\n# MRN {mrn()}",
    }
    denied(
        call(vault, "NotebookEdit", tool_input),
        "phi",
        phi_message("analysis/nb.ipynb", "phi-mrn", "2"),
    )


def test_phi_edit_not_computable_scans_new_strings(vault: Path) -> None:
    denied(
        edit_call(vault, CLAIM_REL, "not in the file", f"MRN {mrn()}"),
        "phi",
        phi_message(CLAIM_REL, "phi-mrn", "1"),
    )


def test_write_messages_never_leak(tmp_path: Path) -> None:
    title = "T" + secrets.token_hex(8)
    goal = "G" + secrets.token_hex(8)
    status = "S" + secrets.token_hex(8)
    key = "k" + secrets.token_hex(8)
    phi = mrn()
    v = build_vault(tmp_path)
    write(v, DONE_REL, done_text(title=title, **{key: title}))
    write(v, HANDOFF_REL, handoff_text(session_goal=goal))
    commit_all(v)
    messages = []
    for denial in (
        write_call(v, DONE_REL, done_text(title=title + "x", status=status, **{key: phi})),
        write_call(v, DONE_REL, done_text(title=title).replace("Done on", f"MRN {phi}")),
        edit_call(v, HANDOFF_REL, goal, goal + phi),
        edit_call(v, HANDOFF_REL, phi, goal),
        write_call(v, f"claims/{title}.md", f"MRN {phi}\n{goal}\n"),
        write_call(v, "manuscripts/x.md", f"{title} MRN {phi}\n"),
        write_call(v, RAW_REL, f"{title} MRN {phi}\n"),
    ):
        assert denial is not None
        messages.append(denial.message)
    assert "<invalid status>" in messages[0] and "<unknown field>" in messages[0]
    for message in messages:
        for sentinel in (goal, status, key, phi):
            assert sentinel not in message
    # The claim's file name is its ID, which may be named; the done note's title may not.
    assert all(title not in m for m in messages[:4] + messages[5:])


def test_symlinked_raw_dir_still_guarded(tmp_path: Path) -> None:
    v = build_vault(tmp_path)
    store = tmp_path / "store"
    store.mkdir()
    (store / "big.bin").write_text("data\n")
    (v / "raw" / "store").symlink_to(store, target_is_directory=True)
    denied(write_call(v, "raw/store/big.bin", "x\n"), "frozen-file", RAW)
    assert write_call(v, "raw/store/new.bin", "x\n") is None


def test_non_bool_replace_all_on_frozen_denied(vault: Path) -> None:
    tool_input = {
        "file_path": str(vault / DONE_REL),
        "old_string": "2026-10-01",
        "new_string": "2026-10-02",
        "replace_all": "false",
    }
    denied(call(vault, "Edit", tool_input), "frozen-file", CANNOT_APPLY)


def test_crlf_file_edited_as_lf(vault: Path) -> None:
    path = vault / DONE_REL
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert edit_call(vault, DONE_REL, "Plan.\r\n", "Plan.\r\nInserted.\r\n") is None
    denied(
        edit_call(vault, DONE_REL, "Plan.\r\n", "Replanned.\r\n"),
        "frozen-file",
        frozen_message(DONE_REL, "experiment", BODY_REWRITE),
    )


def test_write_under_data_path_never_named(tmp_path: Path) -> None:
    v = build_vault(tmp_path, MIN_CONFIG + "data_paths: [data]\n")
    name = "subject-" + secrets.token_hex(4)
    denial = write_call(v, f"data/{name}.md", f"MRN {mrn()}\n")
    assert denial is not None and denial.rule == "data-guard"
    assert name not in denial.message and "#1 ('data')" in denial.message


def test_base_lookup_by_path_folded_path_then_id() -> None:
    tree = {DONE_REL: "a", f"experiments/old/{DONE}.md": "b", "raw/x.md": "c"}
    assert writes._base_rels(tree, DONE_REL) == [DONE_REL]
    assert writes._base_rels(tree, f"Experiments/{DONE}.md") == [DONE_REL]
    moved = sorted(writes._base_rels(tree, f"experiments/new/{DONE}.md"))
    assert moved == [DONE_REL, f"experiments/old/{DONE}.md"]
    assert writes._base_rels(tree, "claims/CLM-20261020-other.md") == []


def test_phi_multiedit_not_computable_scans_new_strings(vault: Path) -> None:
    tool_input = {
        "file_path": str(vault / CLAIM_REL),
        "edits": [
            {"old_string": "not in the file", "new_string": "fine"},
            {"old_string": "x", "new_string": f"MRN {mrn()}", "replace_all": 1},
        ],
    }
    denied(call(vault, "MultiEdit", tool_input), "phi", phi_message(CLAIM_REL, "phi-mrn", "2"))
    tool_input = {"file_path": str(vault / CLAIM_REL), "content": ["MRN", 12345678]}
    assert call(vault, "Write", tool_input) is None
