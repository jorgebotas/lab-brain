from __future__ import annotations

from pathlib import Path

from labbrain.layout import NOTE_TYPES, TYPE_FOLDERS, is_note_rel, iter_note_files


def test_every_type_has_a_folder() -> None:
    assert set(TYPE_FOLDERS) == set(NOTE_TYPES)


def test_is_note_rel() -> None:
    assert is_note_rel("experiments/EXP-20261013-x.md")
    assert is_note_rel("ideas/archive/IDEA-20261013-x.md")
    assert not is_note_rel("experiments/README.md")
    assert not is_note_rel("raw/papers/x.md")
    assert not is_note_rel("index.md")
    assert not is_note_rel("experiments/figure.png")


def test_iter_note_files_skips_readmes_and_other_folders(tmp_path: Path) -> None:
    for rel in [
        "experiments/EXP-20261013-a.md",
        "experiments/README.md",
        "ideas/archive/IDEA-20261013-b.md",
        "raw/notes.md",
        "scratch/alice/c.md",
        "index.md",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    found = [p.relative_to(tmp_path).as_posix() for p in iter_note_files(tmp_path)]
    assert found == ["experiments/EXP-20261013-a.md", "ideas/archive/IDEA-20261013-b.md"]
