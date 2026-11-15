#!/usr/bin/env python3
"""The read-only ship gate: does a PR name real linked work, and is the repo under its open-PR cap?

Pure functions over text and files. It makes no model call, no network call and no `gh` call; the number of open pull
requests is passed in by the caller. It writes nothing.

Subcommands:
    check   read a PR body and print {"ok", "linked", "reason"} as JSON; exit 1 when nothing real is linked
    cap     read the config and print {"cap", "exceeded"} as JSON; exit 1 when --open reaches the cap"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import contracts  # noqa: E402
import miniyaml  # noqa: E402
import state_io  # noqa: E402

LINKED_HEADING: Final[str] = "Linked work"
DEFAULT_CAP: Final[int] = 5
FEATURE_SLUG: Final[re.Pattern[str]] = re.compile(r"\bfeature/[\w.-]+")
SECTION_REF: Final[re.Pattern[str]] = re.compile(r"section\s+(\d+)", re.IGNORECASE)
ACTION_REF: Final[re.Pattern[str]] = re.compile(r"\b([A-Z]\d+)\b")
FEATURE_PREFIX: Final[str] = "feature/"
PLACEHOLDER_PREFIX: Final[str] = "<"
ACTION_ITEMS_SCRIPT: Final[str] = "action-items"
STDIN_MARKER: Final[str] = "-"
END_STATE_REL: Final[str] = state_io.END_STATE_REL
SHIP_CAP_PATH: Final[str] = "ship.open_pr_cap"
AUTOPILOT_CAP_PATH: Final[str] = "autopilot.open_pr_cap"
MISSING_REASON: Final[str] = "no linked end-state section or open action item in the PR body"
EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
LINE_SEPARATOR: Final[str] = "\n"


def section_ids(end_state: str) -> set[str]:
    """The number of every real section row; placeholder rows (names starting with `<`) are skipped."""
    rows: list[contracts.SectionRow] | contracts.Invalid = contracts.parse_sections(end_state)
    if isinstance(rows, contracts.Invalid):
        return set()
    return {row.number for row in rows if not row.name.startswith(PLACEHOLDER_PREFIX)}


def open_action_item_ids(repo: Path) -> set[str]:
    """The id (A1, S2, D1) of every open action item; empty when the file is missing."""
    module: Any = _load.load(ACTION_ITEMS_SCRIPT)
    lines: list[str] = module.read_lines(repo / state_io.ACTION_ITEMS_REL)
    items: list[dict[str, Any]] = module.list_items(lines, date.today())
    return {item["id"] for item in items if module.is_open(item["status"])}


def links_in_body(pr_body: str) -> set[str]:
    """Every reference token in the body: a section number, an action id, or a feature/<slug>."""
    tokens: set[str] = set(SECTION_REF.findall(pr_body))
    tokens.update(ACTION_REF.findall(pr_body))
    tokens.update(FEATURE_SLUG.findall(pr_body))
    return tokens


def resolves(token: str, sections: set[str], action_ids: set[str]) -> bool:
    if token.startswith(FEATURE_PREFIX):
        return True
    return token in sections or token in action_ids


def check(pr_body: str, end_state: str, action_ids: set[str]) -> dict[str, Any]:
    sections: set[str] = section_ids(end_state)
    linked: list[str] = sorted(t for t in links_in_body(pr_body) if resolves(t, sections, action_ids))
    return {"ok": bool(linked), "linked": linked, "reason": "" if linked else MISSING_REASON}


def cap_from_config(config_text: str, default: int = DEFAULT_CAP) -> int:
    """`ship: open_pr_cap`, else `autopilot: open_pr_cap`, else `default`; a non-integer value gives `default`."""
    data: dict[str, Any] = miniyaml.parse(config_text)
    for path in (SHIP_CAP_PATH, AUTOPILOT_CAP_PATH):
        if miniyaml.get(data, path):
            return miniyaml.get_int(data, path, default)
    return default


def cap_exceeded(open_count: int, cap: int) -> bool:
    return open_count >= cap


def read_text_or_empty(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def read_body(source: str) -> str:
    if source == STDIN_MARKER:
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8", errors="replace")


def run_check(repo: Path, body_source: str, end_state_path: str | None) -> int:
    end_state_file: Path = Path(end_state_path) if end_state_path else repo / END_STATE_REL
    result: dict[str, Any] = check(read_body(body_source), read_text_or_empty(end_state_file), open_action_item_ids(repo))
    sys.stdout.write(json.dumps(result) + LINE_SEPARATOR)
    return EXIT_OK if result["ok"] else EXIT_REFUSED


def run_cap(config_path: str, open_count: int) -> int:
    cap: int = cap_from_config(read_text_or_empty(Path(config_path)))
    exceeded: bool = cap_exceeded(open_count, cap)
    sys.stdout.write(json.dumps({"cap": cap, "exceeded": exceeded}) + LINE_SEPARATOR)
    return EXIT_REFUSED if exceeded else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repo root (default: the current folder)")
    sub: Any = parser.add_subparsers(dest="command", required=True)
    check_parser: argparse.ArgumentParser = sub.add_parser("check", help="check a PR body for linked work")
    check_parser.add_argument("--body", default=STDIN_MARKER, help="PR body file, or - for stdin (default)")
    check_parser.add_argument("--end-state", default=None, help="end state file (default: <repo>/.harness/end-state.md)")
    cap_parser: argparse.ArgumentParser = sub.add_parser("cap", help="compare the open PR count to the cap")
    cap_parser.add_argument("--config", required=True, help="config file; a missing file reads as empty")
    cap_parser.add_argument("--open", type=int, required=True, help="number of open pull requests, counted by the caller")
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    if args.command == "check":
        return run_check(Path(args.repo), args.body, args.end_state)
    return run_cap(args.config, args.open)


if __name__ == "__main__":
    sys.exit(main())
