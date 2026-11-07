"""Integration-lane routing (B6, G-25) and the task cap per PR. Files that every lane tends to touch (lockfiles, migrations, route
tables, barrel index files, and any `lanes.shared_files` glob from .harness/config.yaml) are not fought over: they route to one
final `integration` lane that merges after the others. A lane may bundle at most MAX_TASKS_PER_PR tasks, one commit per task."""
from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Final

from model_call import read_block

from .common import lane_files, norm

INTEGRATION_LANE: Final[str] = "integration"
MAX_TASKS_PER_PR: Final[int] = 5
KIND_BUNDLE: Final[str] = "bundle"
SHARED_FIELD: Final[str] = "shared_files"
LOCKFILE_NAMES: Final[tuple[str, ...]] = ("*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum", "bun.lockb", "npm-shrinkwrap.json")
ROUTE_TABLE_NAMES: Final[tuple[str, ...]] = ("routes.*", "*.routes.*", "*-routes.*", "router.*", "routing.*", "urls.py")
BARREL_NAMES: Final[tuple[str, ...]] = ("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs")


def shared_patterns(cwd: Path) -> tuple[str, ...]:
    """`lanes: shared_files:` of .harness/config.yaml, a comma-separated list of globs matched against the whole repo path."""
    raw: str = read_block(cwd, "lanes").get(SHARED_FIELD, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def matches_any(path: str, names: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(PurePosixPath(path).name, pattern) for pattern in names)


def file_kind(path: str, shared: tuple[str, ...] = ()) -> str | None:
    """Why `path` belongs to the integration lane (lockfile, migration, schema, route-table, barrel, shared) or None."""
    clean: str = norm(path)
    name: str = PurePosixPath(clean).name
    if matches_any(clean, LOCKFILE_NAMES):
        return "lockfile"
    if "migrations/" in f"{clean}/" or "/migrations/" in f"/{clean}":
        return "migration"
    if name.startswith("schema."):
        return "schema"
    if matches_any(clean, ROUTE_TABLE_NAMES):
        return "route-table"
    if matches_any(clean, BARREL_NAMES):
        return "barrel"
    if any(fnmatch.fnmatchcase(clean, pattern) for pattern in shared):
        return "shared"
    return None


def is_integration_file(path: str, shared: tuple[str, ...] = ()) -> bool:
    return file_kind(path, shared) is not None


def route(manifest: dict[str, Any], shared: tuple[str, ...] = ()) -> dict[str, Any]:
    """The final integration lane: every routable file with the lanes that wanted it. `files` is empty when nothing routes."""
    routed: dict[str, list[dict[str, str]]] = {}
    files: set[str] = set()
    for lane in manifest["lanes"]:
        rows: list[dict[str, str]] = []
        for path in sorted(lane_files(lane)):
            kind: str | None = file_kind(path, shared)
            if kind:
                rows.append({"file": path, "kind": kind})
                files.add(path)
        if rows:
            routed[str(lane["id"])] = rows
    return {"lane": INTEGRATION_LANE, "files": sorted(files), "routed": routed}


def oversized_bundle(lane: dict[str, Any]) -> int | None:
    """The task count when the lane bundles more than MAX_TASKS_PER_PR tasks, else None."""
    tasks: Any = lane.get("tasks")
    return len(tasks) if isinstance(tasks, list) and len(tasks) > MAX_TASKS_PER_PR else None


def split_tasks(tasks: list[Any]) -> list[list[Any]]:
    return [tasks[i:i + MAX_TASKS_PER_PR] for i in range(0, len(tasks), MAX_TASKS_PER_PR)]
