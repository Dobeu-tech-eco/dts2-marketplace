"""G-14: `reconcile` asks GitHub what really exists for every lane before the head creates a PR, merges one or resumes a
lane, so a crash between "push" and "record" can never produce a second PR for the same branch.

For each lane it reads the PRs whose head is the lane's branch and decides one action:
  merged       a PR for the branch is already merged: the lane is done, do not merge it again
  adopt-pr     a PR is open: record its number and do not create another
  create-pr    the lane reported (or reached pr-open) and GitHub has no PR: it is safe to create one
  resume       the lane is orphaned (quiet, no running process, a dirty worktree, no report.md, no PR): resume it, once
  park         it was already resumed once and is orphaned again: end it incomplete
  stalled      quiet and clean without a report: the usual stalled handling applies (send-back, resume or re-plan)
  none         nothing to do
It fails closed: if GitHub cannot be asked, nothing is decided. There is no per-tool heartbeat hook; staleness is the one
`status` already computes."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Final

from model_call import read_supervisor

from .common import (
    LaneError, PHASE_DONE, PHASE_INCOMPLETE, PHASE_ORPHANED, PHASE_PR_OPEN, REASON_ORPHANED, REASON_STALLED, REPORT_NAME,
    SECONDS_PER_MINUTE, STATUS_NAME, binary, run,
)
from .gitrefs import PR_STATE_MERGED, PR_STATE_OPEN, branch_prs, gh_down, lane_ref
from .merge import inside_son, record_merged, son_refusal
from .phases import transition
from .records import merge_json
from .runstate import lane_status, read_status_files, stale_after

MAX_ORPHAN_RESUMES: Final[int] = 1
ACTION_MERGED: Final[str] = "merged"
ACTION_ADOPT: Final[str] = "adopt-pr"
ACTION_CREATE: Final[str] = "create-pr"
ACTION_RESUME: Final[str] = "resume"
ACTION_PARK: Final[str] = "park"
ACTION_STALLED: Final[str] = "stalled"
ACTION_NONE: Final[str] = "none"
# A lane can be orphaned only while it is not in a finished or waiting state.
# The empty phase (no status yet) is left out: LEGAL has no move from it to orphaned, so there is nothing to flag.
ORPHANABLE: Final[frozenset[str]] = frozenset({"starting", PHASE_INCOMPLETE, PHASE_ORPHANED})

AskGithub = Callable[[Path, str], tuple[list[dict[str, Any]] | None, str | None]]


class GithubDown(LaneError):
    """GitHub could not be asked; reconcile decides nothing."""


def worktree_dirty(worktree: Any) -> bool:
    """True when the lane's worktree has uncommitted work. A missing worktree is not dirty: there is nothing to resume in."""
    if not isinstance(worktree, str) or not Path(worktree).is_dir():
        return False
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "status", "--porcelain"], Path(worktree))
    return code == 0 and bool(out.strip())


def pick(prs: list[dict[str, Any]], state: str) -> dict[str, Any] | None:
    return next((pr for pr in prs if pr.get("state") == state), None)


def pr_view(pr: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if pr is None else {"number": pr.get("number"), "state": pr.get("state"), "url": pr.get("url")}


def is_quiet(info: dict[str, Any], data: dict[str, Any]) -> bool:
    """Not heard from for the stall window: stale now, or already parked as stalled by `status`, or flagged orphaned."""
    phase: str = info["phase"]
    return bool(info["stale"]) or phase == PHASE_ORPHANED or (phase == PHASE_INCOMPLETE and data.get("reason") == REASON_STALLED)


def orphan_action(runs_dir: Path, stamp: str, lane: str, phase: str, data: dict[str, Any]) -> tuple[str, str]:
    """Flag an orphaned lane and grant its one resume, or park it when that resume is already spent."""
    resumes: int = int(data.get("resume_count") or 0)
    if phase == PHASE_ORPHANED or resumes < MAX_ORPHAN_RESUMES:
        number: int = resumes if phase == PHASE_ORPHANED else resumes + 1
        if phase != PHASE_ORPHANED:
            moved: dict[str, Any] = transition(runs_dir, stamp, lane, PHASE_ORPHANED, reason=REASON_ORPHANED, actor="head")
            if not moved["ok"]:
                return ACTION_STALLED, f"could not flag the lane orphaned: {moved['detail']}"
            merge_json(runs_dir / stamp / lane / STATUS_NAME, {"resume_count": number})
        return ACTION_RESUME, (f"orphaned: dirty worktree, no report, no PR; spawn --resume "
                               f"(resume {number} of {MAX_ORPHAN_RESUMES})")
    transition(runs_dir, stamp, lane, PHASE_INCOMPLETE, reason=REASON_ORPHANED, actor="head")
    return ACTION_PARK, "orphaned again after its one resume: parked incomplete, escalate"


def decide(runs_dir: Path, stamp: str, path: Path, data: dict[str, Any], info: dict[str, Any],
           prs: list[dict[str, Any]], dirty: Callable[[Any], bool]) -> tuple[str, str, bool, bool]:
    """(action, detail, dirty, has_report) for one lane; records what GitHub showed (and orphan handling) as it goes."""
    lane: str = info["lane"]
    phase: str = info["phase"]
    report: bool = (path.parent / REPORT_NAME).is_file()
    merged, opened = pick(prs, PR_STATE_MERGED), pick(prs, PR_STATE_OPEN)
    if merged is not None:
        merge_json(path, {"pr": merged.get("number"), "pr_url": merged.get("url"), "merged_on_github": True})
        if phase != PHASE_DONE:
            transition(runs_dir, stamp, lane, PHASE_DONE, reason="merged on GitHub", actor="head")
        record_merged(runs_dir, stamp, lane)
        return ACTION_MERGED, f"PR #{merged.get('number')} is already merged; do not merge it again", False, report
    if opened is not None:
        merge_json(path, {"pr": opened.get("number"), "pr_url": opened.get("url")})
        return ACTION_ADOPT, f"PR #{opened.get('number')} is already open for this branch; do not create another", False, report
    quiet: bool = is_quiet(info, data) and not info["alive"] and phase in ORPHANABLE
    is_dirty: bool = dirty(data.get("worktree")) if quiet else False
    if quiet and is_dirty and not report:
        action, detail = orphan_action(runs_dir, stamp, lane, phase, data)
        return action, detail, True, report
    if (quiet and report) or phase == PHASE_PR_OPEN:
        return ACTION_CREATE, "GitHub has no PR for this branch; creating one is safe", is_dirty, report
    if quiet:
        return ACTION_STALLED, "quiet with a clean worktree and no report; send back, resume or re-plan", is_dirty, report
    return ACTION_NONE, "", False, report


def reconcile_lane(runs_dir: Path, stamp: str, path: Path, data: dict[str, Any], threshold: int, stall_s: int, now: int,
                   ask: AskGithub, dirty: Callable[[Any], bool], cwd: Path) -> dict[str, Any]:
    info: dict[str, Any] = lane_status(path, data, threshold, now, stall_s)
    prs, why = ask(cwd, lane_ref(stamp, info["lane"]))
    if prs is None:
        raise GithubDown(why or "GitHub did not answer")
    action, detail, is_dirty, report = decide(runs_dir, stamp, path, data, info, prs, dirty)
    return {"lane": info["lane"], "phase": info["phase"], "stale": info["stale"], "alive": info["alive"], "dirty": is_dirty,
            "report": report, "pr": pr_view(pick(prs, PR_STATE_MERGED) or pick(prs, PR_STATE_OPEN) or (prs[0] if prs else None)),
            "action": action, "detail": detail}


def reconcile(runs_dir: Path, stamp: str, cwd: Path, now: int | None = None, ask: AskGithub = branch_prs,
              dirty: Callable[[Any], bool] = worktree_dirty) -> dict[str, Any]:
    """Ask GitHub about every lane of the run and settle what the record says; the head acts on each lane's `action`."""
    if inside_son():
        return son_refusal("reconcile")
    clock: int = int(time.time()) if now is None else now
    threshold: int = stale_after(cwd)
    stall_s: int = read_supervisor(cwd)["stall_minutes"] * SECONDS_PER_MINUTE
    rows: list[dict[str, Any]] = []
    try:
        for path, data in read_status_files(runs_dir, stamp):
            rows.append(reconcile_lane(runs_dir, stamp, path, data, threshold, stall_s, clock, ask, dirty, cwd))
    except GithubDown as exc:
        return {"ok": False, "stamp": stamp, "error": str(exc), "detail": gh_down("reconcile"), "lanes": rows}
    return {"ok": True, "stamp": stamp, "lanes": rows, "actions": {row["lane"]: row["action"] for row in rows},
            "orphaned": [row["lane"] for row in rows if row["action"] in (ACTION_RESUME, ACTION_PARK)]}
