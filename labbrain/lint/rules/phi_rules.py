"""phi: PHI scan findings not covered by the allowlist (protected projects only)."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain import phi as phi_scan
from labbrain.findings import ERROR, Finding
from labbrain.lint import LintContext, rule


@rule("phi", ERROR, "phi-scan findings not in the allowlist (protected projects only)")
def phi(ctx: LintContext) -> Iterator[Finding]:
    config = ctx.vault.config
    if not config.protected_data:
        return
    root = ctx.vault.root
    yield from phi_scan.scan(
        [root],
        root=root,
        settings=phi_scan.ScanSettings.from_config(config, root),
        allow=phi_scan.load_allowlist(root),
        rule_name="phi",
    )
