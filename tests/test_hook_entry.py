"""`labbrain hook …`: payload parsing, the exit contract and the fixed failure messages."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from helpers import clean_env, hook_payload

from labbrain.hooks import entry, guard, post, session, writes
from labbrain.hooks.entry import EVENTS, run_hook
from labbrain.hooks.paths import ProtectedRoot
from labbrain.hooks.payload import MAX_STDIN, Denial, PayloadError, data_denial, parse_payload

PRE_FAILED = "lab-brain guard failed; blocked to be safe"
POST_FAILED = "lab-brain validator failed"
SESSION_FAILED = "lab-brain session brief failed"


def raise_secret(*_: Any) -> Any:
    raise RuntimeError("SECRET")


def test_fixtures_have_the_recorded_key_sets() -> None:
    tool_keys = {
        "session_id",
        "transcript_path",
        "cwd",
        "permission_mode",
        "hook_event_name",
        "prompt_id",
        "scratchpad_dir",
        "tool_name",
        "tool_input",
        "tool_use_id",
    }
    inputs = {
        "read": {"file_path"},
        "write": {"file_path", "content"},
        "edit": {"file_path", "old_string", "new_string", "replace_all"},
        "bash": {"command", "description"},
        "post_write": {"file_path", "content"},
    }
    for name, keys in inputs.items():
        data = json.loads(hook_payload(name))
        extra = {"duration_ms", "tool_response"} if name == "post_write" else set()
        assert set(data) == tool_keys | extra, name
        assert set(data["tool_input"]) == keys, name
    response = json.loads(hook_payload("post_write"))["tool_response"]
    assert set(response) == {
        "type",
        "filePath",
        "content",
        "structuredPatch",
        "originalFile",
        "userModified",
    }
    start = json.loads(hook_payload("session_start"))
    assert set(start) == {
        "session_id",
        "transcript_path",
        "cwd",
        "hook_event_name",
        "scratchpad_dir",
        "source",
    }


def test_hook_payload_substitutes_and_overrides(tmp_path: Path) -> None:
    data = json.loads(hook_payload("edit", cwd=tmp_path, path=tmp_path / "f.md", old="a"))
    assert data["cwd"] == str(tmp_path)
    assert data["tool_input"]["file_path"] == str(tmp_path / "f.md")
    assert data["tool_input"]["old_string"] == "a"
    assert data["tool_input"]["new_string"] == "{new}"  # not given: stays literal
    data = json.loads(hook_payload("read", cwd="/x", tool_name="Grep", tool_input={"path": "/y"}))
    assert (data["tool_name"], data["tool_input"]) == ("Grep", {"path": "/y"})


def test_parse_payload_fields(tmp_path: Path) -> None:
    p = parse_payload(hook_payload("bash", cwd=tmp_path, command="ls -la"))
    assert (p.event, p.tool_name, p.source) == ("PreToolUse", "Bash", "")
    assert p.tool_input == {"command": "ls -la", "description": "Run a command"}
    assert p.cwd == tmp_path and p.session_id == "00000000-0000-4000-8000-000000000001"
    s = parse_payload(hook_payload("session_start", cwd=tmp_path, source="resume"))
    assert (s.event, s.tool_name, s.tool_input, s.source) == ("SessionStart", "", {}, "resume")


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"\xff\xfe",
        b"[]",
        b"{}",
        b'{"cwd": ""}',
        b'{"cwd": "relative/dir"}',
        b'{"cwd": 7}',
        b'{"cwd": "/a\\u0000b"}',
        b'{"cwd": "/a", "tool_input": "x"}',
        b'{"cwd": "/a", "tool_input": []}',
        b'{"cwd": "/a", "tool_name": 3}',
        b'{"cwd": "/a", "hook_event_name": null}',
        b'{"cwd": "/a", "session_id": {}}',
        b'{"cwd": "/a", "source": 1}',
        b"[" * 100_000,
    ],
)
def test_parse_payload_rejects(data: bytes) -> None:
    with pytest.raises(PayloadError):
        parse_payload(data)


def test_parse_payload_rejects_oversized() -> None:
    with pytest.raises(PayloadError):
        parse_payload(b'{"cwd": "/a"}' + b" " * MAX_STDIN)


def test_bad_json_denies() -> None:
    assert run_hook("pre-tool-use", b"not json", {}) == (2, "", PRE_FAILED)


def test_oversized_stdin_denies(tmp_path: Path) -> None:
    valid = hook_payload("read", cwd=tmp_path, path=tmp_path / "f")
    assert run_hook("pre-tool-use", valid, {}) == (0, "", "")
    padded = valid + b" " * (MAX_STDIN + 1 - len(valid))
    assert len(padded) == MAX_STDIN + 1
    assert run_hook("pre-tool-use", padded, {}) == (2, "", PRE_FAILED)


def test_exception_denies_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(guard, "check_tool", raise_secret)
    result = run_hook("pre-tool-use", hook_payload("read", cwd=tmp_path, path="/f"), {})
    assert result == (2, "", PRE_FAILED)
    captured = capsys.readouterr()
    for text in (*result[1:], captured.out, captured.err):
        assert "SECRET" not in text and "Traceback" not in text


def test_exit_and_stray_output_never_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def noisy(*_: Any) -> None:
        print('{"permissionDecision": "allow"}')
        print("SECRET", file=sys.stderr)
        sys.exit(0)

    monkeypatch.setattr(writes, "check_write", noisy)
    result = run_hook("pre-tool-use", hook_payload("write", cwd=tmp_path, path="/f"), {})
    assert result == (2, "", PRE_FAILED)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_denial_message_is_stderr_and_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    denial = Denial("data-guard", "lab-brain data guard: denied.")
    monkeypatch.setattr(guard, "check_tool", lambda payload, scope: denial)
    monkeypatch.setattr(writes, "check_write", raise_secret)  # never reached
    result = run_hook("pre-tool-use", hook_payload("read", cwd=tmp_path, path="/f"), {})
    assert result == (2, "", denial.message)


def test_write_check_runs_after_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def check(payload: Any, scope: Any) -> Denial:
        seen.append(payload.tool_name)
        return Denial("frozen-file", "lab-brain frozen-file guard: denied.")

    monkeypatch.setattr(writes, "check_write", check)
    result = run_hook("pre-tool-use", hook_payload("write", cwd=tmp_path, path="/f"), {})
    assert result == (2, "", "lab-brain frozen-file guard: denied.")
    assert seen == ["Write"]


def test_allow_is_silent(tmp_path: Path) -> None:
    payload = hook_payload("read", cwd=tmp_path, path=tmp_path / "notes.md")
    assert run_hook("pre-tool-use", payload, clean_env()) == (0, "", "")


def test_stubs_find_nothing(tmp_path: Path) -> None:
    write = hook_payload("post_write", cwd=tmp_path, path=tmp_path / "a.md", content="x")
    assert run_hook("post-tool-use", write, {}) == (0, "", "")
    start = hook_payload("session_start", cwd=tmp_path, source="startup")
    assert run_hook("session-start", start, {}) == (0, "", "")


def test_post_and_session_failures_use_fixed_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = hook_payload("post_write", cwd=tmp_path, path=tmp_path / "a.md", content="x")
    start = hook_payload("session_start", cwd=tmp_path, source="startup")
    assert run_hook("post-tool-use", b"not json", {}) == (2, "", POST_FAILED)
    assert run_hook("session-start", b"not json", {}) == (2, "", SESSION_FAILED)
    monkeypatch.setattr(post, "post_tool_use", raise_secret)
    monkeypatch.setattr(session, "session_start", raise_secret)
    assert run_hook("post-tool-use", write, {}) == (2, "", POST_FAILED)
    assert run_hook("session-start", start, {}) == (2, "", SESSION_FAILED)
    # A delegate returning an exit code outside the contract is a failure too.
    monkeypatch.setattr(post, "post_tool_use", lambda payload, env: (1, "SECRET"))
    monkeypatch.setattr(session, "session_start", lambda payload, env: (3, "SECRET", ""))
    assert run_hook("post-tool-use", write, {}) == (2, "", POST_FAILED)
    assert run_hook("session-start", start, {}) == (2, "", SESSION_FAILED)
    # Reports and briefs pass through.
    monkeypatch.setattr(post, "post_tool_use", lambda payload, env: (2, "lab-brain: 1 error"))
    monkeypatch.setattr(session, "session_start", lambda payload, env: (0, "brief\n", ""))
    assert run_hook("post-tool-use", write, {}) == (2, "", "lab-brain: 1 error")
    assert run_hook("session-start", start, {}) == (0, "brief\n", "")


def test_unknown_event_denies(tmp_path: Path) -> None:
    assert EVENTS == ("pre-tool-use", "post-tool-use", "session-start")
    assert run_hook("stop", hook_payload("read", cwd=tmp_path), {}) == (2, "", PRE_FAILED)


def test_entry_calls_through_module_attributes() -> None:
    """Later tasks and tests replace guard/writes/post/session functions by attribute."""
    assert entry.guard is guard and entry.writes is writes
    assert entry.post is post and entry.session is session


def run_cli(event: str, data: bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "labbrain", "hook", event],
        input=data,
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
    )


def test_cli_hook_subcommand(tmp_path: Path) -> None:
    proc = run_cli("pre-tool-use", b"{}", tmp_path)
    assert proc.returncode == 2
    assert (proc.stdout, proc.stderr.decode()) == (b"", PRE_FAILED + "\n")
    proc = run_cli("pre-tool-use", hook_payload("read", cwd=tmp_path, path="/f"), tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")
    proc = run_cli("post-tool-use", b"", tmp_path)
    assert (proc.returncode, proc.stderr.decode()) == (2, POST_FAILED + "\n")
    proc = run_cli("session-start", b"", tmp_path)
    assert (proc.returncode, proc.stderr.decode()) == (2, SESSION_FAILED + "\n")
    proc = run_cli("pre-tool-use", b" " * (MAX_STDIN + 10), tmp_path)
    assert (proc.returncode, proc.stderr.decode()) == (2, PRE_FAILED + "\n")


def test_cli_hook_path_skips_pydantic(tmp_path: Path) -> None:
    probe = (
        "import sys\n"
        "from labbrain.cli import main\n"
        "code = main(['hook', 'pre-tool-use'])\n"
        "print(code, 'pydantic' in sys.modules, file=sys.stderr)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        input=hook_payload("bash", cwd=tmp_path, command="ls"),
        cwd=tmp_path,
        env=clean_env(),
        capture_output=True,
        check=True,
    )
    assert (proc.stdout, proc.stderr.decode()) == (b"", "0 False\n")


def test_data_denial_copy(tmp_path: Path) -> None:
    root = ProtectedRoot(tmp_path, 1, "~/phi", tmp_path / "phi")
    denial = data_denial(root, "this Read call")
    assert denial.rule == "data-guard"
    assert denial.message == (
        "lab-brain data guard: this Read call refers to protected data path #1 ('~/phi'). "
        "Individual-level data must not enter the session. If you need this run, ask the "
        "user to run it themselves and share only aggregate results."
    )


def test_data_denial_keeps_one_paragraph(tmp_path: Path) -> None:
    root = ProtectedRoot(tmp_path, 3, "/mnt/a\nb\x1b[2J‮c", tmp_path / "x")
    message = data_denial(root, "this Bash command").message
    assert "\n" not in message and "\x1b" not in message and "‮" not in message
    assert "protected data path #3 ('/mnt/a b [2J c')" in message


def test_cli_hook_closed_stderr_still_exits_2(tmp_path: Path) -> None:
    """A deny whose reason cannot be written still exits 2, never 120: stderr is detached
    after a failed write, so the interpreter's final flush cannot fail again."""
    read_end, write_end = os.pipe()
    os.close(read_end)  # no reader: every write to the pipe fails with EPIPE
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "labbrain", "hook", "pre-tool-use"],
            input=b"{}",
            cwd=tmp_path,
            env=clean_env(),
            stdout=subprocess.PIPE,
            stderr=write_end,
        )
    finally:
        os.close(write_end)
    assert (proc.returncode, proc.stdout) == (2, b"")


def test_pre_deadline_denies_a_slow_check(tmp_path: Path) -> None:
    """Final review item 1(c): a pre-tool-use check that runs past PRE_DEADLINE_S exits 2
    with the fixed message, well before Claude Code's own hook timeout."""
    probe = (
        "import sys, time\n"
        "from labbrain.hooks import entry, guard\n"
        "entry.PRE_DEADLINE_S = 0.3\n"
        "def slow(*_):\n"
        "    print('SECRET', file=sys.stderr)\n"
        "    time.sleep(30)\n"
        "guard.check_tool = slow\n"
        "from labbrain.cli import main\n"
        "sys.exit(main(['hook', 'pre-tool-use']))\n"
    )
    began = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        input=hook_payload("bash", cwd=tmp_path, command="ls"),
        cwd=tmp_path,
        env=clean_env(),
        capture_output=True,
        timeout=60,
    )
    assert time.perf_counter() - began < 15
    assert (proc.returncode, proc.stdout, proc.stderr.decode()) == (2, b"", PRE_FAILED + "\n")


def test_pre_deadline_is_disarmed_after_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timer and the previous SIGALRM handler are restored; other events never arm it."""
    if not hasattr(signal, "setitimer"):
        pytest.skip("no interval timers on this platform")
    assert entry.PRE_DEADLINE_S == 60
    before = signal.getsignal(signal.SIGALRM)
    seen: list[float] = []

    def spy(*_: Any) -> None:
        seen.append(signal.getitimer(signal.ITIMER_REAL)[0])

    monkeypatch.setattr(guard, "check_tool", spy)
    code, _, _ = run_hook("pre-tool-use", hook_payload("read", cwd=tmp_path, path="/f"), {})
    assert code == 0
    assert seen and 0 < seen[0] <= 60
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) == before
    seen.clear()
    monkeypatch.setattr(post, "post_tool_use", lambda *_: (spy(), (0, ""))[1])
    run_hook("post-tool-use", hook_payload("post_write", cwd=tmp_path, path="/f"), {})
    assert seen == [0.0]
