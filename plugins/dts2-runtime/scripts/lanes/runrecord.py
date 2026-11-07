"""G-17: the run's typed record. `run.json` (one per run, for a dpp run and an autopilot run alike) has named, typed
fields; `builders.jsonl` has one event row per builder step (section, branch, status, diff-confirmed sha, round) in the
shared event shape. `run resume` reads both instead of parsing Markdown."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from state_io import event_id, make_event

from .common import BUILDERS_NAME, PHASE_BLOCKED, PHASE_DONE, PHASE_INCOMPLETE, PHASE_PR_OPEN, PHASE_STARTING, RUN_NAME, LaneError, binary, run
from .records import merge_json, read_json_object, state_for

KIND_RUN: Final[str] = "run"
KIND_AUTOPILOT: Final[str] = "autopilot"
RUN_KINDS: Final[tuple[str, ...]] = (KIND_RUN, KIND_AUTOPILOT)
BUILDER_MERGED: Final[str] = "merged"
BUILDER_STATUSES: Final[tuple[str, ...]] = (PHASE_STARTING, PHASE_PR_OPEN, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE, BUILDER_MERGED)
FINISHED: Final[frozenset[str]] = frozenset({PHASE_DONE, BUILDER_MERGED})
BUILDER_KIND: Final[str] = "builder"
# field -> (allowed types, nullable). A field not listed is kept as it is and returned under `extra`.
FIELDS: Final[dict[str, tuple[tuple[type, ...], bool]]] = {
    "kind": ((str,), False), "started": ((int,), True), "claude_version": ((str,), True), "preflight_ok": ((bool,), False),
    "checked": ((int,), True), "problems": ((list,), False), "merge_target": ((str,), True),
    "default_branch_yes": ((bool,), False), "gc_auto_paused": ((bool,), False), "gc_auto_prior": ((str,), True),
}
DEFAULTS: Final[dict[str, Any]] = {"kind": KIND_RUN, "started": None, "claude_version": None, "preflight_ok": False,
                                   "checked": None, "problems": [], "merge_target": None, "default_branch_yes": False,
                                   "gc_auto_paused": False, "gc_auto_prior": None}


@dataclass(frozen=True)
class RunRecord:
    stamp: str
    kind: str = KIND_RUN
    started: int | None = None
    claude_version: str | None = None
    preflight_ok: bool = False
    checked: int | None = None
    problems: tuple[str, ...] = ()
    merge_target: str | None = None
    default_branch_yes: bool = False
    gc_auto_paused: bool = False
    gc_auto_prior: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        named: dict[str, Any] = {name: getattr(self, name) for name in FIELDS}
        return {**self.extra, **named, "problems": list(self.problems), "stamp": self.stamp}


def check_field(name: str, value: Any) -> Any:
    """The value if it has the field's type, else a LaneError that names the field."""
    kinds, nullable = FIELDS[name]
    if value is None and nullable:
        return None
    if isinstance(value, bool) and bool not in kinds:
        raise LaneError(f"run.json: {name} must be {kinds[0].__name__}, got a bool")
    if not isinstance(value, kinds):
        raise LaneError(f"run.json: {name} must be {kinds[0].__name__}{' or null' if nullable else ''}, got {type(value).__name__}")
    if name == "kind" and value not in RUN_KINDS:
        raise LaneError(f"run.json: kind must be one of {', '.join(RUN_KINDS)}")
    if name == "problems" and not all(isinstance(item, str) for item in value):
        raise LaneError("run.json: problems must be a list of strings")
    return value


def parse_run(stamp: str, data: dict[str, Any]) -> RunRecord:
    named: dict[str, Any] = {name: check_field(name, data[name]) if name in data else DEFAULTS[name] for name in FIELDS}
    extra: dict[str, Any] = {k: v for k, v in data.items() if k not in FIELDS and k not in ("stamp", "v")}
    return RunRecord(stamp=stamp, **{**named, "problems": tuple(named["problems"])}, extra=extra)


def run_path(runs_dir: Path, stamp: str) -> Path:
    return runs_dir / stamp / RUN_NAME


def read_run(runs_dir: Path, stamp: str) -> RunRecord:
    """The run's record, every named field checked. A missing run.json reads as the defaults."""
    return parse_run(stamp, read_json_object(run_path(runs_dir, stamp)))


def update_run(runs_dir: Path, stamp: str, changes: dict[str, Any]) -> RunRecord:
    """Merge `changes` into run.json under its lock; a named field with the wrong type is refused before anything is written."""
    for name, value in changes.items():
        if name in FIELDS:
            check_field(name, value)
    merged: dict[str, Any] = merge_json(run_path(runs_dir, stamp), {"stamp": stamp, **changes})
    return parse_run(stamp, merged)


def init_run(runs_dir: Path, stamp: str, kind: str = KIND_RUN, now: int | None = None) -> RunRecord:
    """Open the run record once (its `started` time and kind); calling it again changes nothing."""
    current: dict[str, Any] = read_json_object(run_path(runs_dir, stamp))
    if isinstance(current.get("started"), int):
        return parse_run(stamp, current)
    return update_run(runs_dir, stamp, {"kind": kind, "started": int(time.time()) if now is None else now})


def confirm_sha(cwd: Path, branch: str, sha: str, base: str | None = None) -> tuple[bool, str]:
    """(confirmed, why not): `sha` is a real commit, is the tip of the builder's branch, and (with a base) changes something."""
    git: list[str] = binary("DTS2_GIT_BIN", "git")
    code, out = run([*git, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd)
    full: str = out.strip()
    if code != 0 or not full:
        return False, f"{sha} is not a commit here"
    for ref in (branch, f"origin/{branch}"):
        code, tip = run([*git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)
        if code == 0 and tip.strip():
            if tip.strip() != full:
                return False, f"{sha} is not the tip of {ref}"
            break
    else:
        return False, f"branch {branch} not found"
    if base:
        code, names = run([*git, "diff", "--name-only", f"{base}...{full}"], cwd)
        if code != 0 or not names.strip():
            return False, f"the diff {base}...{sha} is empty"
    return True, ""


def record_builder(runs_dir: Path, stamp: str, lane_id: str, *, section: str, branch: str, status: str, round_no: int,
                   sha: str | None = None, pr: int | None = None, cwd: Path | None = None,
                   base: str | None = None) -> dict[str, Any]:
    """Append one builder row. The sha is `confirmed` only when it checks out against the branch and diff (needs `cwd`);
    recording the same row twice is a no-op."""
    if status not in BUILDER_STATUSES:
        raise LaneError(f"--status must be one of {', '.join(BUILDER_STATUSES)}")
    if round_no < 0:
        raise LaneError("--round must be 0 or more")
    confirmed, why = confirm_sha(cwd, branch, sha, base) if sha and cwd is not None else (False, "no sha" if not sha else "no repo")
    row: dict[str, Any] = make_event(BUILDER_KIND, run=stamp, lane=lane_id,
                                     id=event_id(stamp, lane_id, section, round_no, status, sha or ""),
                                     section=section, branch=branch, status=status, sha=sha, confirmed=confirmed,
                                     round=round_no, pr=pr)
    fresh: bool = state_for(runs_dir / stamp / BUILDERS_NAME).append_event(BUILDERS_NAME, row)
    return {"ok": True, "recorded": fresh, "lane": lane_id, "section": section, "status": status, "confirmed": confirmed,
            "unconfirmed_because": None if confirmed or not sha else why}


def builder_rows(runs_dir: Path, stamp: str) -> list[dict[str, Any]]:
    return state_for(runs_dir / stamp / BUILDERS_NAME).events(BUILDERS_NAME, BUILDER_KIND)


def latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The newest row of each (lane, section), in the order the pairs first appeared."""
    newest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        newest[(str(row.get("lane")), str(row.get("section")))] = row
    return list(newest.values())


def resume_view(runs_dir: Path, stamp: str) -> dict[str, Any]:
    """What `run resume` needs, read from the typed records: the run record, the newest row per builder step, the steps
    still to do (with the sha to continue from only when it was confirmed) and those already finished."""
    record: RunRecord = read_run(runs_dir, stamp)
    latest: list[dict[str, Any]] = latest_rows(builder_rows(runs_dir, stamp))
    todo: list[dict[str, Any]] = [
        {"lane": r.get("lane"), "section": r.get("section"), "branch": r.get("branch"), "status": r.get("status"),
         "round": r.get("round"), "pr": r.get("pr"), "from_sha": r.get("sha") if r.get("confirmed") else None}
        for r in latest if r.get("status") not in FINISHED]
    finished: list[str] = [f"{r.get('lane')}/{r.get('section')}" for r in latest if r.get("status") in FINISHED]
    return {"ok": True, "stamp": stamp, "run": record.to_dict(), "builders": latest, "todo": todo, "finished": finished}
