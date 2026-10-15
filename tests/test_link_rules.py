from __future__ import annotations

import random
from pathlib import Path

from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.findings import render as lint_render
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
    # A frontmatter value is echoed only when it is a valid note ID; a path is not one.
    assert {f[2] for f in rules_fired(root, "broken-link")} == {
        "links: unresolved link [[<not a valid note ID>]]"
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


def test_identifier_shaped_targets_are_not_echoed(tmp_path: Path) -> None:
    """ID-shaped but PHI-shaped targets (SSN, phone, prefixed MRN) never reach messages."""
    rng = random.Random(23)
    ssn = f"{rng.randrange(100, 899)}-{rng.randrange(10, 99)}-{rng.randrange(1000, 9999)}"
    phone = f"{rng.randrange(200, 999)}-{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}"
    mrn = f"MRN-{rng.randrange(10**7, 10**8)}"
    root = make_vault(tmp_path)
    body = body_for("decision") + f"See [[{ssn}]], [[{phone}]] and ![[scans/{mrn}.png]].\n"
    write(
        root,
        "decisions/ADR-20261001-x.md",
        note_text("ADR-20261001-x", "decision", links=[ssn, phone, mrn], body=body),
    )
    findings = lint.run(Vault.load(root), today=TODAY, only=["broken-link"])
    rendered = "\n".join(lint_render(findings, fmt) for fmt in ("text", "json", "github"))
    assert len(findings) == 6
    for secret in (ssn, phone, mrn, mrn[4:]):
        assert secret not in rendered
    assert {f.message for f in findings} == {
        "links: unresolved link [[<not a valid note ID>]]",
        "body: unresolved link [[<not a valid note ID>]]",
        "body: missing file <not a valid file path>",
    }
