"""Son command line, admission, spend estimates and the plan command."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from model_call import (
    read_budget, read_supervisor,
)
from proc import fallback_flags, wrap_son
from son_launch import launch_flags, son_env

from .integration import shared_patterns
from .common import DEFAULT_BURN, DEFAULT_PERMISSION_MODE, DEFAULT_TIER, FRONTMATTER_FENCE, KIND_MAX, LEASE_NAME, LaneError, NONE_FOUND, PERMISSION_FIELD, PLUGIN_ROOT, PROFILE_PATH, SETTINGS_FILE, SON_SKILL, SOURCE_DELEGATION, binary, find_lane, lease_live, norm, son_model
from .conflicts import assess, external_sources
from .gitrefs import gh_down
from .leases import held_items


def read_setting(cwd: Path, field: str, default: str) -> str:
    """Read one scalar from the frontmatter of .claude/dts2-harness.local.md, the way hooks/lib-settings.sh does."""
    path: Path = cwd / SETTINGS_FILE
    if not path.is_file():
        return default
    inside: bool = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == FRONTMATTER_FENCE:
            if inside:
                break
            inside = True
            continue
        match = re.match(rf"^{re.escape(field)}: *(.*?)\s*(#.*)?$", line) if inside else None
        if match:
            return match.group(1).strip().strip("\"'") or default
    return default


def cap_flags(cwd: Path, remaining_usd: float | None, session: str | None) -> list[str]:
    """The cap and resilience flags every son gets: turns, JSON usage output, fallback chain, spend left, resume."""
    caps: dict[str, Any] = read_budget(cwd)
    chain: list[str] = read_supervisor(cwd)["fallback_models"]
    flags: list[str] = ["--max-turns", str(caps["max_turns"]), "--output-format", "json"]
    flags += fallback_flags(chain)  # a comma-separated chain tried in order, at most 3 models
    if caps["max_usd"] is not None and remaining_usd is not None:
        flags += ["--max-budget-usd", f"{max(remaining_usd, 0.01):.2f}"]
    if session:
        flags += ["--resume", session]
    return flags


def son_command(manifest: dict[str, Any], lane_id: str, worktree: Path, cwd: Path,
                remaining_usd: float | None = None, session: str | None = None, lane_dir: Path | None = None) -> dict[str, Any]:
    """The headless command for one son: claude -p inside the lane's worktree, with the budget caps and fallback chain, on the
    `son_model` setting. With `lane_dir` the argv is wrapped by proc.wrap_son (session id, stream-json, son.json)."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    mode: str = read_setting(cwd, PERMISSION_FIELD, DEFAULT_PERMISSION_MODE)
    argv: list[str] = binary("DTS2_CLAUDE_BIN", "claude") + [
        "-p", f"{SON_SKILL} {manifest['stamp']}/{lane['id']}",
        *launch_flags(cwd, mode, manifest, str(lane["id"]), worktree), "--model", son_model(cwd), "--plugin-dir", str(PLUGIN_ROOT),
        *cap_flags(cwd, remaining_usd, session),
    ]
    if lane_dir is not None:
        argv = wrap_son(argv, lane_dir)
    return {"ok": True, "lane": lane["id"], "cwd": str(worktree), "permission_mode": mode, "argv": argv,
            "env": son_env(manifest, str(lane["id"]), cwd)}


def load_draft(path: Path) -> dict[str, Any]:
    """A draft manifest for plan: same shape as load_manifest, but plan applies the lane cap itself."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"cannot read draft {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("lanes"), list) or not data["lanes"]:
        raise LaneError("draft has no lanes")
    return data


def read_checkin(path: Path) -> set[str]:
    """The outstanding item names from check-in.py --json."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"cannot read check-in {path}: {exc}") from exc
    return {str(i) for i in (data.get("outstanding_items") or [])} if isinstance(data, dict) else set()


def token_burn(tier: str) -> int:
    try:
        profile: Any = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return int(profile["tokenBurn"][tier])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_BURN


def estimated_spend(lane: dict[str, Any]) -> dict[str, Any]:
    """tier x tokenBurn x tasks, the number the head reports under ## Spend."""
    tier: str = str(lane.get("tier") or DEFAULT_TIER)
    tasks: int = max(1, len(lane.get("tasks") or []))
    burn: int = token_burn(tier)
    return {"tier": tier, "burn": burn, "tasks": tasks, "total": burn * tasks}


def names_item(text: str, item: str) -> bool:
    return bool(item) and re.search(rf"(?<!\w){re.escape(item)}(?!\w)", text) is not None


def admit_lane(lane: dict[str, Any], outstanding: set[str], outside: str, full: bool) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(lane with spend and marks, None) when admitted, (None, refusal row) otherwise."""
    item: str = str(lane.get("item", ""))
    marked: dict[str, Any] = {**lane, "estimated_spend": estimated_spend(lane)}
    if item in outstanding or (full and lane.get("source") == SOURCE_DELEGATION):
        return marked, None
    if names_item(outside, item):
        return {**marked, "outside_checkin": True}, None
    return None, {"lane": lane.get("id"), "item": item,
                  "reason": "not outstanding in check-in; pass --outside \"<item>: <why>\" to admit it"}


def active_lease_files(runs_dir: Path, stamp: str, now: int | None = None) -> list[tuple[str, set[str]]]:
    """Files held by this run's live leases (active and not expired), so a new lane never overlaps a son still building."""
    found: list[tuple[str, set[str]]] = []
    clock: int = int(time.time()) if now is None else now
    for path in sorted((runs_dir / stamp).glob(f"*/{LEASE_NAME}")):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and lease_live(data, clock):
            found.append((f"lane {stamp}/{data.get('lane') or path.parent.name}",
                          {norm(str(f)) for f in data.get("files", [])}))
    return found


def reported_row(lane: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"lane": lane.get("id"), "item": lane.get("item"), "reasons": reasons}


def select_lanes(draft: dict[str, Any], candidates: list[dict[str, Any]], sources: list[tuple[str, set[str]]],
                 cap: int, shared: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedy --full selection: keep a lane only while the set stays conflict-free; never pad past the cap."""
    selected: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    for lane in candidates:
        if len(selected) >= cap:
            reported.append(reported_row(lane, [f"{KIND_MAX}: lane cap of {cap} reached"]))
            continue
        trial: dict[str, Any] = assess({**draft, "lanes": [*selected, lane]}, sources, True, shared)
        blocking: list[dict[str, Any]] = [c for c in trial["conflicts"]
                                          if lane.get("id") in (c["lane"], c["with"]) and not c.get("routed")]
        if blocking:
            reported.append(reported_row(lane, [f"{c['kind']}: {c['detail']}" for c in blocking]))
        else:
            selected.append(lane)
    return selected, reported


def plan(draft: dict[str, Any], outstanding: set[str], outside: str, full: bool, cap: int, runs_dir: Path, cwd: Path,
         with_prs: bool, frozen: set[str] | None = None) -> dict[str, Any]:
    """`frozen` is the fullauto scope: a lane whose item is not in it is left out before the cap and conflict selection, so
    an out-of-scope lane never takes a place from an in-scope one; its item is returned in `out_of_scope` (recorded as pending)."""
    stamp: str = str(draft.get("stamp"))
    sources, prs_checked = external_sources(runs_dir, stamp, cwd, with_prs)
    sources = sources + active_lease_files(runs_dir, stamp)
    candidates: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    held: dict[str, str] = held_items(runs_dir)
    out_of_scope: list[str] = []
    for lane in draft["lanes"]:
        if frozen is not None and str(lane.get("item", "")) not in frozen:
            out_of_scope.append(str(lane.get("item", "")))
            continue
        holder: str | None = held.get(str(lane.get("item", "")))
        if holder is not None and holder != f"{stamp}/{lane.get('id')}":  # G-47: another live lease already holds this item
            refused.append({"lane": lane.get("id"), "item": lane.get("item"), "reason": f"item held by the live lease of lane {holder}"})
            continue
        kept, refusal = admit_lane(lane, outstanding, outside, full)
        candidates.append(kept) if kept is not None else refused.append(refusal)
    selected, reported = select_lanes(draft, candidates, sources, cap, shared_patterns(cwd)) if full else (candidates, [])
    manifest: dict[str, Any] = {**draft, "lanes": selected}
    feasibility: dict[str, Any] = assess(manifest, sources, prs_checked, shared_patterns(cwd))
    result: dict[str, Any] = {"ok": bool(selected) and not refused and feasibility["ok"], "stamp": stamp,
                              "manifest": manifest, "feasibility": feasibility, "refused": refused, "reported": reported}
    if out_of_scope:
        result["out_of_scope"] = out_of_scope
    if with_prs and not prs_checked:  # fail closed: without gh the open-PR overlap check did not happen
        result = {**result, "ok": False, "detail": gh_down("plan")}
    if full and len(selected) < cap:
        result["note"] = NONE_FOUND
    return result
