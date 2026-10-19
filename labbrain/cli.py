"""`labbrain` command line: parse arguments, call the library, format output.

Only the standard library and labbrain.layout are imported at module level;
everything else is imported inside the command that needs it, because the
lab-brain hooks call this CLI on every tool use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from labbrain import __version__
from labbrain.layout import NOTE_TYPES

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


class UsageError(Exception):
    """Reported on stderr with exit code 2."""


# --- helpers ----------------------------------------------------------------------


def _root(args: argparse.Namespace) -> Path:
    from labbrain.vault import find_root

    return find_root(explicit=args.vault)


def _warn_version(config: Any) -> None:
    from labbrain.vault import version_warning

    warning = version_warning(config)
    if warning:
        print(f"labbrain: warning: {warning}", file=sys.stderr)


def _warn_root(root: Path) -> None:
    """The version warning for commands that need only the root (vault root, log).

    A broken config is left for the commands that use it to report.
    """
    from labbrain.vault import ConfigError, load_config

    try:
        config = load_config(root)
    except ConfigError:
        return
    _warn_version(config)


def _config(args: argparse.Namespace) -> tuple[Path, Any]:
    from labbrain.vault import load_config

    root = _root(args)
    config = load_config(root)
    _warn_version(config)
    return root, config


def _vault(args: argparse.Namespace) -> Any:
    from labbrain.vault import Vault

    root, config = _config(args)
    return Vault.load(root, config)


def _emit(findings: list[Any], fmt: str) -> int:
    from labbrain.findings import exit_code, render

    code = exit_code(findings)
    output = render(findings, fmt)
    try:
        if output:
            print(output)
        sys.stdout.flush()
    except BrokenPipeError:
        # A closed reader (`lint | head`) must not turn error findings into success:
        # CI shells run with pipefail.
        _detach_stdout()
    return code


def _now(at: str | None) -> datetime:
    from labbrain.vault import now

    if not at:
        return now()
    try:
        return datetime.fromisoformat(at)
    except ValueError as exc:
        raise UsageError("--at must be an ISO datetime") from exc


def _author(args: argparse.Namespace) -> str:
    author = args.author or os.environ.get("LABBRAIN_AUTHOR")
    if not author:
        raise UsageError("--author is required (or set LABBRAIN_AUTHOR)")
    return author


# --- commands ---------------------------------------------------------------------


def cmd_vault_root(args: argparse.Namespace) -> int:
    root = _root(args)
    _warn_root(root)
    print(root)
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    _, config = _config(args)
    data: Any = config.model_dump(mode="json")
    if args.key:
        for part in args.key.split("."):
            if not isinstance(data, dict) or part not in data:
                raise UsageError(f"no config key {args.key}")
            data = data[part]
        print(data if isinstance(data, str) else json.dumps(data))
    else:
        print(json.dumps(data, indent=2))
    return EXIT_OK


def cmd_new_id(args: argparse.Namespace) -> int:
    from labbrain.ids import IdError, new_id

    if args.type not in ("protocol", "handoff") and not args.title:
        raise UsageError(f"--title is required for {args.type} IDs")
    root, config = _config(args)
    try:
        note_id = new_id(
            args.type,
            root=root,
            now=_now(args.at),
            title=args.title,
            prefixes=config.id_prefixes,
            agent=args.agent or args.author or "",
            first_author=args.first_author,
            year=args.year,
            name=args.name,
        )
    except IdError as exc:
        raise UsageError(str(exc)) from exc
    print(note_id)
    return EXIT_OK


def cmd_new(args: argparse.Namespace) -> int:
    from labbrain.ids import IdError
    from labbrain.scaffold import create

    if not args.title:
        raise UsageError("--title is required")
    author = _author(args)
    root, config = _config(args)
    if args.summary and not config.is_agent(author):
        print("labbrain: note: --summary is ignored for human authors", file=sys.stderr)
    try:
        path = create(
            root,
            config,
            args.type,
            title=args.title,
            author=author,
            now=_now(args.at),
            links=args.link,
            agent=args.agent,
            first_author=args.first_author,
            year=args.year,
            name=args.name,
            summary=args.summary,
            body=args.body,
            tags=args.tag,
            status=args.status,
        )
    except IdError as exc:
        raise UsageError(str(exc)) from exc
    print(path)
    if args.finish:
        return _finish(args, [path], args.finish, author)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    from labbrain.validate import validate_paths

    configs: dict[Path, Any] = {}
    findings = validate_paths(args.paths, vault=args.vault, configs=configs)
    for config in configs.values():
        _warn_version(config)
    return _emit(findings, args.format)


def cmd_sync(args: argparse.Namespace) -> int:
    from labbrain.sync import apply, plan, report
    from labbrain.vault import today

    vault = _vault(args)
    changes, conflicts = plan(vault)
    failed = []
    if not args.dry_run:
        _, failed = apply(vault, changes, today())
    verb = "would update" if args.dry_run else "updated"
    return _emit(report(changes, conflicts, failed, verb=verb), args.format)


def cmd_index(args: argparse.Namespace) -> int:
    from labbrain.index import is_stale, write

    vault = _vault(args)
    if args.check:
        stale = is_stale(vault)
        if stale is None:
            print("index.md is missing; run `labbrain index`")
            return EXIT_FINDINGS
        if stale:
            print("index.md is out of date; run `labbrain index`")
            return EXIT_FINDINGS
        print("index.md is up to date")
        return EXIT_OK
    print("index.md updated" if write(vault) else "index.md already up to date")
    return EXIT_OK


def cmd_log(args: argparse.Namespace) -> int:
    from labbrain.log import append
    from labbrain.vault import now

    root = _root(args)
    _warn_root(root)
    try:
        path = append(root, args.text, when=now(), author=args.author)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(path)
    return EXIT_OK


def _check_base(root: Path, base: str) -> None:
    """A --base the user typed must name a commit; a git failure is left to frozen-edit."""
    from labbrain import gitutil

    repo = gitutil.open_repo(root)
    if repo is None:
        raise UsageError("--base needs the vault to be inside a git repository")
    try:
        found = gitutil.resolve_ref(repo, base)
    except gitutil.GitError:
        return
    if found is None:
        raise UsageError("--base does not name a commit in the vault's repository")


def cmd_lint(args: argparse.Namespace) -> int:
    from labbrain import lint

    vault = _vault(args)
    if args.base is not None:
        _check_base(vault.root, args.base)
    try:
        findings = lint.run(vault, base=args.base, only=args.rule or None)
    except lint.UnknownRuleError as exc:
        raise UsageError(str(exc)) from exc
    return _emit(findings, args.format)


def cmd_phi_scan(args: argparse.Namespace) -> int:
    from labbrain.phi import ScanSettings, load_allowlist, scan
    from labbrain.vault import default_config, find_root_or_none, load_config

    paths = [p.expanduser().resolve() for p in args.paths]
    for path in paths:
        if not path.exists():
            raise UsageError(f"no such file or directory: {path.name}")
    start = paths[0] if paths[0].is_dir() else paths[0].parent
    root = find_root_or_none(start=start, explicit=args.vault)
    if root is None:
        config = default_config()
    else:
        config = load_config(root)
        _warn_version(config)
    settings = ScanSettings.from_config(config, root)
    return _emit(scan(paths, root=root, settings=settings, allow=load_allowlist(root)), args.format)


def cmd_list(args: argparse.Namespace) -> int:
    from labbrain.findings import strip_controls
    from labbrain.query import list_notes

    rows = list_notes(_vault(args), note_type=args.note_type, status=args.status, tag=args.tag)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            # Titles are free text: no control characters (terminal escapes, line breaks).
            cells = (row["id"], row["type"], row["status"] or "", row["title"] or "")
            print("\t".join(" ".join(strip_controls(str(c)).split()) for c in cells))
    return EXIT_OK


def cmd_links(args: argparse.Namespace) -> int:
    from labbrain.query import links

    try:
        data = links(_vault(args), args.id)
    except KeyError as exc:
        raise UsageError(f"no note with ID {args.id}") from exc
    directions = [args.direction] if args.direction else ["in", "out"]
    if args.json:
        print(json.dumps({"id": data["id"], **{d: data[d] for d in directions}}, indent=2))
    else:
        for direction in directions:
            for target in data[direction]:
                print(f"{direction}\t{target}")
    return EXIT_OK


def cmd_config_hash(args: argparse.Namespace) -> int:
    from labbrain.confighash import config_hash, load_run_config
    from labbrain.vault import DEFAULT_HASH_IGNORE, find_root_or_none, load_config

    root = find_root_or_none(explicit=args.vault)
    if root is None:
        ignore = DEFAULT_HASH_IGNORE
    else:
        config = load_config(root)
        _warn_version(config)
        ignore = config.hash_ignore
    try:
        data = load_run_config(args.file)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(config_hash(data, ignore))
    return EXIT_OK


def cmd_schema(args: argparse.Namespace) -> int:
    from labbrain.schema import json_schema

    print(json.dumps(json_schema(args.type), indent=2))
    return EXIT_OK


def _finish(args: argparse.Namespace, paths: list[Path], text: str, author: str | None) -> int:
    from labbrain.finish import finish
    from labbrain.vault import now

    result = finish(paths, log_text=text, author=author, when=now(), vault=args.vault)
    code = _emit(result.findings, "text")
    if result.index_updated is not None:
        print("index.md updated" if result.index_updated else "index.md already up to date")
    return code


def cmd_finish(args: argparse.Namespace) -> int:
    return _finish(args, args.paths, args.log, args.author or os.environ.get("LABBRAIN_AUTHOR"))


def cmd_brief(args: argparse.Namespace) -> int:
    from labbrain import lint
    from labbrain.brief import build_brief
    from labbrain.vault import Vault, load_config, version_warning

    root = _root(args)
    config = load_config(root)  # no stderr warning: the brief prints it once itself
    vault = Vault.load(root, config)
    text = build_brief(vault, lint.run(vault), short=args.short, warning=version_warning(config))
    print(text, end="")
    return EXIT_OK


def cmd_tracker_fetch(args: argparse.Namespace) -> int:
    from labbrain.trackers import describe, get_adapter

    root, config = _config(args)
    records = get_adapter(config, root).fetch(args.runs)
    print(json.dumps([describe(r, config) for r in records], indent=2, default=str))
    return EXIT_OK


def cmd_code_sha(args: argparse.Namespace) -> int:
    from labbrain.codeinfo import code_sha
    from labbrain.vault import resolve_config_path

    root, config = _config(args)
    if args.repo:
        label, path = args.repo, Path(args.repo).expanduser()
    elif config.code_repo.strip():
        label, path = config.code_repo, resolve_config_path(root, config.code_repo)
    else:
        raise UsageError("code repo not set")
    info = code_sha(path, exclude=root)
    print(json.dumps({"repo": label, "sha": info.sha, "dirty": info.dirty}))
    return EXIT_OK


# --- parser -----------------------------------------------------------------------


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    parser.add_argument(
        "--json", dest="format", action="store_const", const="json", help="same as --format json"
    )


def _add_id_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("type", choices=NOTE_TYPES)
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default=None)
    parser.add_argument("--agent", default="", help="handoff IDs: agent name (default: author)")
    parser.add_argument("--first-author", default="", help="literature IDs: first author surname")
    parser.add_argument("--year", type=int, help="literature IDs: publication year")
    parser.add_argument("--name", default="", help="protocol IDs: optional EVAL-v<N>-<name>")
    parser.add_argument("--at", default=None, help="ISO datetime to use instead of now")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labbrain", description="Tools for lab-brain vaults.")
    parser.add_argument("--version", action="version", version=f"labbrain {__version__}")
    parser.add_argument("--vault", type=Path, help="vault root (overrides LABBRAIN_VAULT)")
    # Subcommands accept --vault too, because pre-commit appends hook args after the
    # subcommand. SUPPRESS keeps a subcommand from resetting a top-level --vault.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    vault = add("vault", "vault commands")
    vault_sub = vault.add_subparsers(dest="vault_command", required=True)
    root_cmd = vault_sub.add_parser("root", help="print the vault root", parents=[common])
    root_cmd.set_defaults(func=cmd_vault_root)

    p = add("config", "print the resolved config as JSON")
    p.add_argument("--key", help="dotted key, e.g. tracker.backend")
    p.set_defaults(func=cmd_config)

    p = add("new-id", "print a fresh, collision-free ID")
    _add_id_options(p)
    p.set_defaults(func=cmd_new_id)

    p = add("new", "create a skeleton note and print its path")
    _add_id_options(p)
    p.add_argument("--link", action="append", default=[], help="ID to put in `links` (repeatable)")
    p.add_argument("--summary", default="", help="one line for the For-future-agents block")
    p.add_argument("--body", default="", help="text placed before the required sections")
    p.add_argument("--tag", action="append", default=[], help="tag (repeatable)")
    p.add_argument("--status", default=None, help="initial status (default: the type's default)")
    p.add_argument("--finish", default="", help="then run `finish` with this log text")
    p.set_defaults(func=cmd_new)

    p = add("validate", "check single files (used by the write hook)")
    p.add_argument("paths", nargs="+", type=Path)
    _add_format(p)
    p.set_defaults(func=cmd_validate)

    p = add("sync", "propagate supersession and freeze referenced protocols")
    p.add_argument("--dry-run", action="store_true")
    _add_format(p)
    p.set_defaults(func=cmd_sync)

    p = add("index", "regenerate index.md")
    p.add_argument("--check", action="store_true", help="exit 1 if index.md would change")
    p.set_defaults(func=cmd_index)

    p = add("log", "append a line to today's log")
    p.add_argument("text")
    p.add_argument("--author")
    p.set_defaults(func=cmd_log)

    p = add("lint", "run every lint rule over the vault")
    p.add_argument(
        "--base",
        default=None,
        help="git revision frozen-edit compares against (default HEAD; a named base must exist)",
    )
    p.add_argument("--rule", action="append", default=[], help="run only this rule (repeatable)")
    _add_format(p)
    p.set_defaults(func=cmd_lint)

    p = add("phi-scan", "scan files or directories for PHI")
    p.add_argument("paths", nargs="+", type=Path)
    _add_format(p)
    p.set_defaults(func=cmd_phi_scan)

    p = add("list", "list notes")
    p.add_argument("--type", dest="note_type", choices=NOTE_TYPES)
    p.add_argument("--status")
    p.add_argument("--tag")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = add("links", "inbound and outbound links of a note")
    p.add_argument("id")
    direction = p.add_mutually_exclusive_group()
    direction.add_argument("--in", dest="direction", action="store_const", const="in")
    direction.add_argument("--out", dest="direction", action="store_const", const="out")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_links, direction=None)

    p = add("config-hash", "hash a run config the way experiments record it")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_config_hash)

    p = add("schema", "print the JSON Schema of the frontmatter models")
    p.add_argument("type", nargs="?", choices=NOTE_TYPES)
    p.set_defaults(func=cmd_schema)

    p = add("finish", "validate written notes, then sync, regenerate the index and log")
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--log", required=True, help="text for today's log")
    p.add_argument("--author")
    p.set_defaults(func=cmd_finish)

    p = add("brief", "print where the project stands")
    p.add_argument("--short", action="store_true", help="at most four lines (SessionStart hook)")
    p.set_defaults(func=cmd_brief)

    tracker = add("tracker", "tracker commands")
    tracker_sub = tracker.add_subparsers(dest="tracker_command", required=True)
    p = tracker_sub.add_parser("fetch", help="print runs as JSON", parents=[common])
    p.add_argument("runs", nargs="+", metavar="RUN")
    p.set_defaults(func=cmd_tracker_fetch)

    code = add("code", "code repository commands")
    code_sub = code.add_subparsers(dest="code_command", required=True)
    p = code_sub.add_parser(
        "sha", help="print the code repo's commit and dirty flag", parents=[common]
    )
    p.add_argument("--repo", help="code repository (default: code_repo from config)")
    p.set_defaults(func=cmd_code_sha)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from labbrain.errors import EngineError
    from labbrain.vault import ConfigError, VaultNotFound

    try:
        code = int(args.func(args))
    except (VaultNotFound, ConfigError, UsageError, EngineError) as exc:
        print(f"labbrain: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        # The reader went away (e.g. `labbrain list | head`) from a command without
        # findings; finding commands keep their exit code in _emit.
        _detach_stdout()
        return EXIT_OK
    except Exception as exc:
        # Only the type: messages and tracebacks can quote file content.
        print(f"labbrain: internal error ({type(exc).__name__})", file=sys.stderr)
        return EXIT_USAGE
    try:
        # Flush here, not at interpreter exit, so a closed pipe cannot print
        # "Exception ignored" and exit 120, and `index --check` keeps its 1.
        sys.stdout.flush()
    except BrokenPipeError:
        _detach_stdout()
    return code


def _detach_stdout() -> None:
    """Point stdout at /dev/null so the interpreter's final flush cannot fail again."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    except (OSError, ValueError):  # stdout is not a real file (e.g. captured)
        pass


def run() -> None:
    sys.exit(main())
