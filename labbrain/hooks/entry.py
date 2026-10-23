"""`labbrain hook <event>`: one entry point per Claude Code hook event.

The exit contract: 0 (allow, or nothing to report) or 2 (deny or report, with a short
sanitized reason on stderr), never any other code. Nothing ever prints an allow decision.
Any failure exits 2 with a fixed message; the exception itself is never shown, because its
text can quote a command, a path or file contents. Output written to sys.stdout or
sys.stderr by the checks themselves is discarded: only the returned strings reach Claude.
That capture is Python-level only (the `sys` streams are swapped); a child process inherits
the real file descriptors, so a check that runs one must capture its output itself.

Ruling R37: a pre-tool-use call that runs past PRE_DEADLINE_S, well under the 120 s
timeout in hooks.json, is denied from a SIGALRM handler with the fixed message, so no
pathological input can outlast the hook (older Claude Code releases let a timed-out hook
through). Where interval timers are missing, or off the main thread, there is no deadline.
"""

from __future__ import annotations

import contextlib
import io
import os
import signal
import threading
from collections.abc import Callable, Iterator, Mapping
from types import FrameType

from labbrain.hooks import bash, guard, post, session, writes  # noqa: F401  (bash: via guard)
from labbrain.hooks.payload import parse_payload
from labbrain.hooks.scope import load_scope

EVENTS = ("pre-tool-use", "post-tool-use", "session-start")

PRE_FAILED = "lab-brain guard failed; blocked to be safe"
POST_FAILED = "lab-brain validator failed"
SESSION_FAILED = "lab-brain session brief failed"

PRE_DEADLINE_S: float = 60  # seconds; hooks.json gives the hook 120

Result = tuple[int, str, str]  # (exit code, stdout, stderr)


def _deadline_passed(_signum: int, _frame: FrameType | None) -> None:
    """Deny now: the fixed message straight to fd 2 (sys.stderr is a capture buffer here),
    then exit 2 without unwinding, so nothing the check was doing can still print."""
    with contextlib.suppress(OSError):
        os.write(2, (PRE_FAILED + "\n").encode())
    os._exit(2)


@contextlib.contextmanager
def _deadline(event: str) -> Iterator[None]:
    """Arm the R37 deadline for a pre-tool-use call, and restore the timer and handler."""
    armed = (
        event == "pre-tool-use"
        and hasattr(signal, "setitimer")
        and threading.current_thread() is threading.main_thread()
    )
    if not armed:
        yield
        return
    previous = signal.signal(signal.SIGALRM, _deadline_passed)
    signal.setitimer(signal.ITIMER_REAL, PRE_DEADLINE_S)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL if previous is None else previous)


def _pre_tool_use(stdin: bytes, env: Mapping[str, str]) -> Result:
    payload = parse_payload(stdin)
    scope = load_scope(payload.cwd, env)
    for check in (guard.check_tool, writes.check_write):
        denial = check(payload, scope)
        if denial is not None:
            return 2, "", denial.message or PRE_FAILED
    return 0, "", ""


def _post_tool_use(stdin: bytes, env: Mapping[str, str]) -> Result:
    code, err = post.post_tool_use(parse_payload(stdin), env)
    return code, "", err


def _session_start(stdin: bytes, env: Mapping[str, str]) -> Result:
    return session.session_start(parse_payload(stdin), env)


_HANDLERS: dict[str, tuple[Callable[[bytes, Mapping[str, str]], Result], str]] = {
    "pre-tool-use": (_pre_tool_use, PRE_FAILED),
    "post-tool-use": (_post_tool_use, POST_FAILED),
    "session-start": (_session_start, SESSION_FAILED),
}


def run_hook(event: str, stdin: bytes, env: Mapping[str, str]) -> Result:
    """(exit code, stdout, stderr) for the hook `event` given its payload bytes."""
    handler, failed = _HANDLERS.get(event, (None, PRE_FAILED))
    if handler is None:
        return 2, "", failed
    try:
        with (
            _deadline(event),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code, out, err = handler(stdin, env)
    except BaseException:  # fail closed, SystemExit and KeyboardInterrupt included
        return 2, "", failed
    if code not in (0, 2) or not isinstance(out, str) or not isinstance(err, str):
        return 2, "", failed
    return code, out, err
