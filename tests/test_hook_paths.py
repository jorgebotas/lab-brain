"""Containment of candidate paths in protected roots, and guard-file matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from labbrain.hooks import paths
from labbrain.hooks.paths import (
    GuardFile,
    ProtectedRoot,
    Targets,
    canonical,
    fold,
    spellings,
)


def root_at(path: Path, vault: Path | None = None, index: int = 1) -> ProtectedRoot:
    return ProtectedRoot(vault or path.parent, index, str(path), canonical(path))


def targets(*roots: ProtectedRoot, guard: tuple[GuardFile, ...] = ()) -> Targets:
    return Targets(list(roots), list(guard))


def test_canonical_and_fold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    base = canonical(tmp_path)
    assert canonical("~/a/../b") == base / "b"
    assert canonical("rel/x", base) == base / "rel" / "x"
    assert canonical(tmp_path / "p" / "." / "q") == base / "p" / "q"
    # NFD "é" (e + combining acute) folds to the same text as NFC "É".
    assert fold("/x/Café") == fold("/x/CAFÉ") == "/x/café"


def test_containing_by_prefix(tmp_path: Path) -> None:
    data = tmp_path / "vault" / "data"
    data.mkdir(parents=True)
    root = root_at(data)
    t = targets(root)
    assert t.roots == (root,)
    assert t.containing(data / "a" / "b") == root
    assert t.containing(data) == root
    assert t.containing(data.parent / "other") is None
    assert t.containing(data.parent / "data-other") is None


def test_containing_through_symlink(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "l").symlink_to(data)
    root = root_at(data)
    assert targets(root).containing(vault / "l" / "f") == root


def test_containing_dotdot(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    root = root_at(data)
    t = targets(root)
    assert t.containing(data / "x" / ".." / "y") == root
    assert t.containing(data / "..") is None
    assert t.containing(tmp_path / "elsewhere" / ".." / "data" / "f") == root


def test_containing_casefold(tmp_path: Path) -> None:
    data = tmp_path / "Data"  # not created: only the text comparison can match
    root = root_at(data)
    spelled = Path(str(data).replace("Data", "dATA"))
    assert targets(root).containing(spelled / "f") == root


def test_containing_by_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    other = tmp_path / "elsewhere"
    data.mkdir()
    other.mkdir()
    same = {canonical(data), canonical(other)}

    def fake_identity(path: Path) -> tuple[int, int] | None:
        return (1, 1) if Path(path) in same else None

    monkeypatch.setattr(paths, "_identity", fake_identity)
    root = root_at(data)
    t = targets(root)
    assert t.containing(other / "f") == root
    assert t.containing(other) == root
    assert t.containing(tmp_path / "third" / "f") is None


def test_identity_of_real_directories(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    ident = paths._identity(data)
    assert ident is not None and ident == paths._identity(tmp_path / "." / "data")
    assert paths._identity(tmp_path / "missing") is None
    assert paths._identity("bad\0path") is None


def test_missing_root_still_contains(tmp_path: Path) -> None:
    data = tmp_path / "mnt" / "phi"  # e.g. a mount that is not attached
    root = root_at(data)
    t = targets(root)
    assert t.containing(data / "x.csv") == root
    assert t.containing(Path(str(data).upper()) / "x.csv") == root
    assert t.containing(tmp_path / "mnt" / "other") is None


def test_containing_picks_the_matching_root(tmp_path: Path) -> None:
    first = root_at(tmp_path / "a", index=1)
    second = root_at(tmp_path / "b", index=2)
    t = targets(first, second)
    assert t.containing(tmp_path / "b" / "f") == second
    assert t.containing(tmp_path / "a") == first


def test_under_strict(tmp_path: Path) -> None:
    data = tmp_path / "vault" / "data"
    root = root_at(data)
    t = targets(root)
    assert t.under(data.parent) == [root]
    assert t.under(tmp_path) == [root]
    assert t.under(Path(str(tmp_path).upper())) == [root]
    assert t.under(data) == []
    assert t.under(data / "inner") == []
    assert t.under(tmp_path / "vault" / "dat") == []


def test_guard_file_tree_and_exact(tmp_path: Path) -> None:
    tree = canonical(tmp_path / "vault" / ".labbrain")
    exact = canonical(tmp_path / "vault" / ".copier-answers.yml")
    t = targets(guard=(GuardFile(tree, True), GuardFile(exact, False)))
    assert t.guard_files == (GuardFile(tree, True), GuardFile(exact, False))
    assert t.is_guard_file(tree)
    assert t.is_guard_file(tree / "config.yaml")
    assert t.is_guard_file(Path(str(tree).upper()) / "phi-allow.yaml")
    assert not t.is_guard_file(tree.parent / ".labbrain-other")
    assert t.is_guard_file(exact)
    assert t.is_guard_file(Path(str(exact).replace("copier", "COPIER")))
    assert not t.is_guard_file(exact / "child")
    assert not t.is_guard_file(tmp_path / "vault" / "notes.md")
    assert not targets().is_guard_file(exact)


def test_spellings(tmp_path: Path) -> None:
    base = canonical(tmp_path)
    target = base / "target"
    target.mkdir()
    (base / "link").symlink_to(target)
    (base / "dir-link").symlink_to(base)
    assert spellings(base / "target") == (target,)
    assert spellings(base / "link") == (target, base / "link")
    assert spellings("link", base) == (target, base / "link")
    # Only the final component is kept as written; links above it are resolved.
    assert spellings(base / "dir-link" / "link") == (target, base / "link")
    assert spellings(base / "missing" / "..") == (base,)
    assert spellings("/") == (Path("/"),)


def test_links_inside_roots_and_guard_trees(tmp_path: Path) -> None:
    """A link inside a root or guarded tree is itself inside, wherever it points:
    rewriting or removing the link changes the protected or guarded tree."""
    base = canonical(tmp_path)
    outside = base / "outside"
    outside.mkdir()
    data = base / "data"
    data.mkdir()
    (data / "out").symlink_to(outside)
    tree = base / "plugins"
    tree.mkdir()
    (tree / "out").symlink_to(outside)
    root = root_at(data)
    t = targets(root, guard=(GuardFile(tree, True),))
    assert t.containing(data / "out") == root
    assert t.containing(outside) is None
    assert t.is_guard_file(tree / "out")
    assert not t.is_guard_file(outside)


def test_root_link_spelling(tmp_path: Path) -> None:
    base = canonical(tmp_path)
    mount = base / "mnt" / "phi"
    root = ProtectedRoot(base / "v", 1, "data", mount, base / "v" / "data")
    t = targets(root)
    assert t.containing(base / "v" / "data" / "f") == root  # even with the link gone
    assert t.containing(base / "V" / "DATA") == root
    assert t.under(base / "v") == [root]
    assert t.under(base) == [root]
    assert t.under(base / "v" / "data") == []
