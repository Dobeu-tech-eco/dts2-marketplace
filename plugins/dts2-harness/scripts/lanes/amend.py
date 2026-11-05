"""Amend one lane of a running manifest (G-29): change its files, dependencies or contracts, re-check the whole manifest, bump the
lease epoch and rewrite the son's brief. A bad decomposition is fixed here instead of by dropping the lane and starting over."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Final

from state_io import atomic_write

from plan_graph import blocking_for, graph_check, graph_lease

from .common import LEASE_NAME, LaneError, STATUS_NAME, TERMINAL_PHASES, find_lane, lane_files, load_manifest, norm
from .leases import lease_epoch, read_lease

BRIEF_NAME: Final[str] = "brief.md"
LIST_FIELDS: Final[tuple[str, ...]] = ("depends_on", "provides", "consumes", "stubbed_on", "merge_after", "tasks")
NO_CHANGE: Final[str] = "nothing to amend: pass --set-files, --add-files, --remove-files or a list field"


def split_list(raw: str | None) -> list[str] | None:
    """A comma-separated CLI value as a list; None when the flag was not given."""
    return None if raw is None else [part.strip() for part in raw.split(",") if part.strip()]


def amended_files(lane: dict[str, Any], changes: dict[str, Any]) -> list[str]:
    files: set[str] = {norm(f) for f in changes["set_files"]} if changes.get("set_files") is not None else set(lane_files(lane))
    files |= {norm(f) for f in changes.get("add_files") or []}
    files -= {norm(f) for f in changes.get("remove_files") or []}
    return sorted(files)


def apply_changes(lane: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """The lane with the changes applied. Only the fields named in `changes` move."""
    amended: dict[str, Any] = copy.deepcopy(lane)
    if any(changes.get(key) is not None for key in ("set_files", "add_files", "remove_files")):
        amended["files"] = amended_files(lane, changes)
    for field in LIST_FIELDS:
        if changes.get(field) is not None:
            amended[field] = list(changes[field])
    return amended


def settled(runs_dir: Path, stamp: str, lane_id: str) -> bool:
    """True when the lane's son already finished or parked: its checkout is no longer something to amend."""
    try:
        data: Any = json.loads((runs_dir / stamp / lane_id / STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("status") in TERMINAL_PHASES


def rewrite_brief(manifest: dict[str, Any], lane_id: str, epoch: int, runs_dir: Path, note: str) -> Path:
    import briefs  # lazy: briefs.py reads the same lane fields this module writes
    path: Path = runs_dir / str(manifest["stamp"]) / lane_id / BRIEF_NAME
    atomic_write(path, briefs.son_brief(manifest, lane_id, epoch) + f"\n## Amended\n{note}\n")
    return path


def amendment_note(epoch: int, before: set[str], after: set[str]) -> str:
    added, removed = sorted(after - before), sorted(before - after)
    return (f"- epoch {epoch} replaces every earlier epoch of this lane. Added: {', '.join(added) or 'none'}. "
            f"Removed: {', '.join(removed) or 'none'}. Work from this brief, not the earlier one.")


def amend_lane(manifest_path: Path, lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool, changes: dict[str, Any]) -> dict[str, Any]:
    """Re-check the manifest with the lane amended; only when the lane is clear does it write the manifest, take the lease at the
    next epoch and rewrite brief.md. On any refusal nothing changes."""
    if not any(value is not None for value in changes.values()):
        raise LaneError(NO_CHANGE)
    manifest: dict[str, Any] = load_manifest(manifest_path)
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    stamp: str = str(manifest.get("stamp"))
    if settled(runs_dir, stamp, lane_id):
        return {"ok": False, "lane": lane_id, "detail": "the lane is done or parked; re-plan it instead of amending", "conflicts": []}
    amended: dict[str, Any] = apply_changes(lane, changes)
    updated: dict[str, Any] = {**manifest, "lanes": [amended if x.get("id") == lane_id else x for x in manifest["lanes"]]}
    blocking: list[dict[str, Any]] = blocking_for(graph_check(updated, runs_dir, cwd, with_prs), lane_id)
    if blocking:
        return {"ok": False, "lane": lane_id, "conflicts": blocking, "detail": "the amended lane conflicts; the manifest is unchanged"}
    previous: int = lease_epoch(read_lease(runs_dir / stamp / lane_id / LEASE_NAME))
    leased: dict[str, Any] = graph_lease(updated, lane_id, runs_dir, cwd, with_prs)
    if not leased.get("ok"):
        return {**leased, "detail": leased.get("detail", "lease refused; the manifest is unchanged")}
    atomic_write(manifest_path, json.dumps(updated, indent=2) + "\n")
    note: str = amendment_note(int(leased["epoch"]), lane_files(lane), lane_files(amended))
    brief: Path = rewrite_brief(updated, lane_id, int(leased["epoch"]), runs_dir, note)
    return {"ok": True, "lane": lane_id, "epoch": leased["epoch"], "previous_epoch": previous, "files": sorted(lane_files(amended)),
            "brief": str(brief), "manifest": str(manifest_path), "conflicts": [],
            "next": "tell the son: resume it with the new brief; a release with the old epoch is now refused"}
