#!/usr/bin/env python3
"""Summarize project progress as a complete / outstanding checklist against the approved end state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contracts  # noqa: E402

COMPLETE: Final[str] = "complete"
OUTSTANDING: Final[str] = "outstanding"
STATUSES: Final[tuple[str, ...]] = (COMPLETE, OUTSTANDING)
DONE_STATUS: Final[str] = "done"
PERCENT_SCALE: Final[int] = 100
PLACEHOLDER_PREFIX: Final[str] = "<"
EMPTY_NOTE: Final[str] = "(no items found)"
JSON_SUFFIX: Final[str] = ".json"
EXIT_USAGE: Final[int] = 2


def validate(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValueError(f"item must be an object with name and status: {item!r}")
    name: str = str(item.get("name", "")).strip()
    status: str = str(item.get("status", ""))
    if not name or status not in STATUSES:
        raise ValueError(f"item needs a name and a status in {STATUSES}: {item!r}")
    return {"name": name, "status": status}


def percent(complete: int, total: int) -> int:
    return complete * PERCENT_SCALE // total if total else 0


def summarize(items: list[Any]) -> dict[str, Any]:
    checked: list[dict[str, str]] = [validate(item) for item in items]
    done: list[str] = [i["name"] for i in checked if i["status"] == COMPLETE]
    open_: list[str] = [i["name"] for i in checked if i["status"] == OUTSTANDING]
    return {
        "total": len(checked), "complete": len(done), "outstanding": len(open_),
        "percent": percent(len(done), len(checked)),
        "complete_items": done, "outstanding_items": open_,
    }


def render(summary: dict[str, Any]) -> str:
    header: str = f"{summary['complete']} of {summary['total']} complete ({summary['percent']}%)"
    lines: list[str] = [f"[x] {name}" for name in summary["complete_items"]]
    lines += [f"[ ] {name}" for name in summary["outstanding_items"]]
    return "\n".join([header, *(lines or [EMPTY_NOTE])])


def status_of(cell: str) -> str:
    return COMPLETE if cell == DONE_STATUS else OUTSTANDING


def section_items(end_state: str) -> list[dict[str, str]]:
    rows = contracts.parse_sections(end_state)
    if isinstance(rows, contracts.Invalid):
        return []
    return [
        {"name": f"section {row.number}: {row.name}", "status": status_of(row.status)}
        for row in rows if not row.name.startswith(PLACEHOLDER_PREFIX)
    ]


def acceptance_items(end_state: str) -> list[dict[str, str]]:
    found = contracts.parse_acceptance(end_state)
    if isinstance(found, contracts.Invalid):
        return []
    return [
        {"name": f"acceptance: {item.text}", "status": COMPLETE if item.done else OUTSTANDING}
        for item in found if not item.text.startswith(PLACEHOLDER_PREFIX)
    ]


def items_from_end_state(text: str) -> list[dict[str, str]]:
    return section_items(text) + acceptance_items(text)


def items_from_file(path: Path) -> list[dict[str, Any]]:
    text: str = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == JSON_SUFFIX:
        data: Any = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("status JSON must be a list of items")
        return data
    return list(items_from_end_state(text))


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    source: Any = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--items", help='JSON list of {"name","status"} items; status is complete or outstanding')
    source.add_argument("--from", dest="source_file", help="status file: .harness/end-state.md (Sections table and acceptance boxes) or a JSON list")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON instead of the checklist")
    return parser


def load_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.items is not None:
        data: Any = json.loads(args.items)
        if not isinstance(data, list):
            raise ValueError("--items must be a JSON list")
        return data
    return items_from_file(Path(args.source_file))


def main() -> int:
    args: argparse.Namespace = build_parser().parse_args()
    try:
        summary: dict[str, Any] = summarize(load_items(args))
    except (ValueError, OSError) as error:
        sys.stderr.write(f"check-in: {error}\n")
        return EXIT_USAGE
    sys.stdout.write((json.dumps(summary) if args.json else render(summary)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
