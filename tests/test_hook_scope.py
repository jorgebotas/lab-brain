"""Which vaults a hook call sees, their protected roots and guard files."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, hook_payload, make_vault, write

from labbrain.hooks.paths import GuardFile, canonical
from labbrain.hooks.scope import find_vault_roots, load_scope, vault_of

PROTECTED = MIN_CONFIG + "data_paths: ['~/phi', data]\n"
HOOK_ENV_KEYS = ("CLAUDE_PROJECT_DIR", "LABBRAIN_VAULT", "CLAUDE_PLUGIN_ROOT", "UV_CACHE_DIR")


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in HOOK_ENV_KEYS}
    env.update(extra)
    return env


def test_no_vault_does_not_import_pydantic(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    probe = (
        "import os, sys\n"
        "from labbrain.hooks.entry import run_hook\n"
        "data = sys.stdin.buffer.read()\n"
        "code, out, err = run_hook('pre-tool-use', data, dict(os.environ))\n"
        "heavy = [m for m in sys.modules if m.split('.')[0] in ('pydantic', 'yaml', 'ruamel')]\n"
        "print(code, repr(out), repr(err), 'pydantic' in sys.modules, heavy)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        input=hook_payload("bash", cwd=empty, command="ls"),
        cwd=empty,
        env=clean_env(),
        capture_output=True,
        check=True,
    )
    assert proc.stdout.decode().split() == ["0", "''", "''", "False", "[]"]
    assert proc.stderr == b""


def test_union_of_cwd_project_and_env(tmp_path: Path) -> None:
    a = make_vault(tmp_path / "a")
    b = make_vault(tmp_path / "b")
    c = make_vault(tmp_path / "c")
    cwd = a / "experiments" / "deep"
    cwd.mkdir(parents=True)
    env = {"CLAUDE_PROJECT_DIR": str(b / "sub"), "LABBRAIN_VAULT": str(c)}
    assert find_vault_roots(cwd, env) == [canonical(a), canonical(b), canonical(c)]
    # The same vault reached twice is listed once, in first-seen order.
    env = {"CLAUDE_PROJECT_DIR": str(a), "LABBRAIN_VAULT": str(tmp_path / "x" / ".." / "a")}
    assert find_vault_roots(cwd, env) == [canonical(a)]

    # Subfolder mode: a relative LABBRAIN_VAULT is taken from the project dir, not cwd.
    project = tmp_path / "project"
    brain = make_vault(project / "brain")
    sub = project / "src"
    make_vault(sub / "brain")  # a decoy the cwd-relative reading would pick
    env = {"CLAUDE_PROJECT_DIR": str(project), "LABBRAIN_VAULT": "brain"}
    assert find_vault_roots(sub, env) == [canonical(brain)]
    # Without a project dir, a relative value is taken from cwd.
    assert find_vault_roots(sub, {"LABBRAIN_VAULT": "brain"}) == [canonical(sub / "brain")]
    # A LABBRAIN_VAULT that is not a vault is ignored; no vault at all is an empty list.
    assert find_vault_roots(sub.parent, {"LABBRAIN_VAULT": str(sub)}) == []
    assert find_vault_roots(tmp_path, {"LABBRAIN_VAULT": "", "CLAUDE_PROJECT_DIR": ""}) == []


def test_vault_of(tmp_path: Path) -> None:
    v = make_vault(tmp_path / "v")
    assert vault_of(v / "experiments" / "new.md") == canonical(v)
    assert vault_of(v / ".labbrain" / "config.yaml") == canonical(v)
    assert vault_of(v / "index.md") == canonical(v)
    assert vault_of(v) is None  # the search starts at the parent
    assert vault_of(tmp_path / "outside.md") is None


def test_no_vault_scope_is_empty(tmp_path: Path) -> None:
    scope = load_scope(tmp_path, {})
    assert scope.vaults == () and scope.targets.roots == () and scope.broken == ()
    assert scope.targets.guard_files == ()
    assert not scope.protected and scope.agents == frozenset()
    assert scope.project_dir is None and scope.env == {}


def test_relative_data_path_resolved_against_vault(tmp_path: Path) -> None:
    v = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: ['', data]\n")
    cwd = v / "experiments"
    cwd.mkdir()
    env = {"CLAUDE_PROJECT_DIR": str(v)}
    scope = load_scope(cwd, env)
    [info] = scope.vaults
    assert info.root == canonical(v) and not info.broken and info.config is not None
    [root] = scope.targets.roots
    assert root.path == canonical(v / "data")
    assert (root.vault, root.index, root.configured) == (canonical(v), 2, "data")
    assert scope.protected and scope.env is env and scope.project_dir == canonical(v)
    assert scope.targets.containing(v / "data" / "f.csv") == root
    assert scope.targets.containing(cwd / "data" / "f.csv") is None


def test_home_relative_data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    v = make_vault(tmp_path / "v", PROTECTED)
    roots = load_scope(v, {}).targets.roots
    assert [(r.index, r.configured, r.path) for r in roots] == [
        (1, "~/phi", canonical(tmp_path / "home" / "phi")),
        (2, "data", canonical(v / "data")),
    ]


def test_unprotected_vaults(tmp_path: Path) -> None:
    off = make_vault(tmp_path / "off", MIN_CONFIG + "protected_data: false\ndata_paths: [data]\n")
    none = make_vault(tmp_path / "none")
    for v in (off, none):
        scope = load_scope(v, {})
        assert not scope.protected and scope.targets.roots == () and scope.broken == ()
        assert scope.agents == frozenset({"claude", "codex", "gemini"})


def test_agents_are_a_union(tmp_path: Path) -> None:
    a = make_vault(tmp_path / "a", MIN_CONFIG + "agents: [claude, aider]\n")
    b = make_vault(tmp_path / "b", MIN_CONFIG + "agents: [goose]\n")
    scope = load_scope(a, {"LABBRAIN_VAULT": str(b)})
    assert scope.agents == frozenset({"claude", "aider", "goose"})


def test_broken_config_marks_vault_broken_and_protected(tmp_path: Path) -> None:
    good = make_vault(tmp_path / "good", MIN_CONFIG + "data_paths: [data]\n")
    for text in ("project_name: [unclosed\n", "protected_data: maybe\n", "- a list\n"):
        bad = make_vault(tmp_path / "bad", text)
        scope = load_scope(bad, {"LABBRAIN_VAULT": str(good)})
        assert scope.protected
        [broken] = scope.broken
        assert broken.root == canonical(bad) and broken.broken and broken.config is None
        # The healthy vault's roots are still listed.
        assert [r.path for r in scope.targets.roots] == [canonical(good / "data")]
    # A broken vault alone is protected too, with no known roots.
    bad = make_vault(tmp_path / "bad", "project_name: [unclosed\n")
    scope = load_scope(bad, {})
    assert scope.protected and len(scope.broken) == 1 and scope.targets.roots == ()


def test_guard_files_listed_only_when_protected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plugin = tmp_path / "plugin"
    project = tmp_path / "project"
    env = {"HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(plugin), "CLAUDE_PROJECT_DIR": str(project)}
    plain = make_vault(project / "plain")
    scope = load_scope(plain, env)
    assert scope.targets.guard_files == ()
    assert not scope.targets.is_guard_file(plain / ".labbrain" / "config.yaml")

    v = make_vault(project / "v", MIN_CONFIG + "data_paths: [data]\n")
    t = load_scope(v, env).targets
    for guarded in (
        v / ".labbrain" / "config.yaml",
        v / ".labbrain" / "phi-allow.yaml",
        v / ".copier-answers.yml",
        v / ".claude" / "settings.json",
        v / ".claude" / "settings.local.json",
        project / ".claude" / "settings.json",
        project / ".claude" / "settings.local.json",
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        home / ".claude" / "plugins" / "data" / "lab-brain" / "cache.json",
        plugin / "labbrain" / "hooks" / "guard.py",
        home / ".cache" / "uv" / "sdists-v9" / "x",
    ):
        assert t.is_guard_file(guarded), guarded
    for free in (
        v / "experiments" / "EXP-1.md",
        v / ".claude" / "agents.md",
        v / ".copier-answers.yml.bak",
        home / ".claude" / "projects" / "x.jsonl",
    ):
        assert not t.is_guard_file(free), free

    uv_env = {**env, "UV_CACHE_DIR": str(tmp_path / "uvcache")}
    t = load_scope(v, uv_env).targets
    assert t.is_guard_file(tmp_path / "uvcache" / "archive-v0" / "f")
    assert not t.is_guard_file(home / ".cache" / "uv" / "f")

    # Guard files reached through symlinks: the link target and the link itself are guarded.
    real = tmp_path / "real-labbrain"
    real.mkdir()
    (real / "config.yaml").write_text(MIN_CONFIG + "data_paths: [data]\n")
    linked = project / "linked"
    linked.mkdir()
    (linked / ".labbrain").symlink_to(real)
    answers = write(tmp_path, "elsewhere/answers.yml", "x")
    (linked / ".copier-answers.yml").symlink_to(answers)
    settings = write(tmp_path, "dotfiles/settings.json", "{}")
    (linked / ".claude").mkdir()
    (linked / ".claude" / "settings.json").symlink_to(settings)
    plugins = tmp_path / "plugins-store"
    plugins.mkdir()
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "plugins").symlink_to(plugins)
    scope = load_scope(linked, env)
    assert scope.protected
    t = scope.targets
    for guarded in (
        linked / ".labbrain" / "config.yaml",
        real / "config.yaml",
        linked / ".labbrain",
        linked / ".copier-answers.yml",
        answers,
        linked / ".claude" / "settings.json",
        settings,
        home / ".claude" / "plugins" / "cache" / "x",
        plugins / "cache" / "x",
    ):
        assert t.is_guard_file(guarded), guarded
    assert GuardFile(canonical(linked) / ".labbrain", True) in t.guard_files
    assert GuardFile(canonical(real), True) in t.guard_files
    assert GuardFile(canonical(linked) / ".copier-answers.yml", False) in t.guard_files
    assert GuardFile(canonical(answers), False) in t.guard_files
    assert not t.is_guard_file(answers.parent / "other.yml")

    # A broken vault makes the scope protected, so its guard files are listed too.
    bad = make_vault(tmp_path / "bad", "project_name: [unclosed\n")
    t = load_scope(bad, {"HOME": str(home)}).targets
    assert t.is_guard_file(bad / ".labbrain" / "config.yaml")
    assert not t.is_guard_file(plugin / "x")


def test_symlinked_data_path_keeps_its_own_spelling(tmp_path: Path) -> None:
    mount = tmp_path / "mnt" / "phi"
    mount.mkdir(parents=True)
    v = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: [data, plain]\n")
    (v / "data").symlink_to(mount)
    first, second = load_scope(v, {}).targets.roots
    assert (first.path, first.link) == (canonical(mount), canonical(v) / "data")
    assert (second.path, second.link) == (canonical(v / "plain"), None)
    t = load_scope(v, {}).targets
    assert t.containing(v / "data" / "f.csv") == first
    assert t.containing(mount / "f.csv") == first
    # A recursive walk from the vault reaches the root through the link.
    assert t.under(v) == [first, second]
    assert t.under(tmp_path / "mnt") == [first]
