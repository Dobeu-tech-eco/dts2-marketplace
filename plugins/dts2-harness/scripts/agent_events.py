#!/usr/bin/env python3
"""G-74: hook handlers for SubagentStop (verifier), StopFailure and PermissionDenied. Reads the hook JSON on stdin.

  subagent-stop      the verifier may not stop while the newest run's ledger lacks one of the five deterministic check lines
                     (N3: test, typecheck, lint, secret-scan, scope-check); blocks once, skipped when `stop_hook_active`.
  stop-failure       a turn ended on an API error (rate limit, overload, auth, billing...): append a Handoff action item.
  permission-denied  a tool call was denied: append a Handoff action item naming the tool, so a person can widen or fix it.

Always exits 0: an event hook never fails the session."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
import state_io  # noqa: E402

PREFIX: Final[str] = "dts2-harness:"
GATED_AGENT: Final[str] = "verifier"
LEDGER_GROUP: Final[str] = "Handoff"
ACTION_ITEMS_SCRIPT: Final[str] = "action-items.py"
ADD_TIMEOUT_S: Final[int] = 10
DETAIL_MAX_CHARS: Final[int] = 120
REASON: Final[str] = ("dts2-harness verifier stop check: the newest run ledger has no check line for: %s. Run `checks.py run` "
                      "(or report the check as skipped with its reason) and send the report again.")


def newest_ledger(cwd: Path) -> Path | None:
    """The run ledger touched last, or None when there is no run."""
    runs: Path = cwd / checks.RUNS_DIR
    if not runs.is_dir():
        return None
    ledgers: list[Path] = [p / checks.LEDGER_NAME for p in runs.iterdir() if (p / checks.LEDGER_NAME).is_file()]
    return max(ledgers, key=lambda p: p.stat().st_mtime) if ledgers else None


def missing_check_lines(cwd: Path) -> list[str]:
    """Expected check names absent from the newest ledger; empty when there is no run to hold the verifier to."""
    ledger: Path | None = newest_ledger(cwd)
    if ledger is None:
        return []
    present: dict[str, dict[str, Any]] = checks.latest_checks(checks.read_ledger(ledger))
    return [name for name in checks.EXPECTED_CHECKS if name not in present]


def subagent_stop(payload: dict[str, Any], cwd: Path) -> dict[str, Any] | None:
    agent: str = str(payload.get("agent_type") or "").removeprefix(PREFIX)
    if agent != GATED_AGENT or payload.get("stop_hook_active"):
        return None
    missing: list[str] = missing_check_lines(cwd)
    return {"decision": "block", "reason": REASON % ", ".join(missing)} if missing else None


def one_line(value: Any) -> str:
    text: str = checks.redact(" ".join(str(value or "").split()))
    return text[:DETAIL_MAX_CHARS]


def item_text(event: str, payload: dict[str, Any]) -> str:
    session: str = one_line(payload.get("session_id")) or "unknown session"
    if event == "stop-failure":
        kind: str = one_line(payload.get("error")) or "unknown"
        detail: str = one_line(payload.get("error_details") or payload.get("last_assistant_message"))
        return f"StopFailure {kind} in session {session}" + (f": {detail}" if detail else "") + "; resume or switch provider"
    tool: str = one_line(payload.get("tool_name")) or "a tool"
    reason: str = one_line(payload.get("reason") or payload.get("permission_denied_reason"))
    return f"PermissionDenied for {tool} in session {session}" + (f": {reason}" if reason else "") + "; allow it or change the plan"


def append_item(cwd: Path, text: str) -> bool:
    """Add the text to the action-items ledger once per event, tool and session (the text before the first colon); False when it is already there or the ledger cannot be written."""
    path: Path = cwd / state_io.ACTION_ITEMS_REL
    if not path.parent.is_dir():
        return False
    key: str = text.split(":", 1)[0]
    if path.is_file() and key in path.read_text(encoding="utf-8"):
        return False
    script: Path = Path(__file__).resolve().parent / ACTION_ITEMS_SCRIPT
    done = subprocess.run([sys.executable, "-I", str(script), str(cwd), "add", LEDGER_GROUP, text],
                          capture_output=True, text=True, timeout=ADD_TIMEOUT_S, check=False)
    return done.returncode == 0


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=("subagent-stop", "stop-failure", "permission-denied"))
    args: argparse.Namespace = parser.parse_args()
    try:
        payload: Any = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        cwd: Path = Path(str(payload.get("cwd") or Path.cwd()))
        if args.event == "subagent-stop":
            result: dict[str, Any] | None = subagent_stop(payload, cwd)
            if result:
                print(json.dumps(result))
            return 0
        append_item(cwd, item_text(args.event, payload))
    except Exception:  # noqa: BLE001 - an event hook must never fail the session
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
