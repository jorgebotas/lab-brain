from __future__ import annotations

from datetime import date
from pathlib import Path

from helpers import body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.lint.rules.hygiene_rules import METRIC_RE
from labbrain.vault import Vault

TODAY = date(2026, 10, 15)


def fired(root: Path, rule: str) -> list[int]:
    return [f.line for f in lint.run(Vault.load(root), today=TODAY, only=[rule])]


def concept(root: Path, body: str, author: str = "claude") -> Path:
    block = "## For future agents\n\nA concept.\n\n" if author == "claude" else ""
    text = note_text("topic", "concept", author=author, sources=["x"], body=block + body)
    return write(root, "concepts/topic.md", text)


def test_metric_regex() -> None:
    assert METRIC_RE.search("ECE 0.04")
    assert METRIC_RE.search("accuracy 87%")
    assert METRIC_RE.search("gain of 12.5 %")
    assert METRIC_RE.search("ECE fell to 0.04.")
    assert not METRIC_RE.search("on 2026-10-15")
    assert not METRIC_RE.search("smoothing 0.1 only")
    assert not METRIC_RE.search("version v1.25")
    assert not METRIC_RE.search("EXP-20261015-x")
    assert not METRIC_RE.search("1.25.3")


def test_undated_fact_flags_unstamped_lines_only(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = (
        "## Summary\n\n"
        "ECE fell to 0.04.\n"  # flagged
        "ECE fell to 0.04 in [[EXP-20261001-a]].\n"
        "ECE fell to 0.04 as of 2026-10-01.\n"
        "ECE fell to 0.04 (run_id r1).\n"
        "Accuracy 87% overall.\n"  # flagged
        "```\n0.99 inside a fence\n```\n"
        "## History\n\n- 2026-10-01: value 0.81\n"
    )
    path = concept(root, body)
    lines = path.read_text().splitlines()
    flagged = fired(root, "undated-fact")
    assert [lines[n - 1] for n in flagged] == ["ECE fell to 0.04.", "Accuracy 87% overall."]


def test_undated_fact_ignores_humans_and_experiments(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    concept(root, "## Summary\n\nECE fell to 0.04.\n", author="alice")
    write(
        root,
        "experiments/EXP-20261001-a.md",
        note_text(
            "EXP-20261001-a",
            "experiment",
            author="alice",
            body=body_for("experiment", "AUROC 0.81"),
        ),
    )
    assert fired(root, "undated-fact") == []


def test_concept_unsourced(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/a.md", note_text("a", "concept", sources=[]))
    write(root, "concepts/b.md", note_text("b", "concept", sources=["a"]))
    findings = lint.run(Vault.load(root), today=TODAY, only=["concept-unsourced"])
    assert [f.path for f in findings] == ["concepts/a.md"]


def test_inbox_age_boundary(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "ideas/inbox/IDEA-20260915-a.md",
        note_text("IDEA-20260915-a", "idea", created=date(2026, 9, 15), body="x\n"),
    )
    write(
        root,
        "ideas/inbox/IDEA-20260914-b.md",
        note_text("IDEA-20260914-b", "idea", created=date(2026, 9, 14), body="x\n"),
    )
    findings = lint.run(Vault.load(root), today=TODAY, only=["inbox-age"])
    assert [f.path for f in findings] == ["ideas/inbox/IDEA-20260914-b.md"]  # 31 days > 30


def test_dirty_code(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "experiments/EXP-20261001-a.md",
        note_text("EXP-20261001-a", "experiment", code={"sha": "1a2b3c4", "dirty": True}),
    )
    write(
        root,
        "experiments/EXP-20261001-b.md",
        note_text("EXP-20261001-b", "experiment", code={"sha": "1a2b3c4", "dirty": False}),
    )
    findings = lint.run(Vault.load(root), today=TODAY, only=["dirty-code"])
    assert [f.path for f in findings] == ["experiments/EXP-20261001-a.md"]
