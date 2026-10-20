"""The vaults a hook call sees, with their protected roots and guard files.

Finding vaults uses only the standard library, so a call outside any vault never imports
pydantic. `labbrain.vault` is imported only once at least one vault has been found.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from labbrain.hooks.paths import GuardFile, ProtectedRoot, Targets, canonical
from labbrain.layout import CONFIG_PATH

if TYPE_CHECKING:
    from labbrain.vault import Config

ENV_PROJECT_DIR = "CLAUDE_PROJECT_DIR"
ENV_VAULT = "LABBRAIN_VAULT"
ENV_PLUGIN_ROOT = "CLAUDE_PLUGIN_ROOT"
SETTINGS_FILES = ("settings.json", "settings.local.json")


def _is_vault(path: Path) -> bool:
    return (path / CONFIG_PATH).is_file()


def _vault_from(start: Path) -> Path | None:
    """The nearest of `start` and its ancestors that is a vault (`start` is canonical)."""
    for candidate in (start, *start.parents):
        if _is_vault(candidate):
            return candidate
    return None


def vault_of(path: Path) -> Path | None:
    """The vault containing `path`, searching up from its parent."""
    return _vault_from(canonical(path).parent)


def find_vault_roots(cwd: Path, env: Mapping[str, str]) -> list[Path]:
    """The vaults in scope, canonical and deduplicated, in this order:

    the vault containing `cwd`; the vault containing `$CLAUDE_PROJECT_DIR`; and
    `$LABBRAIN_VAULT`, a relative value being taken from `$CLAUDE_PROJECT_DIR` (Bash's cwd
    moves during a session) or, without one, from `cwd`. A `$LABBRAIN_VAULT` that is not a
    vault is ignored.
    """
    here = canonical(cwd)
    project = env.get(ENV_PROJECT_DIR) or ""
    project_dir = canonical(project, here) if project else None
    found: list[Path | None] = [_vault_from(here)]
    if project_dir is not None:
        found.append(_vault_from(project_dir))
    named = env.get(ENV_VAULT) or ""
    if named:
        explicit = canonical(named, project_dir or here)
        found.append(explicit if _is_vault(explicit) else None)
    roots: list[Path] = []
    for root in found:
        if root is not None and root not in roots:
            roots.append(root)
    return roots


@dataclass(frozen=True)
class VaultInfo:
    root: Path
    config: Config | None  # None when broken
    broken: bool  # the config failed to load (or its data paths failed to resolve)


@dataclass(frozen=True)
class Scope:
    vaults: tuple[VaultInfo, ...]
    targets: Targets
    agents: frozenset[str]  # union of the configs' `agents`
    protected: bool  # a vault has protected_data with >= 1 data path, or a vault is broken
    project_dir: Path | None
    env: Mapping[str, str]  # the hook's environment, as given to load_scope

    @property
    def broken(self) -> tuple[VaultInfo, ...]:
        return tuple(v for v in self.vaults if v.broken)


def _data_roots(root: Path, config: Config) -> list[ProtectedRoot]:
    """The vault's protected roots; none unless `protected_data` is on."""
    from labbrain.vault import resolve_config_path

    if not config.protected_data:
        return []
    return [
        ProtectedRoot(root, index, entry, canonical(resolve_config_path(root, entry)))
        for index, entry in enumerate(config.data_paths, start=1)
        if entry.strip()
    ]


def _home(env: Mapping[str, str]) -> Path:
    home = env.get("HOME")
    return canonical(home) if home else Path.home().resolve()


def _guard_files(
    vaults: tuple[VaultInfo, ...], project_dir: Path | None, env: Mapping[str, str]
) -> list[GuardFile]:
    """Files whose change could switch the guard off (spec section 5, self-protection)."""
    home = _home(env)
    files: list[GuardFile] = []
    settings_bases = [v.root / ".claude" for v in vaults]
    if project_dir is not None:
        settings_bases.append(project_dir / ".claude")
    settings_bases.append(home / ".claude")
    for vault in vaults:
        files.append(GuardFile(vault.root / ".labbrain", True))
        files.append(GuardFile(vault.root / ".copier-answers.yml", False))
    for base in settings_bases:
        files.extend(GuardFile(canonical(base / name), False) for name in SETTINGS_FILES)
    trees = [home / ".claude" / "plugins"]
    if env.get(ENV_PLUGIN_ROOT):
        trees.append(canonical(env[ENV_PLUGIN_ROOT], home))
    if env.get("UV_CACHE_DIR"):
        trees.append(canonical(env["UV_CACHE_DIR"], home))
    else:
        trees.append(home / ".cache" / "uv")
        if env.get("XDG_CACHE_HOME"):
            trees.append(canonical(Path(env["XDG_CACHE_HOME"]) / "uv", home))
    files.extend(GuardFile(canonical(tree), True) for tree in trees)
    return files


def load_scope(cwd: Path, env: Mapping[str, str]) -> Scope:
    """The scope of a hook call whose payload cwd is `cwd`."""
    project = env.get(ENV_PROJECT_DIR) or ""
    project_dir = canonical(project, canonical(cwd)) if project else None
    roots = find_vault_roots(cwd, env)
    if not roots:
        return Scope((), Targets((), ()), frozenset(), False, project_dir, env)

    from labbrain.vault import load_config

    vaults: list[VaultInfo] = []
    protected_roots: list[ProtectedRoot] = []
    agents: set[str] = set()
    protected = False
    for root in roots:
        try:
            config = load_config(root)
            found = _data_roots(root, config)
        except Exception:  # any failure: protected, with unknown data paths
            vaults.append(VaultInfo(root, None, True))
            protected = True
            continue
        vaults.append(VaultInfo(root, config, False))
        agents.update(config.agents)
        protected_roots.extend(found)
        protected = protected or bool(found)
    infos = tuple(vaults)
    guard = _guard_files(infos, project_dir, env) if protected else []
    return Scope(
        infos, Targets(protected_roots, guard), frozenset(agents), protected, project_dir, env
    )
