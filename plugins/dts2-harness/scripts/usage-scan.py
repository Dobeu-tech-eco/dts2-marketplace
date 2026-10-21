#!/usr/bin/env python3
"""Count Skill, Agent and MCP tool_use blocks in recent Claude Code transcripts. Read-only."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Iterator

DEFAULT_DAYS: Final[int] = 30
MCP_PREFIX: Final[str] = "mcp__"
MCP_SEPARATOR: Final[str] = "__"


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed: datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def tool_uses(record: dict[str, Any]) -> Iterator[dict[str, Any]]:
    content: Any = record["message"]["content"]
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def classify(block: dict[str, Any]) -> tuple[str, str] | None:
    name: str = str(block.get("name", ""))
    inp: Any = block.get("input") or {}
    if name == "Skill" and isinstance(inp, dict) and inp.get("skill"):
        return "skills", str(inp["skill"])
    if name == "Agent" and isinstance(inp, dict) and inp.get("subagent_type"):
        return "agents", str(inp["subagent_type"])
    if name.startswith(MCP_PREFIX):
        return "mcp", name[len(MCP_PREFIX):].split(MCP_SEPARATOR)[0]
    return None


def plugin_of(kind: str, key: str) -> str:
    return key if kind == "mcp" else key.split(":", 1)[0]


def scan_line(line: str, cutoff: datetime, counts: dict[str, Counter[str]]) -> bool:
    """Return False when the line is malformed; True otherwise (including skipped-old)."""
    try:
        record: dict[str, Any] = json.loads(line)
        stamp: datetime | None = parse_time(record["timestamp"])
        uses: list[dict[str, Any]] = list(tool_uses(record))
    except (ValueError, KeyError, TypeError):
        return False
    if stamp is None:
        return False
    if stamp < cutoff:
        return True
    for block in uses:
        hit: tuple[str, str] | None = classify(block)
        if hit:
            counts[hit[0]][hit[1]] += 1
            counts["plugins"][plugin_of(*hit)] += 1
    return True


def scan(home: Path, days: int) -> dict[str, Any]:
    cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=days)
    counts: dict[str, Counter[str]] = {k: Counter() for k in ("skills", "agents", "mcp", "plugins")}
    files: list[Path] = sorted((home / "projects").glob("*/*.jsonl"))
    skipped: int = 0
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip() and not scan_line(line, cutoff, counts):
                skipped += 1
    return {"days": days, **{k: dict(v) for k, v in counts.items()},
            "filesScanned": len(files), "linesSkipped": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-home", required=True)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args()
    print(json.dumps(scan(Path(args.claude_home), args.days)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
