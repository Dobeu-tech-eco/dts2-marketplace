#!/usr/bin/env python3
"""The read-only fold planner: which stray pull requests may the ship step fold into the current one.

A stray is foldable only when it was opened by the same author as the ship branch, targets the same base, touches only
files the ship branch also touches, is mergeable and has green CI. Every other stray is listed with the first reason it
fails. It reads the input it is given and makes no model call, no network call and no `gh` call.

Subcommands:
    plan     print {"foldable": [numbers], "listed": [{"number", "reason"}]} as JSON
             (requires --input, --author, --base and --files-file)"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

CI_GREEN: Final[str] = "green"
CI_UNKNOWN: Final[str] = "unknown"
FOLDABLE_CI: Final[frozenset[str]] = frozenset({CI_GREEN})
STDIN_MARKER: Final[str] = "-"
LINE_SEPARATOR: Final[str] = "\n"
REASON_AUTHOR: Final[str] = "opened by a different author"
REASON_BASE: Final[str] = "targets a different base"
REASON_MERGEABLE: Final[str] = "not mergeable"
REASON_FILES: Final[str] = "changes files outside this PR"


@dataclass(frozen=True)
class Stray:
    number: int
    author: str
    base: str
    files: tuple[str, ...]
    mergeable: bool
    ci: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Stray:
        return cls(
            number=int(raw["number"]),
            author=str(raw["author"]),
            base=str(raw["base"]),
            files=tuple(str(path) for path in raw.get("files") or ()),
            mergeable=bool(raw["mergeable"]),
            ci=str(raw.get("ci", CI_UNKNOWN)),
        )


def fold_reason(stray: Stray, ship_author: str, ship_base: str, ship_files: frozenset[str]) -> str | None:
    """None when the stray is foldable, else the first failing reason in the documented order."""
    if stray.author != ship_author:
        return REASON_AUTHOR
    if stray.base != ship_base:
        return REASON_BASE
    if not stray.mergeable:
        return REASON_MERGEABLE
    if stray.ci not in FOLDABLE_CI:
        return f"CI is {stray.ci}"
    if not frozenset(stray.files) <= ship_files:
        return REASON_FILES
    return None


def fold_plan(
    strays: list[dict[str, Any]], ship_author: str, ship_base: str, ship_files: list[str]
) -> dict[str, Any]:
    allowed: frozenset[str] = frozenset(ship_files)
    parsed: list[Stray] = sorted((Stray.from_dict(raw) for raw in strays), key=lambda item: item.number)
    foldable: list[int] = []
    listed: list[dict[str, Any]] = []
    for stray in parsed:
        reason: str | None = fold_reason(stray, ship_author, ship_base, allowed)
        if reason is None:
            foldable.append(stray.number)
        else:
            listed.append({"number": stray.number, "reason": reason})
    return {"foldable": foldable, "listed": listed}


def read_strays(source: str) -> list[dict[str, Any]]:
    text: str = sys.stdin.read() if source == STDIN_MARKER else Path(source).read_text(encoding="utf-8")
    return json.loads(text)


def read_ship_files(path: str) -> list[str]:
    lines: list[str] = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    sub: Any = parser.add_subparsers(dest="command", required=True)
    plan: argparse.ArgumentParser = sub.add_parser("plan", help="print the fold plan as JSON")
    plan.add_argument("--input", required=True, help="JSON file holding a list of strays, or - for stdin")
    plan.add_argument("--author", required=True, help="author of the ship branch")
    plan.add_argument("--base", required=True, help="base branch of the ship branch")
    plan.add_argument("--files-file", required=True, help="text file, one ship-branch path per line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    plan: dict[str, Any] = fold_plan(
        read_strays(args.input), args.author, args.base, read_ship_files(args.files_file)
    )
    sys.stdout.write(json.dumps(plan) + LINE_SEPARATOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
