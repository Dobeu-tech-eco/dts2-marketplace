#!/usr/bin/env python3
"""Small helpers the hooks/*.sh scripts call, so no hook carries an inline program.

json-field KEY [--file PATH] [--or-empty]   print one top-level field of a JSON object (stdin or PATH); exit 1 on bad JSON
lessons-tail N                              scope-check --lessons JSON on stdin -> the last N lessons, one per line
open-items FILE N                           the last N `- ` bullets under the `## Open items` heading of FILE
open-action-items FILE N                    the first N open rows of an action-items table
stop-timeout HOOKS_JSON DEFAULT             the Stop hook timeout from hooks.json, DEFAULT when unreadable
block-reply                                 red-check output on stdin -> the Stop `decision: block` JSON"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Final

ENCODING: Final[str] = "utf-8"
OPEN_HEADING: Final[str] = "## Open items"
SECTION: Final[str] = "## "
ROW_START: Final[re.Pattern[str]] = re.compile(r"^(open|done)")
BLOCK_TAIL_CHARS: Final[int] = 2000
BLOCK_REASON: Final[str] = "dts2-harness stop checks are red; fix before stopping:\n"
ROW_WINDOW: Final[int] = 3


def read_text(path: str) -> str:
    with open(path, encoding=ENCODING, errors="replace") as handle:
        return handle.read()


def json_field(args: list[str]) -> int:
    path: str | None = None
    or_empty: bool = "--or-empty" in args
    positional: list[str] = [a for a in args if a != "--or-empty"]
    if "--file" in positional:
        index: int = positional.index("--file")
        path = positional[index + 1]
        del positional[index:index + 2]
    data: Any = json.loads(read_text(path) if path else sys.stdin.read())
    value: Any = data.get(positional[0], "")
    print("" if or_empty and not value else value)
    return 0


def lessons_tail(count: int) -> int:
    lessons: list[str] = json.load(sys.stdin)["lessons"][-count:]
    for line in lessons:
        print(line)
    return 0


def open_items(path: str, count: int) -> int:
    inside: bool = False
    bullets: list[str] = []
    for line in read_text(path).splitlines():
        if inside:
            if line.startswith(SECTION):
                inside = False
                continue
        elif line.startswith(OPEN_HEADING):
            inside = True
            continue
        if inside and line.startswith("- "):
            bullets.append(line)
    for line in bullets[-count:]:
        print(line)
    return 0


def row_is_open(line: str) -> bool:
    fields: list[str] = line.split("|")
    if len(fields) <= ROW_WINDOW:
        return False
    for index in range(len(fields) - 2, len(fields) - ROW_WINDOW - 2, -1):
        if index < 1:
            break
        cell: str = fields[index].strip(" \t")
        if ROW_START.match(cell):
            return cell.startswith("open")
    return False


def open_action_items(path: str, count: int) -> int:
    shown: int = 0
    for line in read_text(path).splitlines():
        if shown >= count:
            break
        if row_is_open(line):
            print(line)
            shown += 1
    return 0


def stop_timeout(path: str, default: str) -> int:
    try:
        value: Any = json.loads(read_text(path))["hooks"]["Stop"][0]["hooks"][0]["timeout"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        value = default
    print(value)
    return 0


def block_reply() -> int:
    print(json.dumps({"decision": "block", "reason": BLOCK_REASON + sys.stdin.read()[-BLOCK_TAIL_CHARS:]}))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    try:
        if verb == "json-field":
            return json_field(rest)
        if verb == "lessons-tail":
            return lessons_tail(int(rest[0]))
        if verb == "open-items":
            return open_items(rest[0], int(rest[1]))
        if verb == "open-action-items":
            return open_action_items(rest[0], int(rest[1]))
        if verb == "stop-timeout":
            return stop_timeout(rest[0], rest[1])
        if verb == "block-reply":
            return block_reply()
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
