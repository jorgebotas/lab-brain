"""frozen-edit: append-only notes may not be rewritten (diff against --base).

Only files git reports as changed are examined. Base versions are matched by
ID (filename), so a note moved between folders is compared, not reported as
deleted. The policy and the comparison live in labbrain.frozen, shared with the
frozen-file hook; field values never appear in messages.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from labbrain import gitutil
from labbrain.findings import ERROR, INFO, Finding
from labbrain.frozen import (
    POLICIES,
    RULE,
    DoneProtocolsAtBase,
    compare,
    frozen_at_base,
    parse_blob,
)
from labbrain.layout import RAW_DIR, is_note_rel
from labbrain.lint import LintContext, rule


def _raw_bytes_differ(path: Path, tree: dict[str, str], blobs: dict[str, bytes], rel: str) -> bool:
    if rel not in tree:
        return True
    try:
        return path.read_bytes() != blobs[tree[rel]]
    except OSError:
        return True


@rule(RULE, ERROR, "Frozen notes changed outside allowed fields, deleted, or raw/ files edited")
def frozen_edit(ctx: LintContext) -> Iterator[Finding]:
    # A base the caller named must be honoured; only the default HEAD may be skipped
    # (no repository, or a repository without commits).
    skipped = ERROR if ctx.base_explicit else INFO
    repo = gitutil.open_repo(ctx.vault.root)
    if repo is None:
        if ctx.base_explicit:
            message = "not a git repository, so --base cannot be used; frozen-edit could not run"
        else:
            message = "not a git repository; frozen-edit skipped"
        yield Finding("", 0, RULE, skipped, message)
        return
    try:
        base = gitutil.resolve_ref(repo, ctx.base)
        if base is None:
            outcome = "could not run" if ctx.base_explicit else "skipped"
            message = f"base revision {ctx.base} not found; frozen-edit {outcome}"
            findings = [Finding("", 0, RULE, skipped, message)]
        else:
            findings = list(_check(ctx, repo, base))
    except gitutil.GitError:
        message = "git failed while checking frozen notes; frozen-edit could not run"
        findings = [Finding("", 0, RULE, ERROR, message)]
    yield from findings


def _check(ctx: LintContext, repo: gitutil.Repo, base: str) -> Iterator[Finding]:
    """The diff-driven checks; may raise GitError, which the rule turns into one finding."""
    changes = gitutil.changed_files(repo, base)
    # Only existing raw/ files are immutable: additions are the ingest workflow, and a
    # modification counts only when the bytes differ (mode-only changes are allowed).
    raw_changes = [(s, rel) for s, rel in changes if rel.startswith(f"{RAW_DIR}/") and s != "A"]
    note_changes = [(s, rel) for s, rel in changes if s in ("M", "D", "T") and is_note_rel(rel)]
    raw_edits = [rel for s, rel in raw_changes if s in ("M", "T")]
    if not (raw_changes or note_changes):
        return
    tree = gitutil.ls_tree(repo, base) if raw_edits or note_changes else {}
    wanted = [rel for rel in raw_edits + [rel for _, rel in note_changes] if rel in tree]
    blobs = gitutil.read_blobs(repo, [tree[rel] for rel in wanted])
    for status, rel in raw_changes:
        if status == "D":
            yield Finding(rel, 0, RULE, ERROR, "raw/ files are immutable; this file was deleted")
        elif status in ("M", "T") and _raw_bytes_differ(ctx.vault.root / rel, tree, blobs, rel):
            yield Finding(rel, 0, RULE, ERROR, "raw/ files are immutable; this file was modified")
    if not note_changes:
        return
    done_protocols = DoneProtocolsAtBase(repo, tree)
    for status, rel in note_changes:
        if rel not in tree:
            continue
        base_note = parse_blob(blobs[tree[rel]], rel)
        policy = POLICIES.get(base_note.type or "")
        if policy is None or not frozen_at_base(base_note, policy, done_protocols):
            continue
        current = ctx.vault.get(base_note.stem) if status == "D" else ctx.vault.by_rel.get(rel)
        if current is None:
            message = f"frozen {base_note.type} {base_note.stem} was deleted; supersede it instead"
            yield Finding(rel, 0, RULE, ERROR, message)
            continue
        yield from compare(base_note, current, policy)
