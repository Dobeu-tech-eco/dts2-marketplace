#!/usr/bin/env python3
"""Lane manifest tools for parallel autopilot: overlap check, lane leases, and branch-name collision check."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
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


def check(manifest: dict[str, Any], runs_dir: Path, cwd: Path, with_prs: bool = True) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = manifest["lanes"]
    conflicts: list[dict[str, Any]] = []
    for lane in lanes:
        conflicts.extend(scope_conflicts(lane, manifest.get("scope_root")))
    for index, lane in enumerate(lanes):
        for other in lanes[index + 1:]:
            conflicts.extend(pair_conflicts(lane, other))
    prs: list[tuple[str, set[str]]] | None = open_pr_files(cwd) if with_prs else []
    sources: list[tuple[str, set[str]]] = (prs or []) + active_run_files(runs_dir, str(manifest.get("stamp")))
    for lane in lanes:
        conflicts.extend(external_conflicts(lane, sources))
    return {"ok": not conflicts, "conflicts": conflicts, "prs_checked": prs is not None, "lanes": len(lanes)}


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
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cwd: Path = Path(args.cwd)
    runs_dir: Path = Path(args.runs_dir) if Path(args.runs_dir).is_absolute() else cwd / args.runs_dir
    if args.command == "branch-check":
        return branch_check(args.stamp, [l.strip() for l in args.lanes.split(",") if l.strip()], cwd)
    manifest: dict[str, Any] = load_manifest(Path(args.manifest))
    if args.command == "lease":
        return lease(manifest, args.lane, runs_dir, cwd, not args.no_prs)
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
