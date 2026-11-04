#!/usr/bin/env python3
"""Lane manifest tools for parallel autopilot: overlap check, lane leases, branch-name collision check, the son command line,
and the dpp head's helpers: plan (admission, spend, feasibility, --full selection), status, sendback, release, fold,
stop-check and report-check. It is the only writer of lane state: leases, status.json fields the head owns (heartbeat,
session id, park reason), send-backs, the budget counter, the model-call ledger and merge order. Its supervisor commands:
preflight (pin the CLI version), spawn (start a son under every cap), call (any other model call behind the shared
limit), heartbeat, budget, loop, merge-order, merge-go and merge-done."""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_call import (  # noqa: E402
    cli_version, fallback_used, invoke, is_overload, is_terminated, parse_result, read_budget, read_supervisor,
)
from son_launch import SON_MARKER, cli_too_old, launch_flags, merge_config, sandbox_config, son_env  # noqa: E402
from state_io import atomic_write  # noqa: E402

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
HEAD_NAME: Final[str] = "main"
LANE_PREFIX: Final[str] = "lane-"
MIN_GIT: Final[tuple[int, int]] = (2, 38)
GIT_VERSION: Final[re.Pattern[str]] = re.compile(r"git version (\d+)\.(\d+)")
TIMEOUT_S: Final[int] = 30
GH_PR_FIELDS: Final[str] = "number,files"
PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SETTINGS_FILE: Final[str] = ".claude/dts2-harness.local.md"
PERMISSION_FIELD: Final[str] = "son_permission_mode"
DEFAULT_PERMISSION_MODE: Final[str] = "dontAsk"
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
RUN_NAME: Final[str] = "run.json"
BUDGET_NAME: Final[str] = "budget.json"
MODEL_LEDGER_NAME: Final[str] = "model-ledger.jsonl"
MERGE_ORDER_NAME: Final[str] = "merge-order.json"
MERGE_GO_NAME: Final[str] = "merge-go.md"
PROTECTED_DEFAULTS: Final[tuple[str, ...]] = ("main", "master")
PREFLIGHT_TIMEOUT_S: Final[int] = 30
DEFAULT_CALL_TIMEOUT_S: Final[int] = 1800
PHASE_PR_OPEN: Final[str] = "pr-open"
PHASE_STARTING: Final[str] = "starting"
REASON_TIMEOUT: Final[str] = "timeout"
REASON_MAX_TURNS: Final[str] = "max-turns"
REASON_BUDGET: Final[str] = "budget"
REASON_ERROR: Final[str] = "error"
REASON_NO_STATUS: Final[str] = "no-final-status"
REASON_SLOT: Final[str] = "slot-busy"
REASON_PREFLIGHT: Final[str] = "preflight-missing"
REASON_SKEW: Final[str] = "version-skew"
REASON_SANDBOX: Final[str] = "sandbox-required"
REASON_LOOPS: Final[str] = "loops"
REASON_OVERLOAD: Final[str] = "overload"
REASON_RUNNING: Final[str] = "running"
COST_CLAUDE: Final[str] = "claude"
COST_NONE: Final[str] = "none"
COST_SOURCES: Final[tuple[str, ...]] = (COST_CLAUDE, COST_NONE)
UNREPORTED_KEY: Final[str] = "unreported_calls"
HEARTBEAT_PHASES: Final[tuple[str, ...]] = (PHASE_PR_OPEN, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE)
PID_KEYS: Final[tuple[str, ...]] = ("son_pid", "spawn_pid")
RESERVED_KEY: Final[str] = "reserved_usd"
SUBTYPE_MAX_TURNS: Final[str] = "error_max_turns"
SUBTYPE_MAX_BUDGET: Final[str] = "error_max_budget_usd"
MAX_DIFF_BYTES: Final[int] = 1_000_000
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


def read_lease(path: Path) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


LOCK_TRIES: Final[int] = 50
LOCK_WAIT_SEC: Final[float] = 0.1
LOCK_MODE: Final[int] = 0o600
LOCK_STALE_SEC: Final[float] = 60.0  # a lock is held for one read-compare-write; older than this means its writer died


@contextlib.contextmanager
def lane_lock(lease_path: Path) -> Iterator[bool]:
    """Per-lane exclusive lock around a lease read-compare-write; yields False when it cannot be taken."""
    lock_path: Path = lease_path.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held: bool = False
    for _ in range(LOCK_TRIES):
        try:
            os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, LOCK_MODE))
        except FileExistsError:
            clear_stale_lock(lock_path)
            time.sleep(LOCK_WAIT_SEC)
            continue
        held = True
        break
    try:
        yield held
    finally:
        if held:
            lock_path.unlink(missing_ok=True)


def clear_stale_lock(lock_path: Path) -> None:
    """Remove a lock left by a crashed writer, so one crash cannot block a lane forever."""
    try:
        if time.time() - lock_path.stat().st_mtime > LOCK_STALE_SEC:
            lock_path.unlink(missing_ok=True)
    except OSError:
        pass  # lock vanished or is unreadable: the O_EXCL create in lane_lock decides who wins


def busy(lane_id: str) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": "lease busy"}


def lease_epoch(record: dict[str, Any] | None) -> int:
    value: Any = (record or {}).get("epoch", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def epoch_refusal(lane_id: str, given: int, stored: int) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
            "detail": f"stale epoch {given} is older than the stored lease epoch {stored}; the lease is unchanged"}


def lease(manifest: dict[str, Any], lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool,
          epoch: int | None = None) -> dict[str, Any]:
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    result: dict[str, Any] = check(manifest, runs_dir, cwd, with_prs)
    blocking: list[dict[str, Any]] = [c for c in result["conflicts"] if lane_id in (c["lane"], c["with"])]
    if blocking:
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": blocking}
    stamp: str = str(manifest.get("stamp"))
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    with lane_lock(path) as held:
        if not held:
            return busy(lane_id)
        return write_lease(manifest, lane, path, epoch)


def write_lease(manifest: dict[str, Any], lane: dict[str, Any], path: Path, epoch: int | None) -> dict[str, Any]:
    lane_id: str = str(lane["id"])
    previous: dict[str, Any] | None = read_lease(path)
    if previous is None and path.exists():
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
                "detail": f"unreadable lease at {path}; refusing to overwrite"}
    stored: int = lease_epoch(previous)
    if epoch is not None and epoch < stored:
        return epoch_refusal(lane_id, epoch, stored)
    new_epoch: int = stored + 1
    record: dict[str, Any] = {"stamp": str(manifest.get("stamp")), "lane": lane_id, "status": STATUS_ACTIVE,
                              "created": int(time.time()), "epoch": new_epoch, "base": manifest.get("base"),
                              "files": sorted(lane_files(lane)), "ids": sorted(lane_ids(lane))}
    atomic_write(path, json.dumps(record, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "lease": str(path), "epoch": new_epoch, "conflicts": []}


def head_ref(stamp: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{HEAD_NAME}"


def lane_ref(stamp: str, lane_id: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{LANE_PREFIX}{lane_id}"



def planned_refs(stamp: str, lanes: list[str]) -> list[str]:
    return [head_ref(stamp), *(lane_ref(stamp, lane_id) for lane_id in lanes)]


def git_version_error(cwd: Path) -> str | None:
    """None when git is at least MIN_GIT, else why not. Fails closed on output it cannot parse."""
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "--version"], cwd)
    match = GIT_VERSION.search(out) if code == 0 else None
    need: str = ".".join(str(part) for part in MIN_GIT)
    if match is None:
        return f"cannot read the git version; git merge-tree --write-tree needs git {need} or newer"
    found: tuple[int, int] = (int(match.group(1)), int(match.group(2)))
    if found < MIN_GIT:
        return (f"git {match.group(1)}.{match.group(2)} found; git merge-tree --write-tree needs git {need} "
                f"or newer")
    return None


def existing_refs(cwd: Path) -> list[str]:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "for-each-ref", "--format=%(refname:short)", "refs/heads",
                     "refs/remotes"], cwd)
    if code != 0:
        return []
    return [line.split("/", 1)[1] if line.startswith("origin/") else line for line in out.splitlines() if line.strip()]


def ref_collides(planned: str, existing: str) -> bool:
    return planned == existing or existing.startswith(planned + "/") or planned.startswith(existing + "/")


def branch_check(stamp: str, lanes: list[str], cwd: Path) -> dict[str, Any]:
    version_error: str | None = git_version_error(cwd)
    if version_error is not None:
        return {"ok": False, "planned": [], "collisions": [], "error": version_error}
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


def cap_flags(cwd: Path, remaining_usd: float | None, session: str | None) -> list[str]:
    """The cap and resilience flags every son gets: turns, JSON usage output, fallback chain, spend left, resume."""
    caps: dict[str, Any] = read_budget(cwd)
    chain: list[str] = read_supervisor(cwd)["fallback_models"]
    flags: list[str] = ["--max-turns", str(caps["max_turns"]), "--output-format", "json"]
    if chain:
        flags += ["--fallback-model", ",".join(chain[:3])]  # a comma-separated chain tried in order, at most 3 models
    if caps["max_usd"] is not None and remaining_usd is not None:
        flags += ["--max-budget-usd", f"{max(remaining_usd, 0.01):.2f}"]
    if session:
        flags += ["--resume", session]
    return flags


def son_command(manifest: dict[str, Any], lane_id: str, worktree: Path, cwd: Path,
                remaining_usd: float | None = None, session: str | None = None) -> dict[str, Any]:
    """The headless command for one son: claude -p inside the lane's worktree, with the budget caps and fallback chain."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    mode: str = read_setting(cwd, PERMISSION_FIELD, DEFAULT_PERMISSION_MODE)
    argv: list[str] = binary("DTS2_CLAUDE_BIN", "claude") + [
        "-p", f"{SON_SKILL} {manifest['stamp']}/{lane['id']}",
        *launch_flags(cwd, mode, manifest, str(lane["id"]), worktree), "--model", SON_MODEL, "--plugin-dir", str(PLUGIN_ROOT),
        *cap_flags(cwd, remaining_usd, session),
    ]
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


def valid_beat(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def pid_alive(pid: Any) -> bool:
    """True when a process with this pid exists (signal 0 sends nothing). Bad pids and missing processes are not alive."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lane_alive(data: dict[str, Any]) -> bool:
    """Whether the spawn process or its son, as recorded in status.json, is still running."""
    return any(pid_alive(data.get(key)) for key in PID_KEYS)


def lane_status(path: Path, data: dict[str, Any], threshold: int, now: int, stall_s: int) -> dict[str, Any]:
    """A lane with a heartbeat is judged against stall_minutes from the later of its heartbeat and its status.json
    mtime (a son that keeps writing status.json is alive); otherwise the file's age against builder_timeout_min."""
    phase: str = str(data.get("status", ""))
    updated: int = int(path.stat().st_mtime)
    beat: int | None = valid_beat(data.get("heartbeat"))
    last_seen: int = max(beat, updated) if beat is not None else updated
    limit: int = stall_s if beat is not None else threshold
    stale: bool = phase not in TERMINAL_PHASES | {PHASE_PR_OPEN} and now - last_seen > limit
    alive: bool = lane_alive(data)
    return {"lane": str(data.get("lane") or path.parent.name), "phase": phase, "updated": updated,
            "heartbeat": beat, "last_seen": last_seen, "stale": stale, "alive": alive,
            "incomplete_reason": REASON_STALLED if stale and not alive else None, "snapshot": None}


def merge_json(path: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Read-merge-write one JSON object under its lock; the merged object. Raises LaneError when the lock is busy."""
    with lane_lock(path) as held:
        if not held:
            raise LaneError(f"lock busy for {path}")
        current: dict[str, Any] = read_lease(path) or {}
        merged: dict[str, Any] = {**current, **changes}
        atomic_write(path, json.dumps(merged, indent=2) + "\n")
    return merged


def append_ledger(runs_dir: Path, stamp: str, record: dict[str, Any]) -> None:
    """Add one line to the run's model-call ledger (retries, fallbacks, parks, version checks)."""
    path: Path = runs_dir / stamp / MODEL_LEDGER_NAME
    line: str = json.dumps({"t": int(time.time()), **record}, sort_keys=True)
    with lane_lock(path) as held:
        if not held:
            raise LaneError(f"ledger lock busy for {path}")
        old: str = path.read_text(encoding="utf-8") if path.is_file() else ""
        atomic_write(path, old + line + "\n")


def ledger_emitter(runs_dir: Path, stamp: str, lane_id: str) -> Any:
    return lambda event: append_ledger(runs_dir, stamp, {"lane": lane_id, **event})


def snapshot_stall(folder: Path, path: Path, data: dict[str, Any], now: int) -> str:
    """Keep the stalled lane's last status.json and `git diff` in its run dir; the diff file's path."""
    atomic_write(folder / f"stall-{now}-status.json", path.read_text(encoding="utf-8"))
    worktree: Any = data.get("worktree")
    code, out = (run([*binary("DTS2_GIT_BIN", "git"), "diff"], Path(worktree))
                 if isinstance(worktree, str) and Path(worktree).is_dir() else (1, ""))
    diff: Path = folder / f"stall-{now}.diff"
    atomic_write(diff, out[:MAX_DIFF_BYTES] if code == 0 else "")
    return str(diff)


def recent_snapshot(folder: Path, now: int, stall_s: int) -> str | None:
    """The newest stall diff in the lane's run dir when it is younger than stall_s, so polling a stale but live lane
    does not write a new snapshot every time."""
    diffs: list[Path] = sorted(folder.glob("stall-*.diff"), key=lambda p: p.stat().st_mtime)
    return str(diffs[-1]) if diffs and now - diffs[-1].stat().st_mtime < stall_s else None


def mark_stalled(runs_dir: Path, stamp: str, path: Path, data: dict[str, Any], row: dict[str, Any], now: int) -> None:
    row["snapshot"] = snapshot_stall(path.parent, path, data, now)
    merge_json(path, {"status": PHASE_INCOMPLETE, "reason": REASON_STALLED, "stalled_at": now,
                      "snapshot": row["snapshot"]})
    append_ledger(runs_dir, stamp, {"lane": row["lane"], "event": "stalled", "last_seen": row["last_seen"],
                                    "snapshot": row["snapshot"]})


def status(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Every son's phase from status.json. A lane with a heartbeat is stalled after stall_minutes without one, any other
    quiet non-terminal lane after builder_timeout_min (autopilot §4); a stalled lane is snapshotted and marked incomplete,
    unless its son process is still running: then it is reported `stale` and `alive`, snapshotted, and left as it is
    (the wall-clock deadline of `spawn` ends it), so a lane is never parked or resumed under a running son."""
    threshold: int = stale_after(cwd)
    stall_s: int = read_supervisor(cwd)["stall_minutes"] * SECONDS_PER_MINUTE
    now: int = int(time.time())
    rows: list[dict[str, Any]] = []
    for path, data in read_status_files(runs_dir, stamp):
        row: dict[str, Any] = lane_status(path, data, threshold, now, stall_s)
        if row["stale"] and row["alive"]:
            row["snapshot"] = recent_snapshot(path.parent, now, stall_s) or snapshot_stall(path.parent, path, data, now)
        elif row["stale"]:
            mark_stalled(runs_dir, stamp, path, data, row, now)
        rows.append(row)
    return {"ok": True, "stamp": stamp, "stale_after_s": threshold, "stall_after_s": stall_s, "lanes": rows}


def heartbeat(runs_dir: Path, stamp: str, lane_id: str, turn: int | None, phase: str | None = None,
              reason: str | None = None, blocked_by: list[str] | None = None) -> dict[str, Any]:
    """Stamp the lane's status.json at a turn boundary; creates it when the son has not written one yet. A son sets its
    phase (pr-open, done, blocked, incomplete) and an optional reason through here, never by writing the file."""
    path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    now: int = int(time.time())
    changes: dict[str, Any] = {"lane": lane_id, "heartbeat": now}
    if turn is not None:
        changes["turn"] = turn
    if phase is not None:
        if phase not in HEARTBEAT_PHASES:
            raise LaneError(f"--status must be one of {', '.join(HEARTBEAT_PHASES)}")
        changes["status"] = phase
    if reason is not None:
        changes["reason"] = reason
    if blocked_by:
        changes["blocked_by"] = blocked_by
    merged: dict[str, Any] = merge_json(path, changes)
    return {"ok": True, "lane": lane_id, "heartbeat": now, "status": merged.get("status")}


def sendback(runs_dir: Path, stamp: str, lane_id: str, reason: str) -> dict[str, Any]:
    folder: Path = runs_dir / stamp / lane_id
    count: int = len(list(folder.glob(SEND_BACK_GLOB)))
    if count >= MAX_SEND_BACKS:
        return {"ok": False, "lane": lane_id, "count": count, "path": None,
                "detail": f"{MAX_SEND_BACKS} send-backs already used; the lane ends incomplete"}
    path: Path = folder / SEND_BACK_NAME.format(n=count + 1)
    atomic_write(path, f"# Send-back {count + 1} for lane {lane_id}\n\n{reason}\n")
    return {"ok": True, "lane": lane_id, "count": count + 1, "path": str(path)}


def release(runs_dir: Path, stamp: str, lane_id: str, epoch: int | None = None) -> dict[str, Any]:
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    with lane_lock(path) as held:
        if not held:
            return busy(lane_id)
        return close_lease(path, lane_id, epoch)


def close_lease(path: Path, lane_id: str, epoch: int | None) -> dict[str, Any]:
    try:
        record: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"no lease at {path}: {exc}") from exc
    stored: int = lease_epoch(record)
    if epoch is not None and epoch < stored:
        return epoch_refusal(lane_id, epoch, stored)
    closed: dict[str, Any] = {**record, "status": STATUS_CLOSED, "released": int(time.time())}
    atomic_write(path, json.dumps(closed, indent=2) + "\n")
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


def read_json_object(path: Path) -> dict[str, Any]:
    return read_lease(path) or {}


def new_budget(now: int) -> dict[str, Any]:
    return {"started": now, "spent_usd": 0.0, "unknown_calls": 0, UNREPORTED_KEY: 0, "loops": 0, "lanes": {}}


def charge(budget: dict[str, Any], key: str, session: str | None, reported: float | None,
           new_round: bool = True, refused: bool = False) -> tuple[dict[str, Any], float | None]:
    """Add one call's spend to the counter. `reported` is what the CLI printed for the whole session, which is
    cumulative on a resumed session: charge only the part above what that session already reported. A missing or zero
    cost is unknown (counted in unknown_calls), never zero spend. A refused attempt (`reported` of 0.0 flagged by
    `refused`) cost nothing and counts as neither."""
    lanes: dict[str, Any] = {k: dict(v) for k, v in (budget.get("lanes") or {}).items()}
    entry: dict[str, Any] = lanes.setdefault(key, {"rounds": 0, "sessions": {}})
    entry["rounds"] = int(entry.get("rounds", 0)) + (1 if new_round else 0)
    if refused:
        return {**budget, "lanes": lanes}, 0.0
    if reported is None:
        return {**budget, "lanes": lanes, "unknown_calls": int(budget.get("unknown_calls", 0)) + 1}, None
    sessions: dict[str, float] = dict(entry.get("sessions") or {})
    previous: float = float(sessions.get(session or "", 0.0))
    delta: float = round(reported - previous if reported >= previous else reported, 6)
    sessions[session or ""] = reported
    entry["sessions"] = sessions
    entry["charged_usd"] = round(float(entry.get("charged_usd", 0.0)) + delta, 6)
    return {**budget, "lanes": lanes, "spent_usd": round(float(budget.get("spent_usd", 0.0)) + delta, 6)}, delta


def reserved_total(budget: dict[str, Any], skip: str | None = None) -> float:
    held: Any = budget.get(RESERVED_KEY)
    if not isinstance(held, dict):
        return 0.0
    return round(sum(float(v) for k, v in held.items() if k != skip and isinstance(v, (int, float))), 6)


def spend_state(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    caps: dict[str, Any] = read_budget(cwd)
    budget: dict[str, Any] = read_json_object(runs_dir / stamp / BUDGET_NAME)
    spent: float = float(budget.get("spent_usd", 0.0))
    left: float | None = None if caps["max_usd"] is None else round(caps["max_usd"] - spent, 6)
    reserved: float = reserved_total(budget)
    return {"caps": caps, "budget": budget, "spent_usd": spent, "remaining_usd": left, "reserved_usd": reserved,
            "available_usd": None if left is None else round(left - reserved, 6),
            "spend_complete": int(budget.get("unknown_calls", 0)) == 0 and int(budget.get(UNREPORTED_KEY, 0)) == 0}


def budget_report(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    state: dict[str, Any] = spend_state(runs_dir, stamp, cwd)
    elapsed: int = int(time.time()) - int(state["budget"].get("started", time.time()))
    return {"ok": True, "stamp": stamp, "caps": state["caps"], "spent_usd": state["spent_usd"],
            "remaining_usd": state["remaining_usd"], "reserved_usd": state["reserved_usd"],
            "spend_complete": state["spend_complete"],
            "unknown_calls": int(state["budget"].get("unknown_calls", 0)),
            UNREPORTED_KEY: int(state["budget"].get(UNREPORTED_KEY, 0)), "loops": int(state["budget"].get("loops", 0)),
            "elapsed_s": max(elapsed, 0), "lanes": state["budget"].get("lanes", {})}


def budget_refusal(state: dict[str, Any], lane_id: str | None, now: int) -> str | None:
    """Why no further model call may start, or None. Rounds count starts of one lane; wall time counts from the first.
    Only unknown_calls (a Claude call that should have reported a cost and did not) blocks a dollar cap; unreported_calls
    (a CLI that never reports one) are counted but their dollars are not part of max_usd."""
    caps: dict[str, Any] = state["caps"]
    if state["remaining_usd"] is not None and state["remaining_usd"] <= 0:
        return f"max_usd {caps['max_usd']} reached"
    unknown: int = int(state["budget"].get("unknown_calls", 0))
    if caps["max_usd"] is not None and unknown > 0:
        return f"spend unknown for {unknown} calls; max_usd cannot be enforced"
    started: Any = state["budget"].get("started")
    if isinstance(started, (int, float)) and now - started >= caps["max_wall_minutes"] * SECONDS_PER_MINUTE:
        return f"max_wall_minutes {caps['max_wall_minutes']} reached"
    rounds: int = int(((state["budget"].get("lanes") or {}).get(lane_id or "") or {}).get("rounds", 0))
    if lane_id and rounds >= caps["max_rounds"]:
        return f"max_rounds {caps['max_rounds']} reached for lane {lane_id}"
    return None


def refused_before_running(entry: dict[str, Any], parsed: dict[str, Any]) -> bool:
    """An attempt that reported a 429 as an error result with no cost and at most one turn never reached the model."""
    return (is_overload(int(entry.get("code", 1)), str(entry.get("stdout", "")), str(entry.get("stderr", "")))
            and parsed["is_error"] and not parsed["cost_usd"]
            and (parsed["num_turns"] is None or parsed["num_turns"] <= 1))


def attempt_usages(call: dict[str, Any]) -> list[dict[str, Any] | None]:
    """The parsed result of every attempt, in order. An earlier attempt that printed no result at all was refused before
    it ran (a bare 429) and costs nothing, and so does one whose JSON result is a costless 429 error on its first turn
    (marked `refused`); the last attempt always counts, so a missing cost there is unknown."""
    entries: list[dict[str, Any]] = call.get("results") or [{"stdout": call.get("stdout", "")}]
    parsed: list[dict[str, Any] | None] = [parse_result(str(e.get("stdout", ""))) for e in entries]
    last: int = len(parsed) - 1
    usages: list[dict[str, Any] | None] = []
    for n, (entry, result) in enumerate(zip(entries, parsed)):
        if n != last and result is not None and refused_before_running(entry, result):
            usages.append({"cost_usd": 0.0, "refused": True})
        elif result is not None or n == last:
            usages.append(result)
    return usages


def record_attempts(runs_dir: Path, stamp: str, key: str, usages: list[dict[str, Any] | None],
                    release: str | None = None) -> tuple[float | None, bool]:
    """Fold every attempt's usage into budget.json under one lock, counting one round for the call. Returns the total
    charged (None when no attempt had a known cost) and whether every attempt's cost was known. `release` drops that
    lane's reserved share in the same write."""
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        deltas: list[float | None] = []
        for n, parsed in enumerate(usages or [None]):
            budget, delta = charge(budget, key, (parsed or {}).get("session_id"), (parsed or {}).get("cost_usd"), n == 0,
                                   bool((parsed or {}).get("refused")))
            deltas.append(delta)
        if release and isinstance(budget.get(RESERVED_KEY), dict):
            budget = {**budget, RESERVED_KEY: {k: v for k, v in budget[RESERVED_KEY].items() if k != release}}
        atomic_write(path, json.dumps(budget, indent=2) + "\n")
    known: list[float] = [d for d in deltas if d is not None]
    return (round(sum(known), 6) if known else None), len(known) == len(deltas)


def record_unreported(runs_dir: Path, stamp: str, key: str) -> None:
    """Count one call to a CLI that never reports a cost (a non-Claude seat): one round under `key` and one unreported
    call, under the budget lock. It is never an unknown cost, so it does not stop a `max_usd` run."""
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        lanes: dict[str, Any] = {k: dict(v) for k, v in (budget.get("lanes") or {}).items()}
        entry: dict[str, Any] = lanes.setdefault(key, {"rounds": 0, "sessions": {}})
        entry["rounds"] = int(entry.get("rounds", 0)) + 1
        entry["unreported"] = int(entry.get("unreported", 0)) + 1
        atomic_write(path, json.dumps({**budget, "lanes": lanes, UNREPORTED_KEY: int(budget.get(UNREPORTED_KEY, 0)) + 1},
                                      indent=2) + "\n")


def record_spend(runs_dir: Path, stamp: str, key: str, parsed: dict[str, Any] | None) -> float | None:
    """Fold one call's usage into budget.json; the amount charged, or None when the cost is unknown."""
    return record_attempts(runs_dir, stamp, key, [parsed])[0]


def reserve_share(runs_dir: Path, stamp: str, cwd: Path, manifest: dict[str, Any], lane_id: str) -> tuple[float | None, str | None]:
    """Under the budget lock, set aside this son's share of what is left under max_usd: the unreserved remainder split
    over this lane and every lane not yet started and not holding a share. Returns (share, refusal); no cap gives
    (None, None). Parallel sons therefore never hold more than max_usd between them."""
    caps: dict[str, Any] = read_budget(cwd)
    if caps["max_usd"] is None:
        return None, None
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        reserved: dict[str, Any] = dict(budget.get(RESERVED_KEY) or {})
        available: float = caps["max_usd"] - float(budget.get("spent_usd", 0.0)) - reserved_total(budget, lane_id)
        started: dict[str, Any] = budget.get("lanes") or {}
        waiting: int = sum(1 for lane in manifest["lanes"] if str(lane["id"]) != lane_id and str(lane["id"]) not in reserved
                           and str(lane["id"]) not in started)
        share: float = math.floor(available / (1 + waiting) * 100) / 100
        if share < 0.01:
            return None, f"no unreserved max_usd {caps['max_usd']} left for lane {lane_id}"
        reserved[lane_id] = share
        atomic_write(path, json.dumps({**budget, RESERVED_KEY: reserved}, indent=2) + "\n")
    return share, None


def release_share(runs_dir: Path, stamp: str, lane_id: str) -> None:
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        budget: dict[str, Any] = read_json_object(path)
        if held and isinstance(budget.get(RESERVED_KEY), dict) and lane_id in budget[RESERVED_KEY]:
            atomic_write(path, json.dumps({**budget, RESERVED_KEY: {k: v for k, v in budget[RESERVED_KEY].items()
                                                                     if k != lane_id}}, indent=2) + "\n")


def start_clock(runs_dir: Path, stamp: str) -> None:
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if held and not path.is_file():
            atomic_write(path, json.dumps(new_budget(int(time.time())), indent=2) + "\n")


def claude_version(cwd: Path) -> str | None:
    code, out = run([*binary("DTS2_CLAUDE_BIN", "claude"), "--version"], cwd)
    return cli_version(out) if code == 0 else None


def push_access_problem(cwd: Path, env: dict[str, str]) -> str | None:
    """Why the son env cannot reach the remote (it has no GH_TOKEN or SSH_AUTH_SOCK unless the owner passes them), or None."""
    try:
        done = subprocess.run([*binary("DTS2_GIT_BIN", "git"), "ls-remote", "--exit-code", "origin", "HEAD"], cwd=str(cwd), env=env,
                              capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"`git ls-remote origin` could not run under the son env: {exc}"
    if done.returncode == 0:
        return None
    return ("`git ls-remote origin` fails under the son env, so a son cannot push or open PRs; pass the credential it needs "
            "(for example GH_TOKEN, or SSH_AUTH_SOCK for ssh remotes) with DTS2_SON_ENV_PASS")


def preflight(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Pin `claude --version` in the run's run.json and prove the real son launch answers within 30 s: `claude -p ok` with
    the son's flags, settings and env, so auth, the sandbox (bwrap with failIfUnavailable) and the flags fail once here and
    not in every son. Also proves the son env can reach the remote. A second preflight that finds another version refuses.
    Fails closed: spawn refuses without a passing preflight."""
    path: Path = runs_dir / stamp / RUN_NAME
    pinned: Any = read_json_object(path).get("claude_version")
    version: str | None = claude_version(cwd)
    emit = ledger_emitter(runs_dir, stamp, "-")
    probe: dict[str, Any] = {"stamp": stamp, "lanes": [{"id": "preflight"}]}
    mode: str = read_setting(cwd, PERMISSION_FIELD, DEFAULT_PERMISSION_MODE)
    env: dict[str, str] = son_env(probe, "preflight", cwd)
    argv: list[str] = [*binary("DTS2_CLAUDE_BIN", "claude"), "-p", "ok", *launch_flags(cwd, mode, probe, "preflight", cwd),
                       "--output-format", "json"]
    call: dict[str, Any] = invoke(argv, cwd, PREFLIGHT_TIMEOUT_S, "preflight", emit, env=env)
    parsed: dict[str, Any] | None = parse_result(call["stdout"])
    problems: list[str] = []
    too_old: str | None = cli_too_old(version)
    if version is None:
        problems.append("cannot read `claude --version`")
    elif too_old is not None:
        problems.append(too_old)
    elif isinstance(pinned, str) and pinned != version:
        problems.append(f"claude {version} differs from the version {pinned} pinned for this run")
    if call["code"] != 0 or parsed is None or parsed["is_error"]:
        problems.append(f"`claude -p ok` with the son launch flags failed (exit {call['code']}); check auth, the sandbox "
                        "(bwrap) and the flags")
    access: str | None = push_access_problem(cwd, env)
    if access is not None:
        problems.append(access)
    ok: bool = not problems
    record: dict[str, Any] = {"claude_version": pinned if isinstance(pinned, str) else version, "preflight_ok": ok,
                              "checked": int(time.time()), "problems": problems}
    merge_json(path, record)
    append_ledger(runs_dir, stamp, {"lane": "-", "event": "preflight", "ok": ok, "version": version,
                                    "problems": problems})
    return {"ok": ok, "stamp": stamp, "claude_version": record["claude_version"], "problems": problems}


def spawn_refusal(runs_dir: Path, stamp: str, cwd: Path, lane_id: str) -> tuple[str, str] | None:
    """(reason, detail) when a son must not start: no passing preflight, a different CLI version, or a spent cap."""
    pinned: dict[str, Any] = read_json_object(runs_dir / stamp / RUN_NAME)
    if pinned.get("preflight_ok") is not True or not isinstance(pinned.get("claude_version"), str):
        return REASON_PREFLIGHT, "run `lanes.py preflight` first; no passing preflight is recorded for this run"
    current: str | None = claude_version(cwd)
    if cli_too_old(current) is not None:
        return REASON_SKEW, str(cli_too_old(current))
    if current != pinned["claude_version"]:
        return REASON_SKEW, f"claude is {current}, the run is pinned to {pinned['claude_version']}"
    why: str | None = budget_refusal(spend_state(runs_dir, stamp, cwd), lane_id, int(time.time()))
    return (REASON_BUDGET, why) if why else None


def park(runs_dir: Path, stamp: str, lane_id: str, reason: str, detail: str, session: str | None = None) -> None:
    """End a lane as incomplete with the reason on record. A lane that already finished (done or blocked) is left alone."""
    path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    if read_json_object(path).get("status") in SETTLED_PHASES:
        return
    changes: dict[str, Any] = {"lane": lane_id, "status": PHASE_INCOMPLETE, "reason": reason, "detail": detail,
                               "parked_at": int(time.time())}
    sessions: dict[str, Any] = (((read_json_object(runs_dir / stamp / BUDGET_NAME).get("lanes") or {})
                                 .get(lane_id) or {}).get("sessions") or {})
    if session and session in sessions:
        changes["cost_at_park"] = sessions[session]
    merge_json(path, changes)
    append_ledger(runs_dir, stamp, {"lane": lane_id, "event": "park", "reason": reason, "detail": detail})


def exit_reason(call: dict[str, Any], parsed: dict[str, Any] | None) -> str | None:
    """Why a finished son call ends the lane incomplete (None when it ended cleanly). Exit 143 is the wall-clock kill."""
    if call["code"] == 75:
        return REASON_SLOT
    if call.get("halted_overload"):
        return REASON_OVERLOAD
    if call["timed_out"] or is_terminated(call["code"]):
        return REASON_TIMEOUT
    subtype: str | None = (parsed or {}).get("subtype")
    if subtype == SUBTYPE_MAX_TURNS:
        return REASON_MAX_TURNS
    if subtype == SUBTYPE_MAX_BUDGET:
        return REASON_BUDGET
    if call["code"] != 0 or (parsed or {}).get("is_error"):
        return REASON_ERROR
    return None


def claim_lane(status_path: Path) -> int | None:
    """Under the status lock: the pid of a running spawn or son on this lane, else record this process as the spawner
    and return None. One lane never has two sons."""
    with lane_lock(status_path) as held:
        if not held:
            raise LaneError(f"lock busy for {status_path}")
        current: dict[str, Any] = read_lease(status_path) or {}
        for key in PID_KEYS:
            if pid_alive(current.get(key)) and current.get(key) != os.getpid():
                return int(current[key])
        atomic_write(status_path, json.dumps({**current, "spawn_pid": os.getpid()}, indent=2) + "\n")
    return None


def spawn(manifest: dict[str, Any], lane_id: str, worktree: Path, runs_dir: Path, cwd: Path, resume: bool,
          unsafe: bool = False) -> dict[str, Any]:
    """Start (or with resume, continue) one son under every cap, wait for it, then record session id, spend, fallback and
    exit reason. The only place a son process is started. A lane whose son or spawn is still running is refused
    (`running`) and left untouched."""
    stamp: str = str(manifest["stamp"])
    find_lane(manifest, lane_id)
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    holder: int | None = claim_lane(status_path)
    if holder is not None:
        return {"ok": False, "lane": lane_id, "reason": REASON_RUNNING, "detail": f"process {holder} is still running this lane"}
    try:
        return start_son(manifest, lane_id, worktree, runs_dir, cwd, resume, unsafe)
    finally:
        merge_json(status_path, dict.fromkeys(PID_KEYS))


def sandbox_refusal(runs_dir: Path, stamp: str, cwd: Path, lane_id: str, unsafe: bool) -> tuple[str, str] | None:
    """More than one unattended son needs the sandbox on, or an explicit --unsafe-no-sandbox (which is logged)."""
    if sandbox_config(cwd)["enabled"]:
        return None
    others: list[str] = [str(d.get("lane")) for _p, d in read_status_files(runs_dir, stamp)
                         if d.get("lane") != lane_id and lane_alive(d)]
    if not others:
        return None
    if unsafe:
        append_ledger(runs_dir, stamp, {"lane": lane_id, "event": "unsafe-no-sandbox",
                                        "warning": f"son started without the sandbox beside {', '.join(others)}"})
        print(f"warning: lane {lane_id} starts without the sandbox beside running lanes ({', '.join(others)})",
              file=sys.stderr)
        return None
    return REASON_SANDBOX, "a second unattended son needs sandbox.enabled in .harness/config.yaml or --unsafe-no-sandbox"


def gc_pause(runs_dir: Path, stamp: str, cwd: Path) -> None:
    """`git config gc.auto 0` for the run; the previous local value is kept in run.json for gc_restore."""
    path: Path = runs_dir / stamp / RUN_NAME
    if "gc_auto_prior" in read_json_object(path):
        return
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "config", "--local", "--get", "gc.auto"], cwd)
    merge_json(path, {"gc_auto_prior": out.strip() if code == 0 else None, "gc_auto_paused": True})
    run([*binary("DTS2_GIT_BIN", "git"), "config", "--local", "gc.auto", "0"], cwd)


def gc_restore(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Put gc.auto back to what it was before gc_pause (unset when it was unset). Safe to call twice. A son is refused."""
    if inside_son():
        return son_refusal("gc-restore")
    path: Path = runs_dir / stamp / RUN_NAME
    data: dict[str, Any] = read_json_object(path)
    if not data.get("gc_auto_paused"):
        return {"ok": True, "stamp": stamp, "restored": False}
    prior: Any = data.get("gc_auto_prior")
    git: list[str] = binary("DTS2_GIT_BIN", "git")
    run([*git, "config", "--local", "gc.auto", str(prior)] if isinstance(prior, str) else
        [*git, "config", "--local", "--unset", "gc.auto"], cwd)
    merge_json(path, {"gc_auto_paused": False})
    return {"ok": True, "stamp": stamp, "restored": True, "gc_auto": prior}


def start_son(manifest: dict[str, Any], lane_id: str, worktree: Path, runs_dir: Path, cwd: Path, resume: bool,
              unsafe: bool = False) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    refusal: tuple[str, str] | None = (spawn_refusal(runs_dir, stamp, cwd, lane_id)
                                       or sandbox_refusal(runs_dir, stamp, cwd, lane_id, unsafe))
    if refusal is not None:
        park(runs_dir, stamp, lane_id, refusal[0], refusal[1])
        return {"ok": False, "lane": lane_id, "reason": refusal[0], "detail": refusal[1]}
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    session: Any = read_json_object(status_path).get("session_id") if resume else None
    if resume and not (isinstance(session, str) and session):
        park(runs_dir, stamp, lane_id, REASON_ERROR, "no session_id in status.json to resume")
        return {"ok": False, "lane": lane_id, "reason": REASON_ERROR, "detail": "no session_id to resume"}
    start_clock(runs_dir, stamp)
    gc_pause(runs_dir, stamp, cwd)
    share, no_share = reserve_share(runs_dir, stamp, cwd, manifest, lane_id)
    if no_share is not None:
        park(runs_dir, stamp, lane_id, REASON_BUDGET, no_share)
        return {"ok": False, "lane": lane_id, "reason": REASON_BUDGET, "detail": no_share}
    state: dict[str, Any] = spend_state(runs_dir, stamp, cwd)
    command: dict[str, Any] = son_command(manifest, lane_id, worktree, cwd, share, session)
    left_s: float = (state["caps"]["max_wall_minutes"] * SECONDS_PER_MINUTE
                     - (time.time() - float(state["budget"].get("started", time.time()))))
    fresh: dict[str, Any] = ({} if read_json_object(status_path).get("status") in SETTLED_PHASES else
                             {"status": PHASE_STARTING, "reason": None, "detail": None, "parked_at": None, "stalled_at": None})
    merge_json(status_path, {"lane": lane_id, "worktree": str(worktree), "heartbeat": int(time.time()), **fresh})
    emit = ledger_emitter(runs_dir, stamp, lane_id)
    try:
        call: dict[str, Any] = invoke(command["argv"], worktree, max(left_s, 1.0), f"son:{lane_id}", emit, root=cwd,
                                      halt_on_session=True, env=command["env"],
                                      on_start=lambda pid: merge_json(status_path, {"son_pid": pid, "spawn_pid": os.getpid()}))
        parsed: dict[str, Any] | None = parse_result(call["stdout"])
        return finish_son(runs_dir, stamp, lane_id, worktree, call, parsed, emit)
    finally:
        release_share(runs_dir, stamp, lane_id)


def finish_son(runs_dir: Path, stamp: str, lane_id: str, worktree: Path, call: dict[str, Any], parsed: dict[str, Any] | None,
               emit: Any) -> dict[str, Any]:
    status_path: Path = runs_dir / stamp / lane_id / STATUS_NAME
    session: str | None = (parsed or {}).get("session_id")
    charged, all_known = record_attempts(runs_dir, stamp, lane_id, attempt_usages(call), release=lane_id)
    fallback: str | None = fallback_used(parsed, SON_MODEL)
    changes: dict[str, Any] = {"lane": lane_id, "worktree": str(worktree), "heartbeat": int(time.time()),
                               **dict.fromkeys(PID_KEYS)}
    if session:
        changes["session_id"] = session
    if fallback:
        changes["fallback_model"] = fallback
        emit({"event": "fallback", "model": fallback, "primary": SON_MODEL})
    merge_json(status_path, changes)
    reason: str | None = exit_reason(call, parsed)
    phase: str = str(read_json_object(status_path).get("status", ""))
    if reason is None and phase not in TERMINAL_PHASES | {PHASE_PR_OPEN}:
        reason = REASON_NO_STATUS
    detail: str = f"exit {call['code']}, {call['retries']} retries"
    if reason is not None:
        park(runs_dir, stamp, lane_id, reason, detail, session)
    emit({"event": "son-exit", "code": call["code"], "reason": reason, "cost_usd": (parsed or {}).get("cost_usd"),
          "charged_usd": charged, "cost_known": all_known, "retries": call["retries"]})
    return {"ok": reason is None, "lane": lane_id, "reason": reason, "exit": call["code"],
            "session_id": session, "cost_usd": (parsed or {}).get("cost_usd"), "charged_usd": charged,
            "cost_known": all_known, "fallback_model": fallback, "retries": call["retries"]}


def read_prompt(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LaneError(f"unreadable prompt file {path}: {exc}") from exc


def default_cost_source(argv: list[str]) -> str:
    """`claude` when the command is the Claude CLI (a binary named claude, or DTS2_CLAUDE_BIN), else `none`."""
    claude: list[str] = binary("DTS2_CLAUDE_BIN", "claude")
    named: bool = bool(argv) and os.path.basename(argv[0]) == "claude"
    return COST_CLAUDE if named or (bool(argv) and argv[:len(claude)] == claude) else COST_NONE


def model_call(runs_dir: Path, stamp: str, cwd: Path, label: str, argv: list[str], timeout_s: int,
               out: Path | None, prompt_file: Path | None = None, cost_source: str | None = None) -> dict[str, Any]:
    """Any non-son model call (a panel voter, a council seat) behind the same slot limit, backoff and ledger. With
    cost-source `none` (a CLI that never prints a cost) the call is counted as unreported, not as unknown spend."""
    if not argv:
        raise LaneError("call needs a command after --")
    why: str | None = budget_refusal(spend_state(runs_dir, stamp, cwd), None, int(time.time()))
    if why:
        append_ledger(runs_dir, stamp, {"lane": label, "event": "refused", "reason": why})
        return {"ok": False, "label": label, "reason": REASON_BUDGET, "detail": why}
    prompt: str | None = read_prompt(prompt_file)
    call: dict[str, Any] = invoke(argv, cwd, timeout_s, label, ledger_emitter(runs_dir, stamp, label), stdin_text=prompt)
    parsed: dict[str, Any] | None = parse_result(call["stdout"])
    if (cost_source or default_cost_source(argv)) == COST_NONE:
        record_unreported(runs_dir, stamp, f"call:{label}")
        charged, all_known = None, False
    else:
        charged, all_known = record_attempts(runs_dir, stamp, f"call:{label}", attempt_usages(call))
    if out is not None:
        atomic_write(out, call["stdout"])
    return {"ok": call["code"] == 0 and not (parsed or {}).get("is_error"), "label": label, "code": call["code"],
            "timed_out": call["timed_out"], "retries": call["retries"], "charged_usd": charged,
            "cost_known": all_known, "stdout": None if out is not None else call["stdout"],
            "out": str(out) if out is not None else None, "stderr": call["stderr"][-2000:]}


def loop(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Count one more fullauto round. Past max_fullauto_loops the run parks as incomplete with the ledger written."""
    start_clock(runs_dir, stamp)
    path: Path = runs_dir / stamp / BUDGET_NAME
    cap: int = read_budget(cwd)["max_fullauto_loops"]
    merged: dict[str, Any] = merge_json(path, {"loops": int(read_json_object(path).get("loops", 0)) + 1})
    count: int = int(merged["loops"])
    if count > cap:
        append_ledger(runs_dir, stamp, {"lane": "-", "event": "park", "reason": REASON_LOOPS,
                                        "detail": f"max_fullauto_loops {cap} reached"})
        return {"ok": False, "stamp": stamp, "loops": count, "max": cap, "stop": True, "status": PHASE_INCOMPLETE,
                "reason": REASON_LOOPS}
    return {"ok": True, "stamp": stamp, "loops": count, "max": cap, "stop": False}


def merge_sequence(manifest: dict[str, Any]) -> list[str]:
    """Dependency order first, then manifest lane order (a stable topological sort). A cycle is a manifest error."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    needs: dict[str, set[str]] = {str(lane["id"]): {str(d) for d in (lane.get("depends_on") or []) if str(d) in ids}
                                  for lane in manifest["lanes"]}
    ordered: list[str] = []
    while len(ordered) < len(ids):
        ready: list[str] = [i for i in ids if i not in ordered and needs[i] <= set(ordered)]
        if not ready:
            raise LaneError("depends_on has a cycle; no merge order exists")
        ordered.append(ready[0])
    return ordered


def unmerged_needs(manifest: dict[str, Any], lane_id: str, merged: list[str]) -> list[str]:
    """Lanes `lane_id` depends on, directly or through others, that have not merged yet (manifest order)."""
    direct: dict[str, list[str]] = {str(lane["id"]): [str(d) for d in (lane.get("depends_on") or [])]
                                    for lane in manifest["lanes"]}
    seen: set[str] = set()
    pending: list[str] = list(direct.get(lane_id, []))
    while pending:
        dep: str = pending.pop()
        if dep not in seen and dep in direct:
            seen.add(dep)
            pending.extend(direct[dep])
    return [i for i in direct if i in seen and i not in merged]


def merge_state(runs_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path: Path = runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME
    saved: dict[str, Any] = read_json_object(path)
    return {"order": merge_sequence(manifest), "merged": list(saved.get("merged") or []),
            "current": saved.get("current")}


def lane_phase(runs_dir: Path, stamp: str, lane_id: str) -> str:
    return str(read_json_object(runs_dir / stamp / lane_id / STATUS_NAME).get("status", ""))


@contextlib.contextmanager
def merge_lock(path: Path) -> Iterator[None]:
    """Hold merge-order.json's lock across a read-check-write, so two heads cannot both take the merge."""
    with lane_lock(path) as held:
        if not held:
            raise LaneError(f"lock busy for {path}")
        yield


def merge_order(manifest: dict[str, Any], runs_dir: Path) -> dict[str, Any]:
    """Write merge-order.json (the order, which lanes merged, which one holds the merge) and say who is next."""
    stamp: str = str(manifest["stamp"])
    path: Path = runs_dir / stamp / MERGE_ORDER_NAME
    with merge_lock(path):
        state: dict[str, Any] = merge_state(runs_dir, manifest)
        atomic_write(path, json.dumps(state, indent=2) + "\n")
    return {"ok": True, "stamp": stamp, **state, "next": next_to_merge(runs_dir, stamp, state, manifest)}


def next_to_merge(runs_dir: Path, stamp: str, state: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    """The first unmerged lane in order that is waiting at pr-open; None while a merge is in flight or an earlier lane
    is still building (it keeps its place). A lane parked incomplete or blocked loses its turn, but only for lanes that
    do not depend on it: a lane whose dependency (direct or transitive) is unmerged is never next."""
    if state["current"]:
        return None
    for lane_id in state["order"]:
        phase: str = lane_phase(runs_dir, stamp, lane_id)
        if lane_id in state["merged"] or phase in (PHASE_INCOMPLETE, PHASE_BLOCKED):
            continue
        if unmerged_needs(manifest, lane_id, state["merged"]):
            continue
        return lane_id if phase == PHASE_PR_OPEN else None
    return None


def merge_target_state(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """The branch this run merges into and whether a recorded yes allows the repo's default branch."""
    saved: dict[str, Any] = read_json_object(runs_dir / stamp / RUN_NAME)
    config: dict[str, str] = merge_config(cwd)
    target: str = str(saved.get("merge_target") or config["target"])
    defaults: set[str] = {config["default_branch"], *PROTECTED_DEFAULTS}
    return {"target": target, "is_default": target in defaults, "default_ok": saved.get("default_branch_yes") is True}


def set_merge_target(runs_dir: Path, stamp: str, cwd: Path, branch: str | None, yes_default: bool) -> dict[str, Any]:
    """Record the run's merge target; `yes_default` is the explicit, recorded yes the default branch needs."""
    if inside_son():
        return son_refusal("merge-target")
    if branch is not None and not re.match(r"^[A-Za-z0-9._/-]+$", branch):
        raise LaneError(f"unsafe branch name {branch!r}")
    changes: dict[str, Any] = {**({"merge_target": branch} if branch else {}),
                               **({"default_branch_yes": True, "default_branch_yes_at": int(time.time())} if yes_default else {})}
    if changes:
        merge_json(runs_dir / stamp / RUN_NAME, changes)
    if branch:
        atomic_write(runs_dir / stamp / "merge-target.txt", branch + "\n")  # read by the merge guard, which never opens run state
    return {"ok": True, "stamp": stamp, **merge_target_state(runs_dir, stamp, cwd)}


def base_tip(cwd: Path, target: str) -> str | None:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", f"refs/remotes/origin/{target}"], cwd)
    return out.strip() if code == 0 and re.match(r"^[0-9a-f]{7,40}$", out.strip()) else None


def inside_son() -> bool:
    """True in a son's process: the marker its env carries, or its lane branch prefix."""
    return bool(os.environ.get(SON_MARKER) or os.environ.get("DTS2_SON_BRANCH_PREFIX"))


def son_refusal(what: str) -> dict[str, Any]:
    return {"ok": False, "detail": f"{what} is the head's alone; a son never grants its own merge or changes the merge state"}


def merge_go(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, cwd: Path = Path("."),
             base: str | None = None) -> dict[str, Any]:
    """Write the lane's merge-go.md, only when it is next in order, no other merge is in flight, the run's target is
    allowed and the base commit it was cleared against is known (recorded as `Base:` for the merge guard). A son is refused."""
    if inside_son():
        return {**son_refusal("merge-go"), "lane": lane_id}
    find_lane(manifest, lane_id)
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_target_state(runs_dir, stamp, cwd)
    if state["is_default"] and not state["default_ok"]:
        return {"ok": False, "lane": lane_id, "detail": f"{state['target']} is the default branch; a run may merge there only "
                "after `lanes.py merge-target --yes-default-branch` records an explicit yes"}
    sha: str | None = base or base_tip(cwd, state["target"])
    if sha is not None and not re.match(r"^[0-9a-f]{7,40}$", sha):
        return {"ok": False, "lane": lane_id, "detail": "--base must be a commit sha"}
    if sha is None:
        return {"ok": False, "lane": lane_id, "detail": f"cannot read origin/{state['target']}; fetch it or pass --base"}
    with merge_lock(runs_dir / stamp / MERGE_ORDER_NAME):
        return grant_merge(manifest, runs_dir, lane_id, head, state["target"], sha)


def grant_merge(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, target: str,
                base: str) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_state(runs_dir, manifest)
    if state["current"]:
        return {"ok": False, "lane": lane_id, "detail": f"lane {state['current']} holds the merge; one merge at a time"}
    waiting_on: list[str] = unmerged_needs(manifest, lane_id, state["merged"])
    if waiting_on:
        return {"ok": False, "lane": lane_id, "next": next_to_merge(runs_dir, stamp, state, manifest),
                "waiting_on": waiting_on,
                "detail": f"{lane_id} depends on unmerged lane {', '.join(waiting_on)}"}
    expected: str | None = next_to_merge(runs_dir, stamp, state, manifest)
    if expected != lane_id:
        return {"ok": False, "lane": lane_id, "next": expected,
                "detail": f"{lane_id} is not next to merge ({expected or 'none is waiting at pr-open'})"}
    path: Path = runs_dir / stamp / lane_id / MERGE_GO_NAME
    atomic_write(path, f"# Merge go for lane {lane_id}\n\nVerified head: {head}\nBase: {target} {base}\n"
                       f"Granted: {int(time.time())}\n")
    atomic_write(runs_dir / stamp / MERGE_ORDER_NAME, json.dumps({**state, "current": lane_id}, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "path": str(path), "head": head, "target": target, "base": base}


def merge_done(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    with merge_lock(runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME):
        return finish_merge(manifest, runs_dir, lane_id)


def finish_merge(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_state(runs_dir, manifest)
    if state["current"] != lane_id:
        return {"ok": False, "lane": lane_id, "detail": f"lane {lane_id} does not hold the merge"}
    done: dict[str, Any] = {**state, "merged": [*state["merged"], lane_id], "current": None}
    atomic_write(runs_dir / stamp / MERGE_ORDER_NAME, json.dumps(done, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "merged": done["merged"], "all_merged": len(done["merged"]) >= len(done["order"])}


def split_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def add_supervisor_parsers(sub: Any) -> None:
    """Subcommands that start models and keep the budget, heartbeat and merge order."""
    for name in ("preflight", "budget", "loop"):
        sub.add_parser(name).add_argument("stamp")
    spawn_p = sub.add_parser("spawn")
    spawn_p.add_argument("manifest")
    spawn_p.add_argument("--lane", required=True)
    spawn_p.add_argument("--worktree", required=True)
    spawn_p.add_argument("--resume", action="store_true", help="continue the lane's saved session with --resume")
    spawn_p.add_argument("--unsafe-no-sandbox", action="store_true",
                         help="allow a second unattended son with the sandbox off; logs a warning")
    call_p = sub.add_parser("call")
    call_p.add_argument("stamp")
    call_p.add_argument("--label", required=True)
    call_p.add_argument("--timeout", type=int, default=DEFAULT_CALL_TIMEOUT_S)
    call_p.add_argument("--cost-source", choices=COST_SOURCES, default=None,
                        help="claude: the CLI prints a cost (default for claude or DTS2_CLAUDE_BIN); none: it never does")
    call_p.add_argument("--prompt-file", default=None, help="piped to the command's stdin (the ballot or prompt)")
    call_p.add_argument("--out", default=None, help="write stdout here instead of returning it; the command follows --")
    beat_p = sub.add_parser("heartbeat")
    beat_p.add_argument("stamp")
    beat_p.add_argument("--lane", required=True)
    beat_p.add_argument("--turn", type=int, default=None)
    beat_p.add_argument("--status", choices=HEARTBEAT_PHASES, default=None, help="set the lane's phase")
    beat_p.add_argument("--reason", default=None, help="why, recorded with --status")
    beat_p.add_argument("--blocked-by", default="", help="item ids a blocked lane waits for, comma separated")
    sub.add_parser("merge-order").add_argument("manifest")
    go_p = sub.add_parser("merge-go")
    go_p.add_argument("manifest")
    go_p.add_argument("--lane", required=True)
    go_p.add_argument("--head", required=True, help="the verified HEAD sha the merge is cleared for")
    go_p.add_argument("--base", default=None, help="the base commit approved against; default origin/<target> now")
    target_p = sub.add_parser("merge-target")
    target_p.add_argument("stamp")
    target_p.add_argument("--set", default=None, help="record the branch this run merges into (default: dev)")
    target_p.add_argument("--yes-default-branch", action="store_true", help="record an explicit yes to merging into the default branch")
    gc_p = sub.add_parser("gc-restore")
    gc_p.add_argument("stamp")
    done_p = sub.add_parser("merge-done")
    done_p.add_argument("manifest")
    done_p.add_argument("--lane", required=True)


def add_run_parsers(sub: Any) -> None:
    """Subcommands keyed by run stamp, for the dpp head."""
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--from-checkin", required=True, help="check-in.py --json output")
    plan_p.add_argument("--draft", required=True, help="draft lanes.json")
    plan_p.add_argument("--outside", default="", help="'<item>: <why>' marks admitted outside check-in")
    plan_p.add_argument("--full", action="store_true", help="dpp-full: greedy fill, delegation lanes allowed")
    plan_p.add_argument("--max", type=int, default=0, help="most lanes --full selects; 0 (default) = no cap, the model-call limit throttles")
    plan_p.add_argument("--stamp", default=None)
    sub.add_parser("status").add_argument("stamp")
    for name in ("sendback", "release"):
        lane_p = sub.add_parser(name)
        lane_p.add_argument("stamp")
        lane_p.add_argument("--lane", required=True)
        if name == "sendback":
            lane_p.add_argument("--reason", required=True)
        else:
            lane_p.add_argument("--epoch", type=int, default=None, help="refuse when older than the stored epoch")
    sub.add_parser("fold").add_argument("stamp")
    add_supervisor_parsers(sub)
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
    lease_p.add_argument("--epoch", type=int, default=None, help="refuse when older than the stored lease epoch")
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
    return plan(draft, read_checkin(Path(args.from_checkin)), args.outside, args.full, args.max or len(draft["lanes"]), runs_dir, cwd,
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
        return release(runs_dir, args.stamp, args.lane, args.epoch)
    if args.command == "fold":
        return fold(runs_dir, args.stamp)
    if args.command == "stop-check":
        return stop_check(runs_dir, args.stamp, Path(args.from_checkin))
    if args.command == "report-check":
        return report_check(Path(args.report), split_ids(args.lanes))
    if args.command == "branch-check":
        return branch_check(args.stamp, split_ids(args.lanes), cwd)
    return dispatch_supervisor(args, runs_dir, cwd)


def dispatch_supervisor(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any] | None:
    if args.command == "preflight":
        return preflight(runs_dir, args.stamp, cwd)
    if args.command == "budget":
        return budget_report(runs_dir, args.stamp, cwd)
    if args.command == "loop":
        return loop(runs_dir, args.stamp, cwd)
    if args.command == "merge-target":
        return set_merge_target(runs_dir, args.stamp, cwd, args.set, args.yes_default_branch)
    if args.command == "gc-restore":
        return gc_restore(runs_dir, args.stamp, cwd)
    if args.command == "heartbeat":
        return heartbeat(runs_dir, args.stamp, args.lane, args.turn, args.status, args.reason, split_ids(args.blocked_by))
    if args.command == "call":
        return model_call(runs_dir, args.stamp, cwd, args.label, args.command_argv, args.timeout,
                          Path(args.out) if args.out else None, Path(args.prompt_file) if args.prompt_file else None,
                          args.cost_source)
    return None


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cwd: Path = Path(args.cwd)
    runs_dir: Path = Path(args.runs_dir) if Path(args.runs_dir).is_absolute() else cwd / args.runs_dir
    handled: dict[str, Any] | None = dispatch_run(args, runs_dir, cwd)
    if handled is not None:
        return handled
    manifest: dict[str, Any] = load_manifest(Path(args.manifest))
    if args.command == "lease":
        return lease(manifest, args.lane, runs_dir, cwd, not args.no_prs, args.epoch)
    if args.command == "son-command":
        remaining: float | None = spend_state(runs_dir, str(manifest["stamp"]), cwd)["remaining_usd"]
        return son_command(manifest, args.lane, Path(args.worktree), cwd, remaining)
    if args.command == "spawn":
        return spawn(manifest, args.lane, Path(args.worktree), runs_dir, cwd, args.resume, args.unsafe_no_sandbox)
    if args.command == "merge-order":
        return merge_order(manifest, runs_dir)
    if args.command == "merge-go":
        return merge_go(manifest, runs_dir, args.lane, args.head, cwd, args.base)
    if args.command == "merge-done":
        done: dict[str, Any] = merge_done(manifest, runs_dir, args.lane)
        if done.get("all_merged"):
            gc_restore(runs_dir, str(manifest["stamp"]), cwd)
        return done
    return check(manifest, runs_dir, cwd, not args.no_prs)


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """Everything after the first `--` is a command for `call`, kept away from argparse."""
    return (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])


def main() -> int:
    own, command = split_command(sys.argv[1:])
    args = build_parser().parse_args(own)
    args.command_argv = command
    try:
        result: dict[str, Any] = dispatch(args)
    except LaneError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
