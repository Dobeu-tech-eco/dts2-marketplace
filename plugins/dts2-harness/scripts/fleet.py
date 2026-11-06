#!/usr/bin/env python3
"""Fleet view: every dts2 session on this machine, read-only views of them, and one-to-many broadcasts.

Hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd) keep one small registry file per session under
the shared fleet home (DTS2_FLEET_HOME, else $DTS2_HOME/fleet, else ~/.dts2/fleet). A broadcast is one line in
broadcasts.jsonl; each session picks it up at most once (receipt per session) at its next hook. Nothing here talks to a
running session, starts a daemon, or uses the network.

Layout under the fleet home: sessions/<id>.json, broadcasts.jsonl, delivered/<id>.json, checkins/<id>.jsonl.
CLI: python3 fleet.py hook|list|show|logs|broadcast|status|label|prune|checkin|checkins (see build_parser)."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

ENV_FLEET_HOME: Final[str] = "DTS2_FLEET_HOME"
ENV_HOME: Final[str] = "DTS2_HOME"
ENV_SESSION: Final[str] = "CLAUDE_SESSION_ID"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
FLEET_DIR: Final[str] = "fleet"
SESSIONS_DIR: Final[str] = "sessions"
DELIVERED_DIR: Final[str] = "delivered"
CHECKINS_DIR: Final[str] = "checkins"
BROADCASTS_FILE: Final[str] = "broadcasts.jsonl"
ENCODING: Final[str] = "utf-8"
ISO_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
SESSION_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DURATION_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)([smhd])$")
SECONDS_PER_UNIT: Final[dict[str, int]] = {"s": 1, "m": 60, "h": 3600, "d": 86400}

EVENTS: Final[tuple[str, ...]] = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd")
WORKING: Final[str] = "working"
IDLE: Final[str] = "idle"
ENDED: Final[str] = "ended"
STALE: Final[str] = "stale"
DEAD: Final[str] = "dead"
HEARTBEAT_SECONDS: Final[int] = 60
STALE_AFTER: Final[timedelta] = timedelta(minutes=30)
PRUNE_DAYS: Final[int] = 14
DEFAULT_EXPIRES: Final[str] = "24h"
GIT_TIMEOUT_SECONDS: Final[int] = 2
SUBPROCESS_TIMEOUT_SECONDS: Final[int] = 10
SOURCE_DEFAULT: Final[str] = "operator"

KIND_NOTE: Final[str] = "note"
KIND_HANDOFF: Final[str] = "handoff"
KIND_PAUSE: Final[str] = "pause"
KIND_KNOWLEDGE: Final[str] = "knowledge"
KIND_CHECKIN: Final[str] = "checkin"
KINDS: Final[tuple[str, ...]] = (KIND_NOTE, KIND_HANDOFF, KIND_PAUSE, KIND_KNOWLEDGE, KIND_CHECKIN)
BLOCKING_KINDS: Final[frozenset[str]] = frozenset({KIND_HANDOFF, KIND_PAUSE})
STEER_KINDS: Final[frozenset[str]] = BLOCKING_KINDS
TARGET_ALL: Final[str] = "all"
TARGET_HARNESS: Final[str] = "harness"
TARGET_PREFIXES: Final[tuple[str, ...]] = ("repo:", "id:", "label:")
KIND_INSTRUCTIONS: Final[dict[str, str]] = {
    KIND_HANDOFF: "Action: finish the current step, run the harness handoff (/dts2:handoff), stop starting new work "
                  "and say so in one line.",
    KIND_PAUSE: "Action: finish the current step, then stop and wait. Start no new work until the person replies.",
    KIND_KNOWLEDGE: "This is a finding to apply where it is relevant to your current work.",
}
CHECKIN_COMMAND: Final[str] = (
    'python3 -I "${{CLAUDE_PLUGIN_ROOT}}/scripts/fleet.py" checkin --session {sid} --broadcast {bid} '
    '--status "<one line>" [--blocker "..."]... [--next "..."] [--question "..."]...'
)

LOG_TAIL_BYTES: Final[int] = 2_000_000
LOG_TEXT_CHARS: Final[int] = 300
LOG_ARGS_CHARS: Final[int] = 80
LOG_DEFAULT_TURNS: Final[int] = 20
TAIL_LINES: Final[int] = 15
HANDOFF_LINES: Final[int] = 20
KNOWLEDGE_GLOBS: Final[tuple[str, ...]] = ("knowledge.py", "knowledge-*.py", "knowledge_*.py")
INCIDENTS_SCRIPT: Final[str] = "incidents.py"
EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 2


class FleetError(Exception):
    """A user-facing failure: printed to stderr, exit 2."""


# ---------------------------------------------------------------- time and paths

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        moment: datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def parse_duration(text: str) -> timedelta:
    match: re.Match[str] | None = DURATION_RE.match(text.strip().lower())
    if match is None:
        raise FleetError(f"bad duration {text!r}: use a number and s, m, h or d (for example 24h)")
    return timedelta(seconds=int(match.group(1)) * SECONDS_PER_UNIT[match.group(2)])


def age_text(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "?"
    seconds: int = max(0, int((now - moment).total_seconds()))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{round(seconds / 60)}m"
    if seconds < 129600:
        return f"{round(seconds / 3600)}h"
    return f"{round(seconds / 86400)}d"


def fleet_home() -> Path:
    explicit: str | None = os.environ.get(ENV_FLEET_HOME)
    if explicit:
        return Path(explicit)
    home: str | None = os.environ.get(ENV_HOME)
    base: Path = Path(home) if home else Path.home() / DEFAULT_HOME_DIR
    return base / FLEET_DIR


def valid_session_id(session_id: Any) -> bool:
    return isinstance(session_id, str) and SESSION_ID_RE.match(session_id) is not None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None


def write_json(path: Path, value: Any) -> None:
    state_io.atomic_write(path, json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def append_line(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line with a single O_APPEND write, so concurrent writers never interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: bytes = (json.dumps(record, ensure_ascii=False) + "\n").encode(ENCODING)
    descriptor: int = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        text: str = path.read_text(encoding=ENCODING)
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            parsed: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def session_path(session_id: str) -> Path:
    return fleet_home() / SESSIONS_DIR / f"{session_id}.json"


def receipt_path(session_id: str) -> Path:
    return fleet_home() / DELIVERED_DIR / f"{session_id}.json"


def broadcasts_path() -> Path:
    return fleet_home() / BROADCASTS_FILE


def checkins_path(session_id: str) -> Path:
    return fleet_home() / CHECKINS_DIR / f"{session_id}.jsonl"


def load_sessions() -> list[dict[str, Any]]:
    folder: Path = fleet_home() / SESSIONS_DIR
    sessions: list[dict[str, Any]] = []
    try:
        names: list[str] = sorted(os.listdir(folder))
    except OSError:
        return sessions
    for name in names:
        if not name.endswith(".json"):
            continue
        entry: Any = read_json(folder / name)
        if isinstance(entry, dict) and valid_session_id(entry.get("session_id")):
            sessions.append(entry)
    return sessions


def load_broadcasts() -> list[dict[str, Any]]:
    return [b for b in read_lines(broadcasts_path()) if isinstance(b.get("id"), str) and b.get("kind") in KINDS]


def load_receipt(session_id: str) -> list[str]:
    raw: Any = read_json(receipt_path(session_id))
    return [str(i) for i in raw] if isinstance(raw, list) else []


# ---------------------------------------------------------------- session state

def pid_alive(pid: Any) -> bool | None:
    """True or False on posix, None when it cannot be told (no pid, or Windows)."""
    if not isinstance(pid, int) or pid <= 0 or os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def effective_state(entry: dict[str, Any], now: datetime) -> str:
    """The stored state, except: ended stays ended, a vanished pid is dead, 30 minutes of silence is stale."""
    state: str = str(entry.get("state") or IDLE)
    if state == ENDED:
        return ENDED
    if pid_alive(entry.get("pid")) is False:
        return DEAD
    seen: datetime | None = parse_iso(entry.get("last_seen"))
    if seen is None or now - seen > STALE_AFTER:
        return STALE
    return state


def is_live(entry: dict[str, Any], now: datetime) -> bool:
    return effective_state(entry, now) not in (ENDED, DEAD)


def git_info(cwd: str) -> tuple[str | None, str | None]:
    """(repo name, branch) from git, best effort; (None, None) when git fails or times out."""
    try:
        done = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    lines: list[str] = done.stdout.splitlines()
    if not lines:
        return None, None
    repo: str | None = os.path.basename(lines[0].strip()) or None
    if done.returncode == 0 and len(lines) >= 2:
        return repo, lines[1].strip() or None
    try:  # a repository with no commits yet: HEAD does not resolve, but it still names a branch
        named = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True,
                               text=True, timeout=GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return repo, None
    return repo, named.stdout.strip() or None


def apply_event(event: str, payload: dict[str, Any], now: datetime, pid: int | None) -> tuple[dict[str, Any], bool]:
    """The registry entry after `event`, and whether it needs writing. Preserves label and started_at."""
    session_id: str = payload["session_id"]
    existing: Any = read_json(session_path(session_id))
    entry: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    fresh: bool = not entry
    cwd: str = str(payload.get("cwd") or entry.get("cwd") or os.getcwd())
    stamp: str = to_iso(now)
    if event == "PostToolUse" and not fresh:
        seen: datetime | None = parse_iso(entry.get("last_seen"))
        if entry.get("state") == WORKING and seen is not None and (now - seen).total_seconds() < HEARTBEAT_SECONDS:
            return entry, False
    entry.update(session_id=session_id, cwd=cwd, last_seen=stamp)
    if payload.get("transcript_path"):
        entry["transcript_path"] = str(payload["transcript_path"])
    entry.setdefault("started_at", stamp)
    entry.setdefault("turns", 0)
    entry.setdefault("label", None)
    entry.setdefault("last_prompt_at", None)
    if fresh or event in ("SessionStart", "UserPromptSubmit"):
        repo, branch = git_info(cwd) if event != "PostToolUse" else (None, None)
        entry["repo"] = repo or entry.get("repo") or os.path.basename(cwd.rstrip("/\\")) or cwd
        entry["branch"] = branch if repo else entry.get("branch")
    entry["harness"] = (Path(cwd) / state_io.HARNESS).is_dir()
    if pid:
        entry["pid"] = pid
    if event == "SessionStart":
        entry["state"] = IDLE
    elif event == "UserPromptSubmit":
        entry["state"] = WORKING
        entry["turns"] = int(entry.get("turns") or 0) + 1
        entry["last_prompt_at"] = stamp
    elif event == "PostToolUse":
        entry["state"] = WORKING
    elif event == "Stop":
        entry["state"] = IDLE
    elif event == "SessionEnd":
        entry["state"] = ENDED
    return entry, True


# ---------------------------------------------------------------- targeting and delivery

def target_matches(target: str, entry: dict[str, Any]) -> bool:
    if target == TARGET_ALL:
        return True
    if target == TARGET_HARNESS:
        return bool(entry.get("harness"))
    kind, _, value = target.partition(":")
    if not value:
        return False
    if kind == "repo":
        return entry.get("repo") == value
    if kind == "id":
        return str(entry.get("session_id", "")).startswith(value)
    if kind == "label":
        return entry.get("label") == value
    return False


def broadcast_matches(broadcast: dict[str, Any], entry: dict[str, Any]) -> bool:
    targets: Any = broadcast.get("targets")
    if not isinstance(targets, list) or not targets:
        targets = [TARGET_ALL]
    return any(isinstance(t, str) and target_matches(t, entry) for t in targets)


def is_expired(broadcast: dict[str, Any], now: datetime) -> bool:
    expires: datetime | None = parse_iso(broadcast.get("expires"))
    return expires is not None and expires <= now


def pending_for(entry: dict[str, Any], broadcasts: list[dict[str, Any]], delivered: list[str],
                now: datetime) -> list[dict[str, Any]]:
    return [b for b in broadcasts
            if b["id"] not in delivered and not is_expired(b, now) and broadcast_matches(b, entry)]


def render_broadcast(broadcast: dict[str, Any], session_id: str) -> str:
    source: str = str(broadcast.get("from") or SOURCE_DEFAULT)
    kind: str = str(broadcast["kind"])
    lines: list[str] = [f"[dts2 fleet broadcast {broadcast['id']} · {kind} · from {source}]",
                        str(broadcast.get("text") or "")]
    if kind == KIND_CHECKIN:
        lines.append("Action: report in now. Run: " + CHECKIN_COMMAND.format(sid=session_id, bid=broadcast["id"]))
        lines.append("Then carry on with your work.")
    elif kind in KIND_INSTRUCTIONS:
        lines.append(KIND_INSTRUCTIONS[kind])
    lines.append("[end broadcast]")
    return "\n".join(lines)


def log_steer(entry: dict[str, Any], broadcast: dict[str, Any]) -> None:
    """Record a handoff or pause broadcast in the session's own intake ledger so /dts2:steer shows it. Best effort."""
    cwd: Path = Path(str(entry.get("cwd") or ""))
    if not entry.get("harness") or not (cwd / state_io.HARNESS).is_dir():
        return
    try:
        import intake
        text: str = f"fleet {broadcast['kind']} {broadcast['id']}: {str(broadcast.get('text') or '')[:400]}"
        classified: tuple[str, str] = (intake.STEER, text)
        with intake.locked(cwd, tries=intake.HOOK_LOCK_TRIES):
            intake.append_in(cwd, intake.load_items(cwd), classified, "hook", intake.CLARITY_THRESHOLD,
                             intake.QUESTION_BUDGET)
    except Exception:  # noqa: BLE001 - the ledger is a courtesy copy; delivery must not depend on it
        return


def mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def deliver(event: str, entry: dict[str, Any], now: datetime) -> str | None:
    """The hook output for `event`, marking what it delivers. None when there is nothing to say."""
    if event == "SessionEnd":
        return None
    broadcasts_mtime: int | None = mtime_ns(broadcasts_path())
    if broadcasts_mtime is None:
        return None
    session_id: str = entry["session_id"]
    receipt_mtime: int | None = mtime_ns(receipt_path(session_id))
    if receipt_mtime is not None and receipt_mtime > broadcasts_mtime:
        return None
    delivered: list[str] = load_receipt(session_id)
    broadcasts: list[dict[str, Any]] = load_broadcasts()
    pending: list[dict[str, Any]] = pending_for(entry, broadcasts, delivered, now)
    if event == "Stop":
        # A Stop only ever acts on handoff and pause; it must not mark the file as looked at, or notes would be skipped.
        pending = [b for b in pending if b["kind"] in BLOCKING_KINDS]
    if pending or (event != "Stop" and (receipt_mtime is None or receipt_mtime <= broadcasts_mtime)):
        # Writing the receipt, even unchanged, records that this version of broadcasts.jsonl was looked at.
        known: set[str] = {b["id"] for b in broadcasts}
        kept: list[str] = [i for i in delivered if i in known]
        write_json(receipt_path(session_id), [*kept, *(b["id"] for b in pending)])
        if event == "Stop":
            # Keep the "looked at" time where it was, so notes still pending are seen at the next prompt or tool call.
            restore: int = receipt_mtime if receipt_mtime is not None else broadcasts_mtime
            os.utime(receipt_path(session_id), ns=(restore, restore))
    if not pending:
        return None
    for broadcast in pending:
        if broadcast["kind"] in STEER_KINDS:
            log_steer(entry, broadcast)
    text: str = "\n\n".join(render_broadcast(b, session_id) for b in pending)
    if event == "Stop":
        return json.dumps({"decision": "block", "reason": text}, ensure_ascii=False)
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=False)


def run_hook(event: str, payload: Any, pid: int | None = None, now: datetime | None = None) -> str | None:
    """Update the registry for `event` and return the hook output, if any. Raises on bad input (main swallows)."""
    if event not in EVENTS or not isinstance(payload, dict) or not valid_session_id(payload.get("session_id")):
        return None
    moment: datetime = now or utc_now()
    entry, changed = apply_event(event, payload, moment, pid)
    if changed:
        write_json(session_path(entry["session_id"]), entry)
    if event == "SessionStart":
        try:
            prune_sessions(PRUNE_DAYS, moment)
        except OSError:
            pass
    return deliver(event, entry, moment)


# ---------------------------------------------------------------- references

def resolve_ref(ref: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """One session by exact id, exact label, or unique id prefix. Ambiguous or unknown raises FleetError."""
    for entry in sessions:
        if entry["session_id"] == ref:
            return entry
    labelled: list[dict[str, Any]] = [e for e in sessions if e.get("label") == ref]
    candidates: list[dict[str, Any]] = labelled or [e for e in sessions if e["session_id"].startswith(ref)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FleetError(f"no session matches {ref!r} (try `fleet.py list --all`)")
    names: str = ", ".join(f"{e['session_id'][:8]}{' (' + e['label'] + ')' if e.get('label') else ''}"
                           for e in candidates)
    raise FleetError(f"{ref!r} is ambiguous: {names}")


# ---------------------------------------------------------------- list / show / logs

def cell(value: Any) -> str:
    return "-" if value in (None, "") else str(value)


def render_table(header: list[str], rows: list[list[str]]) -> str:
    widths: list[int] = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    return "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in [header, *rows])


def list_rows(include_ended: bool, now: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in load_sessions():
        state: str = effective_state(entry, now)
        if state == ENDED and not include_ended:
            continue
        seen: datetime | None = parse_iso(entry.get("last_seen"))
        rows.append({**entry, "effective_state": state, "age": age_text(seen, now)})
    rows.sort(key=lambda r: str(r.get("last_seen") or ""), reverse=True)
    return rows


def cmd_list(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = list_rows(args.all, utc_now())
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return EXIT_OK
    if not rows:
        print("no sessions registered" if args.all else "no live sessions (use --all to include ended)")
        return EXIT_OK
    table: list[list[str]] = [[r["session_id"][:8], cell(r.get("label")), r["effective_state"], cell(r.get("repo")),
                               cell(r.get("branch")), str(r.get("turns", 0)), r["age"]] for r in rows]
    print(render_table(["id", "label", "state", "repo", "branch", "turns", "last seen"], table))
    return EXIT_OK


def tail_text(path: Path, lines: int) -> list[str]:
    try:
        return path.read_text(encoding=ENCODING, errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def latest_run_dir(cwd: Path) -> Path | None:
    runs: Path = cwd / state_io.RUNS_REL
    try:
        names: list[str] = sorted(n for n in os.listdir(runs) if (runs / n).is_dir())
    except OSError:
        return None
    return runs / names[-1] if names else None


def lane_summaries(run_dir: Path | None) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    if run_dir is None:
        return lanes
    try:
        names: list[str] = sorted(os.listdir(run_dir))
    except OSError:
        return lanes
    for name in names:
        status: Any = read_json(run_dir / name / state_io.STATUS_NAME)
        if isinstance(status, dict):
            keep: dict[str, Any] = {k: status[k] for k in ("state", "phase", "status", "heartbeat") if k in status}
            lanes.append({"lane": name, **keep})
    return lanes


def run_script_json(script: str, argv: list[str], cwd: Path) -> Any:
    """JSON from a sibling script, or None when it is absent, slow, or fails."""
    path: Path = Path(__file__).resolve().parent / script
    if not path.is_file():
        return None
    try:
        done = subprocess.run([sys.executable, "-I", str(path), *argv], capture_output=True, text=True,
                              timeout=SUBPROCESS_TIMEOUT_SECONDS, cwd=str(cwd), check=False)
        return json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def open_intake_items(cwd: Path) -> list[dict[str, Any]]:
    try:
        import intake
        return [i for i in intake.load_items(cwd) if i.get("status") != intake.DONE]
    except Exception:  # noqa: BLE001 - a broken ledger reads as empty in a read-only view
        return []


def cooling_agents() -> list[str]:
    try:
        import cooldowns
        return list(cooldowns.cooling_names())
    except Exception:  # noqa: BLE001
        return []


def gather_ledgers(entry: dict[str, Any]) -> dict[str, Any]:
    cwd: Path = Path(str(entry.get("cwd") or "."))
    run_dir: Path | None = latest_run_dir(cwd)
    handoff: Path = cwd / state_io.HANDOFF_LATEST_REL
    ledger: Path | None = (run_dir / "task-ledger.md") if run_dir else None
    return {
        "handoff": tail_text(handoff, HANDOFF_LINES) if handoff.is_file() else None,
        "task_ledger_tail": tail_text(ledger, TAIL_LINES) if ledger and ledger.is_file() else None,
        "intake_open": [{k: i.get(k) for k in ("id", "kind", "status", "text")} for i in open_intake_items(cwd)],
        "lanes": lane_summaries(run_dir),
        "cooldowns": cooling_agents(),
        "incidents": run_script_json(INCIDENTS_SCRIPT, ["list", "--json"], cwd) if cwd.is_dir() else None,
    }


def cmd_show(args: argparse.Namespace) -> int:
    entry: dict[str, Any] = resolve_ref(args.ref, load_sessions())
    now: datetime = utc_now()
    ledgers: dict[str, Any] = gather_ledgers(entry)
    delivered: list[str] = load_receipt(entry["session_id"])
    pending: list[str] = [b["id"] for b in pending_for(entry, load_broadcasts(), delivered, now)]
    document: dict[str, Any] = {"session": {**entry, "effective_state": effective_state(entry, now)},
                                "pending_broadcasts": pending, **ledgers}
    if args.json:
        print(json.dumps(document, ensure_ascii=False))
        return EXIT_OK
    session: dict[str, Any] = document["session"]
    print(f"session {session['session_id']}  state {session['effective_state']}  label {cell(session.get('label'))}")
    print(f"repo {cell(session.get('repo'))}@{cell(session.get('branch'))}  cwd {session.get('cwd')}  "
          f"turns {session.get('turns', 0)}  last seen {age_text(parse_iso(session.get('last_seen')), now)} ago")
    print(f"pending broadcasts: {', '.join(pending) if pending else 'none'}")
    sections: list[tuple[str, Any]] = [("Handoff (latest)", ledgers["handoff"]),
                                       ("Task ledger (tail)", ledgers["task_ledger_tail"])]
    for title, lines in sections:
        print(f"\n== {title} ==")
        print("\n".join(lines) if lines else "(none)")
    print("\n== Open intake items ==")
    for item in ledgers["intake_open"] or []:
        print(f"{item['id']} [{item['kind']}/{item['status']}] {str(item['text'])[:160]}")
    if not ledgers["intake_open"]:
        print("(none)")
    print("\n== Lanes ==")
    for lane in ledgers["lanes"] or []:
        print(json.dumps(lane, ensure_ascii=False))
    if not ledgers["lanes"]:
        print("(none)")
    print(f"\n== Cooldowns ==\n{', '.join(ledgers['cooldowns']) if ledgers['cooldowns'] else '(none)'}")
    if ledgers["incidents"] is not None:
        print(f"\n== Incidents ==\n{json.dumps(ledgers['incidents'], ensure_ascii=False)[:1000]}")
    return EXIT_OK


def clip(text: str, limit: int) -> str:
    flat: str = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def block_lines(role: str, content: Any) -> list[str]:
    """Readable lines for one transcript message: text blocks and one-line tool calls; tool results are dropped."""
    if isinstance(content, str):
        return [f"[{role}] {clip(content, LOG_TEXT_CHARS)}"] if content.strip() else []
    lines: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and str(block.get("text") or "").strip():
            lines.append(f"[{role}] {clip(str(block['text']), LOG_TEXT_CHARS)}")
        elif block.get("type") == "tool_use":
            args: str = clip(json.dumps(block.get("input", {}), ensure_ascii=False), LOG_ARGS_CHARS)
            lines.append(f"  tool: {block.get('name', '?')}({args})")
    return lines


def read_transcript_tail(path: Path) -> list[dict[str, Any]]:
    try:
        with open(path, "rb") as handle:
            size: int = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            data: bytes = handle.read()
            truncated: bool = size > LOG_TAIL_BYTES
    except OSError:
        return []
    text_lines: list[str] = data.decode(ENCODING, errors="replace").splitlines()
    if truncated and text_lines:
        text_lines = text_lines[1:]
    rows: list[dict[str, Any]] = []
    for line in text_lines:
        try:
            parsed: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def transcript_turns(path: Path, count: int) -> list[list[str]]:
    """The last `count` user/assistant messages, each as its rendered lines."""
    turns: list[list[str]] = []
    for row in read_transcript_tail(path):
        message: Any = row.get("message")
        if row.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        lines: list[str] = block_lines(str(row["type"]), message.get("content"))
        if lines:
            turns.append(lines)
    return turns[-count:] if count > 0 else []


def cmd_logs(args: argparse.Namespace) -> int:
    entry: dict[str, Any] = resolve_ref(args.ref, load_sessions())
    transcript: str | None = entry.get("transcript_path")
    if not transcript or not Path(transcript).is_file():
        raise FleetError(f"no readable transcript for session {entry['session_id'][:8]}")
    for lines in transcript_turns(Path(transcript), args.n):
        print("\n".join(lines))
    return EXIT_OK


# ---------------------------------------------------------------- broadcast / status

def knowledge_script() -> Path | None:
    here: Path = Path(__file__).resolve().parent
    for pattern in KNOWLEDGE_GLOBS:
        for found in sorted(here.glob(pattern)):
            return found
    return None


def knowledge_text(key: str) -> str:
    script: Path | None = knowledge_script()
    if script is None:
        raise FleetError("--from-knowledge needs the knowledge store script (scripts/knowledge*.py), which is not installed here")
    try:
        done = subprocess.run([sys.executable, "-I", str(script), "get", key], capture_output=True, text=True,
                              timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise FleetError(f"knowledge get {key} failed: {error}") from error
    if done.returncode != 0 or not done.stdout.strip():
        raise FleetError(f"knowledge get {key} returned nothing (exit {done.returncode}): {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def validate_targets(targets: list[str]) -> list[str]:
    for target in targets:
        if target in (TARGET_ALL, TARGET_HARNESS):
            continue
        if not any(target.startswith(p) and len(target) > len(p) for p in TARGET_PREFIXES):
            raise FleetError(f"bad target {target!r}: use all, harness, repo:<name>, id:<prefix> or label:<name>")
    return targets


def new_broadcast_id(now: datetime) -> str:
    return f"bc-{now.strftime('%y%m%d%H%M%S')}-{secrets.token_hex(2)}"


def make_broadcast(kind: str, text: str, targets: list[str], expires: str | None, now: datetime,
                   source: str = SOURCE_DEFAULT) -> dict[str, Any]:
    if kind not in KINDS:
        raise FleetError(f"unknown kind {kind!r}: use one of {', '.join(KINDS)}")
    if not text.strip():
        raise FleetError("a broadcast needs text (--text or --from-knowledge)")
    expiry: datetime | None = None if expires in ("never", "none") else now + parse_duration(expires or DEFAULT_EXPIRES)
    return {"id": new_broadcast_id(now), "created": to_iso(now), "kind": kind, "text": text.strip(),
            "targets": validate_targets(targets or [TARGET_ALL]), "expires": to_iso(expiry) if expiry else None,
            "from": source}


def cmd_broadcast(args: argparse.Namespace) -> int:
    text: str = knowledge_text(args.from_knowledge) if args.from_knowledge else (args.text or " ".join(args.words))
    now: datetime = utc_now()
    record: dict[str, Any] = make_broadcast(args.kind, text, args.to or [TARGET_ALL], args.expires, now)
    append_line(broadcasts_path(), record)
    sessions: list[dict[str, Any]] = [s for s in load_sessions() if broadcast_matches(record, s)]
    live: list[dict[str, Any]] = [s for s in sessions if is_live(s, now)]
    stale: int = sum(1 for s in live if effective_state(s, now) == STALE)
    print(f"{record['id']}  kind={record['kind']}  targets={','.join(record['targets'])}  expires={record['expires']}")
    print(f"matches {len(live)} registered live session(s)" + (f" ({stale} stale)" if stale else ""))
    return EXIT_OK


def status_for(broadcast: dict[str, Any], sessions: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    delivered: list[str] = []
    pending: list[str] = []
    for entry in sessions:
        if not broadcast_matches(broadcast, entry):
            continue
        if broadcast["id"] in load_receipt(entry["session_id"]):
            delivered.append(entry["session_id"])
        elif is_live(entry, now):
            pending.append(entry["session_id"])
    return {"id": broadcast["id"], "kind": broadcast["kind"], "created": broadcast.get("created"),
            "expired": is_expired(broadcast, now), "delivered": delivered, "pending": pending}


def cmd_status(args: argparse.Namespace) -> int:
    now: datetime = utc_now()
    sessions: list[dict[str, Any]] = load_sessions()
    broadcasts: list[dict[str, Any]] = load_broadcasts()
    if args.broadcast_id:
        broadcasts = [b for b in broadcasts if b["id"].startswith(args.broadcast_id)]
        if not broadcasts:
            raise FleetError(f"no broadcast matches {args.broadcast_id!r}")
    results: list[dict[str, Any]] = [status_for(b, sessions, now) for b in broadcasts]
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
        return EXIT_OK
    if not results:
        print("no broadcasts")
        return EXIT_OK
    by_id: dict[str, dict[str, Any]] = {s["session_id"]: s for s in sessions}

    def name(session_id: str) -> str:
        entry: dict[str, Any] = by_id.get(session_id, {})
        return f"{session_id[:8]}{' (' + entry['label'] + ')' if entry.get('label') else ''} {cell(entry.get('repo'))}"

    for result in results:
        print(f"{result['id']}  {result['kind']}  delivered {len(result['delivered'])}  pending {len(result['pending'])}"
              + ("  [expired]" if result["expired"] else ""))
        if args.broadcast_id:
            for session_id in result["delivered"]:
                print(f"  delivered  {name(session_id)}")
            for session_id in result["pending"]:
                print(f"  pending    {name(session_id)}")
    return EXIT_OK


# ---------------------------------------------------------------- label / prune

def cmd_label(args: argparse.Namespace) -> int:
    entry: dict[str, Any] = resolve_ref(args.ref, load_sessions())
    entry["label"] = args.name
    write_json(session_path(entry["session_id"]), entry)
    print(f"{entry['session_id'][:8]} labelled {args.name!r}")
    return EXIT_OK


def prune_sessions(days: int, now: datetime) -> list[str]:
    """Remove ended registry entries (with receipts and check-ins) not seen for `days` days."""
    removed: list[str] = []
    cutoff: datetime = now - timedelta(days=days)
    for entry in load_sessions():
        seen: datetime | None = parse_iso(entry.get("last_seen"))
        if entry.get("state") != ENDED or seen is None or seen > cutoff:
            continue
        session_id: str = entry["session_id"]
        for path in (session_path(session_id), receipt_path(session_id), checkins_path(session_id)):
            path.unlink(missing_ok=True)
        removed.append(session_id)
    return removed


def prune_broadcasts(now: datetime) -> int:
    broadcasts: list[dict[str, Any]] = read_lines(broadcasts_path())
    kept: list[dict[str, Any]] = [b for b in broadcasts if not is_expired(b, now)]
    if len(kept) == len(broadcasts):
        return 0
    state_io.atomic_write(broadcasts_path(), "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in kept))
    return len(broadcasts) - len(kept)


def cmd_prune(args: argparse.Namespace) -> int:
    now: datetime = utc_now()
    sessions: list[str] = prune_sessions(args.days, now)
    broadcasts: int = prune_broadcasts(now)
    print(f"pruned {len(sessions)} ended session(s) older than {args.days} days and {broadcasts} expired broadcast(s)")
    return EXIT_OK


# ---------------------------------------------------------------- check-ins

def cmd_checkin(args: argparse.Namespace) -> int:
    session_id: str | None = args.session or os.environ.get(ENV_SESSION)
    if not valid_session_id(session_id):
        raise FleetError("checkin needs --session <id> (or CLAUDE_SESSION_ID in the environment)")
    assert session_id is not None
    record: dict[str, Any] = {"ts": to_iso(utc_now()), "session_id": session_id, "broadcast_id": args.broadcast,
                              "status": args.status, "blockers": args.blocker or [], "next": args.next,
                              "questions": args.question or []}
    append_line(checkins_path(session_id), record)
    print(f"check-in recorded for {session_id[:8]}")
    return EXIT_OK


def latest_checkin(session_id: str, since: datetime, broadcast_id: str | None) -> dict[str, Any] | None:
    for record in reversed(read_lines(checkins_path(session_id))):
        moment: datetime | None = parse_iso(record.get("ts"))
        if moment is None or moment < since:
            continue
        if broadcast_id and record.get("broadcast_id") != broadcast_id:
            continue
        return record
    return None


def derived_items(entry: dict[str, Any], broadcasts: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    cwd: Path = Path(str(entry.get("cwd") or "."))
    harness: bool = bool(entry.get("harness")) and cwd.is_dir()
    incidents: Any = run_script_json(INCIDENTS_SCRIPT, ["list", "--json"], cwd) if harness else None
    return {
        "open_intake": len(open_intake_items(cwd)) if harness else 0,
        "handoff_present": (cwd / state_io.HANDOFF_LATEST_REL).is_file() if harness else False,
        "pending_broadcasts": len(pending_for(entry, broadcasts, load_receipt(entry["session_id"]), now)),
        "cooldowns": cooling_agents(),
        "incidents": len(incidents) if isinstance(incidents, list) else None,
    }


def build_checkins_report(since: timedelta, include_all: bool, broadcast_id: str | None,
                          now: datetime) -> dict[str, Any]:
    broadcasts: list[dict[str, Any]] = load_broadcasts()
    blocks: list[dict[str, Any]] = []
    for entry in load_sessions():
        state: str = effective_state(entry, now)
        if not include_all and state in (ENDED, DEAD):
            continue
        record: dict[str, Any] | None = latest_checkin(entry["session_id"], now - since, broadcast_id)
        when: datetime | None = parse_iso(record.get("ts")) if record else None
        blocks.append({
            "session_id": entry["session_id"], "label": entry.get("label"), "repo": entry.get("repo"),
            "branch": entry.get("branch"), "state": state,
            "last_seen_age": age_text(parse_iso(entry.get("last_seen")), now),
            "checkin": ({**record, "age": age_text(when, now)} if record else None),
            "derived": derived_items(entry, broadcasts, now),
        })
    blocks.sort(key=lambda b: (b["checkin"] is not None, str(b["label"] or b["session_id"])))
    needs: list[dict[str, str]] = []
    for block in blocks:
        checkin: dict[str, Any] | None = block["checkin"]
        who: str = block["label"] or block["session_id"][:8]
        for blocker in (checkin or {}).get("blockers", []):
            needs.append({"session": who, "type": "blocker", "text": str(blocker)})
        for question in (checkin or {}).get("questions", []):
            needs.append({"session": who, "type": "question", "text": str(question)})
    summary: dict[str, int] = {
        "sessions": len(blocks),
        "checked_in": sum(1 for b in blocks if b["checkin"]),
        "with_blockers": sum(1 for b in blocks if b["checkin"] and b["checkin"].get("blockers")),
        "with_open_questions": sum(1 for b in blocks if b["checkin"] and b["checkin"].get("questions")),
        "stale": sum(1 for b in blocks if b["state"] == STALE),
    }
    return {"summary": summary, "sessions": blocks, "needs_you": needs}


def render_checkins(report: dict[str, Any]) -> str:
    summary: dict[str, int] = report["summary"]
    lines: list[str] = [
        f"{summary['sessions']} sessions, {summary['checked_in']} checked in, {summary['with_blockers']} with blockers, "
        f"{summary['with_open_questions']} with open questions, {summary['stale']} stale", ""]
    for block in report["sessions"]:
        name: str = f"{block['label']} ({block['session_id'][:8]})" if block["label"] else block["session_id"][:8]
        lines.append(f"{name}  {cell(block['repo'])}@{cell(block['branch'])}  {block['state']}  "
                     f"last seen {block['last_seen_age']} ago")
        checkin: dict[str, Any] | None = block["checkin"]
        if checkin:
            lines.append(f"  check-in ({checkin['age']} ago): {checkin.get('status')}")
            lines.extend(f"  blocker: {b}" for b in checkin.get("blockers", []))
            if checkin.get("next"):
                lines.append(f"  next: {checkin['next']}")
            lines.extend(f"  question: {q}" for q in checkin.get("questions", []))
        else:
            lines.append("  no check-in yet")
        derived: dict[str, Any] = block["derived"]
        facts: list[str] = [f"{derived['open_intake']} open intake", f"handoff {'yes' if derived['handoff_present'] else 'no'}",
                            f"{derived['pending_broadcasts']} pending broadcast(s)"]
        if derived["cooldowns"]:
            facts.append("cooling: " + ", ".join(derived["cooldowns"]))
        if derived["incidents"] is not None:
            facts.append(f"{derived['incidents']} incident(s)")
        lines.append("  derived: " + "; ".join(facts))
        lines.append("")
    lines.append("Needs you:")
    lines.extend(f"  {n['session']}  {n['type']}: {n['text']}" for n in report["needs_you"])
    if not report["needs_you"]:
        lines.append("  nothing reported")
    return "\n".join(lines)


def cmd_checkins(args: argparse.Namespace) -> int:
    report: dict[str, Any] = build_checkins_report(parse_duration(args.since), args.all, args.broadcast, utc_now())
    print(json.dumps(report, ensure_ascii=False) if args.json else render_checkins(report))
    return EXIT_OK


# ---------------------------------------------------------------- hook entry and CLI

def cmd_hook(args: argparse.Namespace) -> int:
    """Hook entry point. Never raises and always exits 0, whatever arrives on stdin."""
    try:
        raw: str = "" if sys.stdin.isatty() else sys.stdin.read()
        output: str | None = run_hook(args.event, json.loads(raw) if raw.strip() else None, args.pid or os.getppid())
        if output:
            print(output)
    except Exception:  # noqa: BLE001 - a hook must never fail a session
        return EXIT_OK
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet.py", description="See every dts2 session on this machine and broadcast to them.")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="hook entry point (reads hook JSON on stdin)")
    hook.add_argument("--event", required=True, choices=EVENTS)
    hook.add_argument("--pid", type=int, default=None, help="the Claude process id (the hook shell's $PPID)")
    hook.set_defaults(func=cmd_hook)
    listing = sub.add_parser("list", help="table of sessions (ended hidden)")
    listing.add_argument("--all", action="store_true", help="include ended sessions")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)
    show = sub.add_parser("show", help="one session with its harness ledgers (read-only)")
    show.add_argument("ref", help="session id prefix or label")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)
    logs = sub.add_parser("logs", help="last turns of a session's transcript (read-only)")
    logs.add_argument("ref")
    logs.add_argument("-n", type=int, default=LOG_DEFAULT_TURNS, help="messages to show (default 20)")
    logs.set_defaults(func=cmd_logs)
    cast = sub.add_parser("broadcast", help="send a message to matching sessions")
    cast.add_argument("--kind", required=True, choices=KINDS)
    cast.add_argument("--text", default=None)
    cast.add_argument("words", nargs="*", help="message text when --text is not given")
    cast.add_argument("--to", action="append", default=None, metavar="TARGET",
                      help="all|harness|repo:X|id:X|label:X (repeatable; default all)")
    cast.add_argument("--expires", default=DEFAULT_EXPIRES, help="for example 24h, 30m, 2d, or never")
    cast.add_argument("--from-knowledge", default=None, metavar="KEY", help="use `knowledge get KEY` as the text")
    cast.set_defaults(func=cmd_broadcast)
    status = sub.add_parser("status", help="delivered versus pending per broadcast")
    status.add_argument("broadcast_id", nargs="?", default=None)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)
    label = sub.add_parser("label", help="name a session (for example its terminal tab)")
    label.add_argument("ref")
    label.add_argument("name")
    label.set_defaults(func=cmd_label)
    prune = sub.add_parser("prune", help="remove old ended sessions and expired broadcasts")
    prune.add_argument("--days", type=int, default=PRUNE_DAYS)
    prune.set_defaults(func=cmd_prune)
    checkin = sub.add_parser("checkin", help="a session reports its own status (called by the agent)")
    checkin.add_argument("--session", default=None)
    checkin.add_argument("--status", required=True)
    checkin.add_argument("--blocker", action="append", default=None)
    checkin.add_argument("--next", default=None)
    checkin.add_argument("--question", action="append", default=None)
    checkin.add_argument("--broadcast", default=None)
    checkin.set_defaults(func=cmd_checkin)
    report = sub.add_parser("checkins", help="aggregate check-in report across sessions (read-only)")
    report.add_argument("--since", default=DEFAULT_EXPIRES)
    report.add_argument("--json", action="store_true")
    report.add_argument("--broadcast", default=None)
    report.add_argument("--all", action="store_true", help="include ended and dead sessions")
    report.set_defaults(func=cmd_checkins)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except FleetError as error:
        print(f"fleet: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
