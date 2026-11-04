#!/usr/bin/env python3
"""Task ledger for autopilot adjudication: every open PR, the tasks bundled on it, and the user-input items that block it.

Reads .harness/runs/<stamp>/<lane>/status.json, confirms which PRs are still open with `gh pr list`, looks the
blocking item ids up in .harness/action-items.md, writes .harness/runs/<stamp>/task-ledger.md, and prints JSON.
`--resolved` also lists the PRs whose every blocking item is now done, so a resume can merge them first."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

RUNS_DIR: Final[str] = ".harness/runs"
ITEMS_PATH: Final[str] = ".harness/action-items.md"
STATUS_NAME: Final[str] = "status.json"
LEDGER_NAME: Final[str] = "task-ledger.md"
ACTION_ITEMS_SCRIPT: Final[Path] = Path(__file__).resolve().parent / "action-items.py"
GH_PR_FIELDS: Final[str] = "number,headRefName"
TIMEOUT_S: Final[int] = 30
STATUS_DONE: Final[str] = "done"
LEDGER_HEADER: Final[tuple[str, ...]] = ("PR", "branch", "tasks", "blocked by")
UNKNOWN_ITEM: Final[str] = "(not in action-items.md)"


class LedgerError(Exception):
    """Raised when the run folder or a status file cannot be read."""


def binary(name: str, default: str) -> list[str]:
    value: str = os.environ.get(name, default)
    return [sys.executable, value] if value.endswith(".py") else [value]


def load_action_items() -> ModuleType:
    spec = importlib.util.spec_from_file_location("action_items", ACTION_ITEMS_SCRIPT)
    if spec is None or spec.loader is None:
        raise LedgerError(f"cannot load {ACTION_ITEMS_SCRIPT}")
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses in the script resolve their module namespace through sys.modules
    spec.loader.exec_module(module)
    return module


def read_items(cwd: Path, today: date) -> dict[str, dict[str, Any]]:
    """Every row, open or done, keyed by id. list_items() hides done rows, so walk the tables directly."""
    items: ModuleType = load_action_items()
    lines: list[str] = items.read_lines(cwd / ITEMS_PATH)
    rows: dict[str, dict[str, Any]] = {}
    for table in items.find_tables(lines).values():
        for position in range(len(table.row_at)):
            row: dict[str, Any] = items.build_item(table, lines, position, today)
            rows[row["id"]] = row
    return rows


def read_lanes(run_dir: Path) -> list[dict[str, Any]]:
    if not run_dir.is_dir():
        raise LedgerError(f"no run at {run_dir}")
    lanes: list[dict[str, Any]] = []
    for status_path in sorted(run_dir.glob(f"*/{STATUS_NAME}")):
        try:
            lanes.append(json.loads(status_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise LedgerError(f"unreadable {status_path}: {error}") from error
    return lanes


def open_pr_numbers(cwd: Path) -> set[int] | None:
    cmd: list[str] = binary("DTS2_GH_BIN", "gh") + ["pr", "list", "--state", "open", "--json", GH_PR_FIELDS]
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        return {int(pr["number"]) for pr in json.loads(done.stdout)} if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def is_open_pr(lane: dict[str, Any], open_numbers: set[int] | None) -> bool:
    pr: Any = lane.get("pr")
    if not isinstance(pr, int):
        return False
    return pr in open_numbers if open_numbers is not None else True


def merge_lanes(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    """One PR can carry several folded lanes: take lane-ordered fields from the first, union the rest."""
    ordered: list[dict[str, Any]] = sorted(lanes, key=lambda lane: str(lane.get("lane", "")))
    first: dict[str, Any] = ordered[0]
    tasks: list[str] = list(dict.fromkeys(str(t) for lane in ordered for t in lane.get("tasks", [])))
    blocked_by: list[str] = sorted({str(i) for lane in ordered for i in lane.get("blocked_by", [])})
    return {"pr": first["pr"], "lane": first.get("lane", ""), "lanes": [str(lane.get("lane", "")) for lane in ordered],
            "branch": first.get("branch", ""), "status": first.get("status", ""), "tasks": tasks, "blocked_by": blocked_by}


def pr_row(lanes: list[dict[str, Any]], items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = merge_lanes(lanes)
    row["items"] = [{"id": i, "item": items.get(i, {}).get("item", UNKNOWN_ITEM),
                     "status": items.get(i, {}).get("status", "")} for i in row["blocked_by"]]
    return row


def group_by_pr(lanes: list[dict[str, Any]], open_numbers: set[int] | None) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for lane in lanes:
        if is_open_pr(lane, open_numbers):
            grouped.setdefault(lane["pr"], []).append(lane)
    return grouped


def is_resolved(row: dict[str, Any]) -> bool:
    return bool(row["items"]) and all(item["status"].startswith(STATUS_DONE) for item in row["items"])


def ledger_markdown(stamp: str, rows: list[dict[str, Any]], blocking: list[str]) -> str:
    lines: list[str] = [f"# Task ledger {stamp}", "", "| " + " | ".join(LEDGER_HEADER) + " |",
                        "| " + " | ".join("---" for _ in LEDGER_HEADER) + " |"]
    for row in rows:
        blocked: str = ", ".join(f"{i['id']} {i['item']}" for i in row["items"]) or "-"
        lines.append(f"| {row['pr']} | {row['branch']} | {', '.join(row['tasks']) or '-'} | {blocked} |")
    lines += ["", f"{len(rows)} open PRs, {len(blocking)} blocking items", ""]
    return "\n".join(lines)


def build_ledger(cwd: Path, runs_dir: Path, stamp: str, out: Path | None, resolved: bool, today: date) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = read_items(cwd, today)
    open_numbers: set[int] | None = open_pr_numbers(cwd)
    lanes: list[dict[str, Any]] = read_lanes(runs_dir / stamp)
    grouped: dict[int, list[dict[str, Any]]] = group_by_pr(lanes, open_numbers)
    rows: list[dict[str, Any]] = [pr_row(grouped[number], items) for number in sorted(grouped)]
    blocking: list[str] = sorted({i for row in rows for i in row["blocked_by"]})
    path: Path = out if out is not None else runs_dir / stamp / LEDGER_NAME
    atomic_write(path, ledger_markdown(stamp, rows, blocking))
    result: dict[str, Any] = {"ok": True, "stamp": stamp, "path": str(path), "open_prs": rows,
                              "blocking_items": blocking, "gh_confirmed": open_numbers is not None}
    if resolved:
        result["resolved"] = [row for row in rows if is_resolved(row)]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stamp")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--out", default=None, help="ledger path (default .harness/runs/<stamp>/task-ledger.md)")
    parser.add_argument("--resolved", action="store_true", help="also list PRs whose every blocking item is done")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cwd: Path = Path(args.cwd)
    runs_dir: Path = Path(args.runs_dir) if Path(args.runs_dir).is_absolute() else cwd / args.runs_dir
    try:
        result: dict[str, Any] = build_ledger(cwd, runs_dir, args.stamp, Path(args.out) if args.out else None,
                                             args.resolved, date.today())
    except LedgerError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
