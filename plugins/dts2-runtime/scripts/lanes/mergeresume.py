"""G-15: resume a merge a dead head left half done. If a lane holds the merge, GitHub says what happened to its PR: merged
(record it done and move on) or still open (drop the hold and its grant so the head re-verifies and grants again)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from .common import MERGE_GO_NAME, MERGE_ORDER_NAME
from .gitrefs import PR_STATE_MERGED, PR_STATE_OPEN, branch_prs, gh_down, lane_ref
from .journal import AskGithub, KIND_RECOVERED, note, resume_state
from .merge import effective_manifest, merge_done, merge_lock, merge_state, save_merge_state
from .records import inside_son, son_refusal

ACTION_RETRY: Final[str] = "regrant"
ACTION_RECOVERED: Final[str] = "recovered"


def merge_resume(manifest: dict[str, Any], runs_dir: Path, cwd: Path, ask: AskGithub = branch_prs) -> dict[str, Any]:
    """Pick the merge up where a dead head left it. If a lane holds the merge, GitHub says what happened to its PR: merged
    (record it done and move on) or still open (drop the hold and its grant so the head re-verifies and grants again)."""
    if inside_son():
        return son_refusal("merge-resume")
    stamp: str = str(manifest["stamp"])
    full: dict[str, Any] = effective_manifest(manifest, runs_dir)
    current: Any = merge_state(runs_dir, full)["current"]
    result: dict[str, Any] = {"ok": True, "stamp": stamp, "in_flight": current, "action": None}
    if current:
        prs, why = ask(cwd, lane_ref(stamp, str(current)))
        if prs is None:
            return {"ok": False, "stamp": stamp, "in_flight": current, "error": why, "detail": gh_down("merge-resume")}
        if any(pr.get("state") == PR_STATE_MERGED for pr in prs):
            done: dict[str, Any] = merge_done(manifest, runs_dir, str(current))
            note(runs_dir, stamp, KIND_RECOVERED, lane=str(current), key="", how="merged on GitHub")
            result.update(action=ACTION_RECOVERED, recovered=str(current), all_merged=done.get("all_merged"))
        elif any(pr.get("state") == PR_STATE_OPEN for pr in prs):
            release_hold(runs_dir, stamp, full, str(current))
            result.update(action=ACTION_RETRY, in_flight=None)
        else:
            return {"ok": False, "stamp": stamp, "in_flight": current, "error": f"no PR found for lane {current}",
                    "detail": "the lane holds the merge but GitHub has no PR for its branch; reconcile the lane first"}
    return {**result, **resume_state(runs_dir, stamp, manifest)}


def release_hold(runs_dir: Path, stamp: str, manifest: dict[str, Any], lane_id: str) -> None:
    """Un-grant a merge that never happened: the lane stops holding the merge and its merge-go.md is removed."""
    path: Path = runs_dir / stamp / MERGE_ORDER_NAME
    with merge_lock(path):
        state: dict[str, Any] = merge_state(runs_dir, manifest)
        if state["current"] == lane_id:
            save_merge_state(path, {**state, "current": None})
    (runs_dir / stamp / lane_id / MERGE_GO_NAME).unlink(missing_ok=True)
