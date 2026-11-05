#!/usr/bin/env python3
"""One door for every headless model call (sons, panel voters, council seats): a global concurrency limit shared by all
processes, a wall-clock kill, retry with exponential backoff and jitter on 429 and overload errors, and strict parsing of
the `--output-format json` result.

This module never writes `.harness/` state. It reports events through a callback; `lanes.py` is the only writer and
records them in the run ledger. Model output is untrusted: only a few typed fields are read, each validated."""
from __future__ import annotations

import json
import math
import os
import random
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Final, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: the limit is skipped and the wall-clock cap still applies
    fcntl = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import state_io  # noqa: E402

CONFIG_FILE: Final[str] = state_io.CONFIG_REL
RESULT_STDERR_CHARS: Final[int] = 4000
SLOTS_DIR: Final[str] = state_io.MODEL_SLOTS_REL
BLOCK_BUDGET: Final[str] = "budget"
BLOCK_SUPERVISOR: Final[str] = "supervisor"
DEFAULT_BUDGET: Final[dict[str, int]] = {"max_turns": 80, "max_rounds": 4, "max_fullauto_loops": 3}
DEFAULT_WALL_MINUTES: Final[float] = 90.0
DEFAULT_SUPERVISOR: Final[dict[str, Any]] = {"max_model_calls": 4, "stall_minutes": 10, "retry_max": 4,
                                              "backoff_base_s": 2.0, "backoff_cap_s": 60.0, "fallback_models": "sonnet"}
EXIT_TERMINATED: Final[int] = 143
SIGNALS_TERMINATED: Final[frozenset[int]] = frozenset({143, 124, -signal.SIGTERM, -signal.SIGKILL})
POLL_S: Final[float] = 0.2
KILL_GRACE_S: Final[int] = 5
OVERLOAD: Final[re.Pattern[str]] = re.compile(r"\b429\b|\b529\b|rate[ _-]?limit|overloaded", re.I)
SESSION_ID: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MODEL_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:/\[\]-]{1,100}$")
MAX_COST_USD: Final[float] = 1_000_000.0
VERSION: Final[re.Pattern[str]] = re.compile(r"(\d+\.\d+\.\d+)")
Event = Callable[[dict[str, Any]], None]


def read_block(cwd: Path, block: str) -> dict[str, str]:
    """`key: value` lines under a top-level `block:` of .harness/config.yaml (parsed by miniyaml). Nested values are skipped."""
    try:
        text: str = (cwd / CONFIG_FILE).read_text(encoding="utf-8")
    except OSError:
        return {}
    section: Any = miniyaml.parse(text).get(block)
    if not isinstance(section, dict):
        return {}
    return {key: value for key, value in section.items() if isinstance(value, str) and re.fullmatch(r"[a-z_]+", key)}


def as_int(raw: str | None, default: int) -> int:
    return int(raw) if raw is not None and raw.isdigit() and int(raw) > 0 else default


def as_float(raw: str | None, default: float) -> float:
    try:
        value: float = float(raw) if raw is not None else default
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= 0 else default


def read_budget(cwd: Path) -> dict[str, Any]:
    """The `budget:` caps; `max_usd` is None unless set to a positive number."""
    raw: dict[str, str] = read_block(cwd, BLOCK_BUDGET)
    caps: dict[str, Any] = {key: as_int(raw.get(key), default) for key, default in DEFAULT_BUDGET.items()}
    wall: float = as_float(raw.get("max_wall_minutes"), DEFAULT_WALL_MINUTES)
    caps["max_wall_minutes"] = wall if wall > 0 else DEFAULT_WALL_MINUTES
    usd: float = as_float(raw.get("max_usd"), 0.0)
    caps["max_usd"] = usd if usd > 0 else None
    return caps


def read_supervisor(cwd: Path) -> dict[str, Any]:
    """Concurrency, retry, stall and fallback settings from the `supervisor:` block, with defaults."""
    raw: dict[str, str] = read_block(cwd, BLOCK_SUPERVISOR)
    base: float = as_float(raw.get("backoff_base_s"), DEFAULT_SUPERVISOR["backoff_base_s"])
    chain: list[str] = [m.strip() for m in raw.get("fallback_models", DEFAULT_SUPERVISOR["fallback_models"]).split(",")]
    return {
        "max_model_calls": as_int(raw.get("max_model_calls"), DEFAULT_SUPERVISOR["max_model_calls"]),
        "stall_minutes": as_int(raw.get("stall_minutes"), DEFAULT_SUPERVISOR["stall_minutes"]),
        "retry_max": as_int(raw.get("retry_max"), DEFAULT_SUPERVISOR["retry_max"]),
        "backoff_base_s": base,
        "backoff_cap_s": as_float(raw.get("backoff_cap_s"), DEFAULT_SUPERVISOR["backoff_cap_s"]),
        "fallback_models": [m for m in chain if MODEL_NAME.match(m)],
    }


def slot_lock(path: Path) -> Any:
    """Open a slot file and try a non-blocking exclusive lock; the handle on success, None when the slot is taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 - the open handle IS the held lock; the caller closes it
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def acquire_slot(cwd: Path, limit: int, wait_s: float, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> Any | None:
    """Take one of `limit` machine-wide slots (flock, so a crashed holder frees its slot). None when none frees in time.
    Without fcntl the limit cannot be enforced and a placeholder is returned."""
    if fcntl is None:
        return object()
    deadline: float = clock() + wait_s
    while True:
        for index in range(limit):
            handle = slot_lock(cwd / SLOTS_DIR / f"slot-{index}.lock")
            if handle is not None:
                return handle
        if clock() >= deadline:
            return None
        sleep(POLL_S)


def release_slot(handle: Any) -> None:
    if hasattr(handle, "close"):
        handle.close()


def is_overload(code: int, stdout: str, stderr: str) -> bool:
    """A failed call whose output names a 429, an overload or a rate limit. A clean exit is never retried."""
    if code == 0 and not (parse_result(stdout) or {}).get("is_error"):
        return False
    return OVERLOAD.search(f"{stdout}\n{stderr}") is not None


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """base * 2^attempt, capped, plus up to `base` of jitter."""
    jitter: float = (rng or random).uniform(0, base)
    return min(cap, base * (2 ** attempt)) + jitter


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


def run_once(argv: list[str], cwd: Path, timeout_s: float, env: dict[str, str] | None,
             stdin_text: str | None = None, on_start: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Run one command to completion or to the wall-clock limit. A timeout reports exit 143 and `timed_out`.
    `stdin_text` is piped to the child (a prompt); without it stdin is closed. `on_start` gets the child's pid."""
    try:
        proc: subprocess.Popen[str] = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=env, start_new_session=True)
    except OSError as exc:
        return {"code": 127, "stdout": "", "stderr": str(exc), "timed_out": False}
    if on_start is not None:
        on_start(proc.pid)
    try:
        out, err = proc.communicate(input=stdin_text, timeout=max(1.0, timeout_s))
    except subprocess.TimeoutExpired:
        out, err = terminate(proc)
        return {"code": EXIT_TERMINATED, "stdout": out, "stderr": err, "timed_out": True}
    return {"code": proc.returncode, "stdout": out or "", "stderr": err or "", "timed_out": False}


def timeout_result(code: int, detail: str) -> dict[str, Any]:
    return {"code": code, "stdout": "", "stderr": detail, "timed_out": True, "attempts": 0, "retries": 0,
            "results": [], "halted_overload": False}


def invoke(argv: list[str], cwd: Path, timeout_s: float, label: str, on_event: Event | None = None,
           env: dict[str, str] | None = None, sleep: Callable[[float], None] = time.sleep,
           rng: random.Random | None = None, root: Path | None = None, stdin_text: str | None = None,
           halt_on_session: bool = False, clock: Callable[[], float] = time.monotonic,
           on_start: Callable[[int], None] | None = None) -> dict[str, Any]:
    """The only way harness scripts start a model: slot, run, retry overloads with backoff, report each retry.
    `cwd` is where the process runs (a lane worktree); `root` is the repo whose config and slot files apply.
    One deadline covers the wait for a slot and every attempt. The result lists every attempt's code and stdout under
    `results`. With `halt_on_session`, a failed attempt that reports a session id ends the retries (`halted_overload`):
    rerunning the whole command would start over, so the caller resumes that session instead. `on_start` is called with the
    pid of every process started (a retry starts a new one)."""
    base: Path = root or cwd
    settings: dict[str, Any] = read_supervisor(base)
    emit: Event = on_event or (lambda _event: None)
    deadline: float = clock() + timeout_s
    handle = acquire_slot(base, settings["max_model_calls"], timeout_s, sleep, clock)
    if handle is None:
        emit({"event": "slot-timeout", "label": label, "limit": settings["max_model_calls"]})
        return timeout_result(75, "no model-call slot freed in time")
    try:
        left: float = deadline - clock()
        if left <= 0:
            emit({"event": "slot-timeout", "label": label, "limit": settings["max_model_calls"], "late": True})
            return timeout_result(EXIT_TERMINATED, "wall-clock time ran out waiting for a model-call slot")
        return retry_loop(argv, cwd, left, label, settings, emit, env, sleep, rng, stdin_text, halt_on_session, clock,
                          on_start)
    finally:
        release_slot(handle)


def retry_loop(argv: list[str], cwd: Path, timeout_s: float, label: str, settings: dict[str, Any], emit: Event,
               env: dict[str, str] | None, sleep: Callable[[float], None], rng: random.Random | None,
               stdin_text: str | None = None, halt_on_session: bool = False,
               clock: Callable[[], float] = time.monotonic,
               on_start: Callable[[int], None] | None = None) -> dict[str, Any]:
    deadline: float = clock() + timeout_s
    attempt: int = 0
    results: list[dict[str, Any]] = []
    while True:
        result: dict[str, Any] = run_once(argv, cwd, deadline - clock(), env, stdin_text,
                                       **({"on_start": on_start} if on_start else {}))
        results.append({"code": result["code"], "stdout": result["stdout"],
                        "stderr": result["stderr"][-RESULT_STDERR_CHARS:]})
        retriable: bool = not result["timed_out"] and is_overload(result["code"], result["stdout"], result["stderr"])
        done: dict[str, Any] = {**result, "attempts": attempt + 1, "retries": attempt, "results": results,
                                "halted_overload": False}
        if not retriable or attempt >= settings["retry_max"]:
            return done
        if halt_on_session and (parse_result(result["stdout"]) or {}).get("session_id"):
            emit({"event": "retry-halted", "label": label, "attempt": attempt + 1, "reason": "session-open"})
            return {**done, "halted_overload": True}
        delay: float = backoff_delay(attempt, settings["backoff_base_s"], settings["backoff_cap_s"], rng)
        if clock() + delay >= deadline:
            return done
        emit({"event": "retry", "label": label, "attempt": attempt + 1, "delay_s": round(delay, 3),
              "code": result["code"], "reason": "429-or-overload"})
        sleep(delay)
        attempt += 1


def result_objects(stdout: str) -> Iterator[dict[str, Any]]:
    """Every JSON object in `--output-format json` output: one object, a list of them, or one per line."""
    candidates: list[str] = [stdout, *stdout.splitlines()]
    for text in candidates:
        try:
            data: Any = json.loads(text)
        except ValueError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict):
                yield item


def parse_result(stdout: str) -> dict[str, Any] | None:
    """The final result object, or None. Reads only: session_id, cost, turns, is_error, subtype, and model names; every
    field is type-checked and an invalid one is dropped, so a cost of 0, -1, NaN or "5" counts as unknown."""
    final: dict[str, Any] | None = None
    for item in result_objects(stdout):
        if item.get("type") in (None, "result"):
            final = item
    if final is None:
        return None
    session: Any = final.get("session_id")
    cost: Any = final.get("total_cost_usd", final.get("cost_usd"))
    valid_cost: bool = (isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost)
                        and 0 < cost <= MAX_COST_USD)
    turns: Any = final.get("num_turns")
    usage: Any = final.get("modelUsage")
    return {
        "session_id": session if isinstance(session, str) and SESSION_ID.match(session) else None,
        "cost_usd": float(cost) if valid_cost else None,
        "num_turns": turns if isinstance(turns, int) and not isinstance(turns, bool) and turns >= 0 else None,
        "is_error": final.get("is_error") is True,
        "subtype": final.get("subtype") if isinstance(final.get("subtype"), str) else None,
        "models": sorted(m for m in usage if isinstance(m, str) and MODEL_NAME.match(m)) if isinstance(usage, dict)
        else [],
        "fallback": fallback_name(final.get("fallback_model")),
    }


def fallback_name(value: Any) -> str | None:
    return value if isinstance(value, str) and MODEL_NAME.match(value) else None


def fallback_used(parsed: dict[str, Any] | None, primary: str) -> str | None:
    """The fallback model name when the result says one answered: an explicit field, or usage under a model that is not
    the primary alias (the primary is an alias such as `opus`, so match by containment)."""
    if not parsed:
        return None
    if parsed["fallback"]:
        return str(parsed["fallback"])
    others: list[str] = [m for m in parsed["models"] if primary.lower() not in m.lower()]
    return others[0] if others and parsed["models"] and len(others) == len(parsed["models"]) else None


def cli_version(text: str) -> str | None:
    """x.y.z from `claude --version` output, or None when it cannot be read."""
    match = VERSION.search(text)
    return match.group(1) if match else None


def is_terminated(code: int) -> bool:
    """Exit 143 (SIGTERM) and its neighbours: the wall-clock cap or an outside kill. The lane ends incomplete."""
    return code in SIGNALS_TERMINATED
