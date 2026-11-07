#!/usr/bin/env python3
"""Council seat substitution and the identical-findings ledger note (B7). It does not change when the council sits.

Subcommands print one JSON object each:
  swap       --seats FILE --failed SEAT [--ledger FILE] [--step S] [--reason R]
             FILE holds the `seats` and `bench` that `council.py seats` printed. The timed-out seat is replaced in place by the
             next bench entry, preferring a provider not already seated; the swap goes to the run ledger as a note
  identical  --votes-dir DIR --ledger FILE --step S --prev N --curr M
             when rounds N and M of the vote entries have the same findings, append a ledger note; nothing else changes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import append_ledger  # noqa: E402

TIMEOUT_EXIT: Final[int] = 143
REASON_TIMEOUT: Final[str] = "timeout"
NOTE_KIND: Final[str] = "note"
ENTRY_ROUND: Final[re.Pattern[str]] = re.compile(r"^\d+-[a-z]+-r(\d+)-.+\.md$")
FINDINGS_HEADING: Final[re.Pattern[str]] = re.compile(r"^##\s+Findings\s*$", re.IGNORECASE)
ANY_HEADING: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s")
BULLET: Final[re.Pattern[str]] = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")


def is_timeout(result: dict[str, Any]) -> bool:
    """A dispatch result that ended at the wall-clock limit: exit 143, `timed_out`, or an outcome/reason of timeout."""
    return bool(result.get("timed_out")) or result.get("exit_code") == TIMEOUT_EXIT or REASON_TIMEOUT in (
        result.get("outcome"), result.get("reason"))


def pick_substitute(remaining: list[dict[str, str]], bench: list[dict[str, str]], failed_provider: str) -> dict[str, str] | None:
    """First bench entry from a provider that is neither the failed one nor already seated, else any other provider, else any."""
    seated: set[str] = {s["provider"] for s in remaining}
    for allowed in (lambda p: p != failed_provider and p not in seated, lambda p: p != failed_provider, lambda p: True):
        found: dict[str, str] | None = next((b for b in bench if allowed(b["provider"])), None)
        if found is not None:
            return found
    return None


def swap_seat(seats: list[dict[str, str]], bench: list[dict[str, str]], failed: str, reason: str = REASON_TIMEOUT,
              now: int | None = None) -> dict[str, Any]:
    """Replace seat `failed` in place with the next bench entry. Returns new copies; the inputs are never changed."""
    index: int | None = next((i for i, s in enumerate(seats) if s["seat"] == failed), None)
    if index is None:
        return {"ok": False, "seats": list(seats), "bench": list(bench), "swap": None, "detail": f"{failed} holds no seat"}
    remaining: list[dict[str, str]] = [s for i, s in enumerate(seats) if i != index]
    chosen: dict[str, str] | None = pick_substitute(remaining, bench, seats[index]["provider"])
    if chosen is None:
        return {"ok": False, "seats": list(seats), "bench": list(bench), "swap": None,
                "detail": f"no substitute on the bench for {failed}"}
    new_seats: list[dict[str, str]] = [chosen if i == index else s for i, s in enumerate(seats)]
    new_bench: list[dict[str, str]] = [b for b in bench if b is not chosen]
    swap: dict[str, Any] = {"from": failed, "to": chosen["seat"], "from_provider": seats[index]["provider"],
                            "to_provider": chosen["provider"], "reason": reason, "at": int(time.time()) if now is None else now}
    return {"ok": True, "seats": new_seats, "bench": new_bench, "swap": swap}


def record_swap(ledger: Path, step: str, swap: dict[str, Any]) -> None:
    append_ledger(ledger, {"kind": NOTE_KIND, "event": "seat-swap", "step": step, **swap})


def normalize_findings(text: str) -> frozenset[str]:
    """The findings of one review as comparable strings: the bullets under `## Findings`, else every bullet in the text.
    Lower-cased, whitespace collapsed, trailing punctuation dropped, so wording order and list style do not matter."""
    lines: list[str] = text.splitlines()
    scoped: list[str] = []
    inside: bool = False
    for line in lines:
        if FINDINGS_HEADING.match(line.strip()):
            inside = True
        elif inside and ANY_HEADING.match(line):
            inside = False
        elif inside:
            scoped.append(line)
    has_section: bool = any(FINDINGS_HEADING.match(line.strip()) for line in lines)
    found: set[str] = set()
    for line in scoped if has_section else lines:
        match = BULLET.match(line)
        if match:
            found.add(re.sub(r"\s+", " ", match.group(1)).strip().lower().rstrip(".;,"))
    return frozenset(found)


def identical_findings(first: str, second: str) -> bool:
    """True when both texts have the same, non-empty set of findings."""
    one: frozenset[str] = normalize_findings(first)
    return bool(one) and one == normalize_findings(second)


def round_findings(votes_dir: Path, number: int) -> frozenset[str]:
    """Every finding from every seat's entry of vote round `number`."""
    found: set[str] = set()
    for path in sorted(votes_dir.glob("*.md")):
        match = ENTRY_ROUND.match(path.name)
        if match and int(match.group(1)) == number:
            found |= normalize_findings(path.read_text(encoding="utf-8"))
    return frozenset(found)


def note_identical_rounds(votes_dir: Path, ledger: Path, step: str, prev: int, curr: int) -> dict[str, Any]:
    """Write a ledger note when two rounds produced identical findings. It decides nothing: the council trigger is unchanged."""
    before, after = round_findings(votes_dir, prev), round_findings(votes_dir, curr)
    same: bool = bool(before) and before == after
    if same:
        append_ledger(ledger, {"kind": NOTE_KIND, "event": "identical-findings", "step": step, "rounds": [prev, curr],
                               "findings": len(before), "at": int(time.time())})
    return {"ok": True, "identical": same, "rounds": [prev, curr], "findings": len(before) if same else 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("swap")
    s.add_argument("--seats", required=True)
    s.add_argument("--failed", required=True)
    s.add_argument("--ledger", default=None)
    s.add_argument("--step", default="")
    s.add_argument("--reason", default=REASON_TIMEOUT)
    i = sub.add_parser("identical")
    i.add_argument("--votes-dir", required=True)
    i.add_argument("--ledger", required=True)
    i.add_argument("--step", required=True)
    i.add_argument("--prev", required=True, type=int)
    i.add_argument("--curr", required=True, type=int)
    args = parser.parse_args()
    if args.cmd == "identical":
        print(json.dumps(note_identical_rounds(Path(args.votes_dir), Path(args.ledger), args.step, args.prev, args.curr)))
        return 0
    given: Any = json.loads(Path(args.seats).read_text(encoding="utf-8"))
    result: dict[str, Any] = swap_seat(list(given.get("seats") or []), list(given.get("bench") or []), args.failed, args.reason)
    if result["swap"] and args.ledger:
        record_swap(Path(args.ledger), args.step, result["swap"])
    print(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
