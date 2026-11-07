"""Run metrics from the lanes: a warning when an accepted plan has too few disjoint lanes (scripts/run_metrics.py
plan_warning), and one metrics row when a run ends (record), with the post-run token warning. Both only print to stderr."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import run_metrics

from state_io import harness_path

from .common import BUDGET_NAME, MERGE_ORDER_NAME, MODEL_LEDGER_NAME, PHASE_INCOMPLETE, RUN_NAME, LaneError
from .journal import KIND_GRANTED, KIND_MERGED, journal_events
from .mailbox import REQUESTS_DIR
from .records import read_json_object
from .runrecord import read_run
from .runstate import read_status_files

VERDICT_MERGED = "merged"
VERDICT_SHUTDOWN = "shutdown"
REFUSAL_MARKERS: tuple[str, ...] = ("refus", "denied")
OVERRIDE_MARKER = " override lane "
NONE_ROW = "- none"
MISSING = "-"
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


def read_ledger_rows(runs_dir: Path, stamp: str) -> list[dict[str, Any]]:
    path: Path = runs_dir / stamp / MODEL_LEDGER_NAME
    rows: list[dict[str, Any]] = []
    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def refusal_rows(runs_dir: Path, stamp: str) -> list[str]:
    """Ledger rows whose event names a refusal or a denial (G-82), one line each."""
    out: list[str] = []
    for row in read_ledger_rows(runs_dir, stamp):
        event: str = str(row.get("event") or "")
        if any(marker in event for marker in REFUSAL_MARKERS):
            out.append(f"- {row.get('lane', MISSING)}: {event} {row.get('reason') or row.get('detail') or ''}".rstrip())
    return out


def override_rows(cwd: Path | None) -> list[str]:
    """The owner's overrides logged in state.md (written by `lanes.py override`)."""
    if cwd is None:
        return []
    try:
        text: str = harness_path(cwd, "state.md").read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if OVERRIDE_MARKER in line]


def merge_rows(runs_dir: Path, stamp: str) -> list[str]:
    """Merge order as recorded, then each lane's grants; a lane granted more than once was rebased and re-verified."""
    saved: dict[str, Any] = read_json_object(runs_dir / stamp / MERGE_ORDER_NAME)
    order: list[str] = [str(i) for i in saved.get("order") or []]
    grants: dict[str, int] = {}
    for event in journal_events(runs_dir, stamp, KIND_GRANTED):
        lane: str = str(event.get("lane"))
        grants[lane] = grants.get(lane, 0) + 1
    merged: set[str] = {str(e.get("lane")) for e in journal_events(runs_dir, stamp, KIND_MERGED)}
    rows: list[str] = [f"- order: {', '.join(order) if order else MISSING}"]
    rows += [f"- {lane}: {n} grant(s), {max(n - 1, 0)} rebase(s), {'merged' if lane in merged else 'not merged'}"
             for lane, n in sorted(grants.items())]
    return rows


def spend_rows(runs_dir: Path, stamp: str) -> list[str]:
    budget: dict[str, Any] = read_json_object(runs_dir / stamp / BUDGET_NAME)
    return [f"- total: ${float(budget.get('spent_usd') or 0.0):.2f}", f"- unknown-cost calls: {int(budget.get('unknown_calls') or 0)}"]


def checkin_rows(runs_dir: Path, stamp: str) -> list[str]:
    """Items complete when the run started (run.json `checked`) and when it ended (`checked_end`); the delta."""
    record: dict[str, Any] = read_json_object(runs_dir / stamp / RUN_NAME)
    start: Any = record.get("checked")
    end: Any = record.get("checked_end")
    ints: bool = all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end))
    return [f"- start: {start if start is not None else MISSING}, end: {end if end is not None else MISSING}, "
            f"delta: {end - start if ints else MISSING}"]


def request_rows(runs_dir: Path, stamp: str, lane: str) -> list[str]:
    rows: list[str] = []
    for path in sorted((runs_dir / stamp / lane / REQUESTS_DIR).glob("r*.json")):
        data: dict[str, Any] = read_json_object(path)
        rows.append(f"{data.get('id', path.stem)}={data.get('outcome') or 'open'}")
    return rows


def son_rows(runs_dir: Path, stamp: str) -> list[str]:
    """Per son: CI result, merge commit and out-of-lane requests. A field no record holds is `-`."""
    rows: list[str] = []
    for path, status in read_status_files(runs_dir, stamp):
        lane: str = path.parent.name
        requests: list[str] = request_rows(runs_dir, stamp, lane)
        rows.append(f"- {lane}: ci {status.get('ci') or MISSING}; merge commit {status.get('merge_commit') or MISSING}; "
                    f"out-of-lane {', '.join(requests) if requests else 'none'}")
    return rows


def run_wide_sections(runs_dir: Path, stamp: str, cwd: Path | None = None) -> dict[str, list[str]]:
    """G-82: the run-wide sections of the report, each a list of markdown bullet lines."""
    return {"Refusals": refusal_rows(runs_dir, stamp), "Overrides": override_rows(cwd), "Merge order and rebases": merge_rows(runs_dir, stamp),
            "Total spend": spend_rows(runs_dir, stamp), "Check-in delta": checkin_rows(runs_dir, stamp),
            "Per-son results": son_rows(runs_dir, stamp)}


def render_sections(sections: dict[str, list[str]]) -> str:
    return "".join(f"\n### {name}\n\n" + "\n".join(rows or [NONE_ROW]) + "\n" for name, rows in sections.items())


def run_report_view(runs_dir: Path, stamp: str, repo_url: str | None = None, cwd: Path | None = None) -> dict[str, Any]:
    """The run as run_report.py's markdown table (lane, status, rounds, cost, wall-clock, PR) plus the run-wide sections
    (refusals, overrides, merge order and rebases, total spend, check-in delta, per-son results), for `lanes.py report`."""
    import run_report  # noqa: PLC0415 - run_report imports this package lazily too; keep the import out of module load
    statuses, budget = run_report.load(runs_dir, stamp)
    sections: dict[str, list[str]] = run_wide_sections(runs_dir, stamp, cwd)
    return {"ok": True, "stamp": stamp, "markdown": run_report.render(stamp, statuses, budget, repo_url) + render_sections(sections),
            "sections": sections}
