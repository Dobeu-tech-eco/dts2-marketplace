"""G-15: the per-run merge journal. `merge-journal.jsonl` holds one event row for each step of the fold and the merge
(a grant, a merge done, a fold plan, a fold group shipped, a failed walkthrough), each with a stable id, so a head that
dies half way reads it and carries on instead of starting over. A failed post-merge walkthrough also files one revert
action item (never two)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Final

from state_ids import InvalidId
from state_io import event_id, make_event

from .common import LaneError, MERGE_JOURNAL_NAME, MERGE_ORDER_NAME, PLUGIN_ROOT, STATUS_NAME, binary, run
from .records import inside_son, read_json_object, son_refusal, state_for

KIND_GRANTED: Final[str] = "merge-granted"
KIND_MERGED: Final[str] = "merge-done"
KIND_RECOVERED: Final[str] = "merge-recovered"
KIND_FOLD_PLANNED: Final[str] = "fold-planned"
KIND_FOLD_DONE: Final[str] = "fold-group-done"
KIND_WALKTHROUGH_FAILED: Final[str] = "walkthrough-failed"
KIND_REVERT_FILED: Final[str] = "revert-filed"
KIND_FIX_ATTEMPT: Final[str] = "post-merge-fix"  # G-78
KIND_REVERT_PR: Final[str] = "revert-pr"  # G-78
KIND_SUPERSEDED: Final[str] = "fold-superseded"  # G-79
KIND_ORIGINAL_CLOSED: Final[str] = "original-closed"  # G-79
FIX_ATTEMPTS_FIELD: Final[str] = "post_merge_fix_attempts"
DEFAULT_FIX_ATTEMPTS: Final[int] = 2
PR_STATE_OPEN_WORD: Final[str] = "OPEN"
AskGithub = Callable[[Path, str], tuple[list[dict[str, Any]] | None, str | None]]
ACTION_ITEMS: Final[Path] = PLUGIN_ROOT / "scripts" / "action-items.py"
REVERT_GROUP: Final[str] = "Decisions"


def journal_path(runs_dir: Path, stamp: str) -> Path:
    return runs_dir / stamp / MERGE_JOURNAL_NAME


def note(runs_dir: Path, stamp: str, kind: str, *, lane: str | None = None, key: object = "", **fields: Any) -> bool:
    """Append one journal event; False when the same step (same kind, lane and key) was already noted, or the stamp or
    lane is not a valid id. `key` tells apart repeats of a step that may legitimately happen again (a second grant)."""
    path: Path = journal_path(runs_dir, stamp)
    try:
        event: dict[str, Any] = make_event(kind, run=stamp, lane=lane, id=event_id(stamp, kind, lane or "-", key), **fields)
    except InvalidId:
        return False
    return state_for(path).append_event(path.name, event)


def journal_events(runs_dir: Path, stamp: str, kind: str | None = None) -> list[dict[str, Any]]:
    path: Path = journal_path(runs_dir, stamp)
    return state_for(path).events(path.name, kind)


def group_key(lanes: list[str]) -> str:
    """The name of a fold group: its lanes, sorted, joined with `+`. Stable however the group was found."""
    return "+".join(sorted(lanes))


def note_fold_plan(runs_dir: Path, stamp: str, groups: list[dict[str, Any]]) -> None:
    keys: list[str] = [group_key(g["lanes"]) for g in groups]
    note(runs_dir, stamp, KIND_FOLD_PLANNED, key="|".join(keys), groups=keys)


def fold_done(runs_dir: Path, stamp: str, group: str, pr: int | None) -> dict[str, Any]:
    """Record that a fold group's PR is shipped, so a fold run again after a crash skips it."""
    if inside_son():
        return son_refusal("fold-done")
    fresh: bool = note(runs_dir, stamp, KIND_FOLD_DONE, key=group, group=group, pr=pr)
    return {"ok": True, "stamp": stamp, "group": group, "recorded": fresh}


def done_groups(runs_dir: Path, stamp: str) -> set[str]:
    return {str(e.get("group")) for e in journal_events(runs_dir, stamp, KIND_FOLD_DONE)}


def resume_state(runs_dir: Path, stamp: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a head that died mid-way needs: lanes merged, the merge in flight, the fold groups still to ship and the lanes
    whose walkthrough failed."""
    saved: dict[str, Any] = state_for(runs_dir / stamp / MERGE_ORDER_NAME).read_record(MERGE_ORDER_NAME) or {}
    merged: list[str] = sorted({*[str(i) for i in saved.get("merged") or []],
                                *[str(e.get("lane")) for e in journal_events(runs_dir, stamp, KIND_MERGED)]})
    plans: list[dict[str, Any]] = journal_events(runs_dir, stamp, KIND_FOLD_PLANNED)
    planned: list[str] = [str(k) for k in plans[-1].get("groups") or []] if plans else []
    shipped: set[str] = done_groups(runs_dir, stamp)
    return {"merged": merged, "in_flight": saved.get("current"),
            "fold": {"planned": planned, "done": sorted(shipped & set(planned)),
                     "remaining": [k for k in planned if k not in shipped]},
            "walkthrough_failed": sorted({str(e.get("lane")) for e in journal_events(runs_dir, stamp, KIND_WALKTHROUGH_FAILED)}),
            "events": len(journal_events(runs_dir, stamp))}


def file_revert_item(cwd: Path, lane: str, reason: str) -> bool:
    """One action item telling the owner to revert the lane's merge; True when the item was filed."""
    text: str = f"Revert the merge of lane {lane}: its post-merge walkthrough failed ({reason})"
    code, out = run([sys.executable, str(ACTION_ITEMS), str(cwd), "add", REVERT_GROUP, text], cwd)
    return code == 0


def walkthrough_failed(runs_dir: Path, stamp: str, lane: str, reason: str, cwd: Path) -> dict[str, Any]:
    """Record a failed post-merge walkthrough and file the revert action item, once however often it is reported."""
    if inside_son():
        return son_refusal("walkthrough-failed")
    if not reason.strip():
        raise LaneError("--reason must say what the walkthrough found")
    fresh: bool = note(runs_dir, stamp, KIND_WALKTHROUGH_FAILED, lane=lane, key="", reason=reason, at=int(time.time()))
    already: bool = any(e.get("lane") == lane for e in journal_events(runs_dir, stamp, KIND_REVERT_FILED))
    filed: bool = not already and file_revert_item(cwd, lane, reason)
    if filed:
        note(runs_dir, stamp, KIND_REVERT_FILED, lane=lane, key="")
    return {"ok": True, "stamp": stamp, "lane": lane, "recorded": fresh, "revert_item_filed": filed}


def fix_attempt_cap(cwd: Path) -> int:
    """G-78: `post_merge_fix_attempts` (default 2); a value that is not a positive whole number reads as the default."""
    from .planner import read_setting  # noqa: PLC0415 - planner imports modules that import this one
    raw: str = read_setting(cwd, FIX_ATTEMPTS_FIELD, str(DEFAULT_FIX_ATTEMPTS))
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_FIX_ATTEMPTS


def revert_branch(stamp: str, lane: str) -> str:
    return f"revert/{stamp}-{lane}"


def lane_pr_number(runs_dir: Path, stamp: str, lane: str) -> int | None:
    pr: Any = read_json_object(runs_dir / stamp / lane / STATUS_NAME).get("pr")
    return pr if isinstance(pr, int) and not isinstance(pr, bool) else None


def merge_commit_of(pr: int, cwd: Path) -> str | None:
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "pr", "view", str(pr), "--json", "mergeCommit", "--jq", ".mergeCommit.oid"], cwd)
    return out.strip() if code == 0 and out.strip() else None


def existing_revert_pr(branch: str, cwd: Path) -> dict[str, Any] | None:
    """Check before act: an open PR already on the revert branch."""
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd)
    try:
        rows: Any = json.loads(out) if code == 0 else []
    except ValueError:
        return None
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None


def build_revert_branch(sha: str, branch: str, target: str, folder: Path, cwd: Path) -> str | None:
    """Revert `sha` on a fresh branch off origin/<target> (`-B` resets a branch left by an earlier failed try) in a temporary worktree and push it. None when it worked, else why not."""
    git: list[str] = binary("DTS2_GIT_BIN", "git")
    steps: list[tuple[list[str], Path]] = [([*git, "fetch", "origin", target], cwd),
                                           ([*git, "worktree", "add", "-B", branch, str(folder), f"origin/{target}"], cwd)]
    for cmd, where in steps:
        code, out = run(cmd, where)
        if code != 0:
            return f"{' '.join(cmd[len(git):][:2])} failed: {out.strip()[:200]}"
    code, parents = run([*git, "rev-list", "--parents", "-n", "1", sha], folder)
    mainline: list[str] = ["-m", "1"] if code == 0 and len(parents.split()) > 2 else []
    for cmd in ([*git, "revert", "--no-edit", *mainline, sha], [*git, "push", "--force-with-lease", "-u", "origin", branch]):
        code, out = run(cmd, folder)
        if code != 0:
            return f"git {cmd[len(git)]} failed: {out.strip()[:200]}"
    return None


def create_revert_pr(branch: str, target: str, lane: str, reason: str, cwd: Path) -> tuple[int | None, str]:
    title: str = f"Revert lane {lane}: post-merge walkthrough kept failing"
    body: str = f"Reverts the merge of lane {lane}. The post-merge fixes were capped and the walkthrough still failed ({reason})."
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "pr", "create", "--base", target, "--head", branch, "--title", title,
                     "--body", body], cwd)
    url: str = out.strip().splitlines()[-1] if code == 0 and out.strip() else ""
    tail: str = url.rsplit("/", 1)[-1]
    return (int(tail) if tail.isdigit() else None), url


def open_revert_pr(runs_dir: Path, stamp: str, lane: str, reason: str, cwd: Path) -> dict[str, Any]:
    """G-78: open the revert PR for a lane whose post-merge fixes hit the cap (once however often it is called). The head
    then merges it under the gate (`merge-go-step`) or parks the run; when the PR cannot be opened the existing revert
    action item is filed instead, so the owner always has the revert in front of them."""
    from .merge import merge_target_state  # noqa: PLC0415 - merge imports this module
    done: list[dict[str, Any]] = [e for e in journal_events(runs_dir, stamp, KIND_REVERT_PR) if e.get("lane") == lane]
    if done:
        return {"ok": True, "revert_pr": done[-1].get("pr"), "url": done[-1].get("url"), "already": True}
    target: str = merge_target_state(runs_dir, stamp, cwd)["target"]
    branch: str = revert_branch(stamp, lane)
    found: dict[str, Any] | None = existing_revert_pr(branch, cwd)
    pr: int | None = int(found["number"]) if found and isinstance(found.get("number"), int) else None
    url: str = str(found.get("url", "")) if found else ""
    why: str | None = None
    if found is None:
        landed: int | None = lane_pr_number(runs_dir, stamp, lane)
        sha: str | None = merge_commit_of(landed, cwd) if landed else None
        folder: Path = runs_dir / stamp / f"revert-{lane}"
        why = build_revert_branch(sha, branch, target, folder, cwd) if sha else f"no merge commit known for lane {lane}"
        if why is None:
            pr, url = create_revert_pr(branch, target, lane, reason, cwd)
            why = None if pr is not None else "gh pr create gave no PR number"
        run([*binary("DTS2_GIT_BIN", "git"), "worktree", "remove", "--force", str(folder)], cwd)
    if why is not None or pr is None:
        filed: bool = file_revert_item(cwd, lane, reason)
        return {"ok": False, "parked": True, "revert_item_filed": filed, "detail": f"revert PR not opened: {why}"}
    note(runs_dir, stamp, KIND_REVERT_PR, lane=lane, key="", pr=pr, url=url, branch=branch)
    return {"ok": True, "revert_pr": pr, "url": url, "already": False, "next": f"merge-go-step {stamp} --step revert-{lane}, or park"}


def fix_attempt(runs_dir: Path, stamp: str, lane: str, reason: str, cwd: Path) -> dict[str, Any]:
    """G-78: count one post-merge fix attempt for a lane. Up to `post_merge_fix_attempts` (default 2) the answer is `fix`;
    after that the revert PR is opened (`open_revert_pr`) and the head stops fixing."""
    if inside_son():
        return son_refusal("fix-attempt")
    if not reason.strip():
        raise LaneError("--reason must say what the walkthrough found")
    cap: int = fix_attempt_cap(cwd)
    used: int = len([e for e in journal_events(runs_dir, stamp, KIND_FIX_ATTEMPT) if e.get("lane") == lane])
    if used < cap:
        note(runs_dir, stamp, KIND_FIX_ATTEMPT, lane=lane, key=used + 1, attempt=used + 1, reason=reason)
        return {"ok": True, "stamp": stamp, "lane": lane, "action": "fix", "attempt": used + 1, "cap": cap}
    return {**open_revert_pr(runs_dir, stamp, lane, reason, cwd), "stamp": stamp, "lane": lane, "action": "revert",
            "attempt": used, "cap": cap}


def mark_superseded(runs_dir: Path, stamp: str, group: dict[str, Any], new_pr: int) -> list[dict[str, Any]]:
    """G-79: record `superseded_by` (the fold group) and the new PR on each original lane PR of the group."""
    rows: list[dict[str, Any]] = []
    for original in group.get("originals", []):
        pr: int = int(original["pr"])
        note(runs_dir, stamp, KIND_SUPERSEDED, lane=str(original["lane"]), key=pr, original_pr=pr, superseded_by=group["key"], new_pr=new_pr)
        rows.append({"lane": original["lane"], "original_pr": pr, "superseded_by": group["key"], "new_pr": new_pr})
    return rows


def close_superseded(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """G-79: close each superseded original PR with a link to the new one. Check, then act, then journal: a PR that is no
    longer open is only noted, and the comment and the close are one `gh pr close --comment` call, so a crash between
    them cannot leave a second comment behind."""
    if inside_son():
        return son_refusal("fold-close")
    closed: set[int] = {int(e["original_pr"]) for e in journal_events(runs_dir, stamp, KIND_ORIGINAL_CLOSED)}
    gh: list[str] = binary("DTS2_GH_BIN", "gh")
    results: list[dict[str, Any]] = []
    for event in journal_events(runs_dir, stamp, KIND_SUPERSEDED):
        pr: int = int(event["original_pr"])
        if pr in closed:
            continue
        code, state = run([*gh, "pr", "view", str(pr), "--json", "state", "--jq", ".state"], cwd)
        if code != 0:
            results.append({"original_pr": pr, "closed": False, "detail": "gh could not read the PR"})
            continue
        if state.strip() == PR_STATE_OPEN_WORD:
            text: str = f"Superseded by #{event['new_pr']} (fold group {event['superseded_by']}); closing this PR."
            code, _ = run([*gh, "pr", "close", str(pr), "--comment", text], cwd)
            if code != 0:
                results.append({"original_pr": pr, "closed": False, "detail": "gh pr close failed"})
                continue
        note(runs_dir, stamp, KIND_ORIGINAL_CLOSED, lane=str(event.get("lane")), key=pr, original_pr=pr, new_pr=event["new_pr"])
        results.append({"original_pr": pr, "closed": True, "new_pr": event["new_pr"]})
    return {"ok": all(r["closed"] for r in results), "stamp": stamp, "closed": results}
