"""The data guard for file, search and MCP tools, broken configs and guard self-protection."""

from __future__ import annotations

import getpass
import secrets
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from helpers import MIN_CONFIG, hook_payload, make_vault, write

from labbrain.hooks import bash, guard
from labbrain.hooks.entry import run_hook
from labbrain.hooks.payload import Denial, Payload, parse_payload
from labbrain.hooks.scope import Scope, load_scope

BROKEN = (
    "lab-brain guard: this vault's .labbrain/config.yaml could not be loaded, so protected "
    "data paths are unknown and every tool call is blocked. Ask the user to fix "
    ".labbrain/config.yaml (labbrain lint shows the problem)."
)
GUARD_CONFIG = (
    "lab-brain guard: agents may not change lab-brain or Claude Code guard settings in a "
    "protected vault. Ask the user to make this change."
)


@dataclass
class World:
    """A protected vault at `<tmp>/vault` whose one data path is `<tmp>/phi`."""

    tmp: Path
    vault: Path
    phi: Path
    rows: Path
    sentinel: str
    home: Path
    plugin: Path
    env: dict[str, str]
    denials: list[tuple[Denial, str]] = field(default_factory=list)

    @property
    def configured(self) -> str:
        return str(self.phi)


def protected_config(*entries: Path | str, protected: bool = True) -> str:
    listed = ", ".join(f"'{e}'" for e in entries)
    return MIN_CONFIG + f"protected_data: {str(protected).lower()}\ndata_paths: [{listed}]\n"


@pytest.fixture
def world(tmp_path: Path) -> World:
    phi = tmp_path / "phi"
    sentinel = secrets.token_hex(16)
    rows = write(phi, "rows.csv", f"id,value\n{sentinel},1\n")
    vault = make_vault(tmp_path / "vault", protected_config(phi))
    write(vault, "notes/n.md", "A note.\n")
    home = tmp_path / "home"
    home.mkdir()
    plugin = tmp_path / "plugin"
    env = {"HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(plugin), "CLAUDE_PROJECT_DIR": str(vault)}
    return World(tmp_path, vault, phi, rows, sentinel, home, plugin, env)


def payload(cwd: Path, tool_name: str, tool_input: dict[str, Any]) -> Payload:
    return parse_payload(hook_payload("read", cwd=cwd, tool_name=tool_name, tool_input=tool_input))


def decide(w: World, tool_name: str, tool_input: dict[str, Any], cwd: Path | None = None) -> Any:
    here = w.vault if cwd is None else cwd
    return guard.check_tool(payload(here, tool_name, tool_input), load_scope(here, w.env))


def denied(
    w: World,
    tool_name: str,
    tool_input: dict[str, Any],
    cwd: Path | None = None,
    rule: str = "data-guard",
    entry: tuple[int, str] | None = None,
) -> Denial:
    denial = decide(w, tool_name, tool_input, cwd)
    assert isinstance(denial, Denial), (tool_name, tool_input)
    assert denial.rule == rule, (tool_name, tool_input, denial)
    w.denials.append((denial, tool_name))
    assert_clean(w, denial, entry or (1, w.configured))
    return denial


def assert_clean(w: World, denial: Denial, entry: tuple[int, str]) -> None:
    """No denial quotes data, file names under a data path, or candidate paths."""
    message = denial.message
    assert w.sentinel not in message
    assert "rows.csv" not in message
    assert str(w.rows) not in message and str(w.rows.resolve()) not in message
    assert "\n" not in message
    if denial.rule == "data-guard":
        n, configured = entry
        assert f"protected data path #{n} ('{configured}')" in message
        assert message.startswith("lab-brain data guard: this ")
    elif denial.rule == "config":
        assert message == BROKEN
    else:
        assert denial.rule == "guard-config" and message == GUARD_CONFIG


def allowed(w: World, tool_name: str, tool_input: dict[str, Any], cwd: Path | None = None) -> None:
    assert decide(w, tool_name, tool_input, cwd) is None, (tool_name, tool_input)


# --- Read, Write, Edit and the other file tools -------------------------------------------


def test_read_inside_root_denied(world: World) -> None:
    d = denied(world, "Read", {"file_path": str(world.rows)})
    assert d.message == (
        f"lab-brain data guard: this Read call refers to protected data path #1 "
        f"('{world.configured}'). Individual-level data must not enter the session. If you "
        "need this run, ask the user to run it themselves and share only aggregate results."
    )
    denied(world, "Read", {"file_path": str(world.phi)})  # the root itself
    denied(world, "Read", {"file_path": str(world.tmp / "PHI" / "rows.csv")})  # casefold
    denied(world, "Read", {"file_path": "../phi/rows.csv"})  # relative to cwd
    denied(world, "NotebookRead", {"notebook_path": str(world.phi / "a.ipynb")})
    denied(world, "LS", {"path": str(world.phi)})


def test_read_symlink_into_root_denied(world: World) -> None:
    (world.vault / "linked").symlink_to(world.phi, target_is_directory=True)
    (world.vault / "file.csv").symlink_to(world.rows)
    denied(world, "Read", {"file_path": str(world.vault / "linked" / "rows.csv")})
    denied(world, "Read", {"file_path": "file.csv"})
    denied(world, "LS", {"path": "linked"})


def test_read_dotdot_escape_denied(world: World) -> None:
    denied(world, "Read", {"file_path": str(world.vault / "notes" / ".." / ".." / "phi" / "x")})
    denied(world, "Read", {"file_path": "notes/../../phi/rows.csv"})


def test_read_outside_root_allowed(world: World) -> None:
    allowed(world, "Read", {"file_path": str(world.vault / "notes" / "n.md")})
    allowed(world, "Read", {"file_path": "notes/n.md"})
    allowed(world, "Read", {"file_path": str(world.tmp / "phi2" / "rows.csv")})  # a lookalike
    allowed(world, "LS", {"path": str(world.tmp)})  # one level of names, as a plain ls
    allowed(world, "Read", {})


def test_unconfident_path_denied(world: World) -> None:
    denied(world, "Read", {"file_path": f"~nosuchuser{secrets.token_hex(4)}/rows.csv"})
    denied(world, "Read", {"file_path": str(world.vault / "a\0b")})
    denied(world, "Read", {"file_path": ["not", "a", "string"]})


def test_write_and_edit_into_root_denied(world: World) -> None:
    target = str(world.rows)
    denied(world, "Write", {"file_path": target, "content": "x"})
    denied(world, "Edit", {"file_path": target, "old_string": "a", "new_string": "b"})
    denied(world, "MultiEdit", {"file_path": target, "edits": []})
    denied(world, "NotebookEdit", {"notebook_path": str(world.phi / "a.ipynb"), "new_source": ""})
    allowed(world, "Write", {"file_path": str(world.vault / "notes" / "new.md"), "content": "x"})


def test_unprotected_vault_allows_everything(world: World) -> None:
    for config in (protected_config(world.phi, protected=False), MIN_CONFIG):
        (world.vault / ".labbrain" / "config.yaml").write_text(config)
        allowed(world, "Read", {"file_path": str(world.rows)})
        allowed(world, "Edit", {"file_path": str(world.vault / ".labbrain" / "config.yaml")})
        allowed(world, "Grep", {"pattern": "x", "path": str(world.tmp)})
        allowed(world, "Glob", {"pattern": "**/*.csv", "path": str(world.tmp)})
        allowed(world, "mcp__db__query", {"sql": f"select * from '{world.rows}'"})
        allowed(world, "Read", {"file_path": "x"}, cwd=world.phi)


def test_cwd_inside_root_denies_any_tool(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bash, "check_command", lambda *a, **k: None)
    cwd = world.phi / "sub"
    cwd.mkdir()
    for tool, args in (
        ("Read", {"file_path": str(world.vault / "notes" / "n.md")}),
        ("TodoWrite", {"todos": []}),
        ("Bash", {"command": "ls"}),
        ("mcp__x__y", {}),
    ):
        d = denied(world, tool, args, cwd=cwd)
        assert d.message.startswith(
            "lab-brain data guard: this session's working directory refers to protected "
            "data path #1"
        )


# --- Grep and Glob ------------------------------------------------------------------------


def test_grep_from_ancestor_denied(world: World) -> None:
    d = denied(world, "Grep", {"pattern": "x", "path": str(world.tmp)})
    assert "this Grep call" in d.message
    denied(world, "Grep", {"pattern": "x"}, cwd=world.tmp)  # the default root is cwd
    denied(world, "Grep", {"pattern": "x", "path": ".."})


def test_grep_inside_root_denied(world: World) -> None:
    denied(world, "Grep", {"pattern": "x", "path": str(world.phi)})
    denied(world, "Grep", {"pattern": "x", "path": str(world.rows)})
    # A glob naming the root, by any spelling, is denied wherever the search starts.
    denied(world, "Grep", {"pattern": "x", "path": str(world.vault), "glob": f"{world.phi}/*"})
    spelled = str(world.phi.resolve()).upper()
    denied(world, "Grep", {"pattern": "x", "path": str(world.vault), "glob": spelled})


def test_grep_elsewhere_allowed(world: World) -> None:
    allowed(world, "Grep", {"pattern": "x"})
    allowed(world, "Grep", {"pattern": str(world.phi), "path": str(world.vault / "notes")})
    allowed(world, "Grep", {"pattern": "x", "path": str(world.vault), "glob": "*.md"})


def test_glob_star_star_from_ancestor_denied(world: World) -> None:
    d = denied(world, "Glob", {"pattern": "**/*.csv", "path": str(world.tmp)})
    assert "this Glob call" in d.message
    denied(world, "Glob", {"pattern": "**/*.csv"}, cwd=world.tmp)
    denied(world, "Glob", {"pattern": "*/rows.csv", "path": str(world.tmp)})
    denied(world, "Glob", {"pattern": "p?i/*", "path": str(world.tmp)})
    denied(world, "Glob", {"pattern": "[op]hi", "path": str(world.tmp)})  # the root itself
    denied(world, "Glob", {"pattern": "../**", "path": str(world.vault)})
    # Patterns fnmatch cannot model are treated as recursive.
    denied(world, "Glob", {"pattern": "{phi,x}/*.csv", "path": str(world.tmp)})
    denied(world, "Glob", {"pattern": "@(phi)/rows.csv", "path": str(world.tmp)})
    denied(world, "Glob", {"pattern": "*/../phi/rows.csv", "path": str(world.vault)})


def test_glob_shallow_from_ancestor_allowed(world: World) -> None:
    allowed(world, "Glob", {"pattern": "*.md", "path": str(world.tmp)})
    allowed(world, "Glob", {"pattern": "vault/**/*.md", "path": str(world.tmp)})
    allowed(world, "Glob", {"pattern": "x*/*.csv", "path": str(world.tmp)})
    allowed(world, "Glob", {"pattern": "**/*.md"})


def test_glob_absolute_into_root_denied(world: World) -> None:
    denied(world, "Glob", {"pattern": f"{world.phi}/*.csv"})
    denied(world, "Glob", {"pattern": "*.csv", "path": str(world.phi)})
    denied(world, "Glob", {"pattern": f"{world.rows}"})


# --- Bash routing -------------------------------------------------------------------------


def test_bash_routed_to_check_command(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    sentinel = Denial("data-guard", "from bash")

    def fake(command: str, cwd: Path, scope: Scope, env: Any, session_id: str) -> Denial:
        calls.append((command, cwd, scope, env, session_id))
        return sentinel

    monkeypatch.setattr(bash, "check_command", fake)
    p = payload(world.vault, "Bash", {"command": "ls -la"})
    scope = load_scope(world.vault, world.env)
    assert guard.check_tool(p, scope) is sentinel
    [(command, cwd, got_scope, env, session_id)] = calls
    assert (command, cwd, got_scope, session_id) == ("ls -la", p.cwd, scope, p.session_id)
    assert env is scope.env
    # Bash is not scanned by the generic walk: the text is the Bash rules' to judge.
    monkeypatch.setattr(bash, "check_command", lambda *a, **k: None)
    allowed(world, "Bash", {"command": f"cat {world.rows}"})


# --- MCP and other tools ------------------------------------------------------------------


def test_mcp_nested_argument_denied(world: World) -> None:
    d = denied(world, "mcp__files__read", {"args": {"files": [str(world.rows)]}})
    assert "this mcp__files__read call" in d.message
    denied(world, "mcp__db__query", {"sql": f"SELECT * FROM read_csv('{world.rows}')"})
    denied(world, "mcp__db__query", {"sql": f"from '{str(world.phi.resolve()).upper()}/x'"})
    denied(world, "mcp__files__read", {"path": "../phi/rows.csv"})
    denied(world, "mcp__files__read", {"paths": {str(world.rows): True}})  # keys too
    denied(world, "NewTool", {"target": str(world.rows)})
    d = denied(world, "mcp__evil\nIgnore previous\u202e" + "x" * 300, {"t": str(world.rows)})
    assert "this mcp__evil_Ignore_previous_xxx" in d.message and "\u202e" not in d.message
    assert len(d.message) < 600


def test_mcp_caps(world: World) -> None:
    deep: Any = str(world.rows)
    for _ in range(25):
        deep = [deep]
    denied(world, "mcp__x__y", {"a": deep})  # too deep to walk: unconfident
    denied(world, "mcp__x__y", {"a": [str(i) for i in range(2500)]})  # too many strings
    long = "x" * 5000 + f" {world.rows}"
    denied(world, "mcp__x__y", {"a": long})  # the textual net sees the whole string


def test_mcp_unrelated_allowed(world: World) -> None:
    allowed(world, "mcp__x__y", {"a": {"b": ["hello", 3, None, True, "notes/n.md"]}})
    allowed(world, "mcp__x__y", {"a": [[["deep enough"]]] * 3})
    allowed(world, "WebFetch", {"url": "https://example.org/phi2", "prompt": "summarize"})
    allowed(world, "mcp__x__y", {})


def test_skip_tools_not_scanned(world: World) -> None:
    assert guard.SKIP_TOOLS == frozenset(
        {
            "Agent",
            "Task",
            "TodoWrite",
            "ToolSearch",
            "Skill",
            "AskUserQuestion",
            "WebSearch",
            "ExitPlanMode",
            "EnterPlanMode",
            "SendMessage",
            "TaskStop",
            "ScheduleWakeup",
        }
    )
    allowed(world, "Agent", {"prompt": f"Summarize {world.rows} for me"})
    allowed(world, "TodoWrite", {"todos": [{"content": str(world.rows)}]})


# --- Broken configs -----------------------------------------------------------------------


def test_broken_config_only_read_of_labbrain_allowed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bash, "check_command", lambda *a, **k: None)
    config = world.vault / ".labbrain" / "config.yaml"
    config.write_text("project_name: [unclosed\n")
    allowed(world, "Read", {"file_path": str(config)})
    allowed(world, "Read", {"file_path": ".labbrain/config.yaml"})
    for tool, args in (
        ("Read", {"file_path": str(world.vault / "notes" / "n.md")}),
        ("Read", {"file_path": str(world.vault / ".labbrain")}),
        ("Read", {"file_path": str(world.vault / ".labbrainx" / "f")}),
        ("Read", {"file_path": str(config) + "\0"}),
        ("Read", {"file_path": None}),
        ("Edit", {"file_path": str(config), "old_string": "[", "new_string": ""}),
        ("Write", {"file_path": str(config), "content": "x"}),
        ("Bash", {"command": "labbrain lint"}),
        ("Grep", {"pattern": "x", "path": str(world.vault / ".labbrain")}),
        ("TodoWrite", {"todos": []}),
        ("mcp__x__y", {}),
    ):
        denied(world, tool, args, rule="config")
    # A link in .labbrain/ leading out of it is judged by where it leads.
    (world.vault / ".labbrain" / "out.csv").symlink_to(world.vault / "notes" / "n.md")
    denied(world, "Read", {"file_path": str(world.vault / ".labbrain" / "out.csv")}, rule="config")


def test_broken_vault_among_two(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bash, "check_command", lambda *a, **k: None)
    bad = make_vault(world.tmp / "bad", "project_name: [unclosed\n")
    secret = write(bad, ".labbrain/phi/rows.csv", f"{world.sentinel}\n")
    # The healthy vault guards its own data path and one inside the broken vault's .labbrain.
    (world.vault / ".labbrain" / "config.yaml").write_text(
        protected_config(world.phi, secret.parent)
    )
    for cwd, env in (
        (world.vault, {**world.env, "LABBRAIN_VAULT": str(bad)}),  # subfolder vault + env
        (bad, {**world.env, "LABBRAIN_VAULT": str(world.vault)}),  # the broken one is cwd's
    ):
        world.env = env
        scope = load_scope(cwd, env)
        assert len(scope.vaults) == 2 and len(scope.broken) == 1
        # Only a Read of the broken vault's .labbrain/ gets past the broken config ...
        allowed(world, "Read", {"file_path": str(bad / ".labbrain" / "config.yaml")}, cwd=cwd)
        # ... and the healthy vault's roots still apply to it.
        denied(world, "Read", {"file_path": str(secret)}, cwd=cwd, entry=(2, str(secret.parent)))
        for tool, args in (
            ("Read", {"file_path": str(world.rows)}),
            ("Read", {"file_path": str(world.vault / "notes" / "n.md")}),
            ("Read", {"file_path": str(world.vault / ".labbrain" / "config.yaml")}),
            ("Bash", {"command": "labbrain lint"}),
            ("Glob", {"pattern": "*.md"}),
        ):
            denied(world, tool, args, cwd=cwd, rule="config")


# --- Guard self-protection ----------------------------------------------------------------


def test_guard_files_write_denied(world: World) -> None:
    guarded = [
        world.vault / ".labbrain" / "config.yaml",
        world.vault / ".labbrain" / "phi-allow.yaml",
        world.vault / ".copier-answers.yml",
        world.vault / ".claude" / "settings.json",
        world.vault / ".claude" / "settings.local.json",
        world.home / ".claude" / "settings.json",
        world.plugin / "labbrain" / "hooks" / "guard.py",
    ]
    for path in guarded:
        for tool, key in (
            ("Edit", "file_path"),
            ("Write", "file_path"),
            ("MultiEdit", "file_path"),
            ("NotebookEdit", "notebook_path"),
        ):
            denied(world, tool, {key: str(path)}, rule="guard-config")
        allowed(world, "Read", {"file_path": str(path)})
    denied(world, "Edit", {"file_path": ".claude/settings.json"}, rule="guard-config")
    allowed(world, "Edit", {"file_path": str(world.vault / ".claude" / "agents.md")})


def test_messages_never_leak(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every kind of denial, collected in one place and checked by assert_clean."""
    monkeypatch.setattr(bash, "check_command", lambda *a, **k: None)
    cases: list[tuple[str, dict[str, Any], Path | None, str]] = [
        ("Read", {"file_path": str(world.rows)}, None, "data-guard"),
        ("Read", {"file_path": "../phi/rows.csv"}, None, "data-guard"),
        ("Write", {"file_path": str(world.rows), "content": world.sentinel}, None, "data-guard"),
        ("Edit", {"file_path": str(world.rows), "new_string": world.sentinel}, None, "data-guard"),
        ("Grep", {"pattern": world.sentinel, "path": str(world.rows)}, None, "data-guard"),
        ("Grep", {"pattern": "x", "path": str(world.tmp)}, None, "data-guard"),
        ("Glob", {"pattern": "**/rows.csv", "path": str(world.tmp)}, None, "data-guard"),
        ("Glob", {"pattern": f"{world.phi}/rows.csv"}, None, "data-guard"),
        ("mcp__a__b", {"args": {"files": [str(world.rows)]}}, None, "data-guard"),
        ("mcp__a__b", {"q": f"{world.sentinel} {world.rows}"}, None, "data-guard"),
        ("Read", {"file_path": "x"}, world.phi, "data-guard"),
        ("Edit", {"file_path": str(world.vault / ".copier-answers.yml")}, None, "guard-config"),
    ]
    for tool, args, cwd, rule in cases:
        denied(world, tool, args, cwd=cwd, rule=rule)
    (world.vault / ".labbrain" / "config.yaml").write_text(f"x: [{world.rows}\n")
    denied(world, "Read", {"file_path": str(world.rows)}, rule="config")
    assert len(world.denials) == len(cases) + 1


def test_home_relative_root(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(world.home))  # canonical() expands `~` from the process
    user = getpass.getuser()
    config = protected_config("~/deep/phi", f"~{user}/lb-guard-{secrets.token_hex(4)}")
    (world.vault / ".labbrain" / "config.yaml").write_text(config)
    entry = (1, "~/deep/phi")
    deep = world.home / "deep" / "phi"
    for text in ("cat ~/deep/phi/x", f"cat {deep}/x", f"cat {str(deep).upper()}"):
        denied(world, "mcp__x__y", {"q": text}, entry=entry)
    denied(world, "Glob", {"pattern": "~/deep/*/x.csv"}, entry=entry)
    denied(world, "Glob", {"pattern": "*/*", "path": str(world.home)}, entry=entry)
    allowed(world, "Glob", {"pattern": "*", "path": str(world.home)})  # stops above the root
    denied(world, "Glob", {"pattern": f"~nosuchuser{secrets.token_hex(4)}/*"}, entry=entry)
    for tool, args in (
        ("Glob", {"path": str(world.home)}),
        ("Grep", {"pattern": "x", "glob": ["*.md"]}),
        ("Bash", {}),
    ):
        denied(world, tool, args, entry=entry)  # malformed arguments are unsure


def test_through_run_hook(world: World) -> None:
    stdin = hook_payload("read", cwd=world.vault, path=world.rows)
    code, out, err = run_hook("pre-tool-use", stdin, world.env)
    assert (code, out) == (2, "") and err.startswith("lab-brain data guard: this Read call")
    assert world.sentinel not in err and "rows.csv" not in err
    stdin = hook_payload("read", cwd=world.vault, path=world.vault / "notes" / "n.md")
    assert run_hook("pre-tool-use", stdin, world.env) == (0, "", "")


# --- Fix round 1 --------------------------------------------------------------------------


def test_glob_non_ascii_root(world: World) -> None:
    """Casefolding changes lengths (ß -> ss), so wildcards are matched raw as well as folded."""
    straße = world.tmp / "straße"
    write(straße, "rows.csv", f"{world.sentinel}\n")
    (world.vault / ".labbrain" / "config.yaml").write_text(protected_config(straße))
    entry = (1, str(straße))
    for pattern in (
        "stra?e/*",
        "stra[ß]e/*",
        "straße/*",
        "STRASSE/*",
        "stras?e/*",
        "*ß*/*",
        "STRA?E/*",  # case and a length-changing fold at once
        "Stra?e/*",
        "STRA[ß]E/*",
    ):
        denied(world, "Glob", {"pattern": pattern, "path": str(world.tmp)}, entry=entry)
    allowed(world, "Glob", {"pattern": "stra?x/*", "path": str(world.tmp)})


def test_glob_root_stored_nfd(world: World) -> None:
    """A root configured NFC whose directory is spelled NFD on disk is matched in both forms."""
    nfc, nfd = unicodedata.normalize("NFC", "café"), unicodedata.normalize("NFD", "café")
    write(world.tmp / nfd, "rows.csv", f"{world.sentinel}\n")
    root = world.tmp / nfc
    (world.vault / ".labbrain" / "config.yaml").write_text(protected_config(root))
    entry = (1, str(root))
    for pattern in ("caf??/*", "caf?/*", "cafe?/*", f"{nfd}/*", "CAF??/*"):
        denied(world, "Glob", {"pattern": pattern, "path": str(world.tmp)}, entry=entry)
    allowed(world, "Glob", {"pattern": "caf???/*", "path": str(world.tmp)})


def test_mcp_cannot_touch_guard_files(world: World) -> None:
    config = world.vault / ".labbrain" / "config.yaml"
    for args in (
        {"path": str(config), "content": "protected_data: false"},
        {"path": ".claude/settings.json", "content": "{}"},
        {"path": ".labbrain/phi-allow.yaml"},
        {"cmd": f"cp x {world.plugin}/labbrain/hooks/guard.py"},  # embedded, under the plugin
    ):
        denied(world, "mcp__fs__write_file", args, rule="guard-config")
    denied(world, "mcp__fs__read_file", {"path": str(config)}, rule="guard-config")  # accepted
    allowed(world, "mcp__fs__write_file", {"path": "notes/new.md", "content": "x"})


def test_mcp_embedded_relative_path_denied(world: World) -> None:
    (world.vault / "linked").symlink_to(world.phi, target_is_directory=True)
    for sql in (
        "SELECT * FROM '../phi/rows.csv'",
        "SELECT * FROM 'linked/rows.csv'",
        'SELECT * FROM read_csv("notes/../../phi/rows.csv")',
        "COPY t TO `linked/out.csv`;",
    ):
        denied(world, "mcp__duckdb__query", {"sql": sql})
    allowed(world, "mcp__duckdb__query", {"sql": "SELECT 1.5 FROM 'notes/n.md' -- e.g. ok"})
    # R17: a non-delimiter prefix stuck to the path.
    for text in (
        "file:../phi/rows.csv",
        "SELECT * FROM [../phi/rows.csv]",
        "see @../phi/rows.csv",
        "x=$HOME:{../phi/rows.csv}",
        "glob *+../phi/rows.csv",
    ):
        denied(world, "mcp__x__y", {"q": text})
    allowed(world, "mcp__x__y", {"q": "file:notes/n.md [notes/n.md] a:b"})
    assert guard.PATHLIKE.findall("a '../phi/x' b=~/y c(./z)") == ["../phi/x", "~/y", "./z"]


def test_mcp_over_length_path_denied(world: World) -> None:
    (world.vault / "linked").symlink_to(world.phi, target_is_directory=True)
    (world.phi / "sub").mkdir()
    (world.vault / "lnksub").symlink_to(world.phi / "sub", target_is_directory=True)
    pad = "./" * 3000
    for path in (
        pad + "../phi/rows.csv",
        pad + "linked/rows.csv",
        # `..` after a link climbs from the link's target, so it must never be collapsed as text.
        pad + "linked/../phi/rows.csv",
        pad + "lnksub/../rows.csv",
    ):
        denied(world, "mcp__fs__read", {"path": path})
        denied(world, "mcp__db__q", {"sql": f"SELECT * FROM '{path}'"})  # embedded too
    # Still over the cap once normalised, and path-like: unsure.
    denied(world, "mcp__fs__read", {"path": "/".join(["d" * 200] * 30)})
    allowed(world, "mcp__fs__read", {"text": "word " * 2000})  # long, but nothing path-like
    allowed(world, "mcp__fs__read", {"path": "./" * 3000 + "notes/n.md"})
    denied(world, "mcp__fs__read", {"path": "./" * 3000 + "notes/../notes/n.md"})  # `..`: unsure
    # Too many distinct path-like substrings to check in one call: unsure.
    denied(world, "mcp__fs__read", {"text": " ".join(f"a{i}.md" for i in range(6000))})
    allowed(world, "mcp__fs__read", {"text": " ".join(f"a{i}.md" for i in range(1000))})


def test_glob_home_from_hook_env(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1: `~` in a Glob pattern is the hook environment's HOME, not the process's."""
    elsewhere = world.tmp / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("HOME", str(elsewhere))
    home_phi = world.home / "phi"
    (world.vault / ".labbrain" / "config.yaml").write_text(protected_config(home_phi))
    entry = (1, str(home_phi))
    denied(world, "Glob", {"pattern": "~/phi/*.csv"}, entry=entry)
    denied(world, "Glob", {"pattern": "~/*/*.csv"}, entry=entry)
    allowed(world, "Glob", {"pattern": "~/notes/*.md"})
