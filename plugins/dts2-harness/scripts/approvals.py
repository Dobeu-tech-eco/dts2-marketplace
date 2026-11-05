#!/usr/bin/env python3
"""The human-only approval channel (G-63, ruling Q11).

An approval is a key in `.claude/settings.local.json`, which the model cannot write (every son launch denies Edit and Write
on it, and the sandbox lists it under denyWrite; the head's own instructions say never to edit it). The person edits the file:

    {"dts2_approvals": {"merge": ["42"], "recorded_yes": ["step-3"], "lane_override": ["lane-a"]}}

`is_human_approved(kind, key)` reads only that file. Nothing an agent writes anywhere else counts, and `record_actor` only logs
who asked (`agent:<session_id>` or `human`), so the log shows when an agent claimed an approval it did not hold."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

MARKER_REL: Final[str] = ".claude/settings.local.json"
APPROVALS_KEY: Final[str] = "dts2_approvals"
KINDS: Final[tuple[str, ...]] = ("recorded_yes", "unsafe_no_sandbox", "blocked_pr_done", "lane_override", "merge")
ACTOR_HUMAN: Final[str] = "human"
ACTOR_AGENT_PREFIX: Final[str] = "agent:"
SESSION_VAR: Final[str] = "CLAUDE_CODE_SESSION_ID"
UNKNOWN_SESSION: Final[str] = "unknown"
LOG_REL: Final[str] = state_io.rel("approvals.log")
LOG_HEADER: Final[str] = "# Approval requests: time | kind | key | actor | approved\n"


class ApprovalError(ValueError):
    """An unknown approval kind."""


def human_marker_path(repo: Path | None = None) -> Path:
    """The one file whose contents count as a human approval."""
    return Path(repo if repo is not None else Path.cwd()) / MARKER_REL


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ApprovalError(f"unknown approval kind {kind!r}; use one of {', '.join(KINDS)}")
    return kind


def read_approvals(repo: Path | None = None) -> dict[str, list[str]]:
    """The `dts2_approvals` table; an unreadable file, a missing key or a wrong shape is an empty table (fail closed)."""
    try:
        data: Any = json.loads(human_marker_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    table: Any = data.get(APPROVALS_KEY) if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {str(kind): [str(k) for k in keys] for kind, keys in table.items() if isinstance(keys, list)}


def is_human_approved(kind: str, key: str, repo: Path | None = None) -> bool:
    """True only when the person listed `key` under `kind` in `.claude/settings.local.json`."""
    check_kind(kind)
    return str(key) in read_approvals(repo).get(kind, [])


def actor_label(session_id: str | None = None) -> str:
    """`agent:<session_id>` for a model session, `human` when the caller is the person's own shell (no session variable)."""
    session: str | None = session_id if session_id is not None else os.environ.get(SESSION_VAR)
    return f"{ACTOR_AGENT_PREFIX}{session or UNKNOWN_SESSION}" if session or os.environ.get("DTS2_SON") else ACTOR_HUMAN


def record_actor(kind: str, key: str, actor: str, repo: Path | None = None) -> Path:
    """Log who asked for this approval and whether the channel held it at that moment. Never grants anything."""
    check_kind(kind)
    root: Path = Path(repo if repo is not None else Path.cwd())
    line: str = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} | {kind} | {key} | {actor} | {is_human_approved(kind, key, root)}\n"
    return state_io.append_text(root / LOG_REL, line, header=LOG_HEADER)


def deny_rules() -> list[str]:
    """Permission rules that keep the model away from the channel (used in the son `--settings` permissions.deny)."""
    return [f"Edit({MARKER_REL})", f"Write({MARKER_REL})", f"MultiEdit({MARKER_REL})", f"NotebookEdit({MARKER_REL})"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="exit 0 when the person approved <kind> <key>, 1 otherwise; logs the asker")
    chk.add_argument("kind")
    chk.add_argument("key")
    chk.add_argument("--session", default=None)
    sub.add_parser("path")
    args = parser.parse_args(argv)
    repo: Path = Path(args.repo)
    if args.cmd == "path":
        print(human_marker_path(repo))
        return 0
    try:
        record_actor(args.kind, args.key, actor_label(args.session), repo)
        approved: bool = is_human_approved(args.kind, args.key, repo)
    except ApprovalError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps({"kind": args.kind, "key": args.key, "approved": approved}))
    return 0 if approved else 1


if __name__ == "__main__":
    sys.exit(main())
