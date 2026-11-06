#!/usr/bin/env python3
"""Q-8: check a builder, reviewer or verifier report for its required sections. Reads the hook JSON on stdin; prints a block
decision (once) when sections are missing; always exits 0.

  --event stop       SubagentStop: the report is `last_assistant_message`; skipped when `stop_hook_active` is true.
  --event handback   PostToolUse on SubagentHandback: the report is `tool_input.message`; blocks once per agent (a marker file).

A report whose first line is `PARTIAL: hit turn cap at <step>` is passed: the agent already said it is incomplete."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contracts  # noqa: E402

PREFIX: Final[str] = "dt:"
REQUIRED: Final[dict[str, tuple[str, ...]]] = {
    "builder": ("files changed", "commands run", "concerns"),
    "reviewer": ("findings", "verdict"),
    "verifier": ("results", "verdict"),
}
PARTIAL_PREFIX: Final[str] = "PARTIAL:"
SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]")
HANDBACK_TOOL: Final[str] = "SubagentHandback"
MISSING_FIELD: Final[re.Pattern[str]] = re.compile(r"missing '([^']+)'")
REASON: Final[str] = (
    "dts2-harness report check: your final report is missing these `## ` sections: %s. "
    "Send the report again with a `## <name>` heading for each, keeping the content you already have.")


def agent_kind(payload: dict[str, Any]) -> str | None:
    """`builder`, `reviewer` or `verifier` for a harness agent, else None."""
    name: str = str(payload.get("agent_type") or "").removeprefix(PREFIX)
    return name if name in REQUIRED else None


def report_text(payload: dict[str, Any], event: str) -> str:
    if event == "stop":
        return str(payload.get("last_assistant_message") or "")
    tool_input: Any = payload.get("tool_input")
    return str(tool_input.get("message") or "") if isinstance(tool_input, dict) else ""


def missing_fields(text: str, kind: str) -> list[str]:
    """The required section names the report lacks, in contract order; empty when it passes."""
    if text.lstrip().startswith(PARTIAL_PREFIX):
        return []
    parsed = contracts.parse_report(text, [], (), REQUIRED[kind])
    if parsed:
        return []
    return [m.group(1) for reason in parsed.reasons if (m := MISSING_FIELD.search(reason))]


def already_blocked(payload: dict[str, Any]) -> bool:
    """Handback has no stop_hook_active flag: one marker file per session and agent makes the block fire once."""
    session: str = SAFE.sub("", str(payload.get("session_id") or "none"))
    agent: str = SAFE.sub("", str(payload.get("agent_id") or payload.get("agent_type") or "agent"))
    marker: Path = Path(os.environ.get("TMPDIR") or "/tmp") / f"dts2-report-{session}-{agent}"
    if marker.exists():
        return True
    try:
        marker.touch()
    except OSError:
        # Marker unwritable (read-only TMPDIR, full disk): the block may fire again, but a report check never fails the session.
        return False
    return False


def decide(payload: dict[str, Any], event: str) -> dict[str, Any] | None:
    kind: str | None = agent_kind(payload)
    if kind is None:
        return None
    if event == "stop" and payload.get("stop_hook_active"):
        return None
    if event == "handback" and payload.get("tool_name") != HANDBACK_TOOL:
        return None
    missing: list[str] = missing_fields(report_text(payload, event), kind)
    if not missing or (event == "handback" and already_blocked(payload)):
        return None
    return {"decision": "block", "reason": REASON % ", ".join(f"'{name}'" for name in missing)}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", choices=("stop", "handback"), required=True)
    args: argparse.Namespace = parser.parse_args()
    try:
        payload: Any = json.load(sys.stdin)
        result: dict[str, Any] | None = decide(payload, args.event) if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 - a report check must never fail the session
        return 0
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
