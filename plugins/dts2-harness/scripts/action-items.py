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
STATUS_RESERVED: Final[str] = "reserved"
STATUS_RELEASED: Final[str] = "released"
RESERVED_ITEM: Final[str] = "(reserved)"
RELEASED_ITEM: Final[str] = "(released)"
# Rows that are placeholders, not work: hidden from list, never deleted so later ids keep their position.
HIDDEN_STATUSES: Final[tuple[str, ...]] = (STATUS_RESERVED, STATUS_RELEASED)
MAX_RESERVE: Final[int] = 50
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
    return [item for item in items if is_open(item["status"])]


def is_open(status: str) -> bool:
    return not status.startswith(STATUS_DONE) and status not in HIDDEN_STATUSES


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


def reserve_rows(lines: list[str], group_name: str, count: int, holder: str, today: date) -> dict[str, Any]:
    """Insert `count` placeholder rows owned by `holder` so their ids are fixed before any lane writes."""
    if not 1 <= count <= MAX_RESERVE:
        raise ActionItemsError(f"count must be 1..{MAX_RESERVE}")
    ids: list[str] = []
    for _ in range(count):
        row_id: str = add_row(lines, group_name, RESERVED_ITEM, today)["id"]
        set_cell(lines, row_id, "status", STATUS_RESERVED)
        set_cell(lines, row_id, "owner", clean_text(holder))
        ids.append(row_id)
    return {"group": resolve_group(group_name), "holder": holder, "ids": ids}


def set_first_cell(lines: list[str], row_id: str, value: str) -> None:
    """The first column is `item` or, for Secrets, `name`; write it without adding a column."""
    table, position = locate(lines, row_id)
    cells: list[str] = split_row(lines[table.row_at[position]])
    cells[0] = value
    lines[table.row_at[position]] = join_row(cells)


def row_state(lines: list[str], row_id: str) -> dict[str, str]:
    table, position = locate(lines, row_id)
    header: list[str] = split_row(lines[table.header_at])
    cells: list[str] = split_row(lines[table.row_at[position]])
    return {"status": cell_at(cells, column(header, "status")), "owner": cell_at(cells, column(header, "owner"))}


def fill_reserved(lines: list[str], row_id: str, text: str, holder: str | None) -> dict[str, Any]:
    """Turn one placeholder into a real open item. Only the holder that reserved it may fill it."""
    state: dict[str, str] = row_state(lines, row_id)
    if state["status"] != STATUS_RESERVED:
        raise ActionItemsError(f"{row_id} is not reserved (status {state['status'] or 'open'})")
    if holder is None or clean_text(holder) != state["owner"]:
        raise ActionItemsError(f"{row_id} is reserved by {state['owner']}, not {holder or 'nobody'}")
    set_first_cell(lines, row_id, clean_text(text))
    set_cell(lines, row_id, "status", STATUS_OPEN)
    set_cell(lines, row_id, "owner", "")
    table, _ = locate(lines, row_id)
    return {"id": row_id, "group": table.group}


def reserved_ids(lines: list[str], holder: str, group: str | None = None) -> list[str]:
    tables: dict[str, Table] = find_tables(lines)
    found: list[str] = []
    for name, table in tables.items():
        if group is not None and name != group:
            continue
        for position in range(len(table.row_at)):
            row_id: str = f"{GROUP_IDS[name]}{position + 1}"
            state: dict[str, str] = row_state(lines, row_id)
            if state["status"] == STATUS_RESERVED and state["owner"] == clean_text(holder):
                found.append(row_id)
    return found


def release_rows(lines: list[str], holder: str) -> dict[str, Any]:
    """Mark every unused placeholder of `holder` released. Rows stay so ids after them do not shift."""
    released: list[str] = reserved_ids(lines, holder)
    for row_id in released:
        set_first_cell(lines, row_id, RELEASED_ITEM)
        set_cell(lines, row_id, "status", STATUS_RELEASED)
    return {"holder": holder, "released": released}


def fold_rows(lines: list[str], lane_lines: list[str], holder: str, today: date) -> dict[str, Any]:
    """Copy a lane's open items into the shared file: reserved ids first, then appended rows; release the rest."""
    mapping: dict[str, str] = {}
    for item in list_items(lane_lines, today):
        spare: list[str] = reserved_ids(lines, holder, item["group"])
        if spare:
            target: str = fill_reserved(lines, spare[0], item["item"], holder)["id"]
        else:
            target = add_row(lines, item["group"], item["item"], today)["id"]
        mapping[item["id"]] = target
    released: list[str] = release_rows(lines, holder)["released"]
    return {"holder": holder, "folded": mapping, "released": released}


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
    elif args.command == "reserve":
        result = reserve_rows(lines, args.group, args.count, args.holder, today)
    elif args.command == "release":
        result = release_rows(lines, args.holder)
    elif args.command == "fold":
        result = fold_rows(lines, read_lines(Path(args.lane_file)), args.holder, today)
    elif args.id:
        result = fill_reserved(lines, args.id, " ".join(args.text), args.holder)
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
    add.add_argument("--id", default=None, help="fill a reserved id instead of appending")
    add.add_argument("--holder", default=None, help="lane that reserved --id")
    assign: argparse.ArgumentParser = sub.add_parser("assign")
    assign.add_argument("row")
    assign.add_argument("agent")
    reserve: argparse.ArgumentParser = sub.add_parser("reserve", help="head only: fix ids for a lane")
    reserve.add_argument("group")
    reserve.add_argument("count", type=int)
    reserve.add_argument("--holder", required=True)
    sub.add_parser("release").add_argument("--holder", required=True)
    fold: argparse.ArgumentParser = sub.add_parser("fold", help="head only: merge a lane's items")
    fold.add_argument("lane_file")
    fold.add_argument("--holder", required=True)
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
