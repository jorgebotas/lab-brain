"""The plugin manifests and skills stay consistent with the engine they call."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from labbrain import __version__
from labbrain.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
ENGINE = 'uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain'
ENGINE_RULES = (
    'Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)',
    "Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)",
)
SKILLS = ("brain-core", "brief", "decide", "exp-log", "handoff", "idea")
TAKES_ARGUMENTS = ("decide", "exp-log", "idea")
COMMAND = re.compile(r"\blabbrain ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")
# A shell assignment; `--title=…` is an option, not an assignment, so a preceding `-` is excluded.
ASSIGNMENT = re.compile(r"(?<![\w-])[A-Za-z_][A-Za-z0-9_]*=\S")
# A flag, with any attached `=value` captured separately so the flag itself is checked.
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)(=\S*)?")
# A quoted value separated from its option by a space; a value starting with `-` breaks it.
SPACED_VALUE = re.compile(r"(?<![\w-])--[a-z][a-z-]* '")
QUOTED = re.compile(r"'[^']*'")


def manifest(name: str) -> dict[str, Any]:
    return json.loads((REPO / ".claude-plugin" / name).read_text(encoding="utf-8"))


def skill(name: str) -> tuple[dict[str, Any], str]:
    text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), name
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_manifests_agree_with_pyproject() -> None:
    plugin, market = manifest("plugin.json"), manifest("marketplace.json")
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert plugin["name"] == market["name"] == "lab-brain"
    assert plugin["version"] == project["version"] == __version__ == "0.2.0"
    assert plugin["license"] == project["license"]
    assert plugin["author"]["name"] == project["authors"][0]["name"] == market["owner"]["name"]
    assert market["description"].strip()
    [entry] = market["plugins"]
    assert entry["name"] == plugin["name"]
    assert entry["source"] in ("./", ".")
    assert "version" not in entry


def test_skill_directories_are_exactly_the_six() -> None:
    assert sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir()) == sorted(SKILLS)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_frontmatter(name: str) -> None:
    meta, body = skill(name)
    assert meta["name"] == name
    assert isinstance(meta["description"], str) and meta["description"].strip()
    assert len(meta["description"]) <= 1536
    assert "disable-model-invocation" not in meta
    rules = meta["allowed-tools"]
    rules = rules if isinstance(rules, list) else [r.strip() for r in rules.split(",")]
    for rule in ENGINE_RULES:
        assert rule in rules, (name, rule)
    if name in TAKES_ARGUMENTS:
        assert meta.get("argument-hint") and "$ARGUMENTS" in body


@pytest.mark.parametrize("name", SKILLS)
def test_skill_commands_exist_in_the_cli(name: str) -> None:
    _, body = skill(name)
    top = subparsers(build_parser())
    found = COMMAND.findall(body)
    assert found, name
    for first, second in found:
        assert first in top, (name, first)
        nested = subparsers(top[first])
        if nested:
            assert second in nested, (name, first, second)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_commands_follow_the_shell_rules(name: str) -> None:
    _, body = skill(name)
    assert "$(" not in body
    for match in re.finditer(r"labbrain ", body):
        assert body[: match.start()].endswith('uvx --from "${CLAUDE_PLUGIN_ROOT}" '), (
            name,
            body[max(0, match.start() - 40) : match.end() + 20],
        )
    for line in body.splitlines():
        if "labbrain " in line:
            assert not ASSIGNMENT.search(QUOTED.sub("''", line)), (name, line)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_command_flags_exist_in_the_cli(name: str) -> None:
    _, body = skill(name)
    top = subparsers(build_parser())
    for match in COMMAND.finditer(body):
        first, second = match.groups()
        parser = top[first]
        nested = subparsers(parser)
        if nested:
            parser = nested[second]
        takes_value = {s: a.nargs != 0 for a in parser._actions for s in a.option_strings}
        rest = re.match(r"[^`\n]*", body[match.end() :])
        assert rest is not None
        assert not SPACED_VALUE.search(rest.group()), (name, match.group(), rest.group())
        for flag, value in FLAG.findall(QUOTED.sub("''", rest.group())):
            assert flag in takes_value, (name, match.group(), flag)
            assert takes_value[flag] or not value, (name, match.group(), flag)


def test_brain_core_is_short() -> None:
    lines = (REPO / "skills" / "brain-core" / "SKILL.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 80
