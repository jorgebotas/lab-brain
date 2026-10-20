"""The Bash data guard and the Bash half of guard self-protection: a table-driven corpus.

`CASES`, `GITIGNORED_CASES` and `make_bash_world` are module-level so the integration tests
can replay every row through `run_hook` (controller ruling R4).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, git, make_vault

from labbrain.hooks import bash
from labbrain.hooks.bash import (
    FOLLOWING,
    GUARD_MESSAGE,
    INTERPRETERS,
    RECURSIVE,
    UNCONFIDENT_MESSAGE,
    check_command,
)
from labbrain.hooks.payload import Denial
from labbrain.hooks.scope import Scope, load_scope

SESSION = "00000000-0000-4000-8000-000000000001"


def _h(body: str) -> str:
    """A whole-word quoted-heredoc substitution (ruling R19b's only literal form)."""
    return f"\"$(cat <<'EOF'\n{body}\nEOF\n)\""


# (case_id, command, expected). Placeholders: {tmp}, {R}, {R_upper}, {plugin_root}.
CASES: list[tuple[str, str, str]] = [
    # --- data paths named directly, through ~, $HOME, .., links, case and globs
    ("cat-abs", "cat {R}/rows.csv", "deny"),
    ("head-tilde", "head -5 ~/phi/rows.csv", "deny"),
    ("home-var", "wc -l $HOME/phi/rows.csv", "deny"),
    ("rel-dotdot", "cat ../mnt/phi/rows.csv", "deny"),
    ("quoted-space", 'cat "{R} data/f.csv"', "deny"),
    ("python-c", "python -c \"print(open('{R}/rows.csv').read())\"", "deny"),
    ("duckdb", "duckdb -c \"select * from '{R}/rows.csv'\"", "deny"),
    ("sqlite", "sqlite3 {R}/db.sqlite .dump", "deny"),
    ("symlink-in-repo", "cat data/rows.csv", "deny"),
    ("case", "cat {R_upper}/rows.csv", "deny"),
    ("glob-prefix", "cat {tmp}/mnt/p*/rows.csv", "deny"),
    ("glob-ancestor", "ls {tmp}/mnt/*/", "deny"),
    ("cd-chain", "cd {tmp}/mnt && cat phi/rows.csv", "deny"),
    ("heredoc", "python - <<'EOF'\nopen(\"{R}/rows.csv\")\nEOF", "deny"),
    # --- unbindable variables, substitutions, assignments, loops, dynamic evaluation
    ("unknown-var", 'cat "$DATA_DIR/rows.csv"', "deny"),
    ("subst", "cat $(echo {tmp})/mnt/phi/rows.csv", "deny"),
    ("assign-home", "HOME={tmp}/mnt cat ~/phi/rows.csv", "deny"),
    ("cdpath", "CDPATH={tmp}/mnt cd phi", "deny"),
    ("for-loop", 'for f in {R}/*.csv; do head -1 "$f"; done', "deny"),
    ("eval-basename", 'eval "cat $(printf %s ph)i/rows.csv"', "deny"),
    ("pipe-sh", 'echo "cat ../mnt/phi/rows.csv" | sh', "deny"),
    # --- recursion from an ancestor, and links followed into a root
    ("grep-r-ancestor", "grep -r x {tmp}/mnt", "deny"),
    ("find-ancestor", "find {tmp} -name '*.csv'", "deny"),
    ("grep-R-link", "grep -R x .", "deny"),
    ("zip-link", "zip -r out.zip .", "deny"),
    ("python-glob-link", "python -c \"import glob; glob.glob('**', recursive=True)\"", "deny"),
    ("rg-L-link", "rg -L x", "deny"),
    # --- guard self-protection
    ("nested-claude", "claude -p hi", "deny"),
    ("nested-codex", "codex exec x", "deny"),
    ("copier", "copier update --defaults", "deny"),
    ("guard-file", "sed -i s/true/false/ brain/.labbrain/config.yaml", "deny"),
    ("plugin-root", "cp x.py {plugin_root}/labbrain/hooks/guard.py", "deny"),
    ("plugin-root-dest", "cp x.py {plugin_root}", "deny"),
    ("mv-claude-dir", "mv brain/.claude x", "deny"),
    ("ln-claude-dir", "ln -sfn /tmp/x brain/.claude", "deny"),
    ("rm-labbrain-dir", "rm -rf brain/.labbrain", "deny"),
    # --- builder additions: more ways around the same rules
    ("assigned-var", "X={tmp}/mnt; cat $X/phi/rows.csv", "deny"),
    ("export-var", "export X=~/phi && head $X/rows.csv", "deny"),
    ("brace", "cat {tmp}/mnt/{{phi,other}}/rows.csv", "deny"),
    ("glob-through-link", "cat */rows.csv", "deny"),
    ("unquoted-heredoc", "cat <<EOF\n$HOME/phi/rows.csv\nEOF", "deny"),
    ("backticks", "cat `echo {tmp}`/mnt/phi/rows.csv", "deny"),
    ("param-default", "cat ${{DATA:-x}}/rows.csv", "deny"),
    ("sh-c-relative", "bash -c 'cd ../mnt && cat phi/rows.csv'", "deny"),
    ("git-C", "git -C {tmp}/mnt grep x", "deny"),
    ("tar-ancestor", "tar czf out.tgz {tmp}/mnt", "deny"),
    ("cd-dash", "cd - && cat rows.csv", "deny"),
    ("star-star-link", "ls **/rows.csv", "deny"),
    ("ln-to-ancestor", "ln -s ../mnt m", "deny"),
    ("sh-c-claude", 'sh -c "claude -p hi"', "deny"),
    ("env-claude", "env FOO=1 claude -p hi", "deny"),
    ("npx-claude", "npx @anthropic-ai/claude-code -p hi", "deny"),
    ("uvx-copier", "uvx copier copy gh:x/y .", "deny"),
    ("python-m-copier", "python -m copier update", "deny"),
    ("subst-claude", 'echo "out: $(claude -p hi)"', "deny"),
    ("rm-vault", "rm -rf brain", "deny"),
    ("alias-claude", "alias c=claude; c -p hi", "deny"),
    ("watch-claude", "watch -n 5 claude -p hi", "deny"),
    ("guard-glob-empty", "rm -f brain/.labbrain/cache/*", "deny"),
    ("settings-home", "cat ~/.claude/settings.json", "deny"),
    ("plugin-root-file", "uvx --from {plugin_root}/labbrain labbrain lint", "deny"),
    ("plugin-root-other-arg", 'uvx --from "{plugin_root}" labbrain lint {plugin_root}', "deny"),
    ("unclosed-quote-basename", "cat 'phi/rows.csv", "deny"),
    # --- ruling R19: substitutions of literal text (cat <<heredoc, echo/printf literals)
    (
        "commit-heredoc",
        "git commit -m \"$(cat <<'EOF'\nfix: tidy\n\nCo-Authored-By: X <x@y>\nEOF\n)\"",
        "allow",
    ),
    (
        "commit-heredoc-datapath",
        "git commit -m \"$(cat <<'EOF'\nfix: tidy {R}/rows.csv\nEOF\n)\"",
        "deny",
    ),
    ("echo-literal-subst", "ls $(echo src)", "deny"),
    ("cat-file-subst", "wc -l $(cat {R}/list.txt)", "deny"),
    ("printf-var-subst", 'cat $(printf %s "$X")/rows.csv', "deny"),
    ("subst-leading-unknown", "cat $(pwd)/../mnt/phi/rows.csv", "deny"),
    ("herestring-subst", "ls $(cat <<< src) `echo docs`", "deny"),
    ("echo-glob-subst", "ls $(echo *)", "deny"),
    ("echo-redirect-subst", "ls $(echo x > y)", "deny"),
    ("cat-flag-subst", "ls $(cat -n <<'EOF'\nsrc\nEOF\n)", "deny"),
    ("literal-subst-path", "cat $(echo ../mnt)/phi/rows.csv", "deny"),
    ("printf-format-subst", "cat ../mnt/$(printf %s%s p hi)/rows.csv", "deny"),
    # ruling R19b: only a whole-word "$(cat <<'EOF' ...)" is literal; these all print data
    ("echo-n-subst", "cat {tmp}/mnt/$(echo -n phi)/rows.csv", "deny"),
    ("echo-n-backticks", "cat {tmp}/mnt/`echo -n phi`/rows.csv", "deny"),
    ("echo-nn-subst", "cat {tmp}/mnt/$(echo -nn phi)/rows.csv", "deny"),
    ("echo-n-redirect", "cat < {tmp}/mnt/$(echo -n phi)/rows.csv", "deny"),
    ("echo-n-relative", "cat $(echo -n ../mnt)/phi/rows.csv", "deny"),
    ("echo-dash", "cat {tmp}/mnt/$(echo - phi)/rows.csv", "deny"),
    ("printf-dashdash", "cat {tmp}/mnt/$(printf -- %s phi)/rows.csv", "deny"),
    ("echo-split-rel", "cat $(echo x ../mnt)/phi/rows.csv", "deny"),
    ("echo-split-abs", "cat $(echo x {tmp}/mnt)/phi/rows.csv", "deny"),
    ("heredoc-split", "cat $(cat <<'EOF'\nx\n../mnt\nEOF\n)/phi/rows.csv", "deny"),
    ("heredoc-trailing-blank", "cat \"{tmp}/mnt/$(cat <<'EOF'\nphi\n\nEOF\n)/rows.csv\"", "deny"),
    ("heredoc-dash-tab", "cat \"{tmp}/mnt/$(cat <<-'EOF'\n\tphi\n\tEOF\n)/rows.csv\"", "deny"),
    ("heredoc-bsnl", 'cat "{tmp}/mnt/$(cat <<EOF\np\\\nhi\nEOF\n)/rows.csv"', "deny"),
    ("printf-brace", "cat {tmp}/mnt/$(printf %s {{p,h}})i/rows.csv", "deny"),
    ("herestring-var", 'X=phi; cat {tmp}/mnt/$(cat <<<"$X")/rows.csv', "deny"),
    ("herestring-nested-echo", 'cat {tmp}/mnt/$(cat <<<"$(echo phi)")/rows.csv', "deny"),
    ("herestring-ansi", "cat {tmp}/mnt/$(cat <<< $'phi')/rows.csv", "deny"),
    ("herestring-locale", 'cat {tmp}/mnt/$(cat <<< $"phi")/rows.csv', "deny"),
    ("herestring-nested-claude", 'cat <<<"$(claude -p hi)"', "deny"),
    ("locale-quote", 'cat {tmp}/mnt/$"phi"/rows.csv', "deny"),
    ("heredoc-literal-relative", "cat \"$(cat <<'EOF'\n../mnt/phi/rows.csv\n\nEOF\n)\"", "deny"),
    ("commit-heredoc-dquote-delim", 'git commit -m "$(cat <<"EOF"\nfix: x\nEOF\n)"', "allow"),
    # ruling R19c: literal words never name programs, nor survive redefinitions
    ("lit-prog-sh", _h("sh") + " -c 'cat mn''t/phi/rows.csv'", "deny"),
    ("lit-prog-sh-blank", _h("sh\n") + " -c 'cat mn''t/phi/rows.csv'", "deny"),
    (
        "lit-prog-python",
        _h("python3") + """ -c 'print(open("mn"+"t/phi/rows.csv").read())'""",
        "deny",
    ),
    ("lit-prog-bash-herestring", _h("bash") + " <<<'cat mn''t/phi/rows.csv'", "deny"),
    ("lit-prog-grep-r", _h("grep") + " -r . ..", "deny"),
    ("lit-prog-env-wrapper", _h("env") + " grep -r . ..", "deny"),
    ("lit-prog-after-env", "env " + _h("grep") + " -r . ..", "deny"),
    ("lit-prog-claude", _h("claude") + " -p hi", "deny"),
    (
        "fn-cat-literal",
        "cat() { echo mnt/qhi/rows.csv | tr q p; }; head " + _h("README.md"),
        "deny",
    ),
    (
        "fn-keyword-cat",
        "function cat { echo mnt/qhi/rows.csv | tr q p; }; head " + _h("README.md"),
        "deny",
    ),
    (
        "eval-fn-cat",
        "eval 'cat() { tr q p <<<mnt/qhi/rows.csv; }'; head " + _h("README.md"),
        "deny",
    ),
    (
        "source-fn-cat",
        "printf 'cat() { tr q p <<<mnt/qhi/rows.csv; }' > f.sh; . ./f.sh; head " + _h("README.md"),
        "deny",
    ),
    (
        "alias-cat",
        "shopt -s expand_aliases\nalias cat='tr q p <<<mnt/qhi/rows.csv #'\nhead "
        + _h("README.md"),
        "deny",
    ),
    ("path-cat", "PATH=$PWD/b:$PATH head " + _h("README.md"), "deny"),
    ("hash-cat", "hash -p $PWD/b/cat cat; head " + _h("README.md"), "deny"),
    ("enable-n-cat", "enable -n cat; head " + _h("README.md"), "deny"),
    ("paren-body", "cat " + _h(')mnt/p"hi"/rows.csv"'), "deny"),
    (
        "commit-heredoc-parens",
        "git commit -m " + _h("feat(hooks): x\n\nCo-Authored-By: A <a@b>"),
        "allow",
    ),
    ("commit-heredoc-apostrophe", "git commit -m " + _h("fix: don't drop rows"), "allow"),
    ("head-literal-file", "head " + _h("README.md"), "allow"),
    # ruling R19d: literals only without assignments, environment-changing builtins or \r;
    # every body names a real file (README.md in the cwd), so a wrong allow is meaningful
    ("r19d-ifs-prefix", "IFS=/ head " + _h("README.md"), "deny"),
    ("r19d-bash-env-commit", "BASH_ENV=x git commit -m " + _h("README.md"), "deny"),
    ("r19d-env-prefix", "ENV=x head " + _h("README.md"), "deny"),
    ("r19d-standalone-assign", "X=1; head " + _h("README.md"), "deny"),
    ("r19d-subscript-assign", "functions[cat]='echo x'; head " + _h("README.md"), "deny"),
    ("r19d-array-assign", "BASH_ALIASES[cat]=x; head " + _h("README.md"), "deny"),
    ("r19d-append-assign", "PATH+=:b; head " + _h("README.md"), "deny"),
    ("r19d-zsh-array", "path=(b $path); head " + _h("README.md"), "deny"),
    ("r19d-arith-assign", "(( IFS = 3 )); head " + _h("README.md"), "deny"),
    ("r19d-arith-comma", "echo $((y,IFS=3)); head " + _h("README.md"), "deny"),
    ("r19d-param-default", "echo ${{IFS:=/}}; head " + _h("README.md"), "deny"),
    ("r19d-trap-debug", "trap 'x' DEBUG; head " + _h("README.md"), "deny"),
    ("r19d-export-f", "export -f f; head " + _h("README.md"), "deny"),
    ("r19d-declare-f", "declare -f; head " + _h("README.md"), "deny"),
    ("r19d-setopt", "setopt x; head " + _h("README.md"), "deny"),
    ("r19d-cd-parent", "cd .. && head " + _h("repo/README.md"), "deny"),
    ("r19d-builtin-cd", "builtin cd .. && head " + _h("repo/README.md"), "deny"),
    ("r19d-wrapped-setopt", "noglob setopt x; head " + _h("README.md"), "deny"),
    ("r19d-if-set", "if set -f; then head " + _h("README.md") + "; fi", "deny"),
    ("r19d-read-ifs", "read -r IFS <<<x; head " + _h("README.md"), "deny"),
    ("r19d-printf-v", "printf -v IFS x; head " + _h("README.md"), "deny"),
    ("r19d-crlf-commit", "git commit -m " + _h("README.md").replace("\n", "\r\n"), "deny"),
    ("r19d-cr-body", "head " + _h("README.md\r"), "deny"),
    ("r19d-cr-trailing", "head " + _h("README.md") + "\r", "deny"),
    *[
        (f"r19d-prog-{word}", f"{word} x; head " + _h("README.md"), "deny")
        for word in (
            *("set", "unset", "trap", "export", "declare", "typeset", "local", "readonly"),
            *("builtin", "command", "eval", "source", ".", "alias", "unalias", "shopt"),
            *("enable", "hash", "autoload", "functions", "emulate", "setopt", "unsetopt"),
            *("zmodload", "exec", "cd", "pushd", "popd"),
            *("read", "mapfile", "readarray", "getopts", "let", "vared"),
        )
    ],
    ("r19d-add-commit", "git add x && git commit -m " + _h("fix: tidy"), "allow"),
    ("r19d-add-dot-commit", "git add . && git commit -m " + _h("fix: tidy"), "allow"),
    ("r19d-gh-pr", "gh pr create --title t --body " + _h("## Summary\n- x"), "allow"),
    (
        "r19d-body-words",
        "git commit -m "
        + _h("set up PATH=/x and export it\n\ncd docs; unset X; trap; declare -f\nIFS=/ x"),
        "allow",
    ),
    # ruling R19a: escapes and other conversions are not literal
    ("printf-escape", "cat {tmp}/mnt/$(printf 'p\\x68i')/rows.csv", "deny"),
    ("echo-e-escape", "cat {tmp}/mnt/$(echo -e 'p\\x68i')/rows.csv", "deny"),
    ("echo-backslash", "cat {tmp}/mnt/$(echo 'p\\x68i')/rows.csv", "deny"),
    ("printf-conversion", "cat {tmp}/mnt/$(printf %c phi)/rows.csv", "deny"),
    ("echo-n-literal", "ls $(echo -n src)", "deny"),
    ("printf-s-literal", "ls $(printf '%s' src)", "deny"),
    ("colon-prefix", "cat file:../mnt/phi/rows.csv", "deny"),
    ("bracket-prefix", "echo [../mnt/phi/rows.csv]", "deny"),
    ("link-dotdot", "cat data/../phi-sibling/rows.csv", "deny"),
    # ruling R22: `..` read as text too (logical cd); only that reading reaches R here
    ("textual-dotdot", "cat lnk/../mnt/phi/rows.csv", "deny"),
    ("cd-logical", "cd lnk/.. && cat mnt/phi/rows.csv", "deny"),
    ("cd-logical-deep", "cd brain/up/.. && cat ../../mnt/phi/rows.csv", "deny"),
    ("cd-home", "cd ~ && cat phi/rows.csv", "deny"),
    ("loop-two-values", "for d in x ../mnt; do cat $d/phi/rows.csv; done", "deny"),
    ("too-many-values", "; ".join(f"X=v{n}" for n in range(70)) + "; cat $X$X/f", "deny"),
    ("unknown-middle-var", "cat ../mnt/${{Y}}/rows.csv", "deny"),
    ("find-L-link", "find -L .", "deny"),
    ("env-split-claude", "env -S 'claude -p'", "deny"),
    ("guard-file-case", "cat brain/.LABBRAIN/config.yaml", "deny"),
    ("python-chdir", "python -c \"import os; os.chdir('../mnt'); open('phi/rows.csv')\"", "deny"),
    # --- everyday commands that must keep working
    ("script", "python train.py --config configs/a.yaml", "allow"),
    ("ls-parent", "ls {tmp}/mnt", "allow"),
    ("git-status", "git status", "allow"),
    ("labbrain", 'uvx --from "{plugin_root}" labbrain lint', "allow"),
    ("grep-r-link-nofollow", "grep -r x .", "allow"),
    ("rg-link-nofollow", "rg x", "allow"),
    ("echo-path-var", "echo $PATH", "allow"),
    ("special-params", "echo $? $#", "allow"),
    ("awk-single-quoted", "awk '{{print $1}}' notes.txt | sort | uniq -c", "allow"),
    ("ls-glob", "ls *.md", "allow"),
    ("comment-apostrophe", "ls # don't worry", "allow"),
    ("git-log", "git log --oneline -5 && git diff --stat", "allow"),
    ("uv-run-pytest", "uv run pytest -q tests/test_x.py", "allow"),
    ("echo-home", 'echo "$HOME" && cd brain && ls', "allow"),
    ("labbrain-new", 'uvx --from "{plugin_root}" labbrain new experiment --title "A b"', "allow"),
    ("mkdir-cd", "mkdir -p out && cd out && touch a.txt", "allow"),
    ("git-commit", "git add -A && git commit -m 'feat: x'", "allow"),
    ("loop-allowed", "for d in src docs; do ls $d; done", "allow"),
    ("uv-run-script", "uv run python train.py", "allow"),
    ("wc-glob", "wc -l *.py && ls -la", "allow"),
    ("make-C", "make -C build test", "allow"),
    ("find-nofollow", "find . -name '*.csv'", "allow"),
    ("labbrain-env-var", 'uvx --from "${{CLAUDE_PLUGIN_ROOT}}" labbrain lint', "allow"),
    ("redirect", "python train.py > out.log 2>&1", "allow"),
    (
        "quoted-heredoc-script",
        "cat > run.sh <<'EOF'\nfor f in $FILES; do echo \"$f\"; done\nEOF",
        "allow",
    ),
]

# A second world: a real data folder `repo/data` (a root) that repo/.gitignore lists.
GITIGNORED_CASES: list[tuple[str, str, str]] = [
    ("rg-ignored", "rg x", "allow"),
    ("grep-r-ignored", "grep -r x .", "deny"),
    ("rg-u", "rg -u x", "deny"),
    ("rg-no-ignore", "rg --no-ignore-vcs x", "deny"),
    ("rg-glob-override", "rg -g 'data/**' x", "deny"),
    ("rg-explicit-data", "rg x data", "deny"),
    ("ls-star", "ls *", "deny"),
    ("ls-md", "ls *.md", "allow"),
]


@dataclass
class BashWorld:
    """Everything a corpus row needs: run `render(command)` from `cwd` with `env`."""

    tmp: Path
    repo: Path
    vault: Path
    root: Path  # R, the main protected root
    home: Path
    plugin_root: Path
    plugin_data: Path
    cwd: Path
    env: dict[str, str]
    subs: dict[str, str]
    sentinel: str
    session_id: str = SESSION
    data_paths: list[str] = field(default_factory=list)

    def render(self, command: str) -> str:
        for key, value in self.subs.items():
            command = command.replace("{" + key + "}", value)
        return command.replace("{{", "{").replace("}}", "}")

    def scope(self) -> Scope:
        return load_scope(self.cwd, self.env)

    def check(self, command: str, scope: Scope | None = None) -> Denial | None:
        return check_command(
            self.render(command), self.cwd, scope or self.scope(), self.env, self.session_id
        )


def make_bash_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, gitignored: bool = False
) -> BashWorld:
    """A protected subfolder-mode vault `repo/brain` in a git repo `repo`, the cwd.

    The root R is `<tmp>/mnt/phi`, also reachable as `~/phi` (a link in `$HOME`). Unless
    `gitignored`, `repo/data` links to `R/sub`, so `data/..` resolves to R itself while
    its lexical collapse would not; and the other way round (ruling R22), `repo/lnk` and
    `repo/brain/up` link deep into `<tmp>/other`, so `lnk/..` read as text is `repo` (where
    `repo/mnt` links to `<tmp>/mnt`) while resolved it is not. With `gitignored`, `repo/data` is instead a real data
    folder, a root of its own, listed in `repo/.gitignore`. A second root `R data` has a
    space in its name.
    """
    tmp = tmp_path.resolve()
    sentinel = secrets.token_hex(16)
    root = tmp / "mnt" / "phi"
    root.mkdir(parents=True)
    (root / "rows.csv").write_text(f"id\n{sentinel}\n")
    (root / "db.sqlite").write_text(sentinel)
    for sub in ("sub", "phi-sibling"):
        (root / sub).mkdir()
        (root / sub / "rows.csv").write_text(sentinel)
    spaced = tmp / "mnt" / "phi data"
    spaced.mkdir()
    (spaced / "f.csv").write_text(sentinel)
    home = tmp / "home"
    home.mkdir()
    (home / "phi").symlink_to(root)
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("# repo\n")
    (repo / "train.py").write_text("print('train')\n")
    data_paths = [str(root), str(spaced)]
    if gitignored:
        (repo / "data").mkdir()
        (repo / "data" / "rows.csv").write_text(sentinel)
        (repo / ".gitignore").write_text("data/\n")
        data_paths.append(str(repo / "data"))
    else:
        (repo / "data").symlink_to(root / "sub")
        (tmp / "other" / "deep").mkdir(parents=True)
        (tmp / "other" / "a" / "b" / "deep").mkdir(parents=True)
        (repo / "lnk").symlink_to(tmp / "other" / "deep")
        (repo / "mnt").symlink_to(tmp / "mnt")
    vault = make_vault(repo / "brain", MIN_CONFIG + f"data_paths: {json.dumps(data_paths)}\n")
    if not gitignored:
        (vault / "up").symlink_to(tmp / "other" / "a" / "b" / "deep")
    plugin_root = tmp / "plugin"
    (plugin_root / "labbrain" / "hooks").mkdir(parents=True)
    (plugin_root / "labbrain" / "hooks" / "guard.py").write_text("")
    plugin_data = tmp / "plugin-data"
    monkeypatch.setenv("HOME", str(home))
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "CLAUDE_PROJECT_DIR": str(repo),
        "LABBRAIN_VAULT": "brain",
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subs = {
        "tmp": str(tmp),
        "R_upper": str(root).upper(),
        "R": str(root),
        "plugin_root": str(plugin_root),
    }
    return BashWorld(
        tmp=tmp,
        repo=repo,
        vault=vault,
        root=root,
        home=home,
        plugin_root=plugin_root,
        plugin_data=plugin_data,
        cwd=repo,
        env=env,
        subs=subs,
        sentinel=sentinel,
        data_paths=data_paths,
    )


def _decision(denial: Denial | None) -> str:
    return "allow" if denial is None else "deny"


@pytest.mark.parametrize(("case_id", "command", "expected"), CASES, ids=[c[0] for c in CASES])
def test_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str, command: str, expected: str
) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    assert w.scope().protected
    assert _decision(w.check(command)) == expected, w.render(command)


@pytest.mark.parametrize(
    ("case_id", "command", "expected"), GITIGNORED_CASES, ids=[c[0] for c in GITIGNORED_CASES]
)
def test_gitignored_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str, command: str, expected: str
) -> None:
    w = make_bash_world(tmp_path, monkeypatch, gitignored=True)
    assert _decision(w.check(command)) == expected, w.render(command)


def test_unprotected_scope_allows_all_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    config = w.vault / ".labbrain" / "config.yaml"
    config.write_text(config.read_text() + "protected_data: false\n")
    scope = w.scope()
    assert not scope.protected and scope.targets.roots == ()
    for case_id, command, _ in CASES + GITIGNORED_CASES:
        assert w.check(command, scope) is None, case_id


def test_bash_messages_never_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worlds = [
        (make_bash_world(tmp_path / "main", monkeypatch), CASES),
        (make_bash_world(tmp_path / "ignored", monkeypatch, gitignored=True), GITIGNORED_CASES),
    ]
    for w, cases in worlds:
        scope = w.scope()
        for case_id, command, expected in cases:
            if expected != "deny":
                continue
            denial = w.check(command, scope)
            assert denial is not None, case_id
            text = w.render(command)
            assert text not in denial.message, case_id
            assert "rows.csv" not in denial.message and "f.csv" not in denial.message, case_id
            assert w.sentinel not in denial.message, case_id
            assert "\n" not in denial.message, case_id
            if denial.rule == "data-guard" and denial.message != UNCONFIDENT_MESSAGE:
                assert "protected data path #" in denial.message, case_id
            assert denial.rule in ("data-guard", "guard-config"), case_id


def test_rules_and_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    scope = w.scope()

    def denial(command: str) -> Denial:
        found = w.check(command, scope)
        assert found is not None, command
        return found

    for command in ("claude -p hi", "copier update", "cp x.py {plugin_root}", "rm -rf brain"):
        assert denial(command) == Denial("guard-config", GUARD_MESSAGE)
    for command in ('cat "$DATA_DIR/rows.csv"', "cat $(pwd)/../mnt/phi/rows.csv"):
        assert denial(command) == Denial("data-guard", UNCONFIDENT_MESSAGE)
    found = denial("cat {R}/rows.csv")
    assert found.rule == "data-guard" and "#1" in found.message
    assert f"('{w.root}')" in found.message
    assert "#2" in denial('cat "{R} data/f.csv"').message
    assert GUARD_MESSAGE == (
        "lab-brain guard: this Bash command would change lab-brain or Claude Code guard "
        "settings, or start a nested agent, in a protected vault. Ask the user to run it."
    )
    assert UNCONFIDENT_MESSAGE == (
        "lab-brain data guard: this Bash command cannot be checked safely (it uses an "
        "unresolved variable, a command substitution, or dynamic evaluation) in a protected "
        "vault. Spell paths out, or ask the user to run it themselves."
    )


def test_unconfident_basename_word(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    # Dynamic evaluation that names the root's final component is denied; without it, allowed.
    assert w.check("echo x | xargs -I{{}} cat phi/{{}}") is not None
    assert w.check("echo x | xargs echo") is None
    assert w.check("echo cGhp | base64 -d") is None
    # "exec" inside inline code makes the command unconfident too.
    assert w.check("echo 'exec(open(\"phi\"))'") is not None
    assert w.check("echo 'run(open(\"phi\"))'") is None


def test_scope_without_roots_checks_only_self_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    scope = w.scope()
    no_roots = Scope(
        scope.vaults,
        type(scope.targets)((), scope.targets.guard_files),
        scope.agents,
        True,
        scope.project_dir,
        scope.env,
    )
    assert w.check("cat {R}/rows.csv", no_roots) is None
    assert w.check("claude -p hi", no_roots) == Denial("guard-config", GUARD_MESSAGE)
    assert w.check("cat brain/.labbrain/config.yaml", no_roots) is not None


def test_cwd_inside_root_denies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    scope = w.scope()
    assert check_command("ls", w.root, scope, w.env, SESSION) is not None


def test_link_walk_is_cached_under_plugin_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    assert w.check("grep -r x .") is None
    files = list((w.plugin_data / "exposure").glob("*.json"))
    assert len(files) == 1
    assert w.sentinel not in files[0].read_text()


def test_truncated_walk_denies_any_recursion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    w.env.pop("CLAUDE_PLUGIN_DATA")
    monkeypatch.setattr("labbrain.hooks.exposure.WALK_LIMIT", 3)
    for n in range(5):
        (w.repo / f"f{n}.txt").write_text("")
    assert w.check("grep -r x .") == Denial("data-guard", UNCONFIDENT_MESSAGE)
    assert w.check("git status") is None


def test_gitignore_check_needs_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch, gitignored=True)
    scope = w.scope()
    assert w.check("rg x", scope) is None
    no_git = {**w.env, "PATH": str(tmp_path / "empty-bin")}
    assert check_command("rg x", w.cwd, scope, no_git, SESSION) is not None
    # An .ignore file could re-include the data folder for rg, so the exception lapses.
    (w.repo / ".ignore").write_text("!data/\n")
    assert w.check("rg x", scope) is not None


def test_subprocess_output_never_reaches_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    w = make_bash_world(tmp_path, monkeypatch, gitignored=True)
    scope = w.scope()
    shutil.rmtree(w.repo / ".git")  # git check-ignore now fails loudly ("not a git repository")
    capfd.readouterr()
    assert w.check("rg x", scope) is not None
    out, err = capfd.readouterr()
    assert out == "" and err == ""


def test_program_lists_in_one_place() -> None:
    assert {"grep", "rg", "find", "tar", "zip", "rsync", "cp", "git grep"} <= set(RECURSIVE)
    assert {"grep", "rg", "find", "zip", "tar", "cp", "rsync"} <= set(FOLLOWING)
    assert {"python", "node", "perl", "ruby", "rscript", "duckdb", "sqlite3"} <= INTERPRETERS
    assert bash.RECURSIVE is RECURSIVE


def test_readings_physical_and_textual(tmp_path: Path) -> None:
    """Ruling R22: both readings of `..`; the physical one is never dropped."""
    (tmp_path / "far" / "deep").mkdir(parents=True)
    (tmp_path / "here").mkdir()
    (tmp_path / "here" / "lnk").symlink_to(tmp_path / "far" / "deep")
    base = tmp_path.resolve() / "here"
    readings = bash._readings("lnk/../x", base)
    assert readings == [tmp_path.resolve() / "far" / "x", base / "x"]
    assert bash._readings("/plain/path", base) == [Path("/plain/path")]


def test_tokenizer_matches_shlex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The linear tokenizer for long commands splits exactly like shlex."""
    w = make_bash_world(tmp_path, monkeypatch)
    extra = [
        "a\"b c\"d 'e f'g",
        'x\\ y "q\\"r" "s\\$t" "u\\\\v"',
        "a;b&&c||d|e&f (g) <h >>i 2>&1",
        "line1\nline2 ;\n x",
        "'' \"\" end",
        "unclosed 'quote",
        'unclosed "quote',
        "trailing \\",
    ]
    for command in [w.render(c) for _, c, _ in CASES + GITIGNORED_CASES] + extra:
        marked = bash._scan(command).marked
        try:
            expected: list[str] | None = bash._shlex(marked)
        except ValueError:
            expected = None
        try:
            got: list[str] | None = bash._tokenize(marked)
        except ValueError:
            got = None
        assert got == expected, command


@pytest.mark.slow
def test_huge_commands_are_decided_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Over 1 MB with long undelimited runs: decided (either way) in under 2 s each."""
    w = make_bash_world(tmp_path, monkeypatch)
    scope = w.scope()
    commands = [
        "echo " + "ab/cd." * 200_000,
        "python3 -c '" + "x" * 1_000_000 + "'",
        'echo "' + "a/b $HOME " * 110_000 + '"',
        "cat > f.py <<'EOF'\n" + "print('hello')  # a/b.c\n" * 45_000 + "EOF",
        "echo " + "{a,b}/" * 200_000,
        "echo " + "$X/" * 400_000,
    ]
    for command in commands:
        assert len(command) >= 1_000_000
        began = time.perf_counter()
        w.check(command, scope)
        assert time.perf_counter() - began < 2.0, command[:40]
    # A big heredoc that names nothing protected is still allowed.
    assert w.check(commands[3], scope) is None


def test_lexer_failure_is_unconfident(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_bash_world(tmp_path, monkeypatch)
    assert w.check("echo 'unclosed") is None  # nothing names the root
    assert w.check("echo 'unclosed phi") is not None
    assert w.check('echo "$(unclosed') is not None
