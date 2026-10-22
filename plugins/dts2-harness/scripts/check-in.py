#!/usr/bin/env python3
"""Summarize project progress as a complete / outstanding checklist against the approved end state."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

HANDOFF_SCRIPT: Final[Path] = Path(__file__).resolve().parent / "handoff-write.py"
COMPLETE: Final[str] = "complete"
OUTSTANDING: Final[str] = "outstanding"
STATUSES: Final[tuple[str, ...]] = (COMPLETE, OUTSTANDING)
DONE_STATUS: Final[str] = "done"
PERCENT_SCALE: Final[int] = 100
ACCEPTANCE_HEADING: Final[str] = "## Acceptance criteria"
CHECKBOX: Final[re.Pattern[str]] = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+?)\s*$")
PLACEHOLDER_PREFIX: Final[str] = "<"
EMPTY_NOTE: Final[str] = "(no items found)"
JSON_SUFFIX: Final[str] = ".json"
EXIT_USAGE: Final[int] = 2


def load_handoff() -> ModuleType:
    spec = importlib.util.spec_from_file_location("handoff_write_for_check_in", HANDOFF_SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["handoff_write_for_check_in"] = module
    spec.loader.exec_module(module)
    return module


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


def section_items(end_state: str, handoff: ModuleType) -> list[dict[str, str]]:
    start: int = end_state.find(handoff.SECTIONS_HEADING)
    if start < 0:
        return []
    body: str = end_state[start + len(handoff.SECTIONS_HEADING):]
    end: re.Match[str] | None = handoff.SECTION_END.search(body)
    rows: list[list[str]] = [handoff.table_cells(line) for line in (body[: end.start()] if end else body).splitlines() if line.startswith("|")]
    real: list[list[str]] = [r for r in rows if len(r) > 1 and r[handoff.SECTION_NUMBER_COL].isdigit()]
    return [item_from_row(r, handoff) for r in real if not r[handoff.SECTION_NAME_COL].startswith(PLACEHOLDER_PREFIX)]


def item_from_row(row: list[str], handoff: ModuleType) -> dict[str, str]:
    cell: str = row[handoff.SECTION_NAME_COL]
    match: re.Match[str] | None = handoff.ACTION_ID_SUFFIX.match(cell)
    name: str = f"section {row[handoff.SECTION_NUMBER_COL]}: {match.group(1) if match else cell}"
    return {"name": name, "status": status_of(row[handoff.SECTION_STATUS_COL])}


def acceptance_items(end_state: str, handoff: ModuleType) -> list[dict[str, str]]:
    start: int = end_state.find(ACCEPTANCE_HEADING)
    if start < 0:
        return []
    body: str = end_state[start + len(ACCEPTANCE_HEADING):]
    end: re.Match[str] | None = re.search(r"^## ", body, re.MULTILINE)
    matches: list[re.Match[str] | None] = [CHECKBOX.match(line) for line in (body[: end.start()] if end else body).splitlines()]
    found: list[tuple[str, str]] = [(m.group(1), m.group(2)) for m in matches if m]
    return [
        {"name": f"acceptance: {text}", "status": COMPLETE if box.lower() == "x" else OUTSTANDING}
        for box, text in found if not text.startswith(PLACEHOLDER_PREFIX)
    ]


def items_from_end_state(text: str) -> list[dict[str, str]]:
    handoff: ModuleType = load_handoff()
    return section_items(text, handoff) + acceptance_items(text, handoff)


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
