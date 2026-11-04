#!/usr/bin/env python3
"""Lane manifest tools for parallel autopilot: overlap check, lane leases, branch-name collision check, the son command line,
and the dpp head's helpers: plan (admission, spend, feasibility, --full selection), status, sendback, release, fold,
stop-check and report-check."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Final

RUNS_DIR: Final[str] = ".harness/runs"
MANIFEST_NAME: Final[str] = "lanes.json"
LEASE_NAME: Final[str] = "lease.json"
STATUS_CLOSED: Final[str] = "closed"
STATUS_ACTIVE: Final[str] = "active"
SCHEMA_PATTERNS: Final[tuple[str, ...]] = (
    "migrations/", "schema.", "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock",
    "poetry.lock", "uv.lock",
)
AREA_DEPTH: Final[int] = 2
KIND_FILES: Final[str] = "files"
KIND_SCHEMA: Final[str] = "schema"
KIND_IDS: Final[str] = "ids"
KIND_DEPENDS: Final[str] = "depends_on"
KIND_AREA: Final[str] = "area"
KIND_SCOPE: Final[str] = "scope"
BRANCH_PREFIX: Final[str] = "dts2"
HEAD_SUFFIX: Final[str] = "-dpp"
TIMEOUT_S: Final[int] = 30
GH_PR_FIELDS: Final[str] = "number,files"
MAX_LANES: Final[int] = 5
PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SETTINGS_FILE: Final[str] = ".claude/dts2-harness.local.md"
PERMISSION_FIELD: Final[str] = "son_permission_mode"
DEFAULT_PERMISSION_MODE: Final[str] = "bypassPermissions"
SON_MODEL: Final[str] = "opus"
SON_SKILL: Final[str] = "/dts2-harness:autopilot --son"
FRONTMATTER_FENCE: Final[str] = "---"
STATUS_NAME: Final[str] = "status.json"
LEDGER_NAME: Final[str] = "task-ledger.md"
SEND_BACK_NAME: Final[str] = "send-back-{n}.md"
SEND_BACK_GLOB: Final[str] = "send-back-*.md"
MAX_SEND_BACKS: Final[int] = 2
TIMEOUT_FIELD: Final[str] = "builder_timeout_min"
DEFAULT_TIMEOUT_MIN: Final[int] = 20
SECONDS_PER_MINUTE: Final[int] = 60
PHASE_DONE: Final[str] = "done"
PHASE_BLOCKED: Final[str] = "blocked"
PHASE_INCOMPLETE: Final[str] = "incomplete"
TERMINAL_PHASES: Final[frozenset[str]] = frozenset({PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE})
SETTLED_PHASES: Final[frozenset[str]] = frozenset({PHASE_DONE, PHASE_BLOCKED})
REASON_STALLED: Final[str] = "stalled"
SOURCE_DELEGATION: Final[str] = "delegation"
NONE_FOUND: Final[str] = "no further parallel work found"
PROFILE_PATH: Final[Path] = PLUGIN_ROOT / "profiles" / "agents" / "claude.json"
DEFAULT_TIER: Final[str] = "standard"
DEFAULT_BURN: Final[int] = 1
KIND_MAX: Final[str] = "max"
WILDCARD_LANE: Final[str] = "*"
LANE_HEADING: Final[re.Pattern[str]] = re.compile(r"^## Lane (\S+)\s*$")
RUN_HEADING: Final[re.Pattern[str]] = re.compile(r"^## (.+?)\s*$")
SECTION_HEADING: Final[re.Pattern[str]] = re.compile(r"^### (.+?)\s*$")
LEDGER_ROW: Final[re.Pattern[str]] = re.compile(r"^\| (\d+) \|", re.M)
LANE_SECTIONS: Final[tuple[str, ...]] = (
    "Item", "Plan", "PR", "Models", "Votes", "Findings", "Send-backs", "New rows", "Docs", "Lessons", "Open risks",
    "Post-merge walkthrough",
)
RUN_SECTIONS: Final[tuple[str, ...]] = ("Spend", "Task ledger")
REPORT_SECTIONS: Final[tuple[str, ...]] = LANE_SECTIONS + RUN_SECTIONS


class LaneError(Exception):
    """Raised on a malformed manifest or an unknown lane."""


def binary(name: str, default: str) -> list[str]:
    value: str = os.environ.get(name, default)
    if value.endswith(".py"):
        return [sys.executable, value]
    return [shutil.which(value) or value]


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    return done.returncode, done.stdout or ""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"cannot read manifest {path}: {exc}") from exc
    lanes: Any = data.get("lanes") if isinstance(data, dict) else None
    if not isinstance(lanes, list) or not lanes:
        raise LaneError("manifest has no lanes")
    if len(lanes) > MAX_LANES:
        raise LaneError(f"manifest has {len(lanes)} lanes; the limit is {MAX_LANES}")
    return data


def norm(path: str) -> str:
    """Forward slashes, no leading ./; keeps ../ so scope checks can see an escape."""
    posix: str = path.replace("\\", "/")
    return posix[2:] if posix.startswith("./") else posix


def lane_files(lane: dict[str, Any]) -> set[str]:
    return {norm(str(f)) for f in lane.get("files", []) if f}


def lane_ids(lane: dict[str, Any]) -> set[str]:
    groups: dict[str, Any] = lane.get("ids") or {}
    return {str(i) for ids in groups.values() for i in (ids or [])}


def is_schema_file(path: str) -> bool:
    name: str = PurePosixPath(path).name
    return any(
        (p.endswith("/") and p in f"{path}/") or (p.endswith(".") and name.startswith(p))
        or (not p.endswith(("/", ".")) and fnmatch.fnmatch(name, p))
        for p in SCHEMA_PATTERNS
    )


def area_of(path: str) -> str | None:
    parts: tuple[str, ...] = PurePosixPath(path).parts
    return "/".join(parts[:AREA_DEPTH]) if len(parts) > AREA_DEPTH else None


def conflict(lane: str, other: str, kind: str, detail: str, alternative: str | None) -> dict[str, Any]:
    return {"lane": lane, "with": other, "kind": kind, "detail": detail, "alternative": alternative}


def escapes_scope(path: str, scope_root: Path) -> bool:
    if path.startswith("../") or path == "..":
        return True
    candidate: Path = Path(path)
    if not candidate.is_absolute():
        return False
    try:
        candidate.resolve().relative_to(scope_root.resolve())
    except ValueError:
        return True
    return False


def scope_conflicts(lane: dict[str, Any], scope_root: str | None) -> list[dict[str, Any]]:
    if not scope_root:
        return []
    root: Path = Path(scope_root)
    return [
        conflict(lane["id"], "scope_root", KIND_SCOPE, f"{f} is outside {scope_root}",
                 "drop the file or run dpp from the workspace root that owns it")
        for f in sorted(lane_files(lane)) if escapes_scope(f, root)
    ]


def pair_conflicts(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    shared: list[str] = sorted(lane_files(a) & lane_files(b))
    if shared:
        found.append(conflict(a["id"], b["id"], KIND_FILES, f"both own {', '.join(shared)}",
                              f"give {shared[0]} to one lane, or run {b['id']} after {a['id']}"))
    schema_a: list[str] = sorted(f for f in lane_files(a) if is_schema_file(f))
    schema_b: list[str] = sorted(f for f in lane_files(b) if is_schema_file(f))
    if schema_a and schema_b and not shared:
        found.append(conflict(a["id"], b["id"], KIND_SCHEMA, f"{schema_a[0]} and {schema_b[0]} share one schema or lockfile",
                              f"serialize: run {b['id']} after {a['id']} merges"))
    ids: list[str] = sorted(lane_ids(a) & lane_ids(b))
    if ids:
        found.append(conflict(a["id"], b["id"], KIND_IDS, f"both reserve {', '.join(ids)}",
                              "reserve ids again through action-items.py reserve"))
    found.extend(dependency_conflicts(a, b))
    if not shared:
        found.extend(area_conflicts(a, b))
    return found


def dependency_conflicts(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for first, second in ((a, b), (b, a)):
        if second["id"] in (first.get("depends_on") or []):
            found.append(conflict(first["id"], second["id"], KIND_DEPENDS,
                                  f"{first['id']} needs {second['id']}'s output",
                                  f"start {first['id']} after {second['id']} merges"))
    return found


def area_conflicts(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    areas_a: set[str] = {area for area in map(area_of, lane_files(a)) if area}
    areas_b: set[str] = {area for area in map(area_of, lane_files(b)) if area}
    shared: list[str] = sorted(areas_a & areas_b)
    if not shared:
        return []
    return [conflict(a["id"], b["id"], KIND_AREA, f"both work under {shared[0]}/",
                     f"merge {a['id']} first and rebase {b['id']} before its verifier, or split the area")]


def open_pr_files(cwd: Path) -> list[tuple[str, set[str]]] | None:
    """[(\"pr#12\", files)] for open PRs, or None when gh is unavailable."""
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "pr", "list", "--state", "open", "--json", GH_PR_FIELDS], cwd)
    if code != 0:
        return None
    try:
        prs: Any = json.loads(out or "[]")
    except ValueError:
        return None
    return [(f"pr#{pr.get('number')}", {norm(str(f.get("path", f))) for f in (pr.get("files") or [])})
            for pr in prs if isinstance(pr, dict)]


def active_run_files(runs_dir: Path, stamp: str) -> list[tuple[str, set[str]]]:
    """Files owned by lanes of other runs whose manifest is not closed."""
    found: list[tuple[str, set[str]]] = []
    for manifest in sorted(runs_dir.glob(f"*/{MANIFEST_NAME}")):
        try:
            data: Any = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("stamp") == stamp or data.get("status") == STATUS_CLOSED:
            continue
        files: set[str] = set().union(*(lane_files(lane) for lane in data.get("lanes", []))) if data.get("lanes") else set()
        found.append((f"run:{data.get('stamp')}", files))
    return found


def external_conflicts(lane: dict[str, Any], sources: list[tuple[str, set[str]]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for label, files in sources:
        shared: list[str] = sorted(lane_files(lane) & files)
        if shared:
            found.append(conflict(lane["id"], label, KIND_FILES, f"{label} already touches {', '.join(shared)}",
                                  f"wait for {label} to merge or close, then re-run check"))
    return found


def external_sources(runs_dir: Path, stamp: str, cwd: Path, with_prs: bool) -> tuple[list[tuple[str, set[str]]], bool]:
    """Open PRs plus other active runs; the flag says whether gh answered."""
    prs: list[tuple[str, set[str]]] | None = open_pr_files(cwd) if with_prs else []
    return (prs or []) + active_run_files(runs_dir, stamp), prs is not None


def assess(manifest: dict[str, Any], sources: list[tuple[str, set[str]]], prs_checked: bool) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = manifest["lanes"]
    conflicts: list[dict[str, Any]] = []
    for lane in lanes:
        conflicts.extend(scope_conflicts(lane, manifest.get("scope_root")))
    for index, lane in enumerate(lanes):
        for other in lanes[index + 1:]:
            conflicts.extend(pair_conflicts(lane, other))
    for lane in lanes:
        conflicts.extend(external_conflicts(lane, sources))
    return {"ok": not conflicts, "conflicts": conflicts, "prs_checked": prs_checked, "lanes": len(lanes)}


def check(manifest: dict[str, Any], runs_dir: Path, cwd: Path, with_prs: bool = True) -> dict[str, Any]:
    sources, prs_checked = external_sources(runs_dir, str(manifest.get("stamp")), cwd, with_prs)
    return assess(manifest, sources, prs_checked)


def find_lane(manifest: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in manifest["lanes"]:
        if lane.get("id") == lane_id:
            return lane
    raise LaneError(f"unknown lane '{lane_id}'")


def lease(manifest: dict[str, Any], lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool) -> dict[str, Any]:
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    result: dict[str, Any] = check(manifest, runs_dir, cwd, with_prs)
    blocking: list[dict[str, Any]] = [c for c in result["conflicts"] if lane_id in (c["lane"], c["with"])]
    if blocking:
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": blocking}
    stamp: str = str(manifest.get("stamp"))
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"stamp": stamp, "lane": lane_id, "status": STATUS_ACTIVE, "created": int(time.time()),
                              "base": manifest.get("base"), "files": sorted(lane_files(lane)),
                              "ids": sorted(lane_ids(lane))}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "lane": lane_id, "lease": str(path), "conflicts": []}


def planned_refs(stamp: str, lanes: list[str]) -> list[str]:
    return [f"{BRANCH_PREFIX}/{stamp}{HEAD_SUFFIX}", *(f"{BRANCH_PREFIX}/{stamp}/{lane}" for lane in lanes)]


def existing_refs(cwd: Path) -> list[str]:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "for-each-ref", "--format=%(refname:short)", "refs/heads",
                     "refs/remotes"], cwd)
    if code != 0:
        return []
    return [line.split("/", 1)[1] if line.startswith("origin/") else line for line in out.splitlines() if line.strip()]


def ref_collides(planned: str, existing: str) -> bool:
    return planned == existing or existing.startswith(planned + "/") or planned.startswith(existing + "/")


def branch_check(stamp: str, lanes: list[str], cwd: Path) -> dict[str, Any]:
    planned: list[str] = planned_refs(stamp, lanes)
    present: list[str] = existing_refs(cwd)
    collisions: list[dict[str, str]] = [
        {"planned": p, "existing": e, "detail": "a ref cannot be both a branch and a directory of branches"}
        for p in planned for e in present if ref_collides(p, e)
    ]
    return {"ok": not collisions, "planned": planned, "collisions": collisions}


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


def son_command(manifest: dict[str, Any], lane_id: str, worktree: Path, cwd: Path) -> dict[str, Any]:
    """The headless command the head runs for one son: claude -p inside the lane's worktree."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    mode: str = read_setting(cwd, PERMISSION_FIELD, DEFAULT_PERMISSION_MODE)
    argv: list[str] = binary("DTS2_CLAUDE_BIN", "claude") + [
        "-p", f"{SON_SKILL} {manifest['stamp']}/{lane['id']}",
        "--permission-mode", mode, "--model", SON_MODEL, "--plugin-dir", str(PLUGIN_ROOT),
    ]
    return {"ok": True, "lane": lane["id"], "cwd": str(worktree), "permission_mode": mode, "argv": argv}


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


def active_lease_files(runs_dir: Path, stamp: str) -> list[tuple[str, set[str]]]:
    """Files held by this run's active leases, so a new lane never overlaps a son still building."""
    found: list[tuple[str, set[str]]] = []
    for path in sorted((runs_dir / stamp).glob(f"*/{LEASE_NAME}")):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("status") == STATUS_ACTIVE:
            found.append((f"lane {stamp}/{data.get('lane') or path.parent.name}",
                          {norm(str(f)) for f in data.get("files", [])}))
    return found


def reported_row(lane: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"lane": lane.get("id"), "item": lane.get("item"), "reasons": reasons}


def select_lanes(draft: dict[str, Any], candidates: list[dict[str, Any]], sources: list[tuple[str, set[str]]],
                 cap: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedy --full selection: keep a lane only while the set stays conflict-free; never pad past the cap."""
    selected: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    for lane in candidates:
        if len(selected) >= cap:
            reported.append(reported_row(lane, [f"{KIND_MAX}: lane cap of {cap} reached"]))
            continue
        trial: dict[str, Any] = assess({**draft, "lanes": [*selected, lane]}, sources, True)
        blocking: list[dict[str, Any]] = [c for c in trial["conflicts"] if lane.get("id") in (c["lane"], c["with"])]
        if blocking:
            reported.append(reported_row(lane, [f"{c['kind']}: {c['detail']}" for c in blocking]))
        else:
            selected.append(lane)
    return selected, reported


def plan(draft: dict[str, Any], outstanding: set[str], outside: str, full: bool, cap: int, runs_dir: Path, cwd: Path,
         with_prs: bool) -> dict[str, Any]:
    stamp: str = str(draft.get("stamp"))
    sources, prs_checked = external_sources(runs_dir, stamp, cwd, with_prs)
    sources = sources + active_lease_files(runs_dir, stamp)
    candidates: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for lane in draft["lanes"]:
        kept, refusal = admit_lane(lane, outstanding, outside, full)
        candidates.append(kept) if kept is not None else refused.append(refusal)
    selected, reported = select_lanes(draft, candidates, sources, cap) if full else (candidates, [])
    manifest: dict[str, Any] = {**draft, "lanes": selected}
    feasibility: dict[str, Any] = assess(manifest, sources, prs_checked)
    result: dict[str, Any] = {"ok": bool(selected) and not refused and feasibility["ok"], "stamp": stamp,
                              "manifest": manifest, "feasibility": feasibility, "refused": refused, "reported": reported}
    if full and len(selected) < cap:
        result["note"] = NONE_FOUND
    return result


def read_status_files(runs_dir: Path, stamp: str) -> list[tuple[Path, dict[str, Any]]]:
    run_dir: Path = runs_dir / stamp
    if not run_dir.is_dir():
        raise LaneError(f"no run at {run_dir}")
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(run_dir.glob(f"*/{STATUS_NAME}")):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaneError(f"unreadable {path}: {exc}") from exc
        found.append((path, data if isinstance(data, dict) else {}))
    return found


def stale_after(cwd: Path) -> int:
    raw: str = read_setting(cwd, TIMEOUT_FIELD, str(DEFAULT_TIMEOUT_MIN))
    minutes: int = int(raw) if raw.isdigit() else DEFAULT_TIMEOUT_MIN
    return minutes * SECONDS_PER_MINUTE


def lane_status(path: Path, data: dict[str, Any], threshold: int, now: int) -> dict[str, Any]:
    phase: str = str(data.get("status", ""))
    updated: int = int(path.stat().st_mtime)
    stale: bool = phase not in TERMINAL_PHASES and now - updated > threshold
    return {"lane": str(data.get("lane") or path.parent.name), "phase": phase, "updated": updated, "stale": stale,
            "incomplete_reason": REASON_STALLED if stale else None}


def status(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Every son's phase from status.json; a quiet non-terminal son past builder_timeout_min is stalled (autopilot §4)."""
    threshold: int = stale_after(cwd)
    now: int = int(time.time())
    lanes: list[dict[str, Any]] = [lane_status(p, d, threshold, now) for p, d in read_status_files(runs_dir, stamp)]
    return {"ok": True, "stamp": stamp, "stale_after_s": threshold, "lanes": lanes}


def sendback(runs_dir: Path, stamp: str, lane_id: str, reason: str) -> dict[str, Any]:
    folder: Path = runs_dir / stamp / lane_id
    folder.mkdir(parents=True, exist_ok=True)
    count: int = len(list(folder.glob(SEND_BACK_GLOB)))
    if count >= MAX_SEND_BACKS:
        return {"ok": False, "lane": lane_id, "count": count, "path": None,
                "detail": f"{MAX_SEND_BACKS} send-backs already used; the lane ends incomplete"}
    path: Path = folder / SEND_BACK_NAME.format(n=count + 1)
    path.write_text(f"# Send-back {count + 1} for lane {lane_id}\n\n{reason}\n", encoding="utf-8")
    return {"ok": True, "lane": lane_id, "count": count + 1, "path": str(path)}


def release(runs_dir: Path, stamp: str, lane_id: str) -> dict[str, Any]:
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    try:
        record: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"no lease at {path}: {exc}") from exc
    closed: dict[str, Any] = {**record, "status": STATUS_CLOSED, "released": int(time.time())}
    path.write_text(json.dumps(closed, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "lane": lane_id, "lease": str(path), "status": STATUS_CLOSED}


def add_to_group(group: dict[str, Any], data: dict[str, Any], files: set[str]) -> None:
    group["lanes"].append(str(data.get("lane")))
    group["tasks"].extend(str(t) for t in data.get("tasks", []))
    group["blocked_by"] = sorted(set(group["blocked_by"]) | {str(i) for i in data.get("blocked_by", [])})
    if isinstance(data.get("pr"), int):
        group["prs"].append(data["pr"])
    group["_files"] |= files


def fold(runs_dir: Path, stamp: str) -> dict[str, Any]:
    """Group blocked lanes with disjoint files so they ship on the fewest PRs; never splits a lane."""
    groups: list[dict[str, Any]] = []
    for _, data in read_status_files(runs_dir, stamp):
        if data.get("status") != PHASE_BLOCKED:
            continue
        files: set[str] = {norm(str(f)) for f in data.get("files", [])}
        target: dict[str, Any] | None = next((g for g in groups if not (g["_files"] & files)), None)
        if target is None:
            target = {"lanes": [], "tasks": [], "blocked_by": [], "prs": [], "_files": set()}
            groups.append(target)
        add_to_group(target, data, files)
    public: list[dict[str, Any]] = [{k: v for k, v in g.items() if not k.startswith("_")} for g in groups]
    return {"ok": True, "stamp": stamp, "groups": public, "open_prs": len(public)}


def ledger_prs(runs_dir: Path, stamp: str) -> set[int]:
    path: Path = runs_dir / stamp / LEDGER_NAME
    if not path.is_file():
        return set()
    return {int(m.group(1)) for m in LEDGER_ROW.finditer(path.read_text(encoding="utf-8"))}


def stop_check(runs_dir: Path, stamp: str, checkin: Path) -> dict[str, Any]:
    """fullauto may stop only when check-in has nothing outstanding and every lane is done or blocked in the ledger."""
    outstanding: list[str] = sorted(read_checkin(checkin))
    lanes: list[dict[str, Any]] = [d for _, d in read_status_files(runs_dir, stamp)]
    ledgered: set[int] = ledger_prs(runs_dir, stamp)
    blocked_without: list[str] = sorted(str(d.get("lane")) for d in lanes
                                        if d.get("status") == PHASE_BLOCKED and d.get("pr") not in ledgered)
    active: list[str] = sorted(str(d.get("lane")) for d in lanes if d.get("status") not in SETTLED_PHASES)
    stop: bool = not outstanding and not active and not blocked_without
    return {"ok": True, "stamp": stamp, "stop": stop, "outstanding": outstanding, "active": active,
            "blocked_without_ledger": blocked_without, "lanes": len(lanes)}


def report_sections(text: str) -> tuple[dict[str, set[str]], set[str]]:
    """({lane: {### names}}, {## names}) from a dpp-report.md, names lower-cased."""
    lanes: dict[str, set[str]] = {}
    run: set[str] = set()
    current: str | None = None
    for line in text.splitlines():
        lane_match = LANE_HEADING.match(line)
        run_match = RUN_HEADING.match(line)
        section_match = SECTION_HEADING.match(line)
        if lane_match:
            current = lane_match.group(1)
            lanes.setdefault(current, set())
        elif run_match:
            current = None
            run.add(run_match.group(1).lower())
        elif section_match and current is not None:
            lanes[current].add(section_match.group(1).lower())
    return lanes, run


def has_section(found: set[str], wanted: str) -> bool:
    return any(name.startswith(wanted.lower()) for name in found)


def report_check(path: Path, lane_ids: list[str]) -> dict[str, Any]:
    try:
        text: str = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaneError(f"cannot read report {path}: {exc}") from exc
    lanes, run = report_sections(text)
    missing: list[dict[str, str]] = [{"lane": lane_id, "section": s} for lane_id in lane_ids for s in LANE_SECTIONS
                                     if not has_section(lanes.get(lane_id, set()), s)]
    missing += [{"lane": WILDCARD_LANE, "section": s} for s in RUN_SECTIONS if not has_section(run, s)]
    return {"ok": not missing, "report": str(path), "missing": missing}


def split_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def add_run_parsers(sub: Any) -> None:
    """Subcommands keyed by run stamp, for the dpp head."""
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--from-checkin", required=True, help="check-in.py --json output")
    plan_p.add_argument("--draft", required=True, help="draft lanes.json")
    plan_p.add_argument("--outside", default="", help="'<item>: <why>' marks admitted outside check-in")
    plan_p.add_argument("--full", action="store_true", help="dpp-full: greedy fill, delegation lanes allowed")
    plan_p.add_argument("--max", type=int, default=MAX_LANES)
    plan_p.add_argument("--stamp", default=None)
    sub.add_parser("status").add_argument("stamp")
    for name in ("sendback", "release"):
        lane_p = sub.add_parser(name)
        lane_p.add_argument("stamp")
        lane_p.add_argument("--lane", required=True)
        if name == "sendback":
            lane_p.add_argument("--reason", required=True)
    sub.add_parser("fold").add_argument("stamp")
    stop_p = sub.add_parser("stop-check")
    stop_p.add_argument("stamp")
    stop_p.add_argument("--from-checkin", required=True)
    report_p = sub.add_parser("report-check")
    report_p.add_argument("report")
    report_p.add_argument("--lanes", required=True, help="comma-separated lane ids")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--no-prs", action="store_true", help="skip the open-PR file check")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("manifest")
    lease_p = sub.add_parser("lease")
    lease_p.add_argument("manifest")
    lease_p.add_argument("--lane", required=True)
    branch_p = sub.add_parser("branch-check")
    branch_p.add_argument("stamp")
    branch_p.add_argument("--lanes", required=True, help="comma-separated lane ids")
    son_p = sub.add_parser("son-command")
    son_p.add_argument("manifest")
    son_p.add_argument("--lane", required=True)
    son_p.add_argument("--worktree", required=True)
    add_run_parsers(sub)
    return parser


def dispatch_plan(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any]:
    draft: dict[str, Any] = load_draft(Path(args.draft))
    if args.stamp:
        draft = {**draft, "stamp": args.stamp}
    return plan(draft, read_checkin(Path(args.from_checkin)), args.outside, args.full, args.max, runs_dir, cwd,
                not args.no_prs)


def dispatch_run(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any] | None:
    """The stamp-keyed and report subcommands; None when the command needs a manifest."""
    if args.command == "plan":
        return dispatch_plan(args, runs_dir, cwd)
    if args.command == "status":
        return status(runs_dir, args.stamp, cwd)
    if args.command == "sendback":
        return sendback(runs_dir, args.stamp, args.lane, args.reason)
    if args.command == "release":
        return release(runs_dir, args.stamp, args.lane)
    if args.command == "fold":
        return fold(runs_dir, args.stamp)
    if args.command == "stop-check":
        return stop_check(runs_dir, args.stamp, Path(args.from_checkin))
    if args.command == "report-check":
        return report_check(Path(args.report), split_ids(args.lanes))
    if args.command == "branch-check":
        return branch_check(args.stamp, split_ids(args.lanes), cwd)
    return None


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cwd: Path = Path(args.cwd)
    runs_dir: Path = Path(args.runs_dir) if Path(args.runs_dir).is_absolute() else cwd / args.runs_dir
    handled: dict[str, Any] | None = dispatch_run(args, runs_dir, cwd)
    if handled is not None:
        return handled
    manifest: dict[str, Any] = load_manifest(Path(args.manifest))
    if args.command == "lease":
        return lease(manifest, args.lane, runs_dir, cwd, not args.no_prs)
    if args.command == "son-command":
        return son_command(manifest, args.lane, Path(args.worktree), cwd)
    return check(manifest, runs_dir, cwd, not args.no_prs)


def main() -> int:
    args = build_parser().parse_args()
    try:
        result: dict[str, Any] = dispatch(args)
    except LaneError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
