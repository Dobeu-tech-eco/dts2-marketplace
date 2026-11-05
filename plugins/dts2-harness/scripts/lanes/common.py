"""Shared constants, the error type and small manifest helpers for the lanes package."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import proc  # noqa: E402
from proc import binary  # noqa: E402,F401 - re-exported: the lanes modules take it from here
from state_io import LEASE_NAME, RUNS_REL, STATUS_NAME  # noqa: E402,F401

RUNS_DIR: Final[str] = RUNS_REL
MANIFEST_NAME: Final[str] = "lanes.json"
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
STEP_PREFIX: Final[str] = "step-"
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
PHASE_ORPHANED: Final[str] = "orphaned"
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
BUILDERS_NAME: Final[str] = "builders.jsonl"
MERGE_JOURNAL_NAME: Final[str] = "merge-journal.jsonl"
REPORT_NAME: Final[str] = "report.md"
LEASE_TTL_FACTOR: Final[int] = 2  # a lease lives this many times max_wall_minutes unless a heartbeat renews it
DEFAULT_LEASE_TTL_S: Final[int] = 2 * 90 * 60
PROTECTED_DEFAULTS: Final[tuple[str, ...]] = ("main", "master")
PREFLIGHT_TIMEOUT_S: Final[int] = 30
DEFAULT_CALL_TIMEOUT_S: Final[int] = 1800
PHASE_PR_OPEN: Final[str] = "pr-open"
MESSAGE_VERSION: Final[int] = 1  # G-44: every mailbox message carries "v"
STATUS_VERSION: Final[int] = 1  # G-43: status.json carries "v"; a newer one than this is read as incomplete
REASON_UNREADABLE: Final[str] = "status-unreadable"
REASON_STATUS_VERSION: Final[str] = "status-version"
# G-43: one lane-state enum. Older words map onto it: parked and stopped are `incomplete` with the old word as the reason.
PHASE_ALIASES: Final[dict[str, str]] = {"parked": "incomplete", "stopped": "incomplete"}
MERGE_GO_JSON_NAME: Final[str] = "merge-go.json"  # G-44: the merge-go payload {lane, epoch, verified_head_sha, base_sha}
WAIT_FIELD: Final[str] = "mailbox_wait_min"  # G-44: every mailbox wait has a deadline
DEFAULT_WAIT_MIN: Final[int] = 30
ASK_EACH_LANE_FIELD: Final[str] = "dpp_full_ask_each_lane"  # G-50
FREEZE_SCOPE_FIELD: Final[str] = "fullauto_freeze_scope"  # G-50
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
REASON_SHUTDOWN: Final[str] = "shutdown"
REASON_ORPHANED: Final[str] = "orphaned"
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


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """(exit code, stdout) of one command through proc.run: a timeout is 143, a missing program 127, never an exception."""
    return proc.run(cmd, cwd, timeout_s=TIMEOUT_S)


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


def lease_live(record: dict[str, Any] | None, now: int) -> bool:
    """True for an active lease that has not passed its `expires_at`. A lease with no expiry (written before G-16) never expires."""
    if not isinstance(record, dict) or record.get("status") != STATUS_ACTIVE:
        return False
    expires: Any = record.get("expires_at")
    return not (isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires <= now)
