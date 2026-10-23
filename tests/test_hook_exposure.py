"""The bounded walk that finds symlinks into protected roots (Bash rule 6b)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from labbrain.hooks import exposure
from labbrain.hooks.exposure import SKIP_DIRS, LinkScan, links_under
from labbrain.hooks.paths import ProtectedRoot, Targets, canonical

SESSION = "00000000-0000-4000-8000-000000000001"


def targets_for(root: Path) -> Targets:
    return Targets([ProtectedRoot(root.parent, 1, str(root), canonical(root))], [])


def world(tmp_path: Path) -> tuple[Path, Path, Targets]:
    """A protected root `phi` with a file, and a start directory `repo` with a small tree."""
    root = tmp_path / "phi"
    root.mkdir()
    (root / "rows.csv").write_text("x\n")
    start = tmp_path / "repo"
    (start / "src" / "deep").mkdir(parents=True)
    (start / "src" / "a.py").write_text("")
    return root, start, targets_for(root)


def test_finds_link_into_root(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    (start / "src" / "deep" / "data").symlink_to(root)
    assert links_under(start, targets, None, SESSION) == LinkScan(found=True, truncated=False)


def test_walk_stops_at_the_first_exposing_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review item 10: once one link leads into a root, the rest is not walked (so a
    big tree below cannot truncate the answer)."""
    root, start, targets = world(tmp_path)
    (start / "data").symlink_to(root)  # top level: listed before any subdirectory
    big = start / "big"
    big.mkdir()
    for n in range(20):
        (big / f"f{n}.txt").write_text("")
    monkeypatch.setattr(exposure, "WALK_LIMIT", 5)
    assert links_under(start, targets, None, SESSION) == LinkScan(found=True, truncated=False)


def test_finds_link_to_file_inside_root_and_to_an_ancestor(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    (start / "f.csv").symlink_to(root / "rows.csv")
    assert links_under(start, targets, None, SESSION).found
    (start / "f.csv").unlink()
    (start / "up").symlink_to(tmp_path)  # following it reaches the root
    assert links_under(start, targets, None, SESSION).found


def test_ignores_links_elsewhere(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (start / "src" / "elsewhere").symlink_to(other)
    (start / "broken").symlink_to(tmp_path / "missing")
    assert links_under(start, targets, None, SESSION) == LinkScan(found=False, truncated=False)


def test_skips_git_and_venv(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    assert {".git", ".venv", "node_modules"} <= SKIP_DIRS
    for skipped in (".git", ".venv", "node_modules"):
        (start / skipped / "inner").mkdir(parents=True)
        (start / skipped / "inner" / "data").symlink_to(root)
    assert links_under(start, targets, None, SESSION) == LinkScan(found=False, truncated=False)


def test_does_not_walk_into_protected_roots(tmp_path: Path) -> None:
    root = tmp_path / "repo" / "data"  # a real root below the start
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "loop").symlink_to(root)
    targets = targets_for(root)
    assert links_under(tmp_path / "repo", targets, None, SESSION).found is False


def test_truncated_at_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, start, targets = world(tmp_path)
    for n in range(10):
        (start / f"f{n}.txt").write_text("")
    monkeypatch.setattr(exposure, "WALK_LIMIT", 5)
    assert links_under(start, targets, None, SESSION).truncated
    monkeypatch.setattr(exposure, "WALK_LIMIT", 1000)
    assert not links_under(start, targets, None, SESSION).truncated


def test_cache_hit_skips_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, start, targets = world(tmp_path)
    (start / "data").symlink_to(root)
    cache = tmp_path / "plugin-data"
    real_scandir = os.scandir
    calls = {"walks": 0}

    def counting(path: str | os.PathLike[str]) -> object:
        if calls["walks"] >= 1 and canonical(Path(path)) == canonical(start):
            raise AssertionError("walked again despite the cache")
        if canonical(Path(path)) == canonical(start):
            calls["walks"] += 1
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", counting)
    first = links_under(start, targets, cache, SESSION)
    second = links_under(start, targets, cache, SESSION)
    assert first == second == LinkScan(found=True, truncated=False)
    assert calls["walks"] == 1
    # The same start spelled differently hits the same entry.
    assert links_under(start / "src" / "..", targets, cache, SESSION) == first


def test_cache_is_per_session_and_per_targets(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    cache = tmp_path / "plugin-data"
    assert not links_under(start, targets, cache, SESSION).found
    (start / "data").symlink_to(root)
    # Another session walks afresh; so does the same session with other protected roots.
    assert links_under(start, targets, cache, "another-session").found
    other_root = tmp_path / "phi2"
    other_root.mkdir()
    both = Targets([*targets.roots, ProtectedRoot(tmp_path, 2, "phi2", canonical(other_root))], [])
    assert links_under(start, both, cache, SESSION).found


def test_corrupt_cache_ignored(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    (start / "data").symlink_to(root)
    cache = tmp_path / "plugin-data"
    links_under(start, targets, cache, SESSION)
    [file] = (cache / "exposure").iterdir()
    for garbage in ("{not json", "[1, 2]", json.dumps({"targets": 1, "starts": []}), ""):
        file.write_text(garbage)
        assert links_under(start, targets, cache, SESSION) == LinkScan(True, False)
    # A well-formed file whose entry has the wrong shape is ignored too.
    data = json.loads(file.read_text())
    data["starts"] = {str(canonical(start)): "yes"}
    file.write_text(json.dumps(data))
    assert links_under(start, targets, cache, SESSION) == LinkScan(True, False)


def test_unwritable_cache_still_answers(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    blocker = tmp_path / "plugin-data"
    blocker.write_text("a file, not a directory")
    assert links_under(start, targets, blocker, SESSION) == LinkScan(False, False)


def test_session_id_is_hashed_in_filename(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    cache = tmp_path / "deep" / "plugin-data"
    links_under(start, targets, cache, "../../x")
    files = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix == ".json"]
    assert len(files) == 1
    [file] = files
    assert file.parent == cache / "exposure"
    assert len(file.stem) == 16 and all(c in "0123456789abcdef" for c in file.stem)
    assert "x" not in file.name.replace(".json", "")


def test_missing_start(tmp_path: Path) -> None:
    root, start, targets = world(tmp_path)
    assert links_under(tmp_path / "nowhere", targets, None, SESSION) == LinkScan(False, False)
