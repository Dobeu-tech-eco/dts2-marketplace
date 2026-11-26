#!/usr/bin/env python3
"""Gap research: roadmap suggestions kept in `.harness/research/gaps.jsonl`.

The /dt:loop research step and /dt:learn record gaps, missed items and possible features here. A suggestion joins the
roadmap only through `apply`, which edits `.harness/end-state.md`. That changes the roadmap scope key, so the roadmap
needs a new lock, and the lock gate in approvals.py decides who may lock it. This script never locks anything.
A suggestion that needs a new paid service, account or sign-up is escalated to the owner as a Decisions action item
and can never be applied from here.

Subcommands:
    add      record a suggestion (section or criterion); prints the row as JSON
    list     print the ledger as JSON, optionally filtered by status
    apply    write a proposed suggestion into the end state; prints the old and new scope keys
    reject   mark a suggestion rejected with a reason"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap  # noqa: E402
import state_io  # noqa: E402
from state_io import atomic_write  # noqa: E402

LEDGER_REL: Final[str] = state_io.rel("research", "gaps.jsonl")
KINDS: Final[tuple[str, ...]] = ("section", "criterion")
SOURCES: Final[tuple[str, ...]] = ("loop", "learn", "checkpoint")
STATUS_PROPOSED: Final[str] = "proposed"
STATUS_ESCALATED: Final[str] = "escalated"
STATUS_APPLIED: Final[str] = "applied"
STATUS_REJECTED: Final[str] = "rejected"
STATUSES: Final[tuple[str, ...]] = (STATUS_PROPOSED, STATUS_ESCALATED, STATUS_APPLIED, STATUS_REJECTED)
ID_PREFIX: Final[str] = "G-"
ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^G-(\d+)$")
# Fail safe: a false match only sends a suggestion to the owner instead of the roadmap.
NEEDS_SERVICE: Final[re.Pattern[str]] = re.compile(
    r"\b(paid|subscriptions?|sign[- ]?ups?|accounts?|api[- ]?keys?|pricing|trials?|licen[cs]es?|billing|credit card)\b",
    re.IGNORECASE,
)
SECTIONS_HEADING: Final[str] = "## Sections"
ACCEPTANCE_HEADING: Final[str] = "## Acceptance criteria"
LEVEL_TWO: Final[str] = "## "
LEVEL_THREE: Final[str] = "### "
TABLE_PREFIX: Final[str] = "|"
BOX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^- \[[ xX]\] ")
INDENT: Final[tuple[str, ...]] = (" ", "\t")
ROW_DEFAULTS: Final[dict[str, str]] = {"complexity": "normal", "status": "todo"}
EMPTY_CELL: Final[str] = "-"
DECISIONS_GROUP: Final[str] = "Decisions"
EXIT_FAILURE: Final[int] = 1


class GapError(Exception):
    """A request this script refuses; the message says why."""


def clean(text: str) -> str:
    return roadmap.clean(text.replace(TABLE_PREFIX, "/"))


def ledger_path(repo: Path) -> Path:
    return repo / LEDGER_REL


def read_rows(repo: Path) -> list[dict[str, Any]]:
    path: Path = ledger_path(repo)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise GapError(f"{LEDGER_REL} line {number} is not valid JSON") from error
    return rows


def write_rows(repo: Path, rows: list[dict[str, Any]]) -> None:
    path: Path = ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def next_id(rows: list[dict[str, Any]]) -> str:
    numbers: list[int] = [int(m.group(1)) for row in rows if (m := ID_PATTERN.match(str(row.get("id", ""))))]
    return f"{ID_PREFIX}{max(numbers, default=0) + 1}"


def find_row(rows: list[dict[str, Any]], gap_id: str) -> dict[str, Any]:
    match: list[dict[str, Any]] = [row for row in rows if row.get("id") == gap_id]
    if not match:
        raise GapError(f"no suggestion {gap_id}")
    return match[0]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def escalate(repo: Path, row: dict[str, Any]) -> None:
    script: Path = Path(__file__).resolve().parent / "action-items.py"
    text: str = f"Gap research {row['id']} needs a new service or account: {row['text']}"
    command: list[str] = [sys.executable, "-I", str(script), str(repo), "add", DECISIONS_GROUP, text,
                          "--stamp", "gap-research", "--step", str(row["id"])]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, OSError) as error:
        detail: str = " ".join(filter(None, [getattr(error, "stdout", ""), getattr(error, "stderr", "")])).strip()
        raise GapError(f"could not add the Decisions item for {row['id']}: {detail or error}") from error


def escalate_existing(repo: Path, rows: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    """A repeat suggestion that now needs a service escalates the open row instead of being dropped."""
    if row.get("status") != STATUS_PROPOSED:
        return row
    escalate(repo, row)
    row.update(status=STATUS_ESCALATED, escalated=now())
    write_rows(repo, rows)
    return row


def add(repo: Path, kind: str, lane: str, text: str, why: str, source: str, needs_service: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = read_rows(repo)
    text, lane = clean(text), clean(lane)
    if not text or not lane:
        raise GapError("text and lane must not be empty")
    same: list[dict[str, Any]] = [r for r in rows if r.get("kind") == kind and str(r.get("text", "")).lower() == text.lower()
                                  and r.get("status") != STATUS_REJECTED]
    escalated: bool = needs_service or bool(NEEDS_SERVICE.search(f"{text} {why}"))
    if same:
        return escalate_existing(repo, rows, same[0]) if escalated else same[0]
    row: dict[str, Any] = {"id": next_id(rows), "kind": kind, "lane": lane, "text": text, "why": clean(why),
                           "source": source, "status": STATUS_ESCALATED if escalated else STATUS_PROPOSED,
                           "added": now()}
    if escalated:
        escalate(repo, row)
    write_rows(repo, [*rows, row])
    return row


def block_end(lines: list[str], start: int, prefix: str) -> int:
    later: list[int] = [i for i in range(start + 1, len(lines)) if lines[i].startswith(prefix)]
    return later[0] if later else len(lines)


def heading_index(lines: list[str], heading: str) -> int:
    found: list[int] = [i for i, line in enumerate(lines) if line.strip() == heading]
    if not found:
        raise GapError(f"end state has no '{heading}' heading")
    return found[0]


def insert_criterion(lines: list[str], lane: str, text: str) -> list[str]:
    start: int = heading_index(lines, ACCEPTANCE_HEADING)
    end: int = block_end(lines, start, LEVEL_TWO)
    lane_rows: list[int] = [i for i in range(start, end) if lines[i].startswith(LEVEL_THREE)
                            and lines[i][len(LEVEL_THREE):].strip().lower() == lane.lower()]
    if not lane_rows:
        cut: int = end
        while cut > start + 1 and not lines[cut - 1].strip():
            cut -= 1
        return [*lines[:cut], "", f"{LEVEL_THREE}{lane}", "", f"- [ ] {text}", *([""] if end < len(lines) else []),
                *lines[end:]]
    sub_end: int = min(block_end(lines, lane_rows[0], LEVEL_THREE), end)
    boxes: list[int] = [i for i in range(lane_rows[0], sub_end) if BOX_PATTERN.match(lines[i])]
    if not boxes:
        at: int = lane_rows[0] + 1
        while at < sub_end and not lines[at].strip():
            at += 1
        return [*lines[:lane_rows[0] + 1], "", f"- [ ] {text}", *([""] if at < len(lines) else []), *lines[at:]]
    at = boxes[-1] + 1
    while at < sub_end and lines[at].strip() and lines[at].startswith(INDENT):
        at += 1
    return [*lines[:at], f"- [ ] {text}", *lines[at:]]


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip(TABLE_PREFIX).split(TABLE_PREFIX)]


def insert_section(lines: list[str], lane: str, text: str) -> list[str]:
    start: int = heading_index(lines, SECTIONS_HEADING)
    end: int = block_end(lines, start, LEVEL_TWO)
    table: list[int] = [i for i in range(start, end) if lines[i].startswith(TABLE_PREFIX)]
    numbered: list[int] = [i for i in table if table_cells(lines[i])[0].isdigit()]
    if not table or not numbered:
        raise GapError("end state has no Sections table rows")
    header: list[str] = [cell.lower() for cell in table_cells(lines[table[0]])]
    number: int = max(int(table_cells(lines[i])[0]) for i in numbered) + 1
    values: dict[str, str] = {**ROW_DEFAULTS, "#": str(number), "section": text, "serves component": lane}
    row: str = "| " + " | ".join(values.get(name, EMPTY_CELL) for name in header) + " |"
    return [*lines[:numbered[-1] + 1], row, *lines[numbered[-1] + 1:]]


def scope_key(end_state: str) -> str | None:
    full: str | None = roadmap.scope_hash(end_state)
    return full[:roadmap.KEY_LENGTH] if full else None


def on_roadmap(lines: list[str], kind: str, text: str) -> bool:
    """True when a scope line of the same kind carries this text, compared case-insensitively."""
    prefix: str = "acceptance|" if kind == "criterion" else "section|"
    names: list[str] = [line.split("|", 2)[-1] for line in lines if line.startswith(prefix)]
    return text.lower() in {name.lower() for name in names}


def apply(repo: Path, gap_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = read_rows(repo)
    row: dict[str, Any] = find_row(rows, gap_id)
    if row["status"] != STATUS_PROPOSED:
        raise GapError(f"{gap_id} is {row['status']}; only proposed suggestions can be applied")
    before: str | None = roadmap.read_end_state(repo)
    if before is None:
        raise GapError("no end state")
    pending: str | None = row.get("pending_key_after")
    if pending is not None and pending == scope_key(before):
        return finish_apply(repo, rows, row, row.get("pending_key_before"), pending)
    if on_roadmap(roadmap.scope_lines(before), row["kind"], row["text"]):
        raise GapError(f"{gap_id} is already on the roadmap")
    insert = insert_criterion if row["kind"] == "criterion" else insert_section
    after: str = "\n".join(insert(before.splitlines(), row["lane"], row["text"])) + "\n"
    added: list[str] = list((Counter(roadmap.scope_lines(after)) - Counter(roadmap.scope_lines(before))).elements())
    if len(added) != 1 or not on_roadmap(added, row["kind"], row["text"]) or scope_key(after) == scope_key(before):
        raise GapError("the end state layout is not one this script can edit; add it by hand")
    row.update(pending_key_before=scope_key(before), pending_key_after=scope_key(after))
    write_rows(repo, rows)
    atomic_write(repo / state_io.END_STATE_REL, after)
    return finish_apply(repo, rows, row, scope_key(before), scope_key(after))


def finish_apply(repo: Path, rows: list[dict[str, Any]], row: dict[str, Any], key_before: str | None,
                 key_after: str | None) -> dict[str, Any]:
    """Mark the row applied. A rerun after the end state was written but the ledger was not lands here too."""
    row.pop("pending_key_before", None)
    row.pop("pending_key_after", None)
    row.update(status=STATUS_APPLIED, applied=now(), key_before=key_before, key_after=key_after)
    write_rows(repo, rows)
    return {**row, "next": "the roadmap scope changed; it needs a new lock through approvals.py"}


def reject(repo: Path, gap_id: str, reason: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = read_rows(repo)
    row: dict[str, Any] = find_row(rows, gap_id)
    if row["status"] == STATUS_APPLIED:
        raise GapError(f"{gap_id} is already applied; edit the end state instead")
    row.update(status=STATUS_REJECTED, reason=clean(reason), rejected=now())
    write_rows(repo, rows)
    return row


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    new: argparse.ArgumentParser = sub.add_parser("add")
    new.add_argument("--kind", choices=KINDS, required=True)
    new.add_argument("--lane", required=True, help="component the section serves or the criterion belongs to")
    new.add_argument("--text", required=True)
    new.add_argument("--why", default="")
    new.add_argument("--source", choices=SOURCES, default="loop")
    new.add_argument("--needs-service", action="store_true", help="needs a new paid service, account or sign-up")
    sub.add_parser("list").add_argument("--status", choices=STATUSES, default=None)
    sub.add_parser("apply").add_argument("id")
    drop: argparse.ArgumentParser = sub.add_parser("reject")
    drop.add_argument("id")
    drop.add_argument("--reason", required=True)
    return parser


def run(args: argparse.Namespace) -> Any:
    repo: Path = Path(args.repo)
    if args.command == "add":
        return add(repo, args.kind, args.lane, args.text, args.why, args.source, args.needs_service)
    if args.command == "list":
        return [row for row in read_rows(repo) if args.status in (None, row["status"])]
    if args.command == "apply":
        return apply(repo, args.id)
    return reject(repo, args.id, args.reason)


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        result: Any = run(args)
    except GapError as error:
        print(json.dumps({"error": str(error)}))
        return EXIT_FAILURE
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
