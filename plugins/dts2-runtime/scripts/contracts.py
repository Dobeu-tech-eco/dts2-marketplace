"""The harness's text contracts as parsers. Each returns a frozen dataclass, or `Invalid` with the reasons (and, when a
best-effort reading exists, `partial`), so a caller cannot use half a contract by accident. All of them read through
mdparse.py: no regex of its own touches Markdown structure."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final, Union

import mdparse

VOTE_LINE: Final[re.Pattern[str]] = re.compile(r"^VOTE:\s*(APPROVE|REJECT)\s*$")
SEAT_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERDICTS: Final[frozenset[str]] = frozenset({"APPROVE", "REJECT"})
VERDICT_KEY: Final[str] = "verdict"
DECISION_LINE: Final[re.Pattern[str]] = re.compile(r"^DECISION:\s*(APPROVE|FIX|STRIKE)\s*$")
RESEARCH_DECISION_LINE: Final[re.Pattern[str]] = re.compile(r"^DECISION:\s*(APPROVE|FIX|STRIKE|RESEARCH)\s*$")
ENTRIES_LINE: Final[re.Pattern[str]] = re.compile(r"^Entries reviewed:\s*(\d+)\s*$", re.MULTILINE)
UPDATE_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*-?\s*Update:\s*\S", re.MULTILINE)
ENTRY_KINDS: Final[tuple[str, ...]] = ("plan", "build", "tiebreak", "fix", "ci", "council")
ENTRY_NAME: Final[re.Pattern[str]] = re.compile(r"^(\d+)-(" + "|".join(ENTRY_KINDS) + r")-r(\d+)-(.+)\.md$")
BRIEF_HEADING: Final[str] = "## Dissent brief"
HEAD_BRIEF: Final[str] = "## Head of council brief"
RESPONSES_HEADING: Final[str] = "## Dissent responses"
HISTORY_HEADING: Final[str] = "## History considered"
FIXES_HEADING: Final[str] = "## Fixes"
STRUCK_HEADING: Final[str] = "## Struck"
RESEARCH_HEADING: Final[str] = "## Research brief"
LANE_HEADING: Final[re.Pattern[str]] = re.compile(r"^Lane (\S+)$")
SECTIONS_HEADING: Final[str] = "## Sections"
ACCEPTANCE_HEADING: Final[str] = "## Acceptance criteria"
ACTION_ID_SUFFIX: Final[re.Pattern[str]] = re.compile(r"^(.*?)\s*\(([A-Z]\d+)\)\s*$")
WILDCARD_LANE: Final[str] = "*"


@dataclass(frozen=True)
class Invalid:
    reasons: tuple[str, ...]
    partial: Any = None  # the best-effort reading, when there is one

    def __bool__(self) -> bool:  # `if parsed:` reads as "is it valid"
        return False


@dataclass(frozen=True)
class VoteEntry:
    order: int
    kind: str
    round: int
    seat: str


@dataclass(frozen=True)
class Ballot:
    seat: str
    vote: str | None
    has_brief: bool
    reasons: str


@dataclass(frozen=True)
class Decision:
    decision: str | None
    head_brief: str
    entries_reviewed: int | None
    responses: dict[str, str]
    fixes: tuple[str, ...]
    struck: tuple[str, ...]


@dataclass(frozen=True)
class SectionRow:
    number: str
    name: str
    status: str
    action_id: str | None


@dataclass(frozen=True)
class Acceptance:
    text: str
    done: bool


@dataclass(frozen=True)
class Report:
    lanes: dict[str, tuple[str, ...]]  # lane id -> its `###` section names, lower-cased
    run: tuple[str, ...]  # the `##` section names, lower-cased


def parse_entry_name(name: str) -> VoteEntry | Invalid:
    match = ENTRY_NAME.match(name)
    if not match:
        return Invalid((f"{name!r} is not <n>-<kind>-r<round>-<seat>.md",))
    order, kind, rnd, seat = match.groups()
    return VoteEntry(int(order), kind, int(rnd), seat)


def verdict_of(line: str) -> str | None:
    """APPROVE or REJECT from a strict line: a JSON object with exactly the key "verdict", or `VOTE: X`. Else None."""
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            data: Any = json.loads(stripped)
        except ValueError:
            return None
        ok = isinstance(data, dict) and set(data) == {VERDICT_KEY} and data[VERDICT_KEY] in VERDICTS
        return str(data[VERDICT_KEY]) if ok else None
    match = VOTE_LINE.match(stripped)
    return match.group(1) if match else None


def parse_ballot(text: str, seat: str) -> Ballot | Invalid:
    """A ballot counts only when its first line is a strict verdict, its seat name is plain, and no later line casts a
    second, possibly conflicting, verdict (text quoted from a proposal cannot add one)."""
    vote = verdict_of(mdparse.first_line(text)) if SEAT_NAME.match(seat) else None
    body = text.strip().split("\n", 1)[1] if "\n" in text.strip() else ""
    if vote is not None and any(verdict_of(line) is not None for line in body.split("\n")):
        vote = None
    brief = mdparse.section(text, BRIEF_HEADING)
    cut = body.find(BRIEF_HEADING)
    reasons = (body[:cut] if cut >= 0 else body).strip() or "(no findings given)"
    ballot = Ballot(seat, vote, bool(brief), reasons)
    return ballot if vote else Invalid(("no strict verdict on the first line, or a plain seat name is missing, or a second verdict follows",), ballot)


def parse_decision(text: str, allow_research: bool = False) -> Decision | Invalid:
    """A head-of-council decision. `allow_research` (ask-expert runs only) admits a fourth verdict, RESEARCH."""
    first = (RESEARCH_DECISION_LINE if allow_research else DECISION_LINE).match(mdparse.first_line(text))
    head = mdparse.section(text, HEAD_BRIEF)
    seen = ENTRIES_LINE.search(mdparse.section(text, HISTORY_HEADING))
    decision = Decision(
        decision=first.group(1) if first else None, head_brief=head,
        entries_reviewed=int(seen.group(1)) if seen else None,
        responses=mdparse.subsections(mdparse.section(text, RESPONSES_HEADING), 3),
        fixes=tuple(b.text for b in mdparse.bullets(mdparse.section(text, FIXES_HEADING))),
        struck=tuple(b.text for b in mdparse.bullets(mdparse.section(text, STRUCK_HEADING))),
    )
    verdicts = "APPROVE|FIX|STRIKE|RESEARCH" if allow_research else "APPROVE|FIX|STRIKE"
    reasons = ([] if first else [f"first line is not 'DECISION: {verdicts}'"]) + ([] if head else [f"no '{HEAD_BRIEF}'"])
    return decision if not reasons else Invalid(tuple(reasons), decision)


def has_update(response: str) -> bool:
    return UPDATE_LINE.search(response) is not None


def parse_sections(end_state: str) -> list[SectionRow] | Invalid:
    """The numbered rows of the end state's `## Sections` table."""
    lines = mdparse.section_lines(end_state, SECTIONS_HEADING, stop_at=3, prefix=True)
    if lines is None:
        return Invalid((f"no '{SECTIONS_HEADING}' heading",))
    out: list[SectionRow] = []
    for cells in mdparse.rows("\n".join(lines)):
        if len(cells) < 2 or not cells[0].isdigit():
            continue
        match = ACTION_ID_SUFFIX.match(cells[1])
        out.append(SectionRow(cells[0], match.group(1) if match else cells[1], cells[-1], match.group(2) if match else None))
    return out


def parse_acceptance(end_state: str) -> list[Acceptance] | Invalid:
    if not mdparse.has_section(end_state, ACCEPTANCE_HEADING):
        return Invalid((f"no '{ACCEPTANCE_HEADING}' heading",))
    body = mdparse.section(end_state, ACCEPTANCE_HEADING)
    return [Acceptance(b.text, b.checked) for b in mdparse.bullets(body) if b.checked is not None]


def report_sections(text: str) -> tuple[dict[str, set[str]], set[str]]:
    """({lane: {### names}}, {## names}) from a dpp-report.md, names lower-cased."""
    lanes: dict[str, set[str]] = {}
    run: set[str] = set()
    current: str | None = None
    for token in mdparse.tokenize(text):
        if not isinstance(token, mdparse.Heading):
            continue
        lane = LANE_HEADING.match(token.text) if token.level == 2 else None
        if lane:
            current = lane.group(1)
            lanes.setdefault(current, set())
        elif token.level == 2:
            current = None
            run.add(token.text.lower())
        elif token.level == 3 and current is not None:
            lanes[current].add(token.text.lower())
    return lanes, run


def parse_report(text: str, lane_ids: list[str], lane_sections: tuple[str, ...], run_sections: tuple[str, ...]) -> Report | Invalid:
    """A dpp-report.md with every wanted section present (a heading may continue past the wanted name, e.g. `Plan (done)`)."""
    lanes, run = report_sections(text)

    def has(found: set[str], wanted: str) -> bool:
        return any(name.startswith(wanted.lower()) for name in found)

    missing = [f"lane {lane}: missing '{s}'" for lane in lane_ids for s in lane_sections if not has(lanes.get(lane, set()), s)]
    missing += [f"run: missing '{s}'" for s in run_sections if not has(run, s)]
    report = Report({k: tuple(sorted(v)) for k, v in lanes.items()}, tuple(sorted(run)))
    return report if not missing else Invalid(tuple(missing), report)


Parsed = Union[VoteEntry, Ballot, Decision, Report, Invalid]
