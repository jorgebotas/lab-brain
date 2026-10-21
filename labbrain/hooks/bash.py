"""The Bash rules of the data guard and the Bash half of guard self-protection (spec §5).

Every rule over-approximates: a false positive costs the agent a rephrased command, a false
negative lets individual-level data into the session. The command is never executed or
modelled exactly. Instead:

- a quote-aware pre-pass marks shell expansions (variables, `$(…)`, backticks), sets
  heredoc bodies and comments aside, and collects the text of nested commands
  (substitutions, `sh -c`, `eval`) for analysis in their own right;
- `shlex` splits the marked text into words and simple commands;
- every word, and every path-like run of the raw text, is a candidate path, expanded and
  resolved against every directory the command could run in.

Denial messages are fixed strings or `data_denial`; they never quote the command or a path.
"""

from __future__ import annotations

import fnmatch
import glob
import itertools
import os
import pwd
import re
import shlex
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from labbrain.gitutil import HOOK_GIT_OPTIONS
from labbrain.hooks.exposure import links_under
from labbrain.hooks.paths import (
    STICKY,
    Budget,
    ProtectedRoot,
    TextTooLarge,
    canonical,
    fold,
    loose_runs,
    path_runs,
    readings,
    spellings,
    sticky_pieces,
    suffixes,
)
from labbrain.hooks.payload import Denial, data_denial, unchecked_denial
from labbrain.hooks.scope import ENV_PLUGIN_ROOT, Scope

SUBJECT = "this Bash command"
GUARD_MESSAGE = (
    "lab-brain guard: this Bash command would change lab-brain or Claude Code guard "
    "settings, or start a nested agent, in a protected vault. Ask the user to run it."
)
UNCONFIDENT_MESSAGE = (
    "lab-brain data guard: this Bash command cannot be checked safely (it uses an "
    "unresolved variable, a command substitution, or dynamic evaluation) in a protected "
    "vault. Spell paths out, or ask the user to run it themselves."
)


# --------------------------------------------------------------------------- program lists
# Every program and flag list of the Bash rules lives here. Program names are compared by
# casefolded basename (a case-insensitive filesystem runs `GREP` as grep).


@dataclass(frozen=True)
class Flags:
    """When a program's arguments switch a behaviour on.

    `short` letters match alone or inside a cluster (`-rn`), `long` names match `--name`
    or `--name=value` (a trailing `*` matches a prefix), `exact` matches whole words.
    `always` switches it on with no flag, unless an `unless`/`unless_long` flag is present.
    """

    short: str = ""
    long: frozenset[str] = frozenset()
    exact: frozenset[str] = frozenset()
    always: bool = False
    unless: str = ""
    unless_long: frozenset[str] = frozenset()

    def match(self, args: Sequence[str]) -> bool:
        if self.always:
            return not _has_flag(args, self.unless, self.unless_long, frozenset())
        return _has_flag(args, self.short, self.long, self.exact)


def _has_flag(args: Sequence[str], short: str, long: frozenset[str], exact: frozenset[str]) -> bool:
    for arg in args:
        if arg in exact:
            return True
        if arg.startswith("--"):
            name = arg[2:].split("=", 1)[0]
            if any(name == n or (n.endswith("*") and name.startswith(n[:-1])) for n in long):
                return True
        elif arg.startswith("-") and len(arg) > 1 and any(c in short for c in arg[1:]):
            return True
    return False


ALWAYS = Flags(always=True)
_GREP_RECURSIVE = Flags(
    "rR", frozenset({"recursive", "dereference-recursive"}), frozenset({"recurse"})
)
_GREP_FOLLOWING = Flags("RS", frozenset({"dereference-recursive"}))

# Rule 6: constructs that read a whole tree below their start directories.
RECURSIVE: Mapping[str, Flags] = {
    "grep": _GREP_RECURSIVE,
    "egrep": _GREP_RECURSIVE,
    "fgrep": _GREP_RECURSIVE,
    "ugrep": _GREP_RECURSIVE,
    "ug": ALWAYS,
    "rg": ALWAYS,
    "ag": ALWAYS,
    "ack": ALWAYS,
    "pt": ALWAYS,
    "find": ALWAYS,
    "fd": ALWAYS,
    "fdfind": ALWAYS,
    "tree": ALWAYS,
    "du": ALWAYS,
    "tar": ALWAYS,
    "zip": ALWAYS,
    "rsync": ALWAYS,
    "fzf": ALWAYS,
    "ls": Flags("R", frozenset({"recursive"})),
    "eza": Flags("RT", frozenset({"recurse", "tree"})),
    "exa": Flags("RT", frozenset({"recurse", "tree"})),
    "lsd": Flags("R", frozenset({"recursive", "tree"})),
    "scp": Flags("r"),
    "cp": Flags("rRa", frozenset({"recursive", "archive"})),
    "git grep": ALWAYS,
    "git ls-files": ALWAYS,
    "git status": Flags("u", frozenset({"untracked-files", "ignored"})),
}

# Rule 6b: recursive constructs that follow symlinks.
FOLLOWING: Mapping[str, Flags] = {
    "grep": _GREP_FOLLOWING,
    "egrep": _GREP_FOLLOWING,
    "fgrep": _GREP_FOLLOWING,
    "ugrep": _GREP_FOLLOWING,
    "ug": _GREP_FOLLOWING,
    "rg": Flags("L", frozenset({"follow"})),
    "ag": Flags("f", frozenset({"follow"})),
    "ack": Flags("", frozenset({"follow"})),
    "find": Flags("LH", exact=frozenset({"-follow"})),
    "fd": Flags("L", frozenset({"follow"})),
    "fdfind": Flags("L", frozenset({"follow"})),
    "tree": Flags("l"),
    "du": Flags("L", frozenset({"dereference"})),
    "ls": Flags("L", frozenset({"dereference"})),
    "cp": Flags("LH", frozenset({"dereference"})),
    "rsync": Flags("Lk", frozenset({"copy-links", "copy-dirlinks", "copy-unsafe-links"})),
    "tar": Flags("h", frozenset({"dereference"})),
    "zip": Flags(always=True, unless="y", unless_long=frozenset({"symlinks"})),
    "scp": ALWAYS,
    "fzf": ALWAYS,
}

# Inline-code interpreters: recursive and link-following whenever they run inline code.
INTERPRETERS: frozenset[str] = frozenset(
    {
        "python",
        "pypy",
        "node",
        "nodejs",
        "deno",
        "bun",
        "perl",
        "ruby",
        "rscript",
        "r",
        "julia",
        "php",
        "lua",
        "duckdb",
        "sqlite3",
    }
)
INLINE: Mapping[str, Flags] = {
    "python": Flags("c"),
    "pypy": Flags("c"),
    "node": Flags("ep", frozenset({"eval", "print"})),
    "nodejs": Flags("ep", frozenset({"eval", "print"})),
    "deno": Flags("", exact=frozenset({"eval", "repl"})),
    "bun": Flags("ep", frozenset({"eval", "print"})),
    "perl": Flags("eE"),
    "ruby": Flags("e"),
    "rscript": Flags("e"),
    "r": Flags("e"),
    "julia": Flags("eE", frozenset({"eval", "print"})),
    "php": Flags("r", frozenset({"run"})),
    "lua": Flags("e"),
    "duckdb": ALWAYS,
    "sqlite3": ALWAYS,
}
# Interpreter options whose value is the next word (so it is not the script).
INTERPRETER_VALUES: frozenset[str] = frozenset({"-W", "-X", "-I", "-M", "-r", "--require"})

# Rule 6a's exception: rg flags that disable ignore files, follow links or override ignores.
RG_IGNORE_OFF = Flags(
    "uLg", frozenset({"no-ignore*", "unrestricted", "follow", "glob", "iglob", "no-config"})
)
RG_IGNORE_FILES = (".ignore", ".rgignore")

SHELLS: frozenset[str] = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "csh", "tcsh", "ash", "busybox"}
)
# Rule 8: dynamic evaluation makes a command unconfident.
UNCONFIDENT_PROGRAMS: frozenset[str] = (
    frozenset({"eval", "exec", "source", ".", "xargs", "base64", "alias"}) | SHELLS
)
UNCONFIDENT_WORDS: tuple[str, ...] = ("eval", "exec", "source", "xargs", "base64")

# Program words: wrappers run the rest of the line as a command; their value-taking options.
WRAPPERS: Mapping[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "command": frozenset(),
    "builtin": frozenset(),
    "nice": frozenset({"-n", "--adjustment"}),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "sudo": frozenset(
        {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "--user", "--group", "--chdir"}
    ),
    "doas": frozenset({"-u", "-C"}),
    "xargs": frozenset(
        {"-I", "-L", "-n", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-procs"}
        | {"--delimiter", "--arg-file", "--replace"}
    ),
    "nohup": frozenset(),
    "exec": frozenset({"-a"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "caffeinate": frozenset({"-t", "-w"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
    "unbuffer": frozenset(),
    "chronic": frozenset(),
    "setsid": frozenset(),
    "noglob": frozenset(),
    "nocorrect": frozenset(),
    "watch": frozenset({"-n", "--interval"}),
}
WRAPPER_POSITIONALS: Mapping[str, int] = {"timeout": 1}
KEYWORDS: frozenset[str] = frozenset(
    {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
    | {"case", "esac", "coproc"}
)
# Runners start another program: (subcommands that lead to it, value-taking options).
RUNNERS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "uvx": (
        frozenset(),
        frozenset({"--from", "--with", "-w", "--python", "-p", "--index", "--index-url"}),
    ),
    "uv": (
        frozenset({"run", "tool"}),
        frozenset({"--with", "-w", "--python", "-p", "--project", "--directory", "--package"})
        | frozenset({"--group", "--extra", "--env-file", "--index", "--from"}),
    ),
    "pipx": (frozenset({"run"}), frozenset({"--spec", "--python"})),
    "npx": (frozenset(), frozenset({"-p", "--package"})),
    "bunx": (frozenset(), frozenset({"-p", "--package"})),
    "pnpx": (frozenset(), frozenset()),
    "pnpm": (frozenset({"dlx", "exec"}), frozenset()),
    "yarn": (frozenset({"dlx", "exec"}), frozenset()),
    "poetry": (frozenset({"run"}), frozenset()),
    "pipenv": (frozenset({"run"}), frozenset()),
    "pdm": (frozenset({"run"}), frozenset()),
    "hatch": (frozenset({"run"}), frozenset()),
    "pixi": (frozenset({"run"}), frozenset({"-e", "--environment"})),
    "rye": (frozenset({"run"}), frozenset()),
    "conda": (frozenset({"run"}), frozenset({"-n", "--name", "-p", "--prefix"})),
    "mamba": (frozenset({"run"}), frozenset({"-n", "--name", "-p", "--prefix"})),
    "micromamba": (frozenset({"run"}), frozenset({"-n", "--name", "-p", "--prefix"})),
}
GIT_VALUES: frozenset[str] = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"}
)
# Options naming a directory the program changes into (rule 3).
DIRECTORY_OPTIONS: frozenset[str] = frozenset({"-C", "--directory", "--cwd", "--chdir"})
CD_PROGRAMS: frozenset[str] = frozenset({"cd", "pushd"})

# Guard self-protection.
DEFAULT_AGENTS: frozenset[str] = frozenset({"claude"})
REPLACERS: frozenset[str] = frozenset({"mv", "rm", "rmdir", "unlink", "ln"})
DANGEROUS_ASSIGNMENTS: frozenset[str] = frozenset({"HOME", "CDPATH", "PWD", "OLDPWD"})
BINDING_PROGRAMS: frozenset[str] = frozenset(
    {"read", "unset", "mapfile", "readarray", "getopts", "printf", "for", "select"}
    | {"declare", "typeset", "local"}
)
EXPORTERS: frozenset[str] = frozenset({"export", "declare", "typeset", "local", "readonly"})

# Bounds. Exceeding one makes the command unconfident (denied), never silently unchecked.
MAX_DEPTH = 6
MAX_ALTERNATIVES = 64
MAX_BASES = 64
MAX_CANDIDATES = 20_000
MAX_BRACE_GROUPS = 16
PATH_LIMIT = 4096  # longer candidates cannot be opened as paths (ENAMETOOLONG)
LEX_LIMIT = 64 * 1024  # shlex is quadratic on long tokens; longer text uses _tokenize
GLOB_LIMIT = 2_000
MAX_READINGS = 10_000  # distinct (candidate, base) pairs resolved in one command (item 1)
GIT_TIMEOUT = 5.0

# ------------------------------------------------------------------------------- lexing

_VAR = "\ue000"  # _VAR NAME _END marks a variable reference
_END = "\ue001"
WILD = "\ue002"  # a value nothing can bind: an unknown variable, a substitution
_PUNCT = "();<>|&\n"
_SEPARATORS = set(";|()&\n")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\+?)=")
_SPECIAL = set("?#$!@*-0123456789")
# Rulings R27b, R29 and R32: special parameters. `$? $# $$ $! $-` (zsh's `$?` can be
# negative) are marked _SHORT. `$0`-`$9`, `${n}` and `$@` each hold one word of the command
# (or WILD): marked _POSITIONAL. `$*` joins them all with IFS: WILD. zsh reads `$#` before
# a name or a special character as a length that swallows it (`$#hi`, `$#?`): _REST makes
# the rest of the word WILD. The marks survive binding (`rc=$?`, `for f in "$@"`), and
# `_params` resolves them where a word is used, after expansion.
_SHORT = "\ue005"
_POSITIONAL = "\ue006"
_REST = "\ue007"
_SHORT_PARAMS = {**dict.fromkeys("?#$!-", _SHORT), "*": WILD, "@": _POSITIONAL}
_SHORT_PARAMS.update(dict.fromkeys("0123456789", _POSITIONAL))
_ZSH_LENGTH = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_?$*@#-")
# R33b: zsh's unbraced flag forms, a run of = ~ ^ +, an optional #, then a name or special.
_ZSH_FLAGGED = re.compile(r"[=~^+]+#?(?:[A-Za-z_][A-Za-z0-9_]*|[0-9?#$!@*-])")
# R33c: the pieces a candidate is split into (`_PIECE_SPLIT`) and the text between them.
_MARKS = re.compile("[\ue000-\ue007]")  # the pre-pass's own marks: never in a command
# Ruling R19b: a whole-word `"$(cat <<'EOF' … EOF)"` stands for its literal heredoc body;
# the pre-pass marks it _VAR _LOCAL k _END, which _Check.parse renumbers _VAR _LIT k _END.
_LOCAL = "\ue004"
_LIT = "\ue003"
_LOCAL_REF = re.compile(f"{_VAR}{_LOCAL}([0-9]+){_END}")
_MARKER = re.compile(f"({_VAR}[A-Za-z0-9_{_LIT}]*{_END})")
# R19b: the only literal form, `"$(cat <<'EOF'` (or <<"EOF") as a whole word.
_QUOTED_HEREDOC = re.compile(r"cat[ \t]+<<[ \t]*(['\"])([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n")
_WORD_BOUNDARY = set(" \t\n;&|()<>")
_LIT_REF = re.compile(f"{_VAR}{_LIT}[0-9]+{_END}")
# R19c(c): a command that could redefine `cat` (or what runs as it) gets no literals.
_FUNCTION_DEF = re.compile(r"(?:^|[\s;&|(){}])function\s+\S|[^\s;&|(){}<>]\s*\(\s*\)")
LITERAL_SPOILERS: tuple[str, ...] = ("alias", "unalias", "shopt", "enable", "hash")
# R19d(a): literals need a command with no assignment: NAME=, NAME+=, NAME[x]=, NAME:=, and
# arithmetic's `NAME = 3` or `NAME <<= 3`, at a word's start or after punctuation, in each
# lexed word and in the marked text. Comparisons count too. R19d(c): and no carriage return.
_ANY_ASSIGN = re.compile(r"(?:^|[^\w./-])[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\s*[-+*/%&|^:<>]*=")
# R19e: and every program word, bar the literal form's own `cat`, is `git` or `gh` running
# one of these built-in subcommands (an alias or a git-x / gh extension could be anything),
# with no git option that changes configuration or where git finds its programs.
# (Not push, fetch or pull: --receive-pack, --upload-pack and --exec run their value.)
LITERAL_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {"add", "commit", "tag", "notes", "merge", "stash", "status", "diff", "log", "show"}
    | {"checkout", "switch", "branch", "restore", "reset", "rm", "mv"}
)
LITERAL_GH_SUBCOMMANDS: frozenset[str] = frozenset(
    {"pr", "issue", "release", "label", "run", "workflow", "api", "status", "search"}
    | {"browse"}  # not repo or gist: `gh repo clone … -- <git flags>`
)
LITERAL_GIT_UNSAFE: tuple[str, ...] = ("-c", "--config-env", "--exec-path")
# Raw-text runs are `paths.path_runs`; R17's sticky split is `paths.sticky_pieces`.
_GLOB_CHARS = set("*?[")
_PIECE_SPLIT = re.compile(r"[=:,]")
_GLUED_OPTION = re.compile(r"-[A-Za-z]+(?=[/~.])")
_COMMENT_START = set(" \t\n;&|()")
_SCAN_STOP = re.compile(r"[\\'\"$`#<\n()]")  # where the pre-pass has something to do
_DQUOTE_STOP = re.compile(r'[\\"$`]')
_BODY_STOP = re.compile(r"[\\$`]")
_HEREDOC_ESCAPE = re.compile(r"\\([$`\\\n])")  # R34: what an unquoted heredoc unescapes
_PLAIN = re.compile(r"[^ \t\r'\"\\();<>|&\n]+")
_PUNCT_RUN = re.compile(r"[();<>|&\n]+")
_BLANKS = re.compile(r"[ \t\r]+")
_DQUOTE_END = re.compile(r'[\\"]')


class _Unconfident(Exception):
    """The command cannot be analysed within the bounds; deny as unconfident."""


class _TooLarge(_Unconfident):
    """A size bound was hit (candidates, bases, glob matches, readings): the command is
    denied with the "cannot be checked safely here" message, not the unconfident one."""


@dataclass
class _Scanned:
    marked: str  # the text with expansions replaced by markers, heredoc bodies removed
    nested: list[str]  # raw text of substitutions, to analyse as commands
    literal: list[str]  # heredoc bodies and comments: scanned for paths, not as commands
    ok: bool  # quotes, substitutions and braces all closed
    end: int  # index just past the scanned region (at the closer, for a substitution)
    literals: list[list[str]] = field(default_factory=list)  # R19 outputs, by index
    literal_nested: set[int] = field(default_factory=set)  # nested[k] is a literal's `cat`
    heredocs: list[str] = field(default_factory=list)  # R34: each heredoc as code, in order


def _skip_quoted(text: str, i: int) -> int:
    """The index past the quoted string starting at `text[i]`, or len(text) if unclosed."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\" and quote == '"':
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return len(text)


def _matching_brace(text: str, i: int) -> int:
    """The index of the `}` closing the `${` whose `{` is at `text[i]`, or -1."""
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c in "'\"":
            j = _skip_quoted(text, j)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _heredoc_literal(inner: str) -> list[str] | None:
    """Ruling R19b: the readings of a substitution that is exactly `cat` fed by one heredoc
    with a quoted delimiter (not `<<-`, not a herestring) and nothing else; else None.

    The reading is the body without its trailing newlines (what the substitution yields);
    a body whose parentheses do not balance is refused."""
    match = _QUOTED_HEREDOC.match(inner)
    if match is None:
        return None
    lines = inner[match.end() :].split("\n")
    if match.group(2) not in lines:
        return None
    k = lines.index(match.group(2))
    if "\n".join(lines[k + 1 :]).strip("\n"):
        return None  # something follows the heredoc
    body = "\n".join(lines[:k])
    depth = 0
    for c in body:  # R19c(d): bash 3.2 ends the substitution at the first unmatched `)`
        depth += (c == "(") - (c == ")")
        if depth < 0:
            return None
    if depth:
        return None
    return [body.rstrip("\n")]  # R19c(a): what the substitution yields, and only that


def _substitution(inner: str, out: list[str], scanned: _Scanned, whole: bool) -> None:
    """Record a substitution: its command for analysis, and a marker for its output, which
    is WILD unless `whole` (the word is exactly `"$(…)"`) and the command is R19b's form."""
    scanned.nested.append(inner)
    literal = _heredoc_literal(inner) if whole else None
    if literal is None:
        out.append(WILD)
    else:
        out.append(f"{_VAR}{_LOCAL}{len(scanned.literals)}{_END}")
        scanned.literal_nested.add(len(scanned.nested) - 1)
        scanned.literals.append(literal)


def _expansion(
    text: str, i: int, out: list[str], scanned: _Scanned, quoted_start: bool = False
) -> tuple[int, bool]:
    """Mark the `$…` or backtick expansion at `text[i]`; (index after it, closed).

    `quoted_start`: a double quote opened right before `text[i]`, at the start of a word."""
    nested = scanned.nested
    n = len(text)
    if text[i] == "`":
        j = i + 1
        while j < n and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        if j < n:
            _substitution(text[i + 1 : j].replace("\\`", "`"), out, scanned, False)
        else:
            nested.append(text[i + 1 :])
            out.append(WILD)
        return min(j + 1, n), j < n
    nxt = text[i + 1] if i + 1 < n else ""
    if nxt == "(":
        inner = _scan(text, i + 2, ")")
        if inner.ok:
            after = inner.end + 1  # the closing quote, then a word boundary, must follow
            whole = (
                quoted_start
                and text[after : after + 1] == '"'
                and (after + 1 == n or text[after + 1] in _WORD_BOUNDARY)
            )
            _substitution(text[i + 2 : inner.end], out, scanned, whole)
        else:
            nested.append(text[i + 2 : inner.end])
            out.append(WILD)
        return min(inner.end + 1, n), inner.ok
    if nxt == "{":
        j = _matching_brace(text, i + 1)
        if j < 0:
            nested.append(text[i + 2 :])
            out.append(WILD)
            return n, False
        content = text[i + 2 : j]
        if _NAME.fullmatch(content):
            out.append(_VAR + content + _END)
        elif len(content) == 1 and content in _SHORT_PARAMS:
            out.append(_SHORT_PARAMS[content])
        elif content.isascii() and content.isdigit():
            out.append(_POSITIONAL)
        else:  # ${X:-…}, ${#X}, ${X/a/b}…: the value is not known
            out.append(WILD)
            nested.append(content)
        return j + 1, True
    if nxt == '"':  # $"…" (locale quoting): the double-quoted string that follows
        return i + 1, True
    if nxt == "'":  # $'…' (ANSI-C quoting): escapes could spell anything
        j = i + 2
        while j < n and text[j] != "'":
            j += 2 if text[j] == "\\" else 1
        body = text[i + 2 : j]
        out.append(WILD if "\\" in body else "'" + body + "'")
        return min(j + 1, n), j < n
    match = _ZSH_FLAGGED.match(text, i + 1)
    if match:  # R33b: zsh's `$=X`, `$~X`, `$^X`, `$+X` (`$=#X`): the value is not known
        out.append(WILD)
        return match.end(), True
    match = _NAME.match(text, i + 1)
    if match:
        out.append(_VAR + match.group() + _END)
        return match.end(), True
    if nxt == "#" and i + 2 < n and text[i + 2] in _ZSH_LENGTH:  # zsh's `$#hi`, `$#?`
        out.append(_REST)
        return i + 2, True
    if nxt and nxt in _SPECIAL:  # $? $# $$ $! $- / $0-$9 $@ / $*: see _params
        out.append(_SHORT_PARAMS[nxt])
        return i + 2, True
    out.append("$")
    return i + 1, True


def _heredoc_delimiter(text: str, i: int) -> tuple[int, str, bool, bool]:
    """At `<<` in `text[i]`: (index after the delimiter word, delimiter, quoted, strip)."""
    j = i + 2
    strip = j < len(text) and text[j] == "-"
    if strip:
        j += 1
    while j < len(text) and text[j] in " \t":
        j += 1
    start = j
    while j < len(text) and text[j] not in " \t\n;&|()<>":
        if text[j] in "'\"":
            j = _skip_quoted(text, j)
        else:
            j += 2 if text[j] == "\\" else 1
    word = text[start:j]
    quoted = any(c in word for c in "'\"\\")
    delimiter = word.replace("'", "").replace('"', "").replace("\\", "")
    return j, delimiter, quoted, strip


def _unescape(match: re.Match[str]) -> str:
    return "" if match.group(1) == "\n" else match.group(1)


def _heredoc_bodies(
    text: str, i: int, pending: list[tuple[str, bool, bool]], scanned: _Scanned
) -> int:
    """Read the bodies of the pending heredocs starting at `text[i]`; the index after."""
    for delimiter, quoted, strip in pending:
        lines: list[str] = []
        while i < len(text):
            j = text.find("\n", i)
            line = text[i:] if j < 0 else text[i:j]
            i = len(text) if j < 0 else j + 1
            if (line.lstrip("\t") if strip else line) == delimiter:
                break
            lines.append(line)
        body = "\n".join(lines)
        # R34: the code a shell would read from it; unquoted, after POSIX heredoc unescaping
        scanned.heredocs.append(body if quoted else _HEREDOC_ESCAPE.sub(_unescape, body))
        if quoted:
            scanned.literal.append(body)
        else:  # expansions still happen in an unquoted heredoc
            out: list[str] = []
            k = 0
            while k < len(body):
                stop = _BODY_STOP.search(body, k)
                if stop is None:
                    out.append(body[k:])
                    break
                out.append(body[k : stop.start()])
                k = stop.start()
                if body[k] == "\\":
                    out.append(body[k : k + 2])
                    k += 2
                else:
                    k, closed = _expansion(body, k, out, scanned)
                    scanned.ok = scanned.ok and closed
            scanned.literal.append("".join(out))
    pending.clear()
    return i


def _scan(text: str, i: int = 0, closer: str | None = None) -> _Scanned:
    """The quote-aware pre-pass over `text` from `i`, up to an unmatched `closer`."""
    scanned = _Scanned("", [], [], True, len(text))
    out: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    depth = 0
    n = len(text)
    while i < n:
        stop = _SCAN_STOP.search(text, i)
        if stop is None:
            out.append(text[i:])
            break
        if stop.start() > i:
            out.append(text[i : stop.start()])
            i = stop.start()
        c = text[i]
        if closer == ")" and c == ")" and depth == 0:
            scanned.marked, scanned.end = "".join(out), i
            return scanned
        if c == "\\":
            if text.startswith("\\\n", i):
                i += 2  # line continuation
            else:
                out.append(text[i : i + 2])
                i += 2
        elif c == "'":
            j = _skip_quoted(text, i)
            scanned.ok = scanned.ok and text[j - 1 : j] == "'" and j - 1 > i
            out.append(text[i:j])
            i = j
        elif c == '"':
            out.append('"')
            opened = i + 1
            at_word_start = i == 0 or text[i - 1] in _WORD_BOUNDARY
            i += 1
            while i < n and text[i] != '"':
                stop = _DQUOTE_STOP.search(text, i)
                if stop is None:
                    out.append(text[i:])
                    i = n
                    break
                out.append(text[i : stop.start()])
                i = stop.start()
                d = text[i]
                if d == '"':
                    break
                if d == "\\":  # R33a: POSIX drops the backslash only before $ ` " \ newline
                    escaped = text[i + 1 : i + 2]
                    if escaped in ("$", "`"):
                        out.append(escaped)  # a literal now, an expansion in an `sh -c` body
                    elif escaped != "\n":
                        out.append(text[i : i + 2])  # shlex itself unescapes \" and \\
                    i += 2
                elif d == "`" or (d == "$" and text[i + 1 : i + 2] != '"'):
                    i, closed = _expansion(text, i, out, scanned, at_word_start and i == opened)
                    scanned.ok = scanned.ok and closed
                else:
                    out.append(d)
                    i += 1
            if i < n:
                out.append('"')
                i += 1
            else:
                scanned.ok = False
        elif c in "$`":
            i, closed = _expansion(text, i, out, scanned)
            scanned.ok = scanned.ok and closed
        elif c == "#" and (i == 0 or text[i - 1] in _COMMENT_START):
            j = text.find("\n", i)
            j = n if j < 0 else j
            scanned.literal.append(text[i:j])
            i = j
        elif text.startswith("<<<", i):  # a herestring: its word is scanned as usual
            out.append("<<<")
            i += 3
        elif text.startswith("<<", i):
            j, delimiter, quoted, strip = _heredoc_delimiter(text, i)
            out.append(text[i:j])
            pending.append((delimiter, quoted, strip))
            i = j
        elif c == "\n" and pending:
            out.append("\n")
            i = _heredoc_bodies(text, i + 1, pending, scanned)
        else:
            if closer == ")" and c == "(":
                depth += 1
            elif closer == ")" and c == ")":
                depth -= 1
            out.append(c)
            i += 1
    scanned.marked = "".join(out)
    if closer is not None:
        scanned.ok = False
    return scanned


def _shlex(marked: str) -> list[str]:
    lexer = shlex.shlex(marked, posix=True, punctuation_chars=_PUNCT)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _tokenize(text: str) -> list[str]:
    """`_shlex` in linear time, for long text (tests check the two agree).

    POSIX words split at blanks, runs of `_PUNCT` characters as operator tokens; quotes
    removed, backslash escapes as shlex does them. Raises ValueError like shlex.
    """
    tokens: list[str] = []
    word: list[str] = []
    active = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r" or c in _PUNCT:
            if active:
                tokens.append("".join(word))
                word, active = [], False
            if c in _PUNCT:
                run = _PUNCT_RUN.match(text, i)
                assert run is not None
                tokens.append(run.group())
                i = run.end()
            else:
                blanks = _BLANKS.match(text, i)
                assert blanks is not None
                i = blanks.end()
            continue
        active = True
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError("No closing quotation")
            word.append(text[i + 1 : j])
            i = j + 1
        elif c == '"':
            i += 1
            while True:
                stop = _DQUOTE_END.search(text, i)
                if stop is None:
                    raise ValueError("No closing quotation")
                word.append(text[i : stop.start()])
                i = stop.start()
                if text[i] == '"':
                    i += 1
                    break
                if i + 1 >= n:
                    raise ValueError("No closing quotation")
                nxt = text[i + 1]
                word.append(nxt if nxt in '"\\' else "\\" + nxt)
                i += 2
        elif c == "\\":
            if i + 1 >= n:
                raise ValueError("No escaped character")
            word.append(text[i + 1])
            i += 2
        else:
            plain = _PLAIN.match(text, i)
            assert plain is not None
            word.append(plain.group())
            i = plain.end()
    if active:
        tokens.append("".join(word))
    return tokens


def _lex(marked: str) -> tuple[list[str], bool]:
    """Words and operator tokens of the marked text; (tokens, lexed cleanly)."""
    try:
        return (_shlex(marked) if len(marked) <= LEX_LIMIT else _tokenize(marked)), True
    except ValueError:
        tokens = re.findall(r"[;&|()<>\n]+|[^\s;&|()<>]+", marked)
        return [t.replace('"', "").replace("'", "") for t in tokens], False


def _is_operator(token: str) -> bool:
    return bool(token) and all(c in _PUNCT for c in token)


def _is_separator(token: str) -> bool:
    return any(c in _SEPARATORS for c in re.sub(r"[<>]&", "", token))


# Operators a run of _PUNCT characters splits into, longest first (`2>&1|x`, `;>f`, `&>f`).
_SEPARATOR_OPS: tuple[str, ...] = (";;&", ";;", ";&", "&&", "||", "|&", ";", "&", "|", "(", ")")
_REDIRECT_OPS: tuple[str, ...] = ("<<<", "&>>", "<<", ">>", "<>", ">|", "&>", "<&", ">&", "<", ">")
_OPERATORS: tuple[str, ...] = tuple(
    sorted((*_SEPARATOR_OPS, *_REDIRECT_OPS, "\n"), key=len, reverse=True)
)
_FD_WORD = re.compile(r"[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\}")


def _operators(token: str) -> list[str]:
    """The shell operators a run of operator characters stands for."""
    out: list[str] = []
    i = 0
    while i < len(token):
        op = next(o for o in _OPERATORS if token.startswith(o, i))
        out.append(op)
        i += len(op)
    return out


def _simple_commands(tokens: Iterable[str]) -> list[tuple[list[str], int, list[str | None]]]:
    """The words of each simple command, how many of them are redirection targets, and its
    input redirections that feed text (R34): None for each `<<` heredoc, in order (its body
    is the scan's), and the word of each `<<<` herestring.

    Redirections (operator, target, and an `n` or `{fd}` word before the operator) never
    hold the program word or an argument, at any position: their targets move to the end
    of the command, where they are still path candidates but not arguments (`python3
    <<'EOF'` has no script; `grep -R x 2>/dev/null` searches the cwd)."""
    commands: list[tuple[list[str], int, list[str | None]]] = []
    words: list[str] = []
    redirected: list[str] = []
    fed: list[str | None] = []
    target = herestring = False

    def flush() -> None:
        nonlocal words, redirected, fed, target, herestring
        if words or redirected or fed:
            commands.append((words + redirected, len(redirected), fed))
        words, redirected, fed, target, herestring = [], [], [], False, False

    for token in tokens:
        if not _is_operator(token):
            (redirected if target else words).append(token)
            if herestring:
                fed.append(token)
            target = herestring = False
            continue
        for op in _operators(token):
            if op in _REDIRECT_OPS:
                if words and _FD_WORD.fullmatch(words[-1]):
                    redirected.append(words.pop())  # `2>x`, `{fd}>x` (or `echo 2 >x`)
                target = True
                herestring = op == "<<<"
                if op == "<<":
                    fed.append(None)
            else:
                flush()
    flush()
    return commands


# ---------------------------------------------------------------------------- the views


@dataclass(frozen=True)
class _View:
    """A program a simple command runs: its casefolded name and its word position."""

    name: str
    pos: int


def _program(word: str) -> str:
    return fold(word.rstrip("/").rsplit("/", 1)[-1])


def _skip_options(words: Sequence[str], j: int, values: frozenset[str]) -> int:
    while j < len(words) and words[j].startswith("-") and words[j] != "-":
        j += 2 if words[j] in values else 1
    return j


def _interpreter(name: str) -> str | None:
    """The INTERPRETERS entry for a program name, versions stripped (python3.11)."""
    if name in INTERPRETERS:
        return name
    base = re.sub(r"[\d.]+$", "", name)
    return base if base in INTERPRETERS else None


def _views(words: Sequence[str]) -> list[_View]:
    """The programs a simple command runs: its program word and those that wrappers,
    runners, `git <subcommand>` and `python -m` start."""
    views: list[_View] = []
    i = 0
    while i < len(words) and len(views) < 16:
        word = words[i]
        if _ASSIGN.match(word):
            i += 1
            continue
        name = _program(word)
        if name in KEYWORDS:
            i += 1
            continue
        views.append(_View(name, i))
        if name in WRAPPERS:
            i = _skip_options(words, i + 1, WRAPPERS[name]) + WRAPPER_POSITIONALS.get(name, 0)
            continue
        if name == "git":
            j = _skip_options(words, i + 1, GIT_VALUES)
            if j < len(words):
                views.append(_View(f"git {_program(words[j])}", j))
            break
        if name in RUNNERS:
            subs, values = RUNNERS[name]
            j = _skip_options(words, i + 1, values)
            if subs:
                if j >= len(words) or _program(words[j]) not in subs:
                    break
                while j < len(words) and _program(words[j]) in subs:
                    j = _skip_options(words, j + 1, values)
            i = j
            continue
        if _interpreter(name) in ("python", "pypy") and "-m" in words[i + 1 :]:
            j = words.index("-m", i + 1)
            if j + 1 < len(words):
                views.append(_View(_program(words[j + 1]), j + 1))
        break
    return views


def _inline(name: str, args: Sequence[str]) -> bool:
    """Whether interpreter `name` runs inline code: -c/-e and the like, or stdin."""
    flags = INLINE.get(name, ALWAYS)
    if flags.match(args) or "-" in args:
        return True
    j = 0
    while j < len(args):
        if not args[j].startswith("-"):
            return False  # a script (or, for python -m, a module)
        if args[j] == "-m":
            return False
        j += 2 if args[j] in INTERPRETER_VALUES else 1
    return True  # no script: the code comes from stdin (a heredoc, a pipe)


_SHELL_VALUES: frozenset[str] = frozenset({"--rcfile", "--init-file"})


def _reads_stdin(args: Sequence[str]) -> bool:
    """R34: whether a shell given `args` (no `-c`) reads its code from stdin: `-s`, `-`, or
    no script operand."""
    j = 0
    while j < len(args):
        arg = args[j]
        if arg == "-":
            return True
        if arg == "--":
            return j + 1 >= len(args)
        if arg.startswith("--"):
            j += 2 if arg in _SHELL_VALUES else 1
        elif arg[:1] in "-+" and len(arg) > 1:
            if "s" in arg[1:]:
                return True
            j += 2 if arg[-1] in "oO" else 1
        else:
            return False  # a script file: stdin is its data
    return True


# --------------------------------------------------------------------------- the analysis


@dataclass
class _Simple:
    """One simple command: its marked words, their expansions, and the programs it runs."""

    marked: list[str]
    expanded: list[list[str]]  # per word: every value it can take
    views: list[_View]
    exempt: set[int] = field(default_factory=set)  # word positions: the `uvx --from` value
    targets: int = 0  # the last `targets` words are redirection targets, not arguments

    @property
    def first(self) -> list[str]:
        return [_short(alts[0], True) if alts else "" for alts in self.expanded]

    def args(self, view: _View) -> list[str]:
        end = len(self.expanded) - self.targets
        return [_short(a, True) for alts in self.expanded[view.pos + 1 : end] for a in alts]


@dataclass
class _Candidate:
    text: str  # expanded, tilde-expanded; may hold WILD or glob characters
    simple: int | None  # index of its simple command; None for raw-text runs
    word: int | None  # word position in that simple command
    whole: bool  # a whole word (not a piece split at = : ,)


class _Check:
    def __init__(
        self, command: str, cwd: Path, scope: Scope, env: Mapping[str, str], session_id: str
    ) -> None:
        self.command = command
        self.cwd = canonical(cwd)
        self.scope = scope
        self.targets = scope.targets
        self.env = env
        self.session_id = session_id
        self.home = self._home()
        self.simples: list[_Simple] = []
        self.raw: list[tuple[str, dict[str, list[str]]]] = []  # (marked text, bindings)
        self.unconfident = False
        self.dangerous = False  # HOME/CDPATH/PWD/OLDPWD assigned, or `cd -`
        self.candidates: list[_Candidate] = []
        self.bases: list[Path] = [self.cwd]
        self.extra_starts: list[Path] = []  # recursion starts of `**` globs
        self.long_wild = False  # an over-long candidate starts with a wildcard
        self.seen: set[tuple[str, bool]] = set()  # candidate spellings already listed
        self.literals: list[list[str]] = []  # R19 substitution outputs, by global index
        self.literals_off = False  # R19c(c): every literal reads as WILD
        self.marked_texts: list[str] = []  # each level's marked text (no heredoc bodies)
        self.literal_forms: set[int] = set()  # simples that are a literal's own `cat` (R19e)
        self.folded = fold(command)
        root = scope.env.get(ENV_PLUGIN_ROOT)
        self.plugin_root = canonical(root, self.home) if root else None
        # Final review item 1(b): every rule resolves the same candidates against the same
        # bases, so readings, containment and directory tests are computed once per call.
        self._readings_of: dict[tuple[str, Path], list[Path]] = {}
        self._root_of: dict[Path, ProtectedRoot | None] = {}
        self._dir_of: dict[Path, bool] = {}
        self._names_of: dict[Path, tuple[Path, ...]] = {}
        self.budget = Budget()  # suffix text built by `_pieces` (R36)

    def _read(self, text: str, base: Path) -> list[Path]:
        """`paths.readings`, memoized for this call."""
        key = (text, base)
        found = self._readings_of.get(key)
        if found is None:
            if len(self._readings_of) >= MAX_READINGS:
                raise _TooLarge
            found = self._readings_of[key] = readings(text, base)
        return found

    def _names(self, path: Path) -> tuple[Path, ...]:
        found = self._names_of.get(path)
        if found is None:
            found = self._names_of[path] = spellings(path)
        return found

    def _root(self, path: Path) -> ProtectedRoot | None:
        """`Targets.containing`, memoized for this call."""
        if path not in self._root_of:
            self._root_of[path] = self.targets.containing(path, self._names(path))
        return self._root_of[path]

    def _guards(self, path: Path) -> bool:
        return self.targets.is_guard_file(path, self._names(path))

    def _is_dir(self, path: Path) -> bool:
        found = self._dir_of.get(path)
        if found is None:
            found = self._dir_of[path] = path.is_dir()
        return found

    # ------------------------------------------------------------------ parsing

    def _home(self) -> str:
        home = self.env.get("HOME")
        if home:
            return home
        try:
            return pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            return WILD

    def parse(self, text: str, depth: int = 0, literal_form: bool = False) -> None:
        if depth > MAX_DEPTH:
            raise _Unconfident
        scanned = _scan(text)
        if scanned.literals:  # renumber R19 outputs into this check's list
            offset = len(self.literals)
            self.literals.extend(scanned.literals)

            def renumber(match: re.Match[str]) -> str:
                return f"{_VAR}{_LIT}{int(match.group(1)) + offset}{_END}"

            scanned.marked = _LOCAL_REF.sub(renumber, scanned.marked)
            scanned.literal = [_LOCAL_REF.sub(renumber, body) for body in scanned.literal]
        self.marked_texts.append(scanned.marked)
        tokens, lexed = _lex(scanned.marked)
        if not (scanned.ok and lexed):
            self.unconfident = True
        bindings: dict[str, list[str]] = {}
        nested = list(scanned.nested)
        heredocs = iter(scanned.heredocs)
        for words, targets, fed in _simple_commands(tokens):
            stdin = [next(heredocs, "") if text is None else text for text in fed]
            simple = self._simple(words, bindings, targets)
            if literal_form:
                self.literal_forms.add(len(self.simples))
            self.simples.append(simple)
            self._bind(words, simple, bindings)
            nested.extend(self._nested_texts(simple, stdin))
        for body in (scanned.marked, *scanned.literal):
            self.raw.append((body, bindings))
        for k, inner in enumerate(nested):
            self.parse(inner, depth + 1, k in scanned.literal_nested)

    def _simple(
        self, words: list[str], bindings: dict[str, list[str]], targets: int = 0
    ) -> _Simple:
        words = list(words)
        for _ in range(4):  # R19c(b): a literal in program position is WILD
            expanded = [self._expand(w, bindings) for w in words]
            first = [alts[0] if alts else "" for alts in expanded]
            positions = {v.pos for v in _views(words)} | {v.pos for v in _views(first)}
            spoiled = [pos for pos in positions if _LIT in words[pos]]
            for pos in spoiled:
                words[pos] = _LIT_REF.sub(WILD, words[pos])
            if not spoiled:
                break
        else:
            expanded = [self._expand(w, bindings) for w in words]
        expanded = self._resolve_params(words, expanded)
        simple = _Simple(words, expanded, [], targets=targets)
        simple.views = _views(simple.first)
        for view in simple.views:
            if view.name in UNCONFIDENT_PROGRAMS:
                self.unconfident = True
            if view.name in CD_PROGRAMS and any(a in ("-", "~-") for a in simple.args(view)):
                self.dangerous = True
            if view.name in BINDING_PROGRAMS and DANGEROUS_ASSIGNMENTS & set(words):
                self.dangerous = True
            if view.name == "uvx":
                simple.exempt |= self._from_value(simple.first, view.pos)
        for word in words:
            match = _ASSIGN.match(word)
            if match and match.group(1) in DANGEROUS_ASSIGNMENTS:
                self.dangerous = True
        return simple

    @staticmethod
    def _resolve_params(words: list[str], expanded: list[list[str]]) -> list[list[str]]:
        """R27b and R29: the special-parameter marks of each expanded word, resolved at the
        point of use. A positional parameter alone in program position (`$0 -p hi`) is
        WILD; an assignment (`rc=$?`, before the program or after `export` and its kin)
        resolves its value on its own, the name being no path."""
        first = [alts[0] if alts else "" for alts in expanded]
        views = _views(words) + _views(first)
        programs = {view.pos for view in views}
        assignments: set[int] = set()
        for k, word in enumerate(words):
            if not _ASSIGN.match(word):
                break
            assignments.add(k)
        for view in views:
            if view.name in EXPORTERS:
                assignments.update(
                    k for k in range(view.pos + 1, len(words)) if _ASSIGN.match(words[k])
                )

        def resolve(k: int, value: str) -> str:
            if k in programs and value == _POSITIONAL:
                return WILD
            match = _ASSIGN.match(value) if k in assignments else None
            if match:
                return value[: match.end()] + _params(value[match.end() :])
            return _params(value)

        return [[resolve(k, value) for value in alts] for k, alts in enumerate(expanded)]

    def _from_value(self, words: Sequence[str], pos: int) -> set[int]:
        """The position of the `--from` value of the `uvx` at `pos`."""
        _, values = RUNNERS["uvx"]
        j = pos + 1
        while j < len(words) and words[j].startswith("-"):
            if words[j] == "--from":
                return {j + 1}
            if words[j].startswith("--from="):
                return {j}
            j += 2 if words[j] in values else 1
        return set()

    def _bind(self, words: list[str], simple: _Simple, bindings: dict[str, list[str]]) -> None:
        """Record the variables this simple command assigns, for the commands after it.

        Redirection targets are not words of the command (R27a): `X+=hi 2>/dev/null` is
        assignment-only, and binds, as bash does."""
        words = words[: len(words) - simple.targets]
        assigns = [w for w in words if _ASSIGN.match(w)]
        first = simple.views[0].name if simple.views else ""
        if words and words[0] in ("for", "select") and len(words) > 1:
            if _NAME.fullmatch(words[1]):
                if words[1] in DANGEROUS_ASSIGNMENTS:
                    self.dangerous = True
                values = words[3:] if len(words) > 2 and words[2] == "in" else ["_"]
                bindings[words[1]] = bindings.get(words[1], []) + values
            return
        if not (len(assigns) == len(words) or first in EXPORTERS):
            return  # NAME=value before a program sets it for that program only
        for word in assigns:
            match = _ASSIGN.match(word)
            assert match is not None
            name, value = match.group(1), word[match.end() :]
            if match.group(2):  # NAME+=value
                old = bindings.get(name) or [_VAR + name + _END]
                value_list = [o + value for o in old]
            else:
                value_list = [value]
            bindings[name] = bindings.get(name, []) + value_list

    def _nested_texts(self, simple: _Simple, stdin: Sequence[str] = ()) -> list[str]:
        """Command strings this simple command hands to a shell: sh -c, eval, env -S, and
        (R34) the heredocs and herestrings `stdin` of a shell that reads its code there."""
        texts: list[str] = []
        words = simple.marked
        end = len(words) - simple.targets
        for view in simple.views:
            rest = words[view.pos + 1 :]
            if view.name in SHELLS or view.name == "su":
                options = words[view.pos + 1 : end]  # redirection targets are no options
                for k, word in enumerate(options[:-1]):
                    if word.startswith("-") and not word.startswith("--") and "c" in word:
                        texts.append(options[k + 1])
                        break
                else:
                    if view.name in SHELLS and _reads_stdin(options):
                        texts.extend(stdin)
            elif view.name == "eval":
                texts.append(" ".join(rest))
            elif view.name == "env":
                for k, word in enumerate(rest[:-1]):
                    if word in ("-S", "--split-string"):
                        texts.append(rest[k + 1])
        return texts

    # ---------------------------------------------------------------- expansion

    def _values(self, name: str, bindings: dict[str, list[str]], depth: int) -> list[str]:
        if depth > 8:
            return [WILD]
        if name.startswith(_LIT):
            return [WILD] if self.literals_off else list(self.literals[int(name[1:])])
        if name in bindings:
            out: list[str] = []
            for value in bindings[name]:
                inner = {k: v for k, v in bindings.items() if k != name}
                out.extend(self._expand(value, inner, depth + 1))
            return out or [""]
        if name == "HOME":
            return [self.home]
        if name in self.env:
            return [self.env[name]]
        return [WILD]

    def _expand(self, word: str, bindings: dict[str, list[str]], depth: int = 0) -> list[str]:
        """Every value `word` can take, with WILD where a value is unknown."""
        if _VAR not in word:
            return [word]
        for marker in set(_MARKER.findall(word)):  # single values: substituted at C speed
            values = self._values(marker[1:-1], bindings, depth)
            if len(values) == 1:
                word = word.replace(marker, values[0].replace(_VAR, WILD))
        if _VAR not in word:
            return [word]
        alternatives: list[list[str]] = [[]]  # joined at the end: linear in the word length
        for part in _MARKER.split(word):
            if part.startswith(_VAR) and part.endswith(_END):
                values = self._values(part[1:-1], bindings, depth)
            else:
                values = [part]
            if len(values) == 1:
                for alternative in alternatives:
                    alternative.append(values[0])
                continue
            alternatives = [[*a, v] for a in alternatives for v in values]
            if len(alternatives) > MAX_ALTERNATIVES:
                alternatives = [[*alternatives[0], WILD]]
        return ["".join(a) for a in alternatives]

    def _tilde(self, text: str) -> str:
        if text == "~" or text.startswith("~/"):
            return self.home + text[1:]
        if text.startswith("~+"):
            return str(self.cwd) + text[2:]
        if text.startswith("~-"):
            return WILD + text[2:]
        if text.startswith("~"):
            user, _, rest = text[1:].partition("/")
            try:
                return pwd.getpwnam(user).pw_dir + ("/" + rest if rest else "")
            except (KeyError, ValueError):
                return text
        return text

    # --------------------------------------------------------------- candidates

    def _pieces(self, text: str) -> Iterator[tuple[str, bool]]:
        """`text` brace-expanded, then split at = : , and glued short options, and the text
        after each `=`, `,` or `:` (R36: `--input=` a root named `run=1`): (piece, is the
        whole)."""
        for whole in _braces(text):
            yield self._tilde(_short(whole, True)), True
            pieces = _PIECE_SPLIT.split(whole)
            for piece in pieces[1:] if len(pieces) > 1 else ():
                yield self._tilde(_short(piece, False)), False
            # The text after each `=`, `,` or `:` (R36; `,` and `:` from final review item 3).
            # Item 1(a): only suffixes within SUFFIX_LIMIT are built, since a longer one
            # cannot be opened, and a wildcard leading it is still seen in the piece split
            # above that starts at the same mark.
            for rest in suffixes(whole, self.budget):
                yield self._tilde(_short(rest, False)), False
            glued = _GLUED_OPTION.match(whole)
            if glued:
                yield self._tilde(_short(whole[glued.end() :], False)), False
            if WILD not in whole and STICKY.search(whole):
                for piece in sticky_pieces(whole):
                    yield self._tilde(_short(piece, False)), False

    def _add(self, candidate: _Candidate) -> None:
        text = candidate.text
        if len(text) > PATH_LIMIT:  # cannot be opened as a path; only a leading WILD counts
            self.long_wild = self.long_wild or WILD in text.lstrip("/").split("/", 1)[0]
            return
        if self._exempt(candidate):
            return
        if candidate.simple is None:  # a raw-text run: one per spelling is enough
            if (text, candidate.whole) in self.seen:
                return
            self.seen.add((text, candidate.whole))
        if len(self.candidates) >= MAX_CANDIDATES:
            raise _TooLarge
        self.candidates.append(candidate)
        if candidate.simple is not None:
            self.seen.add((text, candidate.whole))

    def collect(self) -> None:
        for s, simple in enumerate(self.simples):
            for w, alternatives in enumerate(simple.expanded):
                for alternative in alternatives:
                    for piece, whole in self._pieces(alternative):
                        if piece:
                            self._add(_Candidate(piece, s, w, whole))
        exempt_runs = sum(len(simple.exempt) for simple in self.simples)
        for body, bindings in self.raw:
            # R36, final review item 3: runs that `=` and `,` would cut, whole; `_pieces`
            # adds the text after each mark.
            for run in itertools.chain(path_runs(body), loose_runs(body)):
                for alternative in map(_params, self._expand(run, bindings)):
                    for piece, whole in self._pieces(alternative):
                        if not piece:
                            continue
                        if exempt_runs and whole and self._is_plugin_root(piece):
                            exempt_runs -= 1  # the raw spelling of an exempt `--from` value
                            continue
                        self._add(_Candidate(piece, None, None, whole))

    def _is_plugin_root(self, text: str) -> bool:
        if self.plugin_root is None or WILD in text or not text.startswith("/"):
            return False
        return all(r == self.plugin_root for r in self._read(text, Path("/")))

    def _exempt(self, candidate: _Candidate) -> bool:
        """The exact `--from` value after `uvx`, when it is the plugin root."""
        if candidate.simple is None or candidate.word is None:
            return False
        if candidate.word not in self.simples[candidate.simple].exempt:
            return False
        return self._is_plugin_root(self._absolute(candidate.text, self.cwd))

    @staticmethod
    def _absolute(text: str, base: Path) -> str:
        return text if text.startswith("/") else os.path.join(base, text)

    def resolve_bases(self) -> None:
        """Rule 3: the cwd, `cd`/`pushd` targets, -C/--directory values, existing dirs."""
        targets: list[str] = []
        for simple in self.simples:
            words = simple.first
            for view in simple.views:
                if view.name in CD_PROGRAMS:
                    args = [a for a in simple.args(view) if not a.startswith("-")]
                    targets.extend(self._tilde(a) for a in args[:1] or ["~"])
            for k, word in enumerate(words[:-1]):
                if word in DIRECTORY_OPTIONS:
                    targets.append(self._tilde(words[k + 1]))
            for word in words:
                if word.startswith("--") and word.split("=", 1)[0] in DIRECTORY_OPTIONS:
                    targets.append(self._tilde(word.split("=", 1)[1]))
        cdpath = [p for p in self.env.get("CDPATH", "").split(":") if p]
        for _ in range(2):
            for target in targets:
                if WILD in target.lstrip("/").split("/", 1)[0]:
                    self.dangerous = True  # cd into an unknown place
                    continue
                for base in [*self.bases, *(Path(p) for p in cdpath)]:
                    place = self._absolute(target, base)
                    if WILD in place or any(c in _GLOB_CHARS for c in place):
                        pattern = place.replace(WILD, "*")
                        for match in itertools.islice(glob.iglob(pattern), MAX_BASES + 1):
                            for reading in self._read(match, base):
                                self._add_base(reading)
                    else:
                        for reading in self._read(place, base):
                            self._add_base(reading)
            for candidate in self.candidates:
                if not candidate.whole or WILD in candidate.text:
                    continue
                if any(c in _GLOB_CHARS for c in candidate.text):
                    continue
                for base in list(self.bases):
                    for path in self._read(candidate.text, base):
                        if self._is_dir(path):
                            self._add_base(path)

    def _add_base(self, path: Path) -> None:
        if path not in self.bases:
            if len(self.bases) >= MAX_BASES:
                raise _TooLarge
            self.bases.append(path)

    def resolved(self, candidate: _Candidate) -> list[Path]:
        """Both readings (ruling R22) of the candidate against every base."""
        bases = [Path("/")] if candidate.text.startswith("/") else self.bases
        return [r for base in bases for r in self._read(candidate.text, base)]

    # -------------------------------------------------------------------- rules

    def self_protection(self) -> Denial | None:
        guard = Denial("guard-config", GUARD_MESSAGE)
        agents = {fold(a) for a in self.scope.agents} | DEFAULT_AGENTS
        for simple in self.simples:
            for view in simple.views:
                names = {_program(v) for v in simple.expanded[view.pos]} | {view.name}
                for name in names:
                    if name == "copier" or any(
                        name == a or name.startswith((a + "-", a + "@")) for a in agents
                    ):
                        return guard
        if self.unconfident:
            text = self._unconfident_text()
            if any(_delimited(word, text) for word in (*agents, "copier")):
                return guard
        replacers = {
            s
            for s, simple in enumerate(self.simples)
            for view in simple.views
            if view.name in REPLACERS
            or (view.name == "rsync" and any(a.startswith("--delete") for a in simple.args(view)))
        }
        for candidate, path in self._literal_paths():
            if self._guards(path):
                return guard
            if candidate.simple in replacers and self._guard_below(path):
                return guard
        for candidate in self.candidates:  # a glob inside a guard tree, even with no match
            text = candidate.text
            if WILD in text or not any(c in _GLOB_CHARS for c in text):
                continue
            bases = [Path("/")] if text.startswith("/") else self.bases
            for base in bases:
                prefix, _ = _split_pattern(self._absolute(text, base))
                if any(self._guards(r) for r in self._read(prefix, base)):
                    return guard
        return None

    def _guard_below(self, path: Path) -> bool:
        """Whether a guard file lies strictly below `path` (moving `path` moves it)."""
        key = fold(path).rstrip(os.sep) + os.sep
        return any(fold(g.path).startswith(key) for g in self.targets.guard_files)

    def _literal_paths(self) -> Iterator[tuple[_Candidate, Path]]:
        """Every candidate without wildcards, resolved; and every glob match."""
        for candidate in self.candidates:
            text = candidate.text
            if WILD in text:
                continue
            if any(c in _GLOB_CHARS for c in text):
                for match in self._glob(candidate):
                    yield candidate, match
                continue
            for path in self.resolved(candidate):
                yield candidate, path

    def _glob(self, candidate: _Candidate) -> list[Path]:
        matches: list[Path] = []
        bases = [Path("/")] if candidate.text.startswith("/") else self.bases
        for base in bases:
            pattern = self._absolute(candidate.text, base).replace(WILD, "*")
            for spelling in dict.fromkeys([pattern, os.path.normpath(pattern)]):
                for match in itertools.islice(glob.iglob(spelling), GLOB_LIMIT + 1):
                    matches.extend(self._read(match, base))
                    if len(matches) > GLOB_LIMIT:
                        raise _TooLarge
        return matches

    def data_rules(self) -> Denial | None:
        roots = self.targets.roots
        inside = self._root(self.cwd)
        if inside is not None:
            return data_denial(inside, SUBJECT)
        if self.dangerous:
            return Denial("data-guard", UNCONFIDENT_MESSAGE)
        if self.long_wild:
            return Denial("data-guard", UNCONFIDENT_MESSAGE)
        for candidate in self.candidates:  # rule 2: a leading wildcard could point anywhere
            first = candidate.text.lstrip("/").split("/", 1)[0]
            if WILD in first:
                return Denial("data-guard", UNCONFIDENT_MESSAGE)
        hits = [self._root(path) for _, path in self._literal_paths()]  # rule 4
        found = [root for root in hits if root is not None]
        if found:  # the most specific root names the entry best
            return data_denial(max(found, key=lambda root: len(str(root.path))), SUBJECT)
        root = self._textual()  # rule 7
        if root is not None:
            return data_denial(root, SUBJECT)
        denial = self._wildcards()  # rule 5
        if denial is not None:
            return denial
        denial = self._links_created()
        if denial is not None:
            return denial
        if self.unconfident:  # rule 8
            text = self._unconfident_text()
            for root in roots:
                names = {Path(root.path).name, os.path.basename(root.configured.rstrip("/"))}
                if any(name and _delimited(fold(name), text) for name in names):
                    return Denial("data-guard", UNCONFIDENT_MESSAGE)
        return self._recursion()  # rule 6

    def _unconfident_text(self) -> str:
        """The raw text, the raw text without quote characters (ruling R26: `p""hi`), that
        without backslashes too (`p\\hi`, shell's third quoting mechanism), and every
        expanded candidate (an R19 output can spell a name)."""
        unquoted = self.folded.replace("'", "").replace('"', "")
        unescaped = unquoted.replace("\\", "")
        texts = [self.folded, unquoted, unescaped, *(fold(c.text) for c in self.candidates)]
        return "\n".join(texts)

    def _textual(self) -> ProtectedRoot | None:
        """Rule 7: a root's spelling (configured, ~-expanded or canonical) in the raw text."""
        text = self.folded
        hits: list[tuple[int, ProtectedRoot]] = []
        for root in self.targets.roots:
            configured = root.configured.strip()
            relative = not configured.startswith(("/", "~"))
            spellings = {fold(root.path)}
            if configured.startswith("~"):
                spellings.add(fold(self._tilde(configured)))
            for spelling in spellings:
                if spelling and spelling in text:
                    hits.append((len(spelling), root))
            if configured and (
                (relative and _delimited(fold(configured), text))
                or (not relative and fold(configured) in text)
            ):
                hits.append((len(configured), root))
        return max(hits, key=lambda hit: hit[0])[1] if hits else None

    def _wildcards(self) -> Denial | None:
        """Rule 5: a glob or wildcard whose literal prefix is inside or above a root."""
        for candidate in self.candidates:
            text = candidate.text
            if WILD not in text and not any(c in _GLOB_CHARS for c in text):
                continue
            bases = [Path("/")] if text.startswith("/") else self.bases
            for base in bases:
                denial = self._pattern(self._absolute(text, base))
                if denial is not None:
                    return denial
            if "**" in text:  # a recursive glob, which zsh's `***` even follows
                for base in bases:
                    prefix, _ = _split_pattern(self._absolute(text, base))
                    self.extra_starts.extend(self._read(prefix, base))
            for match in self._glob(candidate):
                root = self._root(match)
                if root is not None:
                    return data_denial(root, SUBJECT)
        return None

    def _pattern(self, pattern: str) -> Denial | None:
        prefix, rest = _split_pattern(pattern)
        if ".." in rest:
            return Denial("data-guard", UNCONFIDENT_MESSAGE)
        rest = [part for part in rest if part not in ("", ".")]
        for start in self._read(prefix, Path("/")):
            root = self._root(start)
            if root is not None:
                return data_denial(root, SUBJECT)
            start_key = fold(start).rstrip(os.sep)
            for root in self.targets.under(start):
                relative = fold(root.path)[len(start_key) + 1 :].split(os.sep)
                if any("**" in part for part in rest):
                    return data_denial(root, SUBJECT)
                parts = [fold(part.replace(WILD, "*")) for part in rest]
                if all(fnmatch.fnmatchcase(r, p) for r, p in zip(relative, parts, strict=False)):
                    return data_denial(root, SUBJECT)
        return None

    def _links_created(self) -> Denial | None:
        """`ln` pointing at a root or at a directory above one: a later recursive command
        could follow the new link (the link walk's cache would not know it)."""
        for s, simple in enumerate(self.simples):
            if not any(view.name == "ln" for view in simple.views):
                continue
            mine = [c for c in self.candidates if c.simple == s and WILD not in c.text]
            places = {p.parent for c in mine for p in self.resolved(c)}
            for candidate in mine:
                bases = [Path("/")] if candidate.text.startswith("/") else [*self.bases, *places]
                for base in bases:
                    for path in self._read(candidate.text, base):
                        root = self._root(path)
                        under = self.targets.under(path)
                        if root is not None or under:
                            return data_denial(root or under[0], SUBJECT)
        return None

    def _recursion(self) -> Denial | None:
        """Rule 6: recursive constructs from a start above a root, or above a link."""
        constructs: list[tuple[str, list[str], list[Path], bool]] = []
        for s, simple in enumerate(self.simples):
            for view in simple.views:
                args = simple.args(view)
                interpreter = _interpreter(view.name)
                inline = interpreter is not None and _inline(interpreter, args)
                flags = RECURSIVE.get(view.name)
                if not inline and not (flags is not None and flags.match(args)):
                    continue
                following = inline or FOLLOWING.get(view.name, Flags()).match(args)
                starts = self._dirs(s, view)
                if inline or not starts:
                    starts = [*starts, *self.bases]
                constructs.append((view.name, args, starts, following))
        for start in self.extra_starts:
            constructs.append(("**", [], [start], True))
        for name, args, starts, _ in constructs:  # 6a
            for start in starts:
                under = self.targets.under(start)
                if under and not (name == "rg" and self._rg_ignores(args, start, under)):
                    return data_denial(under[0], SUBJECT)
        data = self.env.get("CLAUDE_PLUGIN_DATA")
        cache = Path(data) if data else None
        for _, _, starts, following in constructs:  # 6b
            for start in dict.fromkeys(starts):
                scan = links_under(start, self.targets, cache, self.session_id)
                if scan.truncated:
                    return unchecked_denial(SUBJECT)
                if scan.found and following:
                    return data_denial(self.targets.roots[0], SUBJECT)
        return None

    def _dirs(self, s: int, view: _View) -> list[Path]:
        """The directories among a view's arguments (literal, or glob matches)."""
        dirs: list[Path] = []
        for candidate in self.candidates:
            if candidate.simple != s or candidate.word is None or candidate.word <= view.pos:
                continue
            if WILD in candidate.text:
                continue
            if any(c in _GLOB_CHARS for c in candidate.text):
                paths = self._glob(candidate)
            else:
                paths = self.resolved(candidate)
            dirs.extend(p for p in paths if self._is_dir(p) and p not in dirs)
        return dirs

    def _rg_ignores(self, args: Sequence[str], start: Path, roots: list[ProtectedRoot]) -> bool:
        """Rule 6a's exception: rg skips every root below `start` because git ignores it."""
        if RG_IGNORE_OFF.match(args):
            return False
        if self.env.get("RIPGREP_CONFIG_PATH") or "ripgrep_config_path" in self.folded:
            return False
        for root in roots:
            for directory in root.path.parents:
                if any((directory / name).exists() for name in RG_IGNORE_FILES):
                    return False  # rg's own ignore files can re-include what git ignores
            if not self._git_ignored(start, root):
                return False
        return True

    def _git_ignored(self, start: Path, root: ProtectedRoot) -> bool:
        """`git check-ignore`; any failure or timeout means "not ignored". The child's
        output goes nowhere: inherited descriptors would reach Claude."""
        try:
            result = subprocess.run(
                ["git", *HOOK_GIT_OPTIONS, "-C", str(start), "check-ignore", "-q", str(root.path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(self.env),
                timeout=GIT_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        return result.returncode == 0

    def _literals_unsafe(self) -> bool:
        """R19c(c): could this command redefine `cat`, or is it dynamic already?
        R19d/R19e: or does it assign, hold a carriage return, or run anything but git/gh?"""
        if self.unconfident or self.dangerous or "\r" in self.command:
            return True
        if any(_ANY_ASSIGN.search(text) for text in self.marked_texts):
            return True
        if any(
            not self._git_or_gh(simple)
            for k, simple in enumerate(self.simples)
            if k not in self.literal_forms
        ):
            return True
        text = "\n".join(fold(t) for t in self.marked_texts)
        if _FUNCTION_DEF.search(text):
            return True
        words = (*LITERAL_SPOILERS, *UNCONFIDENT_WORDS)
        if any(_delimited(word, text, loose=True) for word in words):
            return True
        return any(
            (match := _ASSIGN.match(word)) is not None and match.group(1) == "PATH"
            for simple in self.simples
            for word in simple.marked
        )

    @staticmethod
    def _git_or_gh(simple: _Simple) -> bool:
        """R19d(a) and R19e for one simple command, on its marked words (no heredoc body):
        no assignment, and only `git` or `gh` running a built-in subcommand."""
        if any(_ANY_ASSIGN.search(word) for word in simple.marked):
            return False
        for words in (simple.marked, simple.first):
            subcommand = -1  # the position of the subcommand view `git` starts
            for view in _views(words):
                if view.pos == subcommand:
                    continue  # checked with its `git` below (not a program named "git x")
                word = words[view.pos]  # exactly git or gh: not ./git, bin/gh or GIT
                if word == "gh":
                    sub = words[view.pos + 1] if view.pos + 1 < len(words) else ""
                    if sub not in LITERAL_GH_SUBCOMMANDS or "--" in words[view.pos + 1 :]:
                        return False  # after a bare `--`, gh hands arguments to git
                elif word == "git":
                    j = view.pos + 1
                    while j < len(words) and words[j].startswith("-"):
                        if words[j].startswith(LITERAL_GIT_UNSAFE):
                            return False
                        j += 2 if words[j] in GIT_VALUES else 1
                    if j >= len(words) or words[j] not in LITERAL_GIT_SUBCOMMANDS:
                        return False
                    subcommand = j
                else:
                    return False
        return True

    def _reparse_without_literals(self) -> None:
        self.simples, self.raw, self.literals, self.marked_texts = [], [], [], []
        self.literal_forms = set()
        self.unconfident = self.dangerous = False
        self.literals_off = True
        self.parse(self.command)

    def run(self) -> Denial | None:
        self.parse(self.command)
        if self.literals and self._literals_unsafe():
            self._reparse_without_literals()
        if any(_delimited(word, self.folded, loose=True) for word in UNCONFIDENT_WORDS):
            self.unconfident = True  # e.g. exec() inside python -c, find -exec
        self.collect()
        self.resolve_bases()
        if self.scope.protected:
            denial = self.self_protection()
            if denial is not None:
                return denial
        if self.targets.roots:
            return self.data_rules()
        return None


_readings = readings  # ruling R22's two readings, under the name this module has used


def _params(word: str) -> str:
    """Rulings R27b, R29 and R32: an expanded `word` (or value) with its special-parameter marks
    resolved where it is used.

    From zsh's length form (`$#hi`), the rest of the word is WILD. A word made only of
    `$? $# $$ $! $-` names no path: each is `_`. Joined to anything else, each is `*`
    (R32), unless it is alone in a piece split at `=`, `:` or `,` (R33c: `rc=$?`); those
    marks stay in the word for `_short` to resolve, once the whole word and its pieces are
    known. As `*`,
    rule 5 judges it like any glob, and since it can hold no `/` or `..` it does not
    deny as a leading WILD would. A positional parameter alone (`$1`, `"$@"`) holds one
    word of the command, a candidate in its own right: `_`. Joined to anything, another
    parameter included (`$1$2`), it is WILD."""
    if _REST in word:
        word = word[: word.index(_REST)] + WILD
    if word == _POSITIONAL or (word and not word.strip(_SHORT)):
        return "_" * len(word)
    return word.replace(_POSITIONAL, WILD) if _POSITIONAL in word else word


def _short(text: str, whole: bool) -> str:
    """R33c, after piece splitting (round 4): the `$? $# $$ $! $-` marks `_params` left in
    `text`. A whole word reads each as `*` (`run=$?` can name a root `run=1`); a piece split
    from it at `=`, `:` or `,` that is made only of them is `_` (`rc=$?` gives the piece
    `_`), and any other piece reads each as `*`."""
    if _SHORT not in text:
        return text
    if not whole and not text.strip(_SHORT):
        return "_" * len(text)
    return text.replace(_SHORT, "*")


def _delimited(word: str, text: str, *, loose: bool = False) -> bool:
    """Whether `word` occurs in `text` with no letter, digit or `_` around it, nor (unless
    `loose`) `.` or `-`."""
    around = r"\w" if loose else r"\w.-"
    return re.search(rf"(?<![{around}]){re.escape(word)}(?![{around}])", text) is not None


def _split_pattern(pattern: str) -> tuple[str, list[str]]:
    """(literal prefix, remaining components) of an absolute pattern."""
    parts = pattern.split("/")
    for k, part in enumerate(parts):
        if WILD in part or any(c in _GLOB_CHARS for c in part):
            return "/".join(parts[:k]) or "/", parts[k:]
    return pattern, []


def _braces(text: str) -> list[str]:
    """Bash brace expansion ({a,b}, {1..3}); too many results turn the group into `*`."""
    if "{" not in text:
        return [text]
    if text.count("{") > MAX_BRACE_GROUPS:  # every group that could expand becomes `*`
        return [re.sub(r"\{[^{}]*(,|\.\.)[^{}]*\}", "*", text)]
    depth = 0
    open_at = -1
    for k, c in enumerate(text):
        if c == "{":
            if depth == 0:
                open_at = k
            depth += 1
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                expanded = _brace_group(text, open_at, k)
                if expanded is not None:
                    return expanded
    return [text]


def _brace_group(text: str, start: int, end: int) -> list[str] | None:
    head, body, tail = text[:start], text[start + 1 : end], text[end + 1 :]
    parts: list[str] = []
    depth = 0
    current = ""
    for c in body:
        if c == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        depth += (c == "{") - (c == "}")
        current += c
    parts.append(current)
    if len(parts) < 2:
        parts = _sequence(body)
        if not parts:
            return None  # a literal brace pair, like find's {}
    results: list[str] = []
    for part in parts:
        for expanded in _braces(head + part + tail):
            results.append(expanded)
            if len(results) > MAX_ALTERNATIVES:
                return [head + "*" + tail]
    return results


def _sequence(body: str) -> list[str]:
    """The words of a brace sequence (`1..3`, `a..c`); `*` when it is too long; [] if none."""
    numbers = re.fullmatch(r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?", body)
    letters = re.fullmatch(r"([A-Za-z])\.\.([A-Za-z])", body)
    if numbers:
        low, high = int(numbers.group(1)), int(numbers.group(2))
    elif letters:
        low, high = ord(letters.group(1)), ord(letters.group(2))
    else:
        return []
    if abs(high - low) >= MAX_ALTERNATIVES:
        return ["*"]
    step = 1 if high >= low else -1
    values = range(low, high + step, step)
    return [str(v) for v in values] if numbers else [chr(v) for v in values]


def check_command(
    command: str, cwd: Path, scope: Scope, env: Mapping[str, str], session_id: str
) -> Denial | None:
    """The denial for this Bash command, or None.

    Data rules 1-8 apply when the scope has protected roots; the Bash half of guard
    self-protection when it is protected. Anything the analysis cannot bound, and any
    path that cannot be canonicalised, is denied as unconfident.
    """
    if not scope.protected and not scope.targets.roots:
        return None
    if _MARKS.search(command):  # a mark spelled in the command could pass for an expansion
        return Denial("data-guard", UNCONFIDENT_MESSAGE)
    try:
        return _Check(command, cwd, scope, env, session_id).run()
    except (_TooLarge, TextTooLarge):
        return unchecked_denial(SUBJECT)
    except (_Unconfident, OSError, RuntimeError, ValueError, RecursionError):
        return Denial("data-guard", UNCONFIDENT_MESSAGE)
