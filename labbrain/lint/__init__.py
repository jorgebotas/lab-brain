"""Lint registry and runner.

Rules live in ``labbrain.lint.rules.*`` and register themselves with
``@rule``. Every rule is a pure function of a ``LintContext``; rule modules
are discovered automatically, so adding a rule never touches this file.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from labbrain.findings import Finding, sort_findings
from labbrain.vault import Vault
from labbrain.vault import today as _today


@dataclass
class LintContext:
    vault: Vault
    today: date
    base: str = "HEAD"
    cache: dict[str, Any] = field(default_factory=dict)


RuleFn = Callable[[LintContext], Iterable[Finding]]


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    description: str
    fn: RuleFn


RULES: dict[str, Rule] = {}


class UnknownRuleError(ValueError):
    """--rule named a rule that does not exist."""


def rule(name: str, severity: str, description: str) -> Callable[[RuleFn], RuleFn]:
    def register(fn: RuleFn) -> RuleFn:
        existing = RULES.get(name)
        if existing is not None and existing.fn is not fn:
            raise ValueError(f"duplicate lint rule: {name}")
        RULES[name] = Rule(name, severity, description, fn)
        return fn

    return register


_loaded = False


def load_rules() -> dict[str, Rule]:
    global _loaded
    if not _loaded:
        from labbrain.lint import rules as package

        for info in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package.__name__}.{info.name}")
        _loaded = True
    return RULES


def run(
    vault: Vault,
    *,
    today: date | None = None,
    base: str = "HEAD",
    only: Iterable[str] | None = None,
) -> list[Finding]:
    rules = load_rules()
    selected = set(only) if only else None
    if selected is not None and selected - set(rules):
        unknown = ", ".join(sorted(selected - set(rules)))
        raise UnknownRuleError(f"unknown lint rule(s): {unknown}")
    ctx = LintContext(vault=vault, today=today or _today(), base=base)
    findings: list[Finding] = []
    for name in sorted(rules):
        if selected is None or name in selected:
            findings.extend(rules[name].fn(ctx))
    return sort_findings(findings)
