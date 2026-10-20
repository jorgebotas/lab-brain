"""The SessionStart brief (spec section 8).

On every SessionStart source: find the vault (none: print nothing), regenerate `index.md`,
and print the short brief on stdout, which Claude Code adds to the session's context. A
vault config that fails to load prints one fixed line instead; the guard blocks other calls
until it is fixed. Any other failure is left to the entry point, which exits 2.
"""

from __future__ import annotations

from collections.abc import Mapping

from labbrain.hooks.payload import Payload
from labbrain.hooks.scope import find_vault_roots

CONFIG_ERROR = (
    "lab-brain: vault config error; ask the user to fix .labbrain/config.yaml "
    "(`labbrain lint` shows the problem)\n"
)
INDEX_FAILED = "index.md could not be regenerated\n"


def session_start(payload: Payload, env: Mapping[str, str]) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) for a session start: the short brief on stdout."""
    roots = find_vault_roots(payload.cwd, env)
    if not roots:
        return 0, "", ""
    root = roots[0]

    from labbrain import index, lint
    from labbrain.brief import build_brief
    from labbrain.vault import Vault, load_config, version_warning

    try:
        config = load_config(root)
    except Exception:  # any load failure; its text can quote the config, so it is not shown
        return 0, CONFIG_ERROR, ""
    vault = Vault.load(root, config)
    try:
        index.write(vault)
        index_ok = True
    except Exception:
        index_ok = False
    text = build_brief(vault, lint.run(vault), short=True, warning=version_warning(config))
    return 0, text if index_ok else text + INDEX_FAILED, ""
