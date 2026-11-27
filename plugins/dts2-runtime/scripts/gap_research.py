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
    reject   mark a suggestion rejected with a reason
    resolve  mark an open row resolved with a note (how the gap was closed)
    pass     the setup gap pass: scan the end state and roadmap, add one "gap" row per new finding, and write
             `.harness/research/gap-pass.json` for the current roadmap scope key

The gap pass is the first loop gate. The roadmap does not lock (approvals.py) until `lock_block` returns None: a pass ran
for exactly the current scope key and no "gap" row is open. A gap is open while proposed or escalated and is dispositioned
by `resolve` or `reject` (`apply` refuses a "gap" row). The pass is deterministic and line based, over
`.harness/end-state.md` and, when present, `.harness/roadmap.md`. Headings are never scanned, and the dependency and
assumption checks read prose and list lines only (a table row names components, so it would match "api" by accident). The categories:
    owner       a table row whose owner or lane column (header contains "owner" or "lane") is empty, "-", "tbd" or "?"
    section     an acceptance criterion under a "### <lane>" heading whose lane no Sections row serves
                (the "serves component", "lane" or "owner" column)
    dependency  a line mentioning a dependency, service, vendor or API with no price, cost, free or "$" on it
    assumption  a line containing "assume", "assumption" or "unverified" and not the word "verified"
In gap-pass.json, "found" counts new rows, "open" lists every open gap id and "counts" tallies those open rows by category."""
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
GAP_KIND: Final[str] = "gap"
CATEGORIES: Final[tuple[str, ...]] = ("owner", "section", "dependency", "assumption")
PASS_REL: Final[str] = state_io.rel("research", "gap-pass.json")
ROADMAP_VIEW_REL: Final[str] = roadmap.ROADMAP_REL
PASS_LANE: Final[str] = "setup"
PLACEHOLDER_MARK: Final[str] = roadmap.PLACEHOLDER_PREFIX
SOURCES: Final[tuple[str, ...]] = ("loop", "learn", "checkpoint")
STATUS_PROPOSED: Final[str] = "proposed"
STATUS_ESCALATED: Final[str] = "escalated"
STATUS_APPLIED: Final[str] = "applied"
STATUS_REJECTED: Final[str] = "rejected"
STATUS_RESOLVED: Final[str] = "resolved"
STATUSES: Final[tuple[str, ...]] = (STATUS_PROPOSED, STATUS_ESCALATED, STATUS_APPLIED, STATUS_REJECTED, STATUS_RESOLVED)
OPEN_STATUSES: Final[tuple[str, ...]] = (STATUS_PROPOSED, STATUS_ESCALATED)
UNSET_CELLS: Final[tuple[str, ...]] = ("", "-", "tbd", "?")
OWNER_HEADERS: Final[tuple[str, ...]] = ("owner", "lane")
LANE_HEADERS: Final[tuple[str, ...]] = ("serves component", "lane", "owner")
DEPENDENCY_WORDS: Final[re.Pattern[str]] = re.compile(r"\b(depend(s|ed|ing|ency|encies)?|services?|vendors?|apis?)\b", re.IGNORECASE)
PRICED: Final[re.Pattern[str]] = re.compile(r"\$|\b(price[sd]?|pricing|costs?|free)\b", re.IGNORECASE)
ASSUMPTION_WORDS: Final[re.Pattern[str]] = re.compile(r"\b(assum(e[sd]?|ing|ptions?)|unverified)\b", re.IGNORECASE)
VERIFIED: Final[re.Pattern[str]] = re.compile(r"(?<![a-z])verified", re.IGNORECASE)
SEPARATOR_CELL: Final[re.Pattern[str]] = re.compile(r"^:?-{2,}:?$")
LIST_MARKER: Final[re.Pattern[str]] = re.compile(r"^(- \[[ xX]\] |[-*] )")
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
    if row.get("status") != STATUS_PROPOSED and not row.get("escalation_pending"):
        return row
    row.update(status=STATUS_ESCALATED, escalated=now(), escalation_pending=True)
    write_rows(repo, rows)
    escalate(repo, row)
    row.pop("escalation_pending")
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
        retry: bool = escalated or bool(same[0].get("escalation_pending"))
        return escalate_existing(repo, rows, same[0]) if retry else same[0]
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
    if row.get("kind") == GAP_KIND:
        raise GapError(f"{gap_id} is a gap; close it with resolve or reject, not apply")
    if row["status"] != STATUS_PROPOSED:
        raise GapError(f"{gap_id} is {row['status']}; only proposed suggestions can be applied")
    if NEEDS_SERVICE.search(f"{row['text']} {row.get('why', '')}"):
        raise GapError(f"{gap_id} needs a new service or account; it goes to the owner, not the roadmap")
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
    if row["status"] == STATUS_RESOLVED:
        raise GapError(f"{gap_id} is already resolved")
    current: str | None = roadmap.read_end_state(repo)
    pending: str | None = row.get("pending_key_after")
    if pending is not None and current is not None and pending == scope_key(current):
        raise GapError(f"{gap_id} is already in the end state; rerun apply to finish it")
    row.update(status=STATUS_REJECTED, reason=clean(reason), rejected=now())
    write_rows(repo, rows)
    return row


def resolve(repo: Path, gap_id: str, note: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = read_rows(repo)
    row: dict[str, Any] = find_row(rows, gap_id)
    if row["status"] not in OPEN_STATUSES:
        raise GapError(f"{gap_id} is already {row['status']}; only an open row can be resolved")
    if not clean(note):
        raise GapError("a resolution needs a note")
    row.update(status=STATUS_RESOLVED, note=clean(note), resolved=now())
    write_rows(repo, rows)
    return row


def open_gaps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == GAP_KIND and row.get("status") in OPEN_STATUSES]


def is_unset(cell: str) -> bool:
    return cell.strip().lower() in UNSET_CELLS


def table_blocks(lines: list[str]) -> list[list[list[str]]]:
    """Each table as a list of cell rows, header first, separator rows dropped."""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in [*lines, ""]:
        if line.startswith(TABLE_PREFIX):
            cells: list[str] = table_cells(line)
            if not all(SEPARATOR_CELL.match(cell) for cell in cells if cell) or not any(cells):
                current.append(cells)
        elif current:
            blocks.append(current)
            current = []
    return blocks


def column(header: list[str], names: tuple[str, ...], exact: bool = False) -> int | None:
    lowered: list[str] = [cell.lower() for cell in header]
    for index, cell in enumerate(lowered):
        if cell in names if exact else any(name in cell for name in names):
            return index
    return None


def owner_findings(lines: list[str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for block in table_blocks(lines):
        header, rows = block[0], block[1:]
        owner: int | None = column(header, OWNER_HEADERS)
        name: int | None = column(header, ("section", "item", "name"), exact=True)
        if owner is None:
            continue
        for cells in rows:
            if len(cells) <= owner or not is_unset(cells[owner]) or cells[0].startswith(PLACEHOLDER_MARK):
                continue
            label: str = cells[name] if name is not None and len(cells) > name else cells[min(1, len(cells) - 1)]
            if label and not label.startswith(PLACEHOLDER_MARK):
                found.append(("owner", PASS_LANE, f"{clean(label)} has no owner"))
    return found


def served_lanes(lines: list[str]) -> set[str]:
    lanes: set[str] = set()
    for block in table_blocks(lines):
        index: int | None = column(block[0], LANE_HEADERS, exact=True)
        if index is not None and column(block[0], ("section",), exact=True) is not None:
            lanes |= {cells[index].lower() for cells in block[1:] if len(cells) > index and not is_unset(cells[index])}
    return lanes


def section_findings(end_state: str) -> list[tuple[str, str, str]]:
    lanes: set[str] = served_lanes(end_state.splitlines())
    if not lanes:
        return []
    found: list[tuple[str, str, str]] = []
    in_acceptance: bool = False
    lane: str = ""
    for line in end_state.splitlines():
        if line.startswith(LEVEL_TWO):
            in_acceptance = line.strip() == ACCEPTANCE_HEADING
            lane = ""
        elif in_acceptance and line.startswith(LEVEL_THREE):
            lane = line[len(LEVEL_THREE):].strip()
        elif in_acceptance and lane and BOX_PATTERN.match(line) and lane.lower() not in lanes:
            text: str = clean(BOX_PATTERN.sub("", line))
            if text and not text.startswith(PLACEHOLDER_MARK):
                found.append(("section", lane, f"no section serves lane {lane}: {text}"))
    return found


def line_findings(lines: list[str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for line in lines:
        if line.startswith((TABLE_PREFIX, "#")):
            continue
        text: str = clean(LIST_MARKER.sub("", line))
        if not text or text.startswith(PLACEHOLDER_MARK):
            continue
        if DEPENDENCY_WORDS.search(text) and not PRICED.search(text):
            found.append(("dependency", PASS_LANE, f"{text} has no price or cost"))
        if ASSUMPTION_WORDS.search(text) and not VERIFIED.search(text):
            found.append(("assumption", PASS_LANE, f"{text} is unverified"))
    return found


def pass_findings(end_state: str, roadmap_view: str | None) -> list[tuple[str, str, str]]:
    """(category, lane, text) for every gap in the end state and the roadmap view, in a stable order, without repeats."""
    found: list[tuple[str, str, str]] = []
    for text in (end_state, roadmap_view or ""):
        lines: list[str] = text.splitlines()
        found += owner_findings(lines) + line_findings(lines)
    found += section_findings(end_state)
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for item in found:
        marker: tuple[str, str] = (item[0], item[2].lower())
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def read_text(path: Path, required: bool) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        if required:
            raise GapError(f"cannot read {path}: {error}") from error
        return None


def gap_pass(repo: Path) -> dict[str, Any]:
    end_state: str | None = read_text(repo / state_io.END_STATE_REL, True)
    view: str | None = read_text(repo / ROADMAP_VIEW_REL, False)
    rows: list[dict[str, Any]] = read_rows(repo)
    added: int = 0
    for category, lane, text in pass_findings(end_state or "", view):
        if any(r.get("kind") == GAP_KIND and r.get("category") == category and str(r.get("text", "")).lower() == text.lower()
               and r.get("status") != STATUS_REJECTED for r in rows):
            continue
        rows.append({"id": next_id(rows), "kind": GAP_KIND, "category": category, "lane": lane, "text": text,
                     "why": f"setup gap pass: {category}", "source": "loop", "status": STATUS_PROPOSED, "added": now()})
        added += 1
    write_rows(repo, rows)
    still_open: list[dict[str, Any]] = open_gaps(rows)
    result: dict[str, Any] = {"key": scope_key(end_state or ""), "ran": now(), "found": added,
                              "open": [str(row["id"]) for row in still_open],
                              "counts": {name: sum(1 for row in still_open if row.get("category") == name) for name in CATEGORIES}}
    atomic_write(repo / PASS_REL, json.dumps(result, sort_keys=True) + "\n")
    return result


def lock_block(repo: Path, key: str) -> str | None:
    """None when a gap pass ran for exactly this roadmap key and no "gap" row is open; else a one-line reason."""
    command: str = f"gap_research.py {repo} pass"
    try:
        recorded: Any = json.loads((repo / PASS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"dt: gap pass has not run for roadmap {key}; run `{command}`, then resolve or reject each open gap"
    if not isinstance(recorded, dict) or recorded.get("key") != key:
        ran: str = str(recorded.get("key")) if isinstance(recorded, dict) else "none"
        return f"dt: gap pass ran for roadmap {ran}, not {key}; run `{command}` again"
    try:
        ids: list[str] = [str(row["id"]) for row in open_gaps(read_rows(repo))]
    except GapError as error:
        return f"dt: gap pass cannot read the gap ledger ({error}); fix it, then run `{command}`"
    if ids:
        return (f"dt: gap pass has {len(ids)} open gap(s): {', '.join(ids)}; "
                f"run `gap_research.py {repo} resolve <id> --note <how>` or `reject <id> --reason <why>` for each")
    return None


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
    done: argparse.ArgumentParser = sub.add_parser("resolve")
    done.add_argument("id")
    done.add_argument("--note", required=True)
    sub.add_parser("pass")
    return parser


def run(args: argparse.Namespace) -> Any:
    repo: Path = Path(args.repo)
    if args.command == "add":
        return add(repo, args.kind, args.lane, args.text, args.why, args.source, args.needs_service)
    if args.command == "list":
        return [row for row in read_rows(repo) if args.status in (None, row["status"])]
    if args.command == "apply":
        return apply(repo, args.id)
    if args.command == "resolve":
        return resolve(repo, args.id, args.note)
    if args.command == "pass":
        return gap_pass(repo)
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
