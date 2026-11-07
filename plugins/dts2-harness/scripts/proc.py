"""Every child process the harness starts goes through here: one place for the timeout (a hung child is killed and
reports exit 143), the 429 and overload backoff, the CLI version pin check, the fallback-model flags and dry runs.

A `Runner` is the seam. `SubprocessRunner` starts a real process; `FakeRunner` answers from a script and records the
calls, so tests never need a fake executable; `DryRunRunner` records and runs nothing. The retry and kill logic used to
live in model_call.py; it moved here and model_call imports it, so there is one copy."""
from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Final

from state_io import atomic_write

EXIT_TERMINATED: Final[int] = 143
EXIT_NOT_FOUND: Final[int] = 127
SIGNALS_TERMINATED: Final[frozenset[int]] = frozenset({143, 124, -signal.SIGTERM, -getattr(signal, "SIGKILL", signal.SIGTERM)})
KILL_GRACE_S: Final[int] = 5
INT_GRACE_S: Final[float] = 30.0  # a son gets SIGINT, then SIGKILL after this long (`timeout -s INT -k 30` semantics)
GROUP_POLL_S: Final[float] = 0.1
KILL_SETTLE_S: Final[float] = 5.0  # after SIGKILL, how long to wait for the kernel to clear the group
SON_FILE: Final[str] = "son.json"  # pid, pgid, argv and session id of the lane's son
EXIT_FILE: Final[str] = "exit.json"  # written when the son's process ends: code, signal, cost, session id
RESUME_ENV: Final[str] = "CLAUDE_CODE_RESUME_INTERRUPTED_TURN"
FLAG_SESSION: Final[str] = "--session-id"
FLAG_RESUME: Final[str] = "--resume"
FLAG_FORMAT: Final[str] = "--output-format"
FORMAT_STREAM: Final[str] = "stream-json"
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


def signal_group(pgid: int, sig: int) -> bool:
    """Send `sig` to a process group; False when the group is gone or not ours."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def group_alive(pgid: int) -> bool:
    return signal_group(pgid, 0)


def interrupt_then_kill(proc: subprocess.Popen[str], grace_s: float | None = None) -> None:
    """SIGINT the child's process group, give it `grace_s` (INT_GRACE_S) to exit, then SIGKILL the group (which also sweeps
    any tool process the child left behind). The child is always reaped."""
    signal_group(proc.pid, signal.SIGINT)
    try:
        proc.wait(timeout=INT_GRACE_S if grace_s is None else grace_s)
    except subprocess.TimeoutExpired:
        pass  # the child ignored SIGINT for the whole grace period; the SIGKILL below ends it
    signal_group(proc.pid, signal.SIGKILL)
    proc.wait()


def pump(stream: Any, sink: list[str], on_line: Callable[[str], bool] | None, stop: threading.Event) -> None:
    for line in iter(stream.readline, ""):
        sink.append(line)
        if on_line is not None and on_line(line):
            stop.set()


def drain_readers(proc: subprocess.Popen[str], readers: list[threading.Thread], deadline: float) -> None:
    """Join the pipe readers until `deadline`. Descendants that keep the pipes open past it are SIGKILLed with the
    child's group, and only the streams whose reader finished are closed (closing one a reader blocks on would hang)."""
    for reader in readers:
        reader.join(timeout=max(0.0, deadline - time.monotonic()))
    if any(reader.is_alive() for reader in readers):
        signal_group(proc.pid, signal.SIGKILL)
        for reader in readers:
            reader.join(timeout=KILL_GRACE_S)
    for stream, reader in zip((proc.stdout, proc.stderr), readers):
        if stream is not None and not reader.is_alive():
            stream.close()


def run_streaming(proc: subprocess.Popen[str], timeout_s: float, stdin_text: str | None,
                  on_line: Callable[[str], bool]) -> Result:
    """Read the child's stdout line by line while it runs. `on_line` returning True stops it (stopped); the wall-clock
    limit stops it too (timed_out, exit 143). Either way the child gets SIGINT, then SIGKILL after INT_GRACE_S."""
    out: list[str] = []
    err: list[str] = []
    stop: threading.Event = threading.Event()
    readers: list[threading.Thread] = [
        threading.Thread(target=pump, args=(proc.stdout, out, on_line, stop), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, err, None, stop), daemon=True)]
    for reader in readers:
        reader.start()
    if stdin_text is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except OSError:
            pass  # the child closed its input early; its output tells why
    deadline: float = time.monotonic() + max(1.0, timeout_s)
    timed_out: bool = False
    while proc.poll() is None and not stop.is_set():
        if time.monotonic() >= deadline:
            timed_out = True
            break
        stop.wait(GROUP_POLL_S)
    stopped: bool = stop.is_set() and not timed_out
    if timed_out or stopped:
        interrupt_then_kill(proc)
    proc.wait()
    drain_readers(proc, readers, deadline)
    return {"code": EXIT_TERMINATED if timed_out else proc.returncode, "stdout": "".join(out), "stderr": "".join(err),
            "timed_out": timed_out, "stopped": stopped}


def run_once(argv: list[str], cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
             stdin_text: str | None = None, on_start: Callable[[int], None] | None = None,
             on_line: Callable[[str], bool] | None = None) -> Result:
    """Run one command to completion or to the wall-clock limit. A timeout reports exit 143 and `timed_out`.
    `stdin_text` is piped to the child (a prompt); without it stdin is closed. `on_start` gets the child's pid. With
    `on_line` the output is read as it arrives (a stream-json son) and a True answer stops the child (G-52, G-56)."""
    try:
        proc: subprocess.Popen[str] = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=env, start_new_session=True)  # setsid: the child leads its own group
    except OSError as exc:
        return {"code": EXIT_NOT_FOUND, "stdout": "", "stderr": str(exc), "timed_out": False}
    if on_start is not None:
        on_start(proc.pid)
    if on_line is not None:
        return run_streaming(proc, timeout_s, stdin_text, on_line)
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


# --- G-52: the son's process lifecycle -------------------------------------------------------------------------------

def read_record(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_record(path: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Merge `changes` into the JSON object at `path` (atomic replace) and return the result."""
    record: dict[str, Any] = {**read_record(path), **changes}
    atomic_write(path, json.dumps(record, indent=2) + "\n")
    return record


def option_index(cmd: list[str], flag: str) -> int | None:
    return cmd.index(flag) if flag in cmd else None


def set_option(cmd: list[str], flag: str, value: str) -> list[str]:
    """`cmd` with `flag value` set: the value replaced when the flag is there, appended when it is not."""
    index: int | None = option_index(cmd, flag)
    if index is None or index + 1 >= len(cmd):
        return [*cmd, flag, value]
    return [*cmd[:index + 1], value, *cmd[index + 2:]]


def wrap_son(cmd: list[str], lane_dir: Path, session_id: str | None = None) -> list[str]:
    """The son's command as the supervisor must run it: a pre-assigned `--session-id` (a fresh uuid4 when none is given and
    the command is not a `--resume`, which keeps its session), `--output-format stream-json --verbose` so the head can
    read heartbeats and loops from the events, and a `son.json` in the lane folder holding the argv, the session id and
    (once the process starts, see `record_son_start`) its pid and process group. The planner can call this on the
    `son-command` argv."""
    resuming: bool = FLAG_RESUME in cmd
    session: str | None = None if resuming else (session_id or str(uuid.uuid4()))
    wrapped: list[str] = set_option(cmd, FLAG_FORMAT, FORMAT_STREAM)
    if "--verbose" not in wrapped:
        wrapped.append("--verbose")
    if session is not None:
        wrapped = set_option(wrapped, FLAG_SESSION, session)
    write_record(lane_dir / SON_FILE, {"argv": wrapped, "session_id": session or cmd[cmd.index(FLAG_RESUME) + 1],
                                       "pid": None, "pgid": None, "wrapped_at": int(time.time())})
    return wrapped


def son_session(lane_dir: Path) -> str | None:
    value: Any = read_record(lane_dir / SON_FILE).get("session_id")
    return value if isinstance(value, str) and value else None


def record_son_start(lane_dir: Path, pid: int) -> None:
    """Note the son's pid and process group (the son is its own session leader, so they are the same) in son.json."""
    try:
        pgid: int = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        pgid = pid
    write_record(lane_dir / SON_FILE, {"pid": pid, "pgid": pgid, "started_at": int(time.time())})


def reap_old_group(lane_dir: Path, grace_s: float | None = None, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Before a lane is dispatched again, stop whatever is left of the previous son's process group: SIGINT, then SIGKILL
    after the grace. True when a group was found and stopped. Never signals this process's own group."""
    pgid: Any = read_record(lane_dir / SON_FILE).get("pgid")
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 1 or pgid == os.getpgid(0) or not group_alive(pgid):
        return False
    signal_group(pgid, signal.SIGINT)
    deadline: float = time.monotonic() + (INT_GRACE_S if grace_s is None else grace_s)
    while group_alive(pgid) and time.monotonic() < deadline:
        sleep(GROUP_POLL_S)
    if group_alive(pgid):
        signal_group(pgid, signal.SIGKILL)
        settle: float = time.monotonic() + KILL_SETTLE_S  # SIGKILL is asynchronous; wait so callers see the group gone
        while group_alive(pgid) and time.monotonic() < settle:
            sleep(GROUP_POLL_S)
    write_record(lane_dir / SON_FILE, {"pid": None, "pgid": None, "reaped_at": int(time.time())})
    return True


def signal_name(code: int) -> str | None:
    """`SIGINT` for a process killed by signal 2 (a negative exit code), else None."""
    if code >= 0:
        return None
    try:
        return signal.Signals(-code).name
    except ValueError:
        return f"signal-{-code}"


def write_exit(lane_dir: Path, call: dict[str, Any], parsed: dict[str, Any] | None, reason: str | None) -> dict[str, Any]:
    """`exit.json` in the lane folder: how the son's process ended (code, signal, cost, session id, why the lane is
    incomplete). `lanes.py reconcile` maps it to a phase without asking the model."""
    son: dict[str, Any] = read_record(lane_dir / SON_FILE)
    record: dict[str, Any] = {"code": call["code"], "signal": signal_name(int(call["code"])), "reason": reason,
                              "timed_out": bool(call.get("timed_out")), "stuck": call.get("stuck"),
                              "cost_usd": (parsed or {}).get("cost_usd"),
                              "session_id": (parsed or {}).get("session_id") or son.get("session_id"),
                              "pid": son.get("pid"), "pgid": son.get("pgid"), "ended_at": int(time.time())}
    atomic_write(lane_dir / EXIT_FILE, json.dumps(record, indent=2) + "\n")
    return record


def clear_exit(lane_dir: Path) -> None:
    try:
        (lane_dir / EXIT_FILE).unlink()
    except FileNotFoundError:
        pass  # nothing to clear: the lane has no exit record yet
