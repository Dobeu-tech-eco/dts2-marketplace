"""Supervisor: preflight, spawn, the son lifecycle, model calls behind the shared limit and the loop cap."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

import harness_skew
from model_call import (
    fallback_used, invoke, is_terminated, parse_result, read_budget,
)
from proc import RESUME_ENV, cli_version, clear_exit, reap_old_group, record_son_start, set_option, son_session, version_problem, wrap_son, write_exit
from son_stream import SonWatcher
from son_launch import auth_problem, cli_too_old, init_plugin_errors, launch_flags, prepare_lane, provider_env, sandbox_config, son_env
from state_io import atomic_write

from .common import BUDGET_NAME, COST_CLAUDE, COST_NONE, DEFAULT_PERMISSION_MODE, LaneError, PERMISSION_FIELD, PHASE_INCOMPLETE, PHASE_PR_OPEN, PHASE_STARTING, PID_KEYS, PLUGIN_ROOT, PREFLIGHT_TIMEOUT_S, REASON_BUDGET, REASON_ERROR, REASON_LOOPS, REASON_MAX_TURNS, REASON_NO_STATUS, REASON_OVERLOAD, REASON_PREFLIGHT, REASON_RUNNING, REASON_SANDBOX, REASON_SHUTDOWN, REASON_SKEW, REASON_SLOT, REASON_STALLED, REASON_TIMEOUT, RUN_NAME, SECONDS_PER_MINUTE, SETTLED_PHASES, SON_MODEL, STATUS_NAME, SUBTYPE_MAX_BUDGET, SUBTYPE_MAX_TURNS, TERMINAL_PHASES, TIMEOUT_S, binary, find_lane, run, son_model
from .leases import gc_leases, read_lease
from .merge import inside_son, son_refusal
from .phases import transition
from .planner import read_setting, son_command
from .records import append_ledger, lane_lock, ledger_emitter, merge_json, read_json_object
from .runrecord import read_run, update_run
from .runstate import attempt_usages, budget_refusal, lane_alive, pid_alive, read_status_files, record_attempts, record_unreported, release_share, reserve_share, spend_state, start_clock


PROBE_REF: Final[str] = "dts2-preflight-probe"


def claude_version(cwd: Path) -> str | None:
    code, out = run([*binary("DTS2_CLAUDE_BIN", "claude"), "--version"], cwd)
    return cli_version(out) if code == 0 else None


def push_access_problem(cwd: Path, env: dict[str, str]) -> str | None:
    """Why the son env cannot reach the remote (it has no GH_TOKEN or SSH_AUTH_SOCK unless the owner passes them), or None."""
    try:
        done = subprocess.run([*binary("DTS2_GIT_BIN", "git"), "ls-remote", "--exit-code", "origin", "HEAD"], cwd=str(cwd), env=env,
                              capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"`git ls-remote origin` could not run under the son env: {exc}"
    if done.returncode == 0:
        return None
    return ("`git ls-remote origin` fails under the son env, so a son cannot push or open PRs; pass the credential it needs "
            "(for example GH_TOKEN, or SSH_AUTH_SOCK for ssh remotes) with DTS2_SON_ENV_PASS")


def head_push_problem(cwd: Path) -> str | None:
    """Why the head (the one that publishes, ruling Q1) cannot push: `git push --dry-run` to origin under the head's own env."""
    try:
        done = subprocess.run([*binary("DTS2_GIT_BIN", "git"), "push", "--dry-run", "origin", f"HEAD:refs/heads/{PROBE_REF}"], cwd=str(cwd),
                              capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"`git push --dry-run origin` could not run under the head env: {exc}"
    if done.returncode == 0:
        return None
    return "`git push --dry-run origin` fails under the head env, so the head cannot publish a lane; fix the head's push access"


def preflight(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Pin `claude --version` in the run's run.json and prove the real son launch answers within 30 s: `claude -p ok` with
    the son's flags, settings and env, so auth, the sandbox (bwrap with failIfUnavailable) and the flags fail once here and
    not in every son. Also proves the son env can reach the remote. A second preflight that finds another version refuses.
    Fails closed: spawn refuses without a passing preflight."""
    pinned: Any = read_run(runs_dir, stamp).claude_version
    version: str | None = claude_version(cwd)
    emit = ledger_emitter(runs_dir, stamp, "-")
    probe: dict[str, Any] = {"stamp": stamp, "lanes": [{"id": "preflight"}]}
    mode: str = read_setting(cwd, PERMISSION_FIELD, DEFAULT_PERMISSION_MODE)
    env: dict[str, str] = son_env(probe, "preflight", cwd)
    argv: list[str] = [*binary("DTS2_CLAUDE_BIN", "claude"), "-p", "ok", *launch_flags(cwd, mode, probe, "preflight", cwd),
                       "--plugin-dir", str(PLUGIN_ROOT), "--output-format", "stream-json", "--verbose"]
    call: dict[str, Any] = invoke(argv, cwd, PREFLIGHT_TIMEOUT_S, "preflight", emit, env=env)
    parsed: dict[str, Any] | None = parse_result(call["stdout"])
    problems: list[str] = []
    version_issue: str | None = (cli_too_old(version) if version is not None else None) or version_problem(pinned, version)
    if version_issue is not None:
        problems.append(version_issue)
    if call["code"] != 0 or parsed is None or parsed["is_error"]:
        problems.append(f"`claude -p ok` with the son launch flags failed (exit {call['code']}); check auth, the sandbox "
                        "(bwrap) and the flags")
        login: str | None = auth_problem(cwd, env)  # a probe that answered proves the login; only a failed one asks why
        problems += [login] if login is not None else []
    plugin_errors: list[str] = init_plugin_errors(call["stdout"])
    if plugin_errors:
        problems.append(f"a plugin failed to load in the son launch ({'; '.join(plugin_errors)[:300]}), so the guard hooks may not run")
    problems += [p for p in (push_access_problem(cwd, env), head_push_problem(cwd)) if p is not None]
    ok: bool = not problems
    record: dict[str, Any] = {"claude_version": pinned if isinstance(pinned, str) else version, "preflight_ok": ok,
                              "checked": int(time.time()), "problems": problems}
    update_run(runs_dir, stamp, record)
    gc_leases(runs_dir, int(time.time()))  # the start of a run: close leases a crashed run left behind
    append_ledger(runs_dir, stamp, {"lane": "-", "event": "preflight", "ok": ok, "version": version,
                                    "problems": problems})
    return {"ok": ok, "stamp": stamp, "claude_version": record["claude_version"], "problems": problems}


SON_ROOT_ENV: Final[str] = "DTS2_SON_PLUGIN_ROOT"  # the plugin dir a son loads, when it is not the head's own (G-76)


def spawn_refusal(runs_dir: Path, stamp: str, cwd: Path, lane_id: str, son_root: Path | None = None) -> tuple[str, str] | None:
    """(reason, detail) when a son must not start: no passing preflight, a son harness of another version than the head's,
    a different CLI version, or a spent cap."""
    pinned = read_run(runs_dir, stamp)
    if pinned.preflight_ok is not True or pinned.claude_version is None:
        return REASON_PREFLIGHT, "run `lanes.py preflight` first; no passing preflight is recorded for this run"
    given: str = os.environ.get(SON_ROOT_ENV, "")
    skew: str | None = harness_skew.skew_problem(PLUGIN_ROOT, son_root or (Path(given) if given else PLUGIN_ROOT))
    if skew is not None:
        return REASON_SKEW, skew
    current: str | None = claude_version(cwd)
    if cli_too_old(current) is not None:
        return REASON_SKEW, str(cli_too_old(current))
    if current != pinned.claude_version:
        return REASON_SKEW, f"claude is {current}, the run is pinned to {pinned.claude_version}"
    why: str | None = budget_refusal(spend_state(runs_dir, stamp, cwd), lane_id, int(time.time()))
    return (REASON_BUDGET, why) if why else None


def park(runs_dir: Path, stamp: str, lane_id: str, reason: str, detail: str, session: str | None = None) -> None:
    """End a lane as incomplete with the reason on record. A lane that already finished (done or blocked) is left alone."""
    path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    held: dict[str, Any] = read_json_object(path)
    if held.get("status") in SETTLED_PHASES or held.get("reason") == REASON_SHUTDOWN:
        return  # finished lanes stay as they are, and a shutdown's reason is not overwritten by the kill it caused
    changes: dict[str, Any] = {"detail": detail, "parked_at": int(time.time())}
    sessions: dict[str, Any] = (((read_json_object(runs_dir / stamp / BUDGET_NAME).get("lanes") or {})
                                 .get(lane_id) or {}).get("sessions") or {})
    if session and session in sessions:
        changes["cost_at_park"] = sessions[session]
    transition(runs_dir, stamp, lane_id, PHASE_INCOMPLETE, reason=reason, extra=changes)
    append_ledger(runs_dir, stamp, {"lane": lane_id, "event": "park", "reason": reason, "detail": detail})


BUDGET_TEXT: Final[re.Pattern[str]] = re.compile(r"budget limit reached|exceeded .{0,20}budget|max[- ]budget", re.I)
TURNS_TEXT: Final[re.Pattern[str]] = re.compile(r"reached max(?:imum)? turns|max[- ]turns", re.I)


def exit_reason(call: dict[str, Any], parsed: dict[str, Any] | None) -> str | None:
    """Why a finished son call ends the lane incomplete (None when it ended cleanly). Exit 143 is the wall-clock kill. A
    son stopped for going round in circles is `stalled`; a max-turns or "Budget limit reached" result is `incomplete`
    (G-56) whatever the exit code."""
    if call.get("stuck"):
        return REASON_STALLED
    if call["code"] == 75:
        return REASON_SLOT
    if call.get("halted_overload"):
        return REASON_OVERLOAD
    if call["timed_out"] or is_terminated(call["code"]):
        return REASON_TIMEOUT
    subtype: str | None = (parsed or {}).get("subtype")
    if subtype == SUBTYPE_MAX_TURNS:
        return REASON_MAX_TURNS
    if subtype == SUBTYPE_MAX_BUDGET:
        return REASON_BUDGET
    text: str = str((parsed or {}).get("result_text") or "")
    if (parsed or {}).get("is_error") and BUDGET_TEXT.search(text):
        return REASON_BUDGET
    if (parsed or {}).get("is_error") and TURNS_TEXT.search(text):
        return REASON_MAX_TURNS
    if call["code"] != 0 or (parsed or {}).get("is_error"):
        return REASON_ERROR
    return None


def claim_lane(status_path: Path) -> int | None:
    """Under the status lock: the pid of a running spawn or son on this lane, else record this process as the spawner
    and return None. One lane never has two sons."""
    with lane_lock(status_path) as held:
        if not held:
            raise LaneError(f"lock busy for {status_path}")
        current: dict[str, Any] = read_lease(status_path) or {}
        for key in PID_KEYS:
            if pid_alive(current.get(key)) and current.get(key) != os.getpid():
                return int(current[key])
        atomic_write(status_path, json.dumps({**current, "spawn_pid": os.getpid()}, indent=2) + "\n")
    return None


def spawn(manifest: dict[str, Any], lane_id: str, worktree: Path, runs_dir: Path, cwd: Path, resume: bool,
          unsafe: bool = False) -> dict[str, Any]:
    """Start (or with resume, continue) one son under every cap, wait for it, then record session id, spend, fallback and
    exit reason. The only place a son process is started. A lane whose son or spawn is still running is refused
    (`running`) and left untouched."""
    stamp: str = str(manifest["stamp"])
    find_lane(manifest, lane_id)
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    holder: int | None = claim_lane(status_path)
    if holder is not None:
        return {"ok": False, "lane": lane_id, "reason": REASON_RUNNING, "detail": f"process {holder} is still running this lane"}
    try:
        return start_son(manifest, lane_id, worktree, runs_dir, cwd, resume, unsafe)
    finally:
        merge_json(status_path, dict.fromkeys(PID_KEYS))


def sandbox_refusal(runs_dir: Path, stamp: str, cwd: Path, lane_id: str, unsafe: bool) -> tuple[str, str] | None:
    """More than one unattended son needs the sandbox on, or an explicit --unsafe-no-sandbox (which is logged)."""
    if sandbox_config(cwd)["enabled"]:
        return None
    others: list[str] = [str(d.get("lane")) for _p, d in read_status_files(runs_dir, stamp)
                         if d.get("lane") != lane_id and lane_alive(d)]
    if not others:
        return None
    if unsafe:
        append_ledger(runs_dir, stamp, {"lane": lane_id, "event": "unsafe-no-sandbox",
                                        "warning": f"son started without the sandbox beside {', '.join(others)}"})
        print(f"warning: lane {lane_id} starts without the sandbox beside running lanes ({', '.join(others)})",
              file=sys.stderr)
        return None
    return REASON_SANDBOX, "a second unattended son needs sandbox.enabled in .harness/config.yaml or --unsafe-no-sandbox"


def gc_pause(runs_dir: Path, stamp: str, cwd: Path) -> None:
    """`git config gc.auto 0` for the run; the previous local value is kept in run.json for gc_restore."""
    if "gc_auto_prior" in read_json_object(runs_dir / stamp / RUN_NAME):
        return
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "config", "--local", "--get", "gc.auto"], cwd)
    update_run(runs_dir, stamp, {"gc_auto_prior": out.strip() if code == 0 else None, "gc_auto_paused": True})
    run([*binary("DTS2_GIT_BIN", "git"), "config", "--local", "gc.auto", "0"], cwd)


def gc_restore(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Put gc.auto back to what it was before gc_pause (unset when it was unset). Safe to call twice. A son is refused."""
    if inside_son():
        return son_refusal("gc-restore")
    data = read_run(runs_dir, stamp)
    if not data.gc_auto_paused:
        return {"ok": True, "stamp": stamp, "restored": False}
    prior: Any = data.gc_auto_prior
    git: list[str] = binary("DTS2_GIT_BIN", "git")
    run([*git, "config", "--local", "gc.auto", str(prior)] if isinstance(prior, str) else
        [*git, "config", "--local", "--unset", "gc.auto"], cwd)
    update_run(runs_dir, stamp, {"gc_auto_paused": False})
    return {"ok": True, "stamp": stamp, "restored": True, "gc_auto": prior}


def start_son(manifest: dict[str, Any], lane_id: str, worktree: Path, runs_dir: Path, cwd: Path, resume: bool,
              unsafe: bool = False) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    refusal: tuple[str, str] | None = (spawn_refusal(runs_dir, stamp, cwd, lane_id)
                                       or sandbox_refusal(runs_dir, stamp, cwd, lane_id, unsafe))
    if refusal is not None:
        park(runs_dir, stamp, lane_id, refusal[0], refusal[1])
        return {"ok": False, "lane": lane_id, "reason": refusal[0], "detail": refusal[1]}
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    session: Any = read_json_object(status_path).get("session_id") if resume else None
    if resume and not (isinstance(session, str) and session):
        park(runs_dir, stamp, lane_id, REASON_ERROR, "no session_id in status.json to resume")
        return {"ok": False, "lane": lane_id, "reason": REASON_ERROR, "detail": "no session_id to resume"}
    start_clock(runs_dir, stamp)
    gc_pause(runs_dir, stamp, cwd)
    prepare_lane(cwd, stamp, lane_id)
    if resume:
        gc_leases(runs_dir, int(time.time()))  # a crashed run's expired lease must not block the resumed one
    share, no_share = reserve_share(runs_dir, stamp, cwd, manifest, lane_id)
    if no_share is not None:
        park(runs_dir, stamp, lane_id, REASON_BUDGET, no_share)
        return {"ok": False, "lane": lane_id, "reason": REASON_BUDGET, "detail": no_share}
    state: dict[str, Any] = spend_state(runs_dir, stamp, cwd)
    command: dict[str, Any] = son_command(manifest, lane_id, worktree, cwd, share, session)
    left_s: float = (state["caps"]["max_wall_minutes"] * SECONDS_PER_MINUTE
                     - (time.time() - float(state["budget"].get("started", time.time()))))
    merge_json(status_path, {"lane": lane_id, "worktree": str(worktree), "heartbeat": int(time.time())})
    if read_json_object(status_path).get("status") not in SETTLED_PHASES:
        transition(runs_dir, stamp, lane_id, PHASE_STARTING)
    emit = ledger_emitter(runs_dir, stamp, lane_id)
    lane_dir: Path = status_path.parent
    try:
        argv, env, watcher = prepare_son(command, lane_dir, status_path, cwd, resume, emit)
        call: dict[str, Any] = invoke(argv, worktree, max(left_s, 1.0), f"son:{lane_id}", emit, root=cwd,
                                      halt_on_session=True, env=env, on_line=watcher.feed,
                                      on_start=lambda pid: start_record(status_path, lane_dir, pid))
        if watcher.stuck:
            call = {**call, "stuck": watcher.stuck}
            emit({"event": "stuck", "detail": watcher.stuck})
        parsed: dict[str, Any] | None = parse_result(call["stdout"])
        return finish_son(runs_dir, stamp, lane_id, worktree, call, parsed, emit, cwd)
    finally:
        release_share(runs_dir, stamp, lane_id)


def start_record(status_path: Path, lane_dir: Path, pid: int) -> None:
    merge_json(status_path, {"son_pid": pid, "spawn_pid": os.getpid()})
    record_son_start(lane_dir, pid)


def prepare_son(command: dict[str, Any], lane_dir: Path, status_path: Path, cwd: Path, resume: bool,
                emit: Any) -> tuple[list[str], dict[str, str], SonWatcher]:
    """G-52 / G-56: stop what is left of the lane's previous son, forget its exit.json, then build the launch: the son's
    model from the `son_model` setting, a pre-assigned session id (saved at once, so a crash can still be resumed),
    stream-json output, and the env that lets the CLI finish an interrupted turn on resume."""
    if reap_old_group(lane_dir):
        emit({"event": "reaped", "detail": "stopped a process group left by the previous son"})
    clear_exit(lane_dir)
    argv: list[str] = wrap_son(set_option(command["argv"], "--model", son_model(cwd)), lane_dir)
    session: str | None = son_session(lane_dir)
    if not resume and isinstance(session, str):
        merge_json(status_path, {"session_id": session})
    beat = lambda: merge_json(status_path, {"heartbeat": int(time.time())})  # noqa: E731 - one short closure, used once
    return argv, {**command["env"], RESUME_ENV: "1"}, SonWatcher(beat)


def finish_son(runs_dir: Path, stamp: str, lane_id: str, worktree: Path, call: dict[str, Any], parsed: dict[str, Any] | None,
               emit: Any, cwd: Path | None = None) -> dict[str, Any]:
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    primary: str = son_model(cwd) if cwd is not None else SON_MODEL
    session: str | None = (parsed or {}).get("session_id")
    charged, all_known = record_attempts(runs_dir, stamp, lane_id, attempt_usages(call), release=lane_id)
    fallback: str | None = fallback_used(parsed, primary)
    changes: dict[str, Any] = {"lane": lane_id, "worktree": str(worktree), "heartbeat": int(time.time()),
                               **dict.fromkeys(PID_KEYS)}
    if session:
        changes["session_id"] = session
    if fallback:
        changes["fallback_model"] = fallback
        emit({"event": "fallback", "model": fallback, "primary": primary})
    merge_json(status_path, changes)
    reason: str | None = exit_reason(call, parsed)
    phase: str = str(read_json_object(status_path).get("status", ""))
    if reason is None and phase not in TERMINAL_PHASES | {PHASE_PR_OPEN}:
        reason = REASON_NO_STATUS
    detail: str = f"exit {call['code']}, {call['retries']} retries" + (f", stuck: {call['stuck']}" if call.get("stuck") else "")
    write_exit(status_path.parent, call, parsed, reason)
    if reason is not None:
        park(runs_dir, stamp, lane_id, reason, detail, session)
    emit({"event": "son-exit", "code": call["code"], "reason": reason, "cost_usd": (parsed or {}).get("cost_usd"),
          "charged_usd": charged, "cost_known": all_known, "retries": call["retries"]})
    return {"ok": reason is None, "lane": lane_id, "reason": reason, "exit": call["code"],
            "session_id": session, "cost_usd": (parsed or {}).get("cost_usd"), "charged_usd": charged,
            "cost_known": all_known, "fallback_model": fallback, "retries": call["retries"]}


def read_prompt(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LaneError(f"unreadable prompt file {path}: {exc}") from exc


def default_cost_source(argv: list[str]) -> str:
    """`claude` when the command is the Claude CLI (a binary named claude, or DTS2_CLAUDE_BIN), else `none`."""
    claude: list[str] = binary("DTS2_CLAUDE_BIN", "claude")
    named: bool = bool(argv) and os.path.basename(argv[0]) == "claude"
    return COST_CLAUDE if named or (bool(argv) and argv[:len(claude)] == claude) else COST_NONE


def model_call(runs_dir: Path, stamp: str, cwd: Path, label: str, argv: list[str], timeout_s: int,
               out: Path | None, prompt_file: Path | None = None, cost_source: str | None = None) -> dict[str, Any]:
    """Any non-son model call (a panel voter, a council seat) behind the same slot limit, backoff and ledger. With
    cost-source `none` (a CLI that never prints a cost) the call is counted as unreported, not as unknown spend."""
    if not argv:
        raise LaneError("call needs a command after --")
    why: str | None = budget_refusal(spend_state(runs_dir, stamp, cwd), None, int(time.time()))
    if why:
        append_ledger(runs_dir, stamp, {"lane": label, "event": "refused", "reason": why})
        return {"ok": False, "label": label, "reason": REASON_BUDGET, "detail": why}
    prompt: str | None = read_prompt(prompt_file)
    source: str = cost_source or default_cost_source(argv)
    env: dict[str, str] = provider_env(dict(os.environ), claude=source == COST_CLAUDE)  # no GH_TOKEN, cloud keys or Anthropic key for a third-party CLI
    call: dict[str, Any] = invoke(argv, cwd, timeout_s, label, ledger_emitter(runs_dir, stamp, label), stdin_text=prompt, env=env)
    parsed: dict[str, Any] | None = parse_result(call["stdout"])
    if source == COST_NONE:
        record_unreported(runs_dir, stamp, f"call:{label}")
        charged, all_known = None, False
    else:
        charged, all_known = record_attempts(runs_dir, stamp, f"call:{label}", attempt_usages(call))
    if out is not None:
        atomic_write(out, call["stdout"])
    return {"ok": call["code"] == 0 and not (parsed or {}).get("is_error"), "label": label, "code": call["code"],
            "timed_out": call["timed_out"], "retries": call["retries"], "charged_usd": charged,
            "cost_known": all_known, "stdout": None if out is not None else call["stdout"],
            "out": str(out) if out is not None else None, "stderr": call["stderr"][-2000:]}


def loop(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Count one more fullauto round. Past max_fullauto_loops the run parks as incomplete with the ledger written."""
    start_clock(runs_dir, stamp)
    path: Path = runs_dir / stamp / BUDGET_NAME
    cap: int = read_budget(cwd)["max_fullauto_loops"]
    merged: dict[str, Any] = merge_json(path, {"loops": int(read_json_object(path).get("loops", 0)) + 1})
    count: int = int(merged["loops"])
    if count > cap:
        append_ledger(runs_dir, stamp, {"lane": "-", "event": "park", "reason": REASON_LOOPS,
                                        "detail": f"max_fullauto_loops {cap} reached"})
        return {"ok": False, "stamp": stamp, "loops": count, "max": cap, "stop": True, "status": PHASE_INCOMPLETE,
                "reason": REASON_LOOPS}
    return {"ok": True, "stamp": stamp, "loops": count, "max": cap, "stop": False}
