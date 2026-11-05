#!/usr/bin/env python3
"""PostToolUse context guard: one cheap process per tool call. Reads the hook JSON on stdin, always exits 0."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from state_io import atomic_write  # noqa: E402
import state_io  # noqa: E402
from state_ids import STAMP_PATTERN  # noqa: E402
import _load  # noqa: E402

BYTES_PER_MB: Final[int] = 1048576
SESSION_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]")
TOOL_USE: Final[re.Pattern[bytes]] = re.compile(rb'"type": ?"tool_use"')
NEWLINE: Final[bytes] = b"\n"
ACTIVE_BRANCH: Final[re.Pattern[str]] = re.compile(r"^ref: refs/heads/dts2/([A-Za-z0-9._-]+)/")
MISPLACED: Final[str] = "workspace-member"
MESSAGE: Final[str] = (
    "dts2-harness CONTEXT GUARD (%s): %s. STOP: do not dispatch or continue any agent. "
    "Follow the run skill's 'Context guard and pivot' section now: write .harness/state.md and the handoff file, "
    "run scope-check, then /dts2:setup (workspace re-link if a manifest exists) and resume with run resume.")


DEFAULT_EVENT: Final[str] = "PostToolUse"
BATCH_EVENT: Final[str] = "PostToolBatch"  # same guard, fired once per parallel batch
STOP_REASON: Final[str] = "dts2-harness context guard (%s): %s. Re-run setup and resume with run resume."


def load_scope_module() -> ModuleType:
    return _load.load("scope-check")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fire(marker_dir: Path, session: str, trigger: str, details: str, stop: bool = False, event: str = DEFAULT_EVENT) -> None:
    marker: Path = marker_dir / f"dts2-guard-{session}-{trigger}"
    if marker.exists():
        return
    try:
        marker.touch()
    except OSError:
        pass
    output: dict[str, Any] = {"hookSpecificOutput": {
        "hookEventName": event, "additionalContext": MESSAGE % (trigger, details)}}
    if stop:  # context_guard_stop: also end the turn instead of only advising
        output["continue"] = False
        output["stopReason"] = STOP_REASON % (trigger, details)
    print(json.dumps(output))


def head_ref(repo: Path) -> str:
    """The branch ref `.git/HEAD` names (follows a worktree's `.git` file); empty when it cannot be read."""
    git: Path = repo / ".git"
    try:
        if git.is_file():
            pointer: str = git.read_text(encoding="utf-8").strip()
            git = (repo / pointer.removeprefix("gitdir:").strip()) if pointer.startswith("gitdir:") else git
        return (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def active_stamp(repo: Path) -> str | None:
    """The run stamp in a `dts2/<stamp>/...` branch name: the run this session is on (new or resumed), or None."""
    match: re.Match[str] | None = ACTIVE_BRANCH.match(head_ref(repo))
    return match.group(1) if match else None


def current_run(effective: Path, active: str | None = None) -> Path | None:
    """The run this session is in: the active run (stamp in the `dts2/<stamp>/` branch name) when its folder exists, else the
    newest stamped run folder by name, else the most recently touched folder."""
    if active is not None and (effective / state_io.RUNS_REL / active).is_dir():
        return effective / state_io.RUNS_REL / active
    runs: list[Path] = [p for p in (effective / state_io.RUNS_REL).glob("*") if p.is_dir()]
    stamped: list[Path] = sorted(p for p in runs if STAMP_PATTERN.fullmatch(p.name))
    if stamped:
        return stamped[-1]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def has_plan(effective: Path, active: str | None = None) -> bool:
    """True when the current run (not any older run) has reached its plan checkpoint."""
    run: Path | None = current_run(effective, active)
    return run is not None and (run / "plan.md").is_file()


def int_field(state: dict[str, Any], key: str) -> int:
    value: Any = state.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def count_new_calls(transcript: Path, state_file: Path) -> tuple[int, int]:
    """Return (cumulative tool_use lines, transcript size in bytes), reading only bytes not yet counted."""
    state: dict[str, Any] = read_json(state_file)
    size: int = os.path.getsize(transcript)
    offset: int = int_field(state, "offset")
    calls: int = int_field(state, "calls")
    if state.get("path") != str(transcript) or size < offset:
        offset, calls = 0, 0
    with open(transcript, "rb") as handle:
        handle.seek(offset)
        chunk: bytes = handle.read()
    complete: int = chunk.rfind(NEWLINE) + 1
    calls += sum(1 for line in chunk[:complete].split(NEWLINE) if TOOL_USE.search(line))
    offset += complete
    try:
        atomic_write(state_file, json.dumps({"path": str(transcript), "offset": offset, "calls": calls}))
    except OSError:
        pass
    return calls, size


def run(tool_calls: int, mb: int, stop: bool) -> None:
    payload: Any = json.load(sys.stdin)
    if not isinstance(payload, dict):
        return
    session: str = SESSION_UNSAFE.sub("", str(payload.get("session_id") or ""))
    if not session:
        return
    event: str = BATCH_EVENT if payload.get("hook_event_name") == BATCH_EVENT else DEFAULT_EVENT
    cwd: str = str(payload.get("cwd") or "")
    if not cwd or not os.path.isdir(cwd):
        cwd = os.getcwd()
    marker_dir: Path = Path(os.environ.get("TMPDIR") or "/tmp")
    scope: dict[str, Any] = load_scope_module().detect(Path(cwd))
    if scope.get("scope") == MISPLACED:
        fire(marker_dir, session, "misplaced", f"cwd {cwd} is a member repo of workspace {scope.get('workspaceRoot')}", stop, event)
        return
    effective: Path = Path(scope.get("workspaceRoot") or cwd)
    if has_plan(effective, active_stamp(Path(cwd))):
        return
    transcript: Path = Path(str(payload.get("transcript_path") or ""))
    if not transcript.is_file():
        return
    calls, size = count_new_calls(transcript, marker_dir / f"dts2-guard-{session}-offset.json")
    size_mb: int = size // BYTES_PER_MB
    if calls >= tool_calls or size_mb >= mb:
        fire(marker_dir, session, "spike", f"{calls} tool calls / {size_mb} MB with no plan checkpoint reached", stop, event)


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-calls", type=int, required=True)
    parser.add_argument("--mb", type=int, required=True)
    parser.add_argument("--stop", action="store_true", help="also emit continue:false with a stopReason when the guard fires")
    args: argparse.Namespace = parser.parse_args()
    try:
        run(args.tool_calls, args.mb, args.stop)
    except Exception:  # noqa: BLE001 - a guard must never fail the session
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
