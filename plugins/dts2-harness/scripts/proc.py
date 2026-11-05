"""Every child process the harness starts goes through here: one place for the timeout (a hung child is killed and
reports exit 143), the 429 and overload backoff, the CLI version pin check, the fallback-model flags and dry runs.

A `Runner` is the seam. `SubprocessRunner` starts a real process; `FakeRunner` answers from a script and records the
calls, so tests never need a fake executable; `DryRunRunner` records and runs nothing. The retry and kill logic used to
live in model_call.py; it moved here and model_call imports it, so there is one copy."""
from __future__ import annotations

import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Final

EXIT_TERMINATED: Final[int] = 143
EXIT_NOT_FOUND: Final[int] = 127
SIGNALS_TERMINATED: Final[frozenset[int]] = frozenset({143, 124, -signal.SIGTERM, -signal.SIGKILL})
KILL_GRACE_S: Final[int] = 5
DEFAULT_TIMEOUT_S: Final[int] = 30
MAX_FALLBACK_MODELS: Final[int] = 3
OVERLOAD: Final[re.Pattern[str]] = re.compile(r"\b429\b|\b529\b|rate[ _-]?limit|overloaded", re.I)
VERSION: Final[re.Pattern[str]] = re.compile(r"(\d+\.\d+\.\d+)")
ANSI: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
Result = dict[str, Any]  # {"code", "stdout", "stderr", "timed_out"}
Event = Callable[[dict[str, Any]], None]


def binary(name: str, default: str) -> list[str]:
    """argv head for a tool: the `name` environment override if set, else `default`. A `.py` override runs under this
    Python; anything else is resolved on PATH (Windows needs which() to find `npx.cmd`)."""
    value: str = os.environ.get(name, default)
    if value.endswith(".py"):
        return [sys.executable, value]
    return [shutil.which(value) or value]


def terminate(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """SIGTERM the whole process group, then SIGKILL after a grace period; the partial output."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass  # the group already exited or is not ours to signal; communicate() below still reaps the child
        try:
            out, err = proc.communicate(timeout=KILL_GRACE_S)
            return out or "", err or ""
        except subprocess.TimeoutExpired:
            continue
    return "", ""


def run_once(argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
             stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> Result:
    """Run one command to completion or to the wall-clock limit. A timeout reports exit 143 and `timed_out`.
    `stdin_text` is piped to the child (a prompt); without it stdin is closed. `on_start` gets the child's pid."""
    try:
        proc: subprocess.Popen[str] = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=env, start_new_session=True)
    except OSError as exc:
        return {"code": EXIT_NOT_FOUND, "stdout": "", "stderr": str(exc), "timed_out": False}
    if on_start is not None:
        on_start(proc.pid)
    try:
        out, err = proc.communicate(input=stdin_text, timeout=max(1.0, timeout_s))
    except subprocess.TimeoutExpired:
        out, err = terminate(proc)
        return {"code": EXIT_TERMINATED, "stdout": out, "stderr": err, "timed_out": True}
    return {"code": proc.returncode, "stdout": out or "", "stderr": err or "", "timed_out": False}


class Runner:
    """Starts one command and returns its Result. Subclasses are the adapters."""

    def run(self, argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
            stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> Result:
        raise NotImplementedError


class SubprocessRunner(Runner):
    def run(self, argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
            stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> Result:
        return run_once(argv, cwd, timeout_s, env, stdin_text, on_start)


class FakeRunner(Runner):
    """Answers from a script. Each entry is a Result (or a partial one: missing keys default to a clean empty exit 0) or a
    callable taking the argv and returning one. Every call is recorded in `calls`. Running out of answers is an error."""

    def __init__(self, answers: list[Any] | None = None, default: Any = None) -> None:
        self.answers: list[Any] = list(answers or [])
        self.default: Any = default
        self.calls: list[dict[str, Any]] = []

    def run(self, argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
            stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> Result:
        self.calls.append({"argv": list(argv), "cwd": str(cwd), "timeout_s": timeout_s, "stdin": stdin_text})
        if self.answers:
            answer: Any = self.answers.pop(0)
        elif self.default is not None:
            answer = self.default
        else:
            raise AssertionError(f"FakeRunner has no answer left for {argv}")
        result: Any = answer(argv) if callable(answer) else answer
        return {"code": 0, "stdout": "", "stderr": "", "timed_out": False, **result}


class DryRunRunner(Runner):
    """Records what would run and runs nothing; every call is a clean exit 0 flagged `dry_run`."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
            stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> Result:
        self.calls.append(list(argv))
        return {"code": 0, "stdout": "", "stderr": "", "timed_out": False, "dry_run": True}


def run(cmd: list[str], cwd: Path | str, *, timeout_s: float = DEFAULT_TIMEOUT_S, runner: Runner | None = None,
        strip_ansi: bool = False, merge_stderr: bool = False, timeout_code: int = EXIT_TERMINATED) -> tuple[int, str]:
    """(exit code, stdout) of one command; never raises. A start failure is 127, a timeout `timeout_code` (143).
    `merge_stderr` returns stdout then stderr; `strip_ansi` removes colour codes."""
    result: Result = (runner or SubprocessRunner()).run(cmd, cwd, timeout_s, None, None, None)
    out: str = result["stdout"] + (result["stderr"] if merge_stderr else "")
    if result["timed_out"]:
        return timeout_code, "timed out"
    if result["code"] == EXIT_NOT_FOUND and not result["stdout"] and result["stderr"] and not merge_stderr:
        return EXIT_NOT_FOUND, result["stderr"]
    return result["code"], ANSI.sub("", out) if strip_ansi else out


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """base * 2^attempt, capped, plus up to `base` of jitter."""
    jitter: float = (rng or random).uniform(0, base)
    return min(cap, base * (2 ** attempt)) + jitter


def looks_overloaded(text: str) -> bool:
    return OVERLOAD.search(text) is not None


def run_retrying(attempt_fn: Callable[[float], Result], timeout_s: float, *, retry_max: int, base_s: float, cap_s: float,
                 retriable: Callable[[Result], bool], halt: Callable[[Result], bool] | None = None,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
                 clock: Callable[[], float] = time.monotonic, emit: Event | None = None, label: str = "",
                 stderr_chars: int = 4000) -> Result:
    """Call `attempt_fn(seconds_left)` until it succeeds, a failure is not `retriable`, `retry_max` retries are spent, or
    the one deadline `timeout_s` would be crossed by the next backoff. Each retry waits an exponential backoff with
    jitter and reports a `retry` event. `halt` ends the retries early (a session is open: resume it, do not restart).
    The result lists every attempt's code and stdout under `results`."""
    send: Event = emit or (lambda _event: None)
    deadline: float = clock() + timeout_s
    attempt: int = 0
    results: list[Result] = []
    while True:
        result: Result = attempt_fn(deadline - clock())
        results.append({"code": result["code"], "stdout": result["stdout"], "stderr": result["stderr"][-stderr_chars:]})
        done: Result = {**result, "attempts": attempt + 1, "retries": attempt, "results": results, "halted_overload": False}
        if result["timed_out"] or not retriable(result) or attempt >= retry_max:
            return done
        if halt is not None and halt(result):
            send({"event": "retry-halted", "label": label, "attempt": attempt + 1, "reason": "session-open"})
            return {**done, "halted_overload": True}
        delay: float = backoff_delay(attempt, base_s, cap_s, rng)
        if clock() + delay >= deadline:
            return done
        send({"event": "retry", "label": label, "attempt": attempt + 1, "delay_s": round(delay, 3),
              "code": result["code"], "reason": "429-or-overload"})
        sleep(delay)
        attempt += 1


def is_terminated(code: int) -> bool:
    """Exit 143 (SIGTERM) and its neighbours: the wall-clock cap or an outside kill. The lane ends incomplete."""
    return code in SIGNALS_TERMINATED


def cli_version(text: str) -> str | None:
    """x.y.z from `claude --version` output, or None when it cannot be read."""
    match = VERSION.search(text)
    return match.group(1) if match else None


def version_problem(pinned: Any, actual: str | None, tool: str = "claude") -> str | None:
    """Why the CLI may not be used under this pin, or None. An unreadable version fails closed; no pin accepts any."""
    if actual is None:
        return f"cannot read `{tool} --version`"
    if isinstance(pinned, str) and pinned != actual:
        return f"{tool} {actual} differs from the version {pinned} pinned for this run"
    return None


def fallback_flags(models: list[str]) -> list[str]:
    """`--fallback-model a,b,c` (a chain tried in order, at most 3 models), or nothing when the chain is empty."""
    chain: list[str] = [m for m in models if m][:MAX_FALLBACK_MODELS]
    return ["--fallback-model", ",".join(chain)] if chain else []


def finite_nonnegative(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else default
