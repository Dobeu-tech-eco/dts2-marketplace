"""Shared constants, the error type and small manifest helpers for the lanes package."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
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
HEAD_NAME: Final[str] = "main"
LANE_PREFIX: Final[str] = "lane-"
MIN_GIT: Final[tuple[int, int]] = (2, 38)
GIT_VERSION: Final[re.Pattern[str]] = re.compile(r"git version (\d+)\.(\d+)")
TIMEOUT_S: Final[int] = 30
GH_PR_FIELDS: Final[str] = "number,files"
PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
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
MERGE_PENDING_NAME: Final[str] = "merge-pending.txt"  # unmerged lane ids, one per line; the merge guard reads this, never run state
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


def find_lane(manifest: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in manifest["lanes"]:
        if lane.get("id") == lane_id:
            return lane
    raise LaneError(f"unknown lane '{lane_id}'")
