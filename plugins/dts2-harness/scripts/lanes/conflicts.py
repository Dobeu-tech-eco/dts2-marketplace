"""Lane overlap detection: file, schema, id, dependency, area and scope conflicts, plus the open-PR and active-run sources."""
from __future__ import annotations

import fnmatch
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .integration import INTEGRATION_LANE, KIND_BUNDLE, MAX_TASKS_PER_PR, is_integration_file, oversized_bundle, route, shared_patterns, split_tasks
from .common import AREA_DEPTH, DEFAULT_LEASE_TTL_S, GH_PR_FIELDS, KIND_AREA, KIND_DEPENDS, KIND_FILES, KIND_IDS, KIND_SCHEMA, KIND_SCOPE, LEASE_NAME, MANIFEST_NAME, SCHEMA_PATTERNS, STATUS_CLOSED, lane_files, lane_ids, lease_live, norm
from .gitrefs import gh_json


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


def conflict(lane: str, other: str, kind: str, detail: str, alternative: str | None, routed: bool = False) -> dict[str, Any]:
    """A routed conflict is settled by the integration lane: it is reported but does not block the run."""
    found: dict[str, Any] = {"lane": lane, "with": other, "kind": kind, "detail": detail, "alternative": alternative}
    if routed:
        found["routed"] = INTEGRATION_LANE
    return found


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


def pair_conflicts(a: dict[str, Any], b: dict[str, Any], shared_globs: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    shared: list[str] = sorted(lane_files(a) & lane_files(b))
    if shared:
        found.append(conflict(a["id"], b["id"], KIND_FILES, f"both own {', '.join(shared)}",
                              f"give {shared[0]} to one lane, or run {b['id']} after {a['id']}",
                              routed=all(is_integration_file(f, shared_globs) for f in shared)))
    schema_a: list[str] = sorted(f for f in lane_files(a) if is_schema_file(f))
    schema_b: list[str] = sorted(f for f in lane_files(b) if is_schema_file(f))
    if schema_a and schema_b and not shared:
        found.append(conflict(a["id"], b["id"], KIND_SCHEMA, f"{schema_a[0]} and {schema_b[0]} share one schema or lockfile",
                              f"serialize: run {b['id']} after {a['id']} merges", routed=True))
    ids: list[str] = sorted(lane_ids(a) & lane_ids(b))
    if ids:
        found.append(conflict(a["id"], b["id"], KIND_IDS, f"both reserve {', '.join(ids)}",
                              "reserve ids again through action-items.py reserve"))
    found.extend(dependency_conflicts(a, b))
    if not shared:
        found.extend(area_conflicts(a, b, shared_globs))
    return found


def dependency_conflicts(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for first, second in ((a, b), (b, a)):
        if second["id"] in (first.get("depends_on") or []):
            found.append(conflict(first["id"], second["id"], KIND_DEPENDS,
                                  f"{first['id']} needs {second['id']}'s output",
                                  f"start {first['id']} after {second['id']} merges"))
    return found


def routed_files(lane: dict[str, Any], shared_globs: tuple[str, ...]) -> set[str]:
    return {f for f in lane_files(lane) if is_integration_file(f, shared_globs)}


def bundle_conflicts(lane: dict[str, Any]) -> list[dict[str, Any]]:
    count: int | None = oversized_bundle(lane)
    if count is None:
        return []
    chunks: int = len(split_tasks(lane["tasks"]))
    return [conflict(lane["id"], "pr", KIND_BUNDLE, f"{count} tasks in one PR; the cap is {MAX_TASKS_PER_PR}",
                     f"split it into {chunks} lanes of at most {MAX_TASKS_PER_PR} tasks, one commit per task")]


def area_conflicts(a: dict[str, Any], b: dict[str, Any], shared_globs: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Areas are judged without the files that route to the integration lane."""
    areas_a: set[str] = {area for area in map(area_of, lane_files(a) - routed_files(a, shared_globs)) if area}
    areas_b: set[str] = {area for area in map(area_of, lane_files(b) - routed_files(b, shared_globs)) if area}
    shared: list[str] = sorted(areas_a & areas_b)
    if not shared:
        return []
    return [conflict(a["id"], b["id"], KIND_AREA, f"both work under {shared[0]}/",
                     f"merge {a['id']} first and rebase {b['id']} before its verifier, or split the area")]


def open_pr_files(cwd: Path) -> list[tuple[str, set[str]]] | None:
    """[(\"pr#12\", files)] for open PRs, or None when gh is unavailable (after bounded retries)."""
    prs, why = gh_json(["pr", "list", "--state", "open", "--json", GH_PR_FIELDS], cwd)
    if why is not None or not isinstance(prs, list):
        return None
    return [(f"pr#{pr.get('number')}", {norm(str(f.get("path", f))) for f in (pr.get("files") or [])})
            for pr in prs if isinstance(pr, dict)]


def lane_abandoned(manifest: Path, lane_id: str, now: int) -> bool:
    """A lane whose lease is closed or past `expires_at` no longer holds its files (a crashed run stops blocking others).
    A lane with no lease yet counts until its manifest is older than the default lease ttl."""
    try:
        record: Any = json.loads((manifest.parent / lane_id / LEASE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        try:
            return now - manifest.stat().st_mtime > DEFAULT_LEASE_TTL_S
        except OSError:
            return False
    return isinstance(record, dict) and not lease_live(record, now)


def active_run_files(runs_dir: Path, stamp: str, now: int | None = None) -> list[tuple[str, set[str]]]:
    """Files owned by lanes of other runs whose manifest is not closed, leaving out lanes whose lease expired or closed."""
    found: list[tuple[str, set[str]]] = []
    clock: int = int(time.time()) if now is None else now
    for manifest in sorted(runs_dir.glob(f"*/{MANIFEST_NAME}")):
        try:
            data: Any = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("stamp") == stamp or data.get("status") == STATUS_CLOSED:
            continue
        held: list[dict[str, Any]] = [lane for lane in data.get("lanes", []) if isinstance(lane, dict)
                                      and not lane_abandoned(manifest, str(lane.get("id")), clock)]
        files: set[str] = set().union(*(lane_files(lane) for lane in held)) if held else set()
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


def assess(manifest: dict[str, Any], sources: list[tuple[str, set[str]]], prs_checked: bool,
           shared: tuple[str, ...] = ()) -> dict[str, Any]:
    """`ok` ignores routed conflicts: the integration lane settles them. `integration` lists what routes there."""
    lanes: list[dict[str, Any]] = manifest["lanes"]
    conflicts: list[dict[str, Any]] = []
    for lane in lanes:
        conflicts.extend(scope_conflicts(lane, manifest.get("scope_root")))
        conflicts.extend(bundle_conflicts(lane))
    for index, lane in enumerate(lanes):
        for other in lanes[index + 1:]:
            conflicts.extend(pair_conflicts(lane, other, shared))
    for lane in lanes:
        conflicts.extend(external_conflicts(lane, sources))
    return {"ok": not [c for c in conflicts if not c.get("routed")], "conflicts": conflicts, "prs_checked": prs_checked,
            "lanes": len(lanes), "integration": route(manifest, shared)}


def check(manifest: dict[str, Any], runs_dir: Path, cwd: Path, with_prs: bool = True) -> dict[str, Any]:
    sources, prs_checked = external_sources(runs_dir, str(manifest.get("stamp")), cwd, with_prs)
    return assess(manifest, sources, prs_checked, shared_patterns(cwd))
