"""G-46, G-48, G-50: scope and approval policy the head applies around `plan`: the owner override, "ask before each new lane",
"freeze the approved item set", and reading the end state from a fetched `origin/<base>`."""
from __future__ import annotations

import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
from typing import Any, Final

from _load import load
from state_io import END_STATE_REL, append_text, atomic_write, harness_path

from .common import ASK_EACH_LANE_FIELD, FREEZE_SCOPE_FIELD, LaneError, binary, run
from .leases import APPROVED_NAME, POLICY_NAME, read_names
from .mailbox import lane_dir
from .planner import read_setting
from .records import inside_son, son_refusal

SCOPE_NAME: Final[str] = "scope.json"
PENDING_NAME: Final[str] = "pending-items.json"
OVERRIDE_KIND: Final[str] = "lane_override"  # the approvals.py kind the owner records in .claude/settings.local.json
# Roles that vote or sit on the council; an override is never available to them (G-48).
BARRED_ROLES: Final[frozenset[str]] = frozenset({"vote", "voter", "council"})
ROLE_ENV: Final[str] = "DTS2_ROLE"
TRUE_WORDS: Final[frozenset[str]] = frozenset({"true", "yes", "on", "1"})


def flag(cwd: Path, field: str) -> bool:
    return read_setting(cwd, field, "false").lower() in TRUE_WORDS


def human_approved(kind: str, key: str) -> bool:
    """The human-only channel: a key in `.claude/settings.local.json` the model cannot write. The module is built on another
    branch, so import it lazily and treat its absence as "not approved"."""
    try:
        module: Any = importlib.import_module("approvals")
    except ImportError:
        return False
    check: Any = getattr(module, "is_human_approved", None)
    return bool(check(kind, key)) if callable(check) else False


def git_user(cwd: Path) -> str:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "config", "user.name"], cwd)
    return out.strip() if code == 0 and out.strip() else "unknown"


def override(lane_id: str, reason: str, cwd: Path) -> dict[str, Any]:
    """G-48: the owner's override of a lane rule, logged to state.md. Refused in a son, in any vote or council role, and
    whenever the human channel has not approved `override` for this lane. It is a record, never a vote or a council input."""
    if inside_son():
        return {**son_refusal("an override"), "lane": lane_id}
    if os.environ.get(ROLE_ENV, "").lower() in BARRED_ROLES:
        return {"ok": False, "lane": lane_id, "detail": "an override is the owner's alone; a vote or council never has it"}
    if not reason.strip():
        raise LaneError("an override needs a --reason")
    if not human_approved(OVERRIDE_KIND, lane_id):
        return {"ok": False, "lane": lane_id,
                "detail": f"no human approval for override {lane_id}; the owner records it in .claude/settings.local.json"}
    today: str = datetime.date.today().isoformat()
    append_text(harness_path(cwd, "state.md"), f"- {today} override lane {lane_id} by {git_user(cwd)}: {reason.strip()}\n")
    return {"ok": True, "lane": lane_id, "logged": True}


def scope_hash(items: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(items))).encode("utf-8")).hexdigest()[:16]


def read_object(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def frozen_items(runs_dir: Path, stamp: str, cwd: Path, fullauto: bool) -> set[str] | None:
    """The stored fullauto scope, or None when it is not frozen yet (or the setting is off): `plan` filters by it first."""
    if not (fullauto and flag(cwd, FREEZE_SCOPE_FIELD)):
        return None
    items: Any = read_object(runs_dir / stamp / SCOPE_NAME).get("items")
    return set(items) if isinstance(items, list) and items else None


def freeze_scope(result: dict[str, Any], runs_dir: Path, stamp: str) -> dict[str, Any]:
    """G-50: the first fullauto plan stores its item set and hash in `<stamp>/scope.json`; later plans keep only lanes whose
    item is in it. Any other item goes to `pending-items.json` and the result's `pending` list, never into a lane."""
    path: Path = runs_dir / stamp / SCOPE_NAME
    lanes: list[dict[str, Any]] = list(result["manifest"]["lanes"])
    frozen: dict[str, Any] = read_object(path)
    if not frozen:
        items: list[str] = sorted({str(lane.get("item", "")) for lane in lanes if lane.get("item")})
        frozen = {"v": 1, "hash": scope_hash(items), "items": items}
        atomic_write(path, json.dumps(frozen, indent=2) + "\n")
        return {**result, "scope_hash": frozen["hash"], "pending": []}
    inside: list[dict[str, Any]] = [lane for lane in lanes if str(lane.get("item", "")) in frozen["items"]]
    outside: list[str] = sorted(({str(lane.get("item", "")) for lane in lanes} | set(result.get("out_of_scope", []))) - set(frozen["items"]))
    pending: list[str] = sorted({*read_object(runs_dir / stamp / PENDING_NAME).get("items", []), *outside})
    if outside:
        atomic_write(runs_dir / stamp / PENDING_NAME, json.dumps({"v": 1, "items": pending}, indent=2) + "\n")
    manifest: dict[str, Any] = {**result["manifest"], "lanes": inside}
    return {**result, "manifest": manifest, "ok": bool(result["ok"] and inside), "scope_hash": frozen["hash"], "pending": pending}


def apply_policy(result: dict[str, Any], runs_dir: Path, cwd: Path, *, full: bool, fullauto: bool, autopilot: bool) -> dict[str, Any]:
    """G-50: the two settings. `dpp_full_ask_each_lane` (dpp-full outside autopilot) records that every new lane needs the
    user's yes before it is leased; `fullauto_freeze_scope` (fullauto) freezes the approved item set."""
    stamp: str = str(result["stamp"])
    if full and not autopilot and flag(cwd, ASK_EACH_LANE_FIELD):
        atomic_write(runs_dir / stamp / POLICY_NAME, json.dumps({"v": 1, "ask_each_lane": True}, indent=2) + "\n")
        approved: list[str] = read_names(runs_dir / stamp / APPROVED_NAME)
        result = {**result, "ask_each_lane": True,
                  "needs_approval": [str(lane["id"]) for lane in result["manifest"]["lanes"] if str(lane["id"]) not in approved]}
    if fullauto and flag(cwd, FREEZE_SCOPE_FIELD):
        result = freeze_scope(result, runs_dir, stamp)
    return result


def approve_lane(runs_dir: Path, stamp: str, lane_id: str) -> dict[str, Any]:
    """Record the user's yes for one lane (head only); `lease` then admits it."""
    if inside_son():
        return {**son_refusal("approving a lane"), "lane": lane_id}
    lane_dir(runs_dir, stamp, lane_id)  # validates the stamp and lane id as plain path segments
    folder: Path = runs_dir / stamp
    names: list[str] = sorted({*read_names(folder / APPROVED_NAME), lane_id})
    atomic_write(folder / APPROVED_NAME, json.dumps({"v": 1, "lanes": names}, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "approved": names}


def base_outstanding(cwd: Path, base: str, checkin: set[str]) -> tuple[set[str], str | None]:
    """G-46: the outstanding items with the end state read from the fetched `origin/<base>`, not the working tree (a run's
    own branch may carry a stale or half-edited copy). Section and acceptance items come from that end state; items in the
    check-in list that are not end-state items (action items) are kept as they are. (items, None), or (set(), why) when
    git cannot show the file."""
    code, _ = run([*binary("DTS2_GIT_BIN", "git"), "fetch", "origin", base], cwd)
    code, text = run([*binary("DTS2_GIT_BIN", "git"), "show", f"origin/{base}:{END_STATE_REL}"], cwd) if code == 0 else (code, "")
    if code != 0 or not text.strip():
        return set(), f"cannot read {END_STATE_REL} from origin/{base}; fetch it first"
    items: list[dict[str, str]] = load("check-in").items_from_end_state(text)
    names: set[str] = {i["name"] for i in items}
    return {i["name"] for i in items if i["status"] == "outstanding"} | (checkin - names), None
