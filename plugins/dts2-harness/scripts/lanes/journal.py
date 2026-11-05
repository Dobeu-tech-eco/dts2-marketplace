"""G-15: the per-run merge journal. `merge-journal.jsonl` holds one event row for each step of the fold and the merge
(a grant, a merge done, a fold plan, a fold group shipped, a failed walkthrough), each with a stable id, so a head that
dies half way reads it and carries on instead of starting over. A failed post-merge walkthrough also files one revert
action item (never two)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Final

from state_ids import InvalidId
from state_io import event_id, make_event

from .common import LaneError, MERGE_JOURNAL_NAME, MERGE_ORDER_NAME, PLUGIN_ROOT, run
from .records import inside_son, son_refusal, state_for

KIND_GRANTED: Final[str] = "merge-granted"
KIND_MERGED: Final[str] = "merge-done"
KIND_RECOVERED: Final[str] = "merge-recovered"
KIND_FOLD_PLANNED: Final[str] = "fold-planned"
KIND_FOLD_DONE: Final[str] = "fold-group-done"
KIND_WALKTHROUGH_FAILED: Final[str] = "walkthrough-failed"
KIND_REVERT_FILED: Final[str] = "revert-filed"
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
