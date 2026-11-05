#!/usr/bin/env python3
"""SE-1: run metrics with lanes, tokens and wall-clock, a plan-time lane warning and a post-run token warning."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import METRICS_REL, append_text  # noqa: E402

METRICS_PATH: Final[str] = METRICS_REL
MIN_DISJOINT_LANES: Final[int] = 2
OVERRUN_FACTOR: Final[int] = 3
MIN_HISTORY: Final[int] = 3  # prior runs of the same size class needed before a median means anything
DEFAULT_SIZE_CLASS: Final[str] = "standard"


def norm(path: str) -> str:
    posix: str = path.replace("\\", "/")
    return posix[2:] if posix.startswith("./") else posix


def disjoint_lane_count(lanes: list[dict[str, Any]]) -> int:
    """Lanes whose files overlap no other lane. Order-independent: each lane is compared with every other lane."""
    sets: list[set[str]] = [{norm(str(f)) for f in lane.get("files", []) if f} for lane in lanes]
    return sum(1 for i, mine in enumerate(sets)
               if not any(mine & other for j, other in enumerate(sets) if j != i))


def plan_warning(manifest: dict[str, Any]) -> str | None:
    lanes: list[dict[str, Any]] = [lane for lane in manifest.get("lanes", []) if isinstance(lane, dict)]
    found: int = disjoint_lane_count(lanes)
    if found >= MIN_DISJOINT_LANES:
        return None
    return (f"Warning: fewer than {MIN_DISJOINT_LANES} disjoint lanes ({found} found); "
            "lanes add cost without parallel gain, consider a single-lane run")


def read_rows(repo: Path) -> list[dict[str, Any]]:
    path: Path = repo / METRICS_PATH
    if not path.is_file():
        return []
    found: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            found.append(row)
    return found


def token_count(row: dict[str, Any]) -> int | None:
    value: Any = row.get("tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def overrun_warning(history: list[dict[str, Any]], row: dict[str, Any]) -> str | None:
    tokens: int | None = token_count(row)
    size: str = str(row.get("size_class") or DEFAULT_SIZE_CLASS)
    prior: list[int] = [t for r in history if str(r.get("size_class") or DEFAULT_SIZE_CLASS) == size
                        if (t := token_count(r)) is not None]
    if tokens is None or len(prior) < MIN_HISTORY:
        return None
    median: float = statistics.median(prior)
    if tokens <= OVERRUN_FACTOR * median:
        return None
    return f"Warning: run used {tokens} tokens, above {OVERRUN_FACTOR}x median ({median:g}) for size class {size}"


def build_row(args: argparse.Namespace) -> dict[str, Any]:
    failures: dict[str, int] = {}
    for item in args.failures.split(","):
        name, _, count = item.partition("=")
        if name.strip() and count.strip().isdigit():
            failures[name.strip()] = int(count)
    return {"stamp": args.stamp, "rounds": args.rounds, "failures": failures, "duration_s": args.duration,
            "agents": [a for a in args.agents.split(",") if a], "verdict": args.verdict, "lanes": args.lanes,
            "tokens": args.tokens, "wall_clock_s": args.wall_clock_s, "size_class": args.size_class}


def record(repo: Path, row: dict[str, Any]) -> str | None:
    """Append the row and return the post-run warning, judged against the rows that came before it."""
    warning: str | None = overrun_warning(read_rows(repo), row)
    append_text(repo / METRICS_PATH, json.dumps(row, separators=(",", ":")) + "\n")
    return warning


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("plan-check", help="warn when a lane manifest has fewer than 2 disjoint lanes")
    check.add_argument("manifest", help="path to the lane manifest or plan JSON")
    add = sub.add_parser("record", help="append one run with lanes, tokens and wall-clock")
    add.add_argument("repo")
    add.add_argument("--stamp", required=True)
    add.add_argument("--rounds", type=int, required=True)
    add.add_argument("--duration", type=int, required=True, help="seconds")
    add.add_argument("--verdict", required=True)
    add.add_argument("--agents", default="")
    add.add_argument("--failures", default="", help="category=count,...")
    add.add_argument("--lanes", type=int, required=True)
    add.add_argument("--tokens", type=int, required=True)
    add.add_argument("--wall-clock-s", type=int, required=True)
    add.add_argument("--size-class", default=DEFAULT_SIZE_CLASS)
    return parser


def main() -> int:
    args: argparse.Namespace = build_parser().parse_args()
    if args.command == "plan-check":
        data: Any = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        warning: str | None = plan_warning(data.get("manifest", data) if isinstance(data, dict) else {})
    else:
        warning = record(Path(args.repo), build_row(args))
    if warning:
        print(warning)
    return 0


if __name__ == "__main__":
    sys.exit(main())
