#!/usr/bin/env python3
"""The read-only router: from the state on disk, say which command comes next.

It walks a fixed ladder of rungs 0 to 10 and stops at the first one that applies. It reads files and makes no model call,
no network call and no `gh` call; the number of open pull requests is passed in by the caller. The only file it writes is
`.harness/STOP`, and only a person removes that file.

Subcommands:
    next     print the decision as JSON: rung, state, next_command, reason, blocked_on
    status   print one line per rung, with `>` marking the current one
    stop     write `.harness/STOP` with a reason (requires --reason)"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import contracts  # noqa: E402
import mdparse  # noqa: E402
import roadmap  # noqa: E402
import state_io  # noqa: E402

STOP_REL: Final[str] = state_io.rel("STOP")
HOME_ENV: Final[str] = "DTS2_HOME"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
COMPOSIO_DECISION: Final[str] = "composio.json"
PARALLEL_MIN: Final[int] = 2
PLACEHOLDER_PREFIX: Final[str] = "<"
TODO_STATUS: Final[str] = "todo"
DONE_STATUS: Final[str] = "done"
APPROVED_PREFIX: Final[str] = "approved"
NO_PREFIX: Final[str] = "no"
HEADING_PREFIX: Final[str] = "## "
DEPLOY_HEADING: Final[str] = "## Deploy"
HEADER_LINE: Final[re.Pattern[str]] = re.compile(r"^- ([A-Za-z]+): *(.*)$")
DEPLOY_PLANNED: Final[re.Pattern[str]] = re.compile(r"^\s*status:\s*planned\b", re.MULTILINE)
LINE_SEPARATOR: Final[str] = "\n"
CURRENT_MARK: Final[str] = ">"
OTHER_MARK: Final[str] = " "
STOP_BLOCK: Final[str] = "a person deletes .harness/STOP"
NO_SCOPE_BLOCK: Final[str] = "the end state has no sections; run setup"
ACTION_ITEMS_SCRIPT: Final[str] = "action-items"


@dataclass(frozen=True)
class Context:
    repo: Path
    home: Path
    open_prs: int | None
    end_state: str | None


Verdict = tuple[str | None, str, str | None]  # next_command, reason, blocked_on
Check = Callable[[Context], Verdict | None]


def resolve_home(home: Path | None) -> Path:
    if home is not None:
        return home
    configured: str = os.environ.get(HOME_ENV, "")
    return Path(configured) if configured else Path.home() / DEFAULT_HOME_DIR


def header_values(end_state: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in end_state.splitlines():
        if line.startswith(HEADING_PREFIX):
            break
        match: re.Match[str] | None = HEADER_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def as_number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def clarity_below_threshold(header: dict[str, str]) -> bool:
    clarity: float | None = as_number(header.get("clarity"))
    threshold: float | None = as_number(header.get("threshold"))
    return clarity is not None and threshold is not None and clarity < threshold


def count_sections(end_state: str) -> tuple[int, int]:
    """(sections not done, sections still todo), placeholders skipped."""
    rows: list[contracts.SectionRow] | contracts.Invalid = contracts.parse_sections(end_state)
    if isinstance(rows, contracts.Invalid):
        return 0, 0
    real: list[contracts.SectionRow] = [row for row in rows if not row.name.startswith(PLACEHOLDER_PREFIX)]
    return sum(1 for row in real if row.status != DONE_STATUS), sum(1 for row in real if row.status == TODO_STATUS)


def open_action_items(repo: Path) -> int:
    module: Any = _load.load(ACTION_ITEMS_SCRIPT)
    lines: list[str] = module.read_lines(repo / state_io.ACTION_ITEMS_REL)
    items: list[dict[str, Any]] = module.list_items(lines, date.today())
    return sum(1 for item in items if module.is_open(item["status"]))


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def check_stopped(ctx: Context) -> Verdict | None:
    if not (ctx.repo / STOP_REL).exists():
        return None
    return None, "a STOP file is present", STOP_BLOCK


def check_composio(ctx: Context) -> Verdict | None:
    if (ctx.home / COMPOSIO_DECISION).exists():
        return None
    return "composio", "no Composio decision is recorded yet", None


def check_end_state_missing(ctx: Context) -> Verdict | None:
    if ctx.end_state is not None:
        return None
    return "setup", "there is no end state file", None


def check_end_state_approved(ctx: Context) -> Verdict | None:
    header: dict[str, str] = header_values(ctx.end_state or "")
    if not header.get("status", "").lower().startswith(APPROVED_PREFIX):
        return "setup", "the end state is not approved yet", None
    continued: str = header.get("continuedAnyway", "").lower()
    if clarity_below_threshold(header) and continued.startswith(NO_PREFIX):
        return "setup", "the end state clarity is below its threshold", None
    return None


def check_roadmap(ctx: Context) -> Verdict | None:
    info: dict[str, Any] = roadmap.status(ctx.repo)
    if info["approved"]:
        return None
    phrase: str | None = info["lock_phrase"]
    if phrase is None:
        return None, "the roadmap has no scope to approve", NO_SCOPE_BLOCK
    blocked: str = f"the owner says \"lock it in\" in chat, or types: {phrase} (any harness: approvals.py lock-roadmap)"
    return None, "the roadmap scope is not approved yet", blocked


def check_sections(ctx: Context) -> Verdict | None:
    outstanding, todo = count_sections(ctx.end_state or "")
    if outstanding == 0:
        return None
    command: str = "dpp" if todo >= PARALLEL_MIN else "run"
    return command, f"{plural(outstanding, 'section')} not done, {todo} still to do", None


def check_pull_requests(ctx: Context) -> Verdict | None:
    if ctx.open_prs is None or ctx.open_prs <= 0:
        return None
    return "pr-sweep", f"{plural(ctx.open_prs, 'pull request')} open", None


def check_action_items(ctx: Context) -> Verdict | None:
    count: int = open_action_items(ctx.repo)
    if count == 0:
        return None
    return "action-items", f"{plural(count, 'action item')} open", None


def check_deploy(ctx: Context) -> Verdict | None:
    body: str = mdparse.section(ctx.end_state or "", DEPLOY_HEADING)
    if DEPLOY_PLANNED.search(body) is None:
        return None
    return "run", "a deploy is planned and not live yet", None


def check_acceptance(ctx: Context) -> Verdict | None:
    count: int = roadmap.status(ctx.repo)["acceptance_outstanding"]
    if count == 0:
        return None
    return "run", f"{plural(count, 'acceptance criterion')} not met yet".replace("criterions", "criteria"), None


def check_complete(_ctx: Context) -> Verdict | None:
    return "learn", "every rung is clear", None


RUNGS: Final[tuple[tuple[int, str, Check], ...]] = (
    (0, "stopped", check_stopped),
    (1, "no-composio-decision", check_composio),
    (2, "no-end-state", check_end_state_missing),
    (3, "end-state-not-approved", check_end_state_approved),
    (4, "roadmap-not-approved", check_roadmap),
    (5, "sections-outstanding", check_sections),
    (6, "open-pull-requests", check_pull_requests),
    (7, "action-items-open", check_action_items),
    (8, "deploy-planned", check_deploy),
    (9, "acceptance-outstanding", check_acceptance),
    (10, "complete", check_complete),
)


def make_context(repo: Path, home: Path | None, open_prs: int | None) -> Context:
    return Context(repo, resolve_home(home), open_prs, roadmap.read_end_state(repo))


def decide(repo: Path, home: Path | None = None, open_prs: int | None = None) -> dict[str, Any]:
    ctx: Context = make_context(repo, home, open_prs)
    for rung, state, check in RUNGS:
        verdict: Verdict | None = check(ctx)
        if verdict is not None:
            command, reason, blocked = verdict
            return {"rung": rung, "state": state, "next_command": command, "reason": reason, "blocked_on": blocked}
    raise AssertionError("the last rung always applies")


def ladder(repo: Path, home: Path | None = None, open_prs: int | None = None) -> list[dict[str, Any]]:
    current: int = decide(repo, home, open_prs)["rung"]
    return [{"rung": rung, "state": state, "current": rung == current} for rung, state, _ in RUNGS]


def stop(repo: Path, reason: str) -> Path:
    return state_io.atomic_write(repo / STOP_REL, reason + LINE_SEPARATOR)


def render_ladder(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        f"{CURRENT_MARK if e['current'] else OTHER_MARK} {e['rung']} {e['state']}" for e in entries
    ]
    return LINE_SEPARATOR.join(lines) + LINE_SEPARATOR


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repo root (default: the current folder)")
    parser.add_argument("--open-prs", type=int, default=None, help="number of open pull requests, counted by the caller")
    sub: Any = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next", help="print the decision as JSON")
    sub.add_parser("status", help="print one line per rung")
    sub.add_parser("stop", help="write .harness/STOP").add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    repo: Path = Path(args.repo)
    if args.command == "next":
        sys.stdout.write(json.dumps(decide(repo, None, args.open_prs)) + LINE_SEPARATOR)
    elif args.command == "status":
        sys.stdout.write(render_ladder(ladder(repo, None, args.open_prs)))
    else:
        sys.stdout.write(json.dumps({"stopped": str(stop(repo, args.reason))}) + LINE_SEPARATOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
