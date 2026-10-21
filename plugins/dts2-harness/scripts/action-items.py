#!/usr/bin/env python3
"""List and update .harness/action-items.md: open items per group with age, owner and the command that resolves each."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

ITEMS_PATH: Final[str] = ".harness/action-items.md"
GROUP_IDS: Final[dict[str, str]] = {
    "Secrets": "S", "Decisions": "D", "Handoff": "H", "Deploy": "Y", "Promotions": "P",
}
SECRET_HEADER: Final[list[str]] = ["name", "unlocks", "consumed in", "how to add", "status", "owner", "added"]
ITEM_HEADER: Final[list[str]] = ["item", "context", "status", "owner", "added"]
STATUS_OPEN: Final[str] = "open"
STATUS_DONE: Final[str] = "done"
HANDOFF_PATH: Final[re.Pattern[str]] = re.compile(r"\.harness/handoff/\S+?\.md")
LESSON_ID: Final[re.Pattern[str]] = re.compile(r"L-\d+")
ROW_ID: Final[re.Pattern[str]] = re.compile(r"^([A-Z])(\d+)$")
SECRET_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=\S+")
FALLBACK_HANDOFF: Final[str] = "open .harness/handoff/"


class ActionItemsError(Exception):
    """Raised for an unknown group or row id."""


@dataclass
class Table:
    group: str
    header_at: int
    row_at: list[int] = field(default_factory=list)


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def join_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def find_tables(lines: list[str]) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    current: Table | None = None
    for index, line in enumerate(lines):
        heading: str = line[3:].strip() if line.startswith("## ") else ""
        if heading:
            current = Table(heading, -1) if heading in GROUP_IDS else None
            if current is not None:
                tables[heading] = current
        elif current is not None and line.startswith("|"):
            collect_line(current, index)
    return tables


def collect_line(table: Table, index: int) -> None:
    if table.header_at < 0:
        table.header_at = index
    elif index > table.header_at + 1:
        table.row_at.append(index)


def column(header: list[str], name: str) -> int:
    lowered: list[str] = [cell.lower() for cell in header]
    return lowered.index(name) if name in lowered else -1


def cell_at(cells: list[str], index: int) -> str:
    return cells[index] if 0 <= index < len(cells) else ""


def age_days(added: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(added)).days
    except ValueError:
        return None


def resolve_command(group: str, row_id: str, cells: list[str]) -> str:
    if group == "Secrets":
        return f"run add secret {cells[0]}"
    if group == "Promotions":
        match: re.Match[str] | None = LESSON_ID.search(" ".join(cells[:2]))
        return f"learn promote {match.group(0) if match else row_id}"
    if group == "Handoff":
        match = HANDOFF_PATH.search(" ".join(cells))
        return f"open {match.group(0)}" if match else FALLBACK_HANDOFF
    return "run"


def build_item(table: Table, lines: list[str], position: int, today: date) -> dict[str, Any]:
    header: list[str] = split_row(lines[table.header_at])
    cells: list[str] = split_row(lines[table.row_at[position]])
    row_id: str = f"{GROUP_IDS[table.group]}{position + 1}"
    added: str = cell_at(cells, column(header, "added"))
    return {
        "id": row_id, "group": table.group, "item": cells[0],
        "status": cell_at(cells, column(header, "status")),
        "owner": cell_at(cells, column(header, "owner")),
        "age_days": age_days(added, today),
        "resolve_command": resolve_command(table.group, row_id, cells),
    }


def list_items(lines: list[str], today: date) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tables: dict[str, Table] = find_tables(lines)
    for group in GROUP_IDS:
        table: Table | None = tables.get(group)
        rows: range = range(len(table.row_at)) if table else range(0)
        items.extend(build_item(table, lines, i, today) for i in rows if table)
    return [item for item in items if not item["status"].startswith(STATUS_DONE)]


def locate(lines: list[str], row_id: str) -> tuple[Table, int]:
    match: re.Match[str] | None = ROW_ID.match(row_id)
    letters: dict[str, str] = {letter: group for group, letter in GROUP_IDS.items()}
    tables: dict[str, Table] = find_tables(lines)
    if match is None or match.group(1) not in letters:
        raise ActionItemsError(f"unknown row {row_id}")
    table: Table | None = tables.get(letters[match.group(1)])
    position: int = int(match.group(2)) - 1
    if table is None or not 0 <= position < len(table.row_at):
        raise ActionItemsError(f"unknown row {row_id}")
    return table, position


def ensure_column(lines: list[str], table: Table, name: str) -> None:
    header: list[str] = split_row(lines[table.header_at])
    if column(header, name) >= 0:
        return
    width: int = len(header)
    lines[table.header_at] = join_row(header + [name])
    lines[table.header_at + 1] = join_row(["---"] * (width + 1))
    for index in table.row_at:
        lines[index] = join_row((split_row(lines[index]) + [""] * width)[:width] + [""])


def set_cell(lines: list[str], row_id: str, name: str, value: str) -> dict[str, Any]:
    table, position = locate(lines, row_id)
    ensure_column(lines, table, name)
    header: list[str] = split_row(lines[table.header_at])
    cells: list[str] = split_row(lines[table.row_at[position]])
    cells += [""] * (len(header) - len(cells))
    cells[column(header, name)] = value
    lines[table.row_at[position]] = join_row(cells)
    return {"id": row_id, name: value}


def clean_text(text: str) -> str:
    return SECRET_ASSIGNMENT.sub(r"\1=<redacted>", text.replace("|", "/").strip())


def new_row(header: list[str], text: str, today: date) -> list[str]:
    fixed: dict[str, str] = {"status": STATUS_OPEN, "added": today.isoformat()}
    cells: list[str] = [fixed.get(name.lower(), "") for name in header]
    cells[0] = clean_text(text)
    return cells


def new_table(group: str) -> list[str]:
    header: list[str] = SECRET_HEADER if group == "Secrets" else ITEM_HEADER
    return ["", f"## {group}", "", join_row(header), join_row(["---"] * len(header))]


def resolve_group(name: str) -> str:
    for group in GROUP_IDS:
        if group.lower() == name.lower():
            return group
    raise ActionItemsError(f"unknown group {name}; use one of {', '.join(GROUP_IDS)}")


def add_row(lines: list[str], group_name: str, text: str, today: date) -> dict[str, Any]:
    group: str = resolve_group(group_name)
    if group not in find_tables(lines):
        lines.extend(new_table(group))
    table: Table = find_tables(lines)[group]
    for name in ("owner", "added"):
        ensure_column(lines, table, name)
    header: list[str] = split_row(lines[table.header_at])
    last: int = table.row_at[-1] if table.row_at else table.header_at + 1
    lines.insert(last + 1, join_row(new_row(header, text, today)))
    return {"id": f"{GROUP_IDS[group]}{len(table.row_at) + 1}", "group": group}


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mutate(path: Path, args: argparse.Namespace, today: date) -> dict[str, Any]:
    lines: list[str] = read_lines(path)
    if args.command == "done":
        result: dict[str, Any] = set_cell(lines, args.row, "status", STATUS_DONE)
    elif args.command == "assign":
        result = set_cell(lines, args.row, "owner", clean_text(args.agent))
    else:
        result = add_row(lines, args.group, " ".join(args.text), today)
    write_lines(path, lines)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    sub.add_parser("done").add_argument("row")
    add: argparse.ArgumentParser = sub.add_parser("add")
    add.add_argument("group")
    add.add_argument("text", nargs="+")
    assign: argparse.ArgumentParser = sub.add_parser("assign")
    assign.add_argument("row")
    assign.add_argument("agent")
    return parser


def main() -> int:
    args: argparse.Namespace = build_parser().parse_args()
    path: Path = Path(args.repo) / ITEMS_PATH
    today: date = date.today()
    try:
        if args.command in (None, "list"):
            items: list[dict[str, Any]] = list_items(read_lines(path), today)
            output: dict[str, Any] = {"items": items, "open": len(items)}
        else:
            output = mutate(path, args, today)
    except ActionItemsError as error:
        json.dump({"error": str(error)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
