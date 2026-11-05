#!/usr/bin/env python3
"""Print one run as a markdown table (lane, status, rounds, cost, wall-clock, PR link) for pasting into a check-in."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

RUNS_DIR: Final[str] = ".harness/runs"
HEADER: Final[tuple[str, ...]] = ("Lane", "Status", "Rounds", "Cost (USD)", "Wall-clock", "PR")
MISSING: Final[str] = "-"
SECONDS_PER_MINUTE: Final[int] = 60


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def wall_clock(status: dict[str, Any], budget: dict[str, Any]) -> str:
    begin: float | None = number(status.get("started")) or number(budget.get("started"))
    end: float | None = number(status.get("heartbeat"))
    if begin is None or end is None or end < begin:
        return MISSING
    minutes, seconds = divmod(int(end - begin), SECONDS_PER_MINUTE)
    return f"{minutes}m{seconds:02d}s"


def pr_cell(status: dict[str, Any], repo_url: str | None) -> str:
    pr: Any = status.get("pr")
    if not isinstance(pr, int) or isinstance(pr, bool):
        return MISSING
    return f"[#{pr}]({repo_url.rstrip('/')}/pull/{pr})" if repo_url else f"#{pr}"


def lane_row(lane: str, status: dict[str, Any], budget: dict[str, Any], repo_url: str | None) -> list[str]:
    spend: dict[str, Any] = (budget.get("lanes") or {}).get(lane) or {}
    rounds: Any = spend.get("rounds")
    cost: float | None = number(spend.get("charged_usd"))
    return [lane, str(status.get("status") or MISSING), str(rounds) if isinstance(rounds, int) else MISSING,
            f"{cost:.2f}" if cost is not None else MISSING, wall_clock(status, budget), pr_cell(status, repo_url)]


def table(rows: list[list[str]]) -> str:
    lines: list[str] = ["| " + " | ".join(HEADER) + " |", "| " + " | ".join(["---"] * len(HEADER)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render(stamp: str, statuses: dict[str, dict[str, Any]], budget: dict[str, Any], repo_url: str | None = None) -> str:
    """`statuses` maps lane id to its status record; `budget` is the run's spend record. Pure: no file access."""
    rows: list[list[str]] = [lane_row(lane, statuses[lane], budget, repo_url) for lane in sorted(statuses)]
    rounds: int = sum(int(row[2]) for row in rows if row[2] != MISSING)
    costs: list[float] = [float(row[3]) for row in rows if row[3] != MISSING]
    rows.append(["Total", "", str(rounds), f"{sum(costs):.2f}" if costs else MISSING, "", ""])
    return f"Run {stamp}\n\n{table(rows)}\n"


def load(runs_dir: Path, stamp: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read the run through lanes.py, the only module that knows the state file layout."""
    import lanes  # noqa: PLC0415 - lazy so render() stays importable without the supervisor
    found = lanes.read_status_files(runs_dir, stamp)
    return ({path.parent.name: data for path, data in found},
            lanes.read_json_object(runs_dir / stamp / lanes.BUDGET_NAME))


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="run stamp")
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--repo-url", default=None, help="turns PR numbers into links")
    args: argparse.Namespace = parser.parse_args()
    try:
        statuses, budget = load(Path(args.runs_dir), args.run)
        sys.stdout.write(render(args.run, statuses, budget, args.repo_url))
    except Exception as exc:  # noqa: BLE001 - lanes.LaneError for a missing or unreadable run
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
