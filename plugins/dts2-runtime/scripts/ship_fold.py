#!/usr/bin/env python3
"""The read-only fold planner: which stray pull requests may the ship step fold into the current one.

A stray is foldable only when every test passes: opened by the same author as the ship branch, the same base, not a
draft, not a fork (cross-repository) PR, not the ship PR itself, mergeable, green CI, and touching only files the ship
branch also touches. Anything the planner cannot confirm is refused, so a missing or malformed field never makes a stray
foldable. Every other stray is listed with the first reason it fails. It reads the input it is given and makes no model
call, no network call and no `gh` call.

Subcommands:
    plan     print {"foldable": [numbers], "listed": [{"number", "reason"}]} as JSON
             (requires --input, --author, --base and --files-file; optional --self to exclude the ship PR's own number)"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

CI_GREEN: Final[str] = "green"
FOLDABLE_CI: Final[frozenset[str]] = frozenset({CI_GREEN})
MERGEABLE_WORDS: Final[frozenset[str]] = frozenset({"mergeable", "true"})
TRUE_WORDS: Final[frozenset[str]] = frozenset({"true"})
STDIN_MARKER: Final[str] = "-"
LINE_SEPARATOR: Final[str] = "\n"
EXIT_OK: Final[int] = 0
EXIT_INPUT: Final[int] = 2
REASON_AUTHOR: Final[str] = "opened by a different author"
REASON_BASE: Final[str] = "targets a different base"
REASON_DRAFT: Final[str] = "is a draft"
REASON_FORK: Final[str] = "is a fork PR"
REASON_SELF: Final[str] = "is this PR"
REASON_MERGEABLE: Final[str] = "not mergeable"
REASON_NO_FILES: Final[str] = "has no file list"
REASON_FILES: Final[str] = "changes files outside this PR"
REASON_DUPLICATE: Final[str] = "duplicate PR number"


class StrayError(ValueError):
    """A stray dict that cannot be parsed into the fields the planner needs."""


def as_int(value: Any) -> int:
    """An int from an int or an all-digit string; a bool or anything else is refused."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise StrayError(f"bad PR number {value!r}")
    text: str = str(value).strip()
    if not text.lstrip("-").isdigit():
        raise StrayError(f"bad PR number {value!r}")
    return int(text)


def as_bool(value: Any, default: bool) -> bool:
    """A bool from a real bool or the words true/false; anything else gives `default`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() in TRUE_WORDS
    return default


def is_mergeable(value: Any) -> bool:
    """True only for the bool True or the word MERGEABLE/true; every other value (UNKNOWN, CONFLICTING, false) is False."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in MERGEABLE_WORDS


def file_tuple(value: Any) -> tuple[str, ...] | None:
    """A tuple of paths from a non-empty list of strings; a missing, null, empty or non-list value is None (unknown)."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(path, str) for path in value):
        return None
    return tuple(value)


@dataclass(frozen=True)
class Stray:
    number: int
    author: str
    base: str
    files: tuple[str, ...] | None
    mergeable: bool
    ci: str
    draft: bool
    cross_repo: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Stray:
        return cls(
            number=as_int(raw["number"]),
            author=str(raw["author"]),
            base=str(raw["base"]),
            files=file_tuple(raw.get("files")),
            mergeable=is_mergeable(raw.get("mergeable")),
            ci=str(raw.get("ci", "")).strip().lower(),
            # Fail closed: a missing or unrecognized draft/fork flag is treated as draft/fork, so only an
            # explicit false lets a stray fold. A legitimate stray always carries isDraft and isCrossRepository.
            draft=as_bool(raw.get("draft"), True),
            cross_repo=as_bool(raw.get("cross_repo"), True),
        )


def fold_reason(stray: Stray, ship_author: str, ship_base: str, ship_files: frozenset[str]) -> str | None:
    """None when the stray is foldable, else the first failing reason in the documented order (fail closed)."""
    if stray.author != ship_author:
        return REASON_AUTHOR
    if stray.base != ship_base:
        return REASON_BASE
    if stray.draft:
        return REASON_DRAFT
    if stray.cross_repo:
        return REASON_FORK
    if not stray.mergeable:
        return REASON_MERGEABLE
    if stray.ci not in FOLDABLE_CI:
        return f"CI is {stray.ci or 'unknown'}"
    if stray.files is None:
        return REASON_NO_FILES
    if not frozenset(stray.files) <= ship_files:
        return REASON_FILES
    return None


def duplicate_numbers(strays: list[Stray]) -> set[int]:
    seen: set[int] = set()
    repeated: set[int] = set()
    for stray in strays:
        repeated.add(stray.number) if stray.number in seen else seen.add(stray.number)
    return repeated


def plan_reason(stray: Stray, ctx: PlanContext, repeated: set[int]) -> str | None:
    if stray.number in repeated:
        return REASON_DUPLICATE
    if stray.number == ctx.exclude:
        return REASON_SELF
    return fold_reason(stray, ctx.author, ctx.base, ctx.files)


@dataclass(frozen=True)
class PlanContext:
    author: str
    base: str
    files: frozenset[str]
    exclude: int | None


def fold_plan(
    strays: list[dict[str, Any]], ship_author: str, ship_base: str, ship_files: list[str], exclude: int | None = None
) -> dict[str, Any]:
    ctx: PlanContext = PlanContext(ship_author, ship_base, frozenset(ship_files), exclude)
    parsed: list[Stray] = sorted((Stray.from_dict(raw) for raw in strays), key=lambda item: item.number)
    repeated: set[int] = duplicate_numbers(parsed)
    foldable: list[int] = []
    listed: list[dict[str, Any]] = []
    for stray in parsed:
        reason: str | None = plan_reason(stray, ctx, repeated)
        foldable.append(stray.number) if reason is None else listed.append({"number": stray.number, "reason": reason})
    return {"foldable": foldable, "listed": listed}


def read_strays(source: str) -> list[dict[str, Any]]:
    text: str = sys.stdin.read() if source == STDIN_MARKER else Path(source).read_text(encoding="utf-8")
    data: Any = json.loads(text)
    if not isinstance(data, list):
        raise StrayError("the strays input must be a JSON list")
    return data


def read_ship_files(path: str) -> list[str]:
    lines: list[str] = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    sub: Any = parser.add_subparsers(dest="command", required=True)
    plan: argparse.ArgumentParser = sub.add_parser("plan", help="print the fold plan as JSON")
    plan.add_argument("--input", required=True, help="JSON list of strays, or - for stdin")
    plan.add_argument("--author", required=True, help="GitHub login of the ship branch's author")
    plan.add_argument("--base", required=True, help="base branch of the ship branch")
    plan.add_argument("--files-file", required=True, help="text file, one ship-branch path per line")
    plan.add_argument("--self", dest="exclude", type=int, default=None, help="the ship PR's own number, always excluded")
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        strays: list[dict[str, Any]] = read_strays(args.input)
        ship_files: list[str] = read_ship_files(args.files_file)
        plan: dict[str, Any] = fold_plan(strays, args.author, args.base, ship_files, args.exclude)
    except (StrayError, OSError, ValueError) as error:
        sys.stderr.write(f"ship_fold: {error}{LINE_SEPARATOR}")
        return EXIT_INPUT
    sys.stdout.write(json.dumps(plan) + LINE_SEPARATOR)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
