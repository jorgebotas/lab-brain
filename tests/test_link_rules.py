from __future__ import annotations

from pathlib import Path

from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.vault import Vault


def rules_fired(root: Path, *names: str) -> list[tuple[str, str, str]]:
    findings = lint.run(Vault.load(root), today=TODAY, only=names)
    return [(f.rule, f.path, f.message) for f in findings]


def test_path_targets_resolve_against_the_filesystem(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision", "![[figures/roc.png]] ![[pr.png]] ![[figures/missing.png]]")
    write(root, "decisions/ADR-20261001-x.md", note_text("ADR-20261001-x", "decision", body=body))
    write(root, "figures/roc.png", "png")
    write(root, "raw/plots/pr.png", "png")
    found = rules_fired(root, "broken-link")
    assert {f[2] for f in found} == {"body: missing file figures/missing.png"}


def test_unresolved_ids_in_body_and_frontmatter(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision", "See [[EXP-20990101-nowhere]].")
    write(
        root,
        "decisions/ADR-20261001-x.md",
        note_text("ADR-20261001-x", "decision", links=["EVAL-v9"], body=body),
    )
    messages = {f[2] for f in rules_fired(root, "broken-link")}
    assert messages == {
        "links: unresolved link [[EVAL-v9]]",
        "body: unresolved link [[EXP-20990101-nowhere]]",
    }


def test_orphans_and_exemptions(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "decisions/ADR-20261001-a.md", note_text("ADR-20261001-a", "decision"))
    write(
        root,
        "decisions/ADR-20261001-b.md",
        note_text("ADR-20261001-b", "decision", links=["ADR-20261001-a"]),
    )
    write(root, "ideas/inbox/IDEA-20261001-c.md", note_text("IDEA-20261001-c", "idea", body="x\n"))
    write(root, "concepts/stray.md", "no frontmatter\n")
    assert rules_fired(root, "orphan") == [
        ("orphan", "decisions/ADR-20261001-b.md", "no inbound links")
    ]


def test_frontmatter_values_never_resolve_as_files(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-x.md",
        note_text("ADR-20261001-x", "decision", links=["figures/roc.png"]),
    )
    write(root, "figures/roc.png", "png")
    assert {f[2] for f in rules_fired(root, "broken-link")} == {
        "links: unresolved link [[figures/roc.png]]"
    }


def test_unresolved_non_id_targets_are_not_echoed(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-x.md",
        note_text("ADR-20261001-x", "decision", links=["patient John Doe"]),
    )
    messages = [f[2] for f in rules_fired(root, "broken-link")]
    assert messages == ["links: unresolved link [[<not a valid note ID>]]"]
    assert not any("John" in m or "Doe" in m for m in messages)
