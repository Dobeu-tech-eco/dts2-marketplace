"""Run metrics from the lanes: a warning when an accepted plan has too few disjoint lanes (scripts/run_metrics.py
plan_warning), and one metrics row when a run ends (record), with the post-run token warning. Both only print to stderr."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import run_metrics

from .common import BUDGET_NAME, PHASE_INCOMPLETE, LaneError
from .records import read_json_object
from .runrecord import read_run
from .runstate import read_status_files

VERDICT_MERGED = "merged"
VERDICT_SHUTDOWN = "shutdown"
NO_TOKENS = 0  # lanes.py tracks spend in dollars, not tokens; run_metrics ignores a row with no token count


def warn_thin_plan(result: dict[str, Any]) -> str | None:
    """When a plan was accepted, print run_metrics' warning for a manifest with fewer than 2 disjoint lanes; the warning."""
    if not result.get("ok"):
        return None
    warning: str | None = run_metrics.plan_warning(result.get("manifest") or {})
    if warning:
        print(warning, file=sys.stderr)
    return warning


def run_end_row(runs_dir: Path, stamp: str, verdict: str, now: int) -> dict[str, Any]:
    budget: dict[str, Any] = read_json_object(runs_dir / stamp / BUDGET_NAME)
    lanes: list[dict[str, Any]] = [data for _path, data in read_status_files(runs_dir, stamp)]
    started: Any = budget.get("started") or read_run(runs_dir, stamp).started
    elapsed: int = max(now - int(started), 0) if isinstance(started, (int, float)) else 0
    rounds: int = sum(int(entry.get("rounds", 0)) for entry in (budget.get("lanes") or {}).values() if isinstance(entry, dict))
    failures: dict[str, int] = {}
    for data in lanes:
        if data.get("status") == PHASE_INCOMPLETE:
            reason: str = str(data.get("reason") or "unknown")
            failures[reason] = failures.get(reason, 0) + 1
    return {"stamp": stamp, "rounds": rounds, "failures": failures, "duration_s": elapsed, "agents": [], "verdict": verdict,
            "lanes": len(lanes), "tokens": NO_TOKENS, "wall_clock_s": elapsed, "size_class": run_metrics.DEFAULT_SIZE_CLASS}


def record_run_end(runs_dir: Path, stamp: str, cwd: Path, verdict: str = VERDICT_MERGED) -> bool:
    """Append the run's metrics row once (a stamp already in metrics.jsonl is left alone) and print the post-run warning.
    Best effort: a metrics failure must never fail the run. True when a row was written."""
    try:
        if any(row.get("stamp") == stamp for row in run_metrics.read_rows(cwd)):
            return False
        warning: str | None = run_metrics.record(cwd, run_end_row(runs_dir, stamp, verdict, int(time.time())))
    except (OSError, ValueError, LaneError):
        return False
    if warning:
        print(warning, file=sys.stderr)
    return True


def run_report_view(runs_dir: Path, stamp: str, repo_url: str | None = None) -> dict[str, Any]:
    """The run as run_report.py's markdown table (lane, status, rounds, cost, wall-clock, PR), for `lanes.py report`."""
    import run_report  # noqa: PLC0415 - run_report imports this package lazily too; keep the import out of module load
    statuses, budget = run_report.load(runs_dir, stamp)
    return {"ok": True, "stamp": stamp, "markdown": run_report.render(stamp, statuses, budget, repo_url)}
