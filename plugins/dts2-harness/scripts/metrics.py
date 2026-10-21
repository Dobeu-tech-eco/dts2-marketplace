#!/usr/bin/env python3
"""Append one run's metrics to .harness/metrics.jsonl and print a trend line from recent runs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

METRICS_PATH: Final[str] = ".harness/metrics.jsonl"
DEFAULT_WINDOW: Final[int] = 5
VERIFIED: Final[str] = "VERIFIED"
NO_RUNS: Final[str] = "Trend: no runs yet"
NO_FAILURES: Final[str] = "none"


def parse_failures(text: str) -> dict[str, int]:
    pairs: list[list[str]] = [item.split("=", 1) for item in text.split(",") if "=" in item]
    return {name.strip(): int(count) for name, count in pairs if name.strip()}


def append_row(repo: Path, row: dict[str, Any]) -> None:
    path: Path = repo / METRICS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def parse_line(line: str) -> dict[str, Any] | None:
    try:
        row: Any = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict) or not isinstance(row.get("rounds"), int):
        return None
    return row


def read_rows(repo: Path) -> list[dict[str, Any]]:
    path: Path = repo / METRICS_PATH
    if not path.is_file():
        return []
    lines: list[str] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    parsed: list[dict[str, Any] | None] = [parse_line(line) for line in lines if line.strip()]
    return [row for row in parsed if row is not None]


def top_failure(rows: list[dict[str, Any]]) -> str:
    totals: dict[str, int] = {}
    for row in rows:
        failures: Any = row.get("failures")
        for name, count in (failures.items() if isinstance(failures, dict) else []):
            totals[name] = totals.get(name, 0) + (count if isinstance(count, int) else 0)
    ranked: list[tuple[str, int]] = sorted((item for item in totals.items() if item[1] > 0), key=lambda item: (-item[1], item[0]))
    return ranked[0][0] if ranked else NO_FAILURES


def trend(repo: Path, last: int) -> str:
    rows: list[dict[str, Any]] = read_rows(repo)[-max(last, 1):]
    if not rows:
        return NO_RUNS
    average: float = sum(row["rounds"] for row in rows) / len(rows)
    verified: int = sum(1 for row in rows if row.get("verdict") == VERIFIED)
    return f"Trend (last {len(rows)}): rounds avg {average:.1f}, failures top {top_failure(rows)}, verdict VERIFIED {verified}/{len(rows)}"


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("append", help="append one run")
    add.add_argument("--stamp", required=True)
    add.add_argument("--rounds", type=int, required=True)
    add.add_argument("--duration", type=int, required=True, help="seconds")
    add.add_argument("--verdict", required=True)
    add.add_argument("--agents", default="", help="comma-separated")
    add.add_argument("--failures", default="", help="category=count,...")
    show = sub.add_parser("trend", help="print the trend line")
    show.add_argument("--last", type=int, default=DEFAULT_WINDOW)
    return parser


def main() -> int:
    args: argparse.Namespace = build_parser().parse_args()
    repo: Path = Path(args.repo)
    if args.command == "trend":
        print(trend(repo, args.last))
        return 0
    append_row(repo, {
        "stamp": args.stamp, "rounds": args.rounds, "failures": parse_failures(args.failures),
        "duration_s": args.duration, "agents": [a for a in args.agents.split(",") if a], "verdict": args.verdict,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
