#!/usr/bin/env python3
"""Autopilot council: build the full-history dossier, tally the five council ballots, check the head's decision.

Subcommands print one JSON object each:
  eligible       --votes-dir DIR                    may the council sit? only after three normal vote rounds failed
  dossier        --votes-dir DIR --out FILE        every note from every round, in order, in one file
                                                   (ok only when `eligible` is true)
  tally          BALLOT [BALLOT ...]                majority, dissenters, and dissenters missing a brief
  check-decision DECISION --tally FILE --entries N  the head of council answered every dissent and read every entry
  ledger         --ballots-dir DIR --tally FILE --decision FILE --step S --stamp X --out FILE
                 append the vote, every member's reasons, the decision and the head's brief to the harness record
  seats          --usable a,b,c [--config FILE] [--failed provider:model,...]
                 seat five council members across as many providers as possible, one model per seat
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

DECISIONS_HEADER: Final[str] = ("# Council decisions\n\nEvery autopilot step that went to council: the vote, each member's reasons, "
                                "the decision, and the head of council's brief. Appended, never rewritten.\n")

COUNCIL_SEATS: Final[int] = 5
PANEL_SEATS: Final[int] = 3
ROUNDS_BEFORE_COUNCIL: Final[int] = 3
VOTE_KINDS: Final[tuple[str, ...]] = ("plan", "build")
KINDS: Final[tuple[str, ...]] = ("plan", "build", "tiebreak", "fix", "ci", "council")
ENTRY_NAME: Final[re.Pattern[str]] = re.compile(r"^(\d+)-(" + "|".join(KINDS) + r")-r(\d+)-(.+)\.md$")
VOTE_LINE: Final[re.Pattern[str]] = re.compile(r"^VOTE:\s*(APPROVE|REJECT)\s*$")
DECISION_LINE: Final[re.Pattern[str]] = re.compile(r"^DECISION:\s*(APPROVE|FIX|STRIKE)\s*$")
ENTRIES_LINE: Final[re.Pattern[str]] = re.compile(r"^Entries reviewed:\s*(\d+)\s*$", re.MULTILINE)
BRIEF_HEADING: Final[str] = "## Dissent brief"
HEAD_BRIEF: Final[str] = "## Head of council brief"
REQUIRED_LIST: Final[dict[str, str]] = {"FIX": "## Fixes", "STRIKE": "## Struck"}
PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "agents"
DEFAULT_ORDER: Final[tuple[str, ...]] = ("claude", "codex", "gemini", "grok", "cursor", "muse")
CLAUDE_AGENT_ALIASES: Final[frozenset[str]] = frozenset({"opus", "sonnet", "haiku", "fable"})
# Council model ids live in profiles/agents/<provider>.json under `councilModels`:
#   head: ids reserved for the head of council (never seated as voters)
#   alternates: frontier ids a provider may field as a further seat when there are not five providers
#   checked / maxAgeDays: when a person last confirmed the ids, and how old that may get before a warning
DEFAULT_MAX_AGE_DAYS: Final[int] = 90


def first_line(text: str) -> str:
    lines: list[str] = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def section(text: str, heading: str) -> str:
    """Body under a `## ` heading up to the next `## ` heading (### subheadings stay inside)."""
    start: int = text.find(heading + "\n")
    if start < 0:
        return ""
    body: str = text[start + len(heading) + 1:]
    match = re.search(r"^## ", body, re.MULTILINE)
    return (body[:match.start()] if match else body).strip()


def parse_entry(path: Path) -> dict[str, Any]:
    match = ENTRY_NAME.match(path.name)
    if not match:
        return {"file": path.name, "recognized": False}
    order, kind, rnd, seat = match.groups()
    return {"file": path.name, "recognized": True, "order": int(order), "kind": kind, "round": int(rnd), "seat": seat}


def round_outcomes(votes_dir: Path) -> list[dict[str, Any]]:
    """Every normal vote round (panel of three, plus its tiebreak if any), in the order it was held."""
    rounds: dict[tuple[str, int], dict[str, Any]] = {}
    last_kind: str | None = None
    for path in sorted(p for p in votes_dir.glob("*.md") if p.is_file()):
        entry: dict[str, Any] = parse_entry(path)
        if not entry["recognized"] or entry["kind"] not in VOTE_KINDS + ("tiebreak",):
            continue
        match = VOTE_LINE.match(first_line(path.read_text(encoding="utf-8")))
        vote: str | None = match.group(1) if match else None
        if entry["kind"] == "tiebreak":
            # A tiebreak belongs to the ballot it broke: the most recent plan or build vote of that round.
            target = rounds.get((last_kind or "", entry["round"]))
            if target is not None:
                target["tiebreak"] = vote or "INVALID"
            continue
        last_kind = entry["kind"]
        key: tuple[str, int] = (entry["kind"], entry["round"])
        held = rounds.setdefault(key, {"kind": entry["kind"], "round": entry["round"], "votes": [], "tiebreak": None})
        if vote:
            held["votes"].append(vote)
    for held in rounds.values():
        approve: int = held["votes"].count("APPROVE")
        held["complete"] = len(held["votes"]) >= PANEL_SEATS
        held["passed"] = held["complete"] and (approve == len(held["votes"]) or held["tiebreak"] == "APPROVE")
    return list(rounds.values())


def eligibility(votes_dir: Path) -> dict[str, Any]:
    """The council sits only after three complete rounds of the normal vote on the same ballot have all failed."""
    rounds: list[dict[str, Any]] = round_outcomes(votes_dir)
    if not rounds:
        return {"eligible": False, "ballot": None, "failedRounds": 0, "rounds": [],
                "reason": "no normal vote rounds on record; run the normal vote first"}
    ballot: str = rounds[-1]["kind"]
    held: list[dict[str, Any]] = [r for r in rounds if r["kind"] == ballot]
    failed: list[int] = [r["round"] for r in held if r["complete"] and not r["passed"]]
    summary: list[dict[str, Any]] = [{k: r[k] for k in ("kind", "round", "complete", "passed", "tiebreak")} for r in rounds]
    base: dict[str, Any] = {"ballot": ballot, "failedRounds": len(failed), "rounds": summary}
    if any(r["passed"] for r in held):
        return {**base, "eligible": False, "reason": f"the {ballot} vote already passed; no council"}
    if not held[-1]["complete"]:
        return {**base, "eligible": False,
                "reason": f"{ballot} round {held[-1]['round']} is not finished (needs {PANEL_SEATS} panel votes)"}
    if len(failed) < ROUNDS_BEFORE_COUNCIL:
        return {**base, "eligible": False,
                "reason": f"only {len(failed)} of {ROUNDS_BEFORE_COUNCIL} {ballot} vote rounds have failed; fix and vote again"}
    return {**base, "eligible": True,
            "reason": f"{len(failed)} complete {ballot} vote rounds failed; escalate to the council"}


def build_dossier(votes_dir: Path, out: Path) -> dict[str, Any]:
    paths: list[Path] = sorted(p for p in votes_dir.glob("*.md") if p.is_file())
    entries: list[dict[str, Any]] = [parse_entry(p) for p in paths]
    parts: list[str] = [f"# Council dossier: {votes_dir.name}\n", f"Entries: {len(paths)}\n"]
    for path, entry in zip(paths, entries):
        label: str = f"{entry['kind']} round {entry['round']} — {entry['seat']}" if entry["recognized"] else "unlabelled note"
        parts.append(f"\n---\n\n## Entry {path.name} ({label})\n\n{path.read_text(encoding='utf-8').strip()}\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(out, "".join(parts))
    unrecognized: list[str] = [e["file"] for e in entries if not e["recognized"]]
    kinds: dict[str, int] = {}
    for entry in entries:
        if entry["recognized"]:
            kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    seats: list[str] = sorted({e["seat"] for e in entries if e["recognized"]})
    gate: dict[str, Any] = eligibility(votes_dir)
    return {"ok": bool(paths) and gate["eligible"], "entries": len(paths), "byKind": kinds, "participants": seats,
            "unrecognized": unrecognized, "eligible": gate["eligible"], "eligibility": gate["reason"], "out": str(out)}


def read_ballot(path: Path) -> dict[str, Any]:
    text: str = path.read_text(encoding="utf-8")
    match = VOTE_LINE.match(first_line(text))
    seat: str = path.stem
    return {"seat": seat, "vote": match.group(1) if match else None, "brief": bool(section(text, BRIEF_HEADING))}


def tally(paths: list[Path]) -> dict[str, Any]:
    ballots: list[dict[str, Any]] = [read_ballot(p) for p in paths]
    valid: list[dict[str, Any]] = [b for b in ballots if b["vote"]]
    approve: int = sum(1 for b in valid if b["vote"] == "APPROVE")
    reject: int = len(valid) - approve
    majority: str = "APPROVE" if approve > reject else "REJECT"
    dissenters: list[str] = [b["seat"] for b in valid if b["vote"] != majority]
    missing: list[str] = [b["seat"] for b in valid if b["seat"] in dissenters and not b["brief"]]
    invalid: list[str] = [b["seat"] for b in ballots if not b["vote"]]
    problems: list[str] = []
    if len(valid) != COUNCIL_SEATS:
        problems.append(f"need {COUNCIL_SEATS} valid ballots, got {len(valid)}")
    problems += [f"dissenter {seat} has no '{BRIEF_HEADING}'" for seat in missing]
    return {"ok": not problems, "approve": approve, "reject": reject, "majority": majority,
            "unanimous": not dissenters, "dissenters": dissenters, "missingBrief": missing,
            "invalid": invalid, "problems": problems}


def dissent_problems(text: str, dissenters: list[str]) -> list[str]:
    responses: str = section(text, "## Dissent responses")
    problems: list[str] = []
    for seat in dissenters:
        block = re.search(rf"^### {re.escape(seat)}\s*$(.*?)(?=^### |\Z)", responses, re.MULTILINE | re.DOTALL)
        if not block:
            problems.append(f"no response to dissenter {seat}")
        elif not re.search(r"^\s*-?\s*Update:\s*\S", block.group(1), re.MULTILINE):
            problems.append(f"response to {seat} has no 'Update:' line")
    return problems


def check_decision(path: Path, tally_result: dict[str, Any], entries: int) -> dict[str, Any]:
    text: str = path.read_text(encoding="utf-8")
    match = DECISION_LINE.match(first_line(text))
    decision: str | None = match.group(1) if match else None
    problems: list[str] = [] if decision else ["first line is not 'DECISION: APPROVE|FIX|STRIKE'"]
    if not section(text, HEAD_BRIEF):
        problems.append(f"no '{HEAD_BRIEF}'")
    seen = ENTRIES_LINE.search(section(text, "## History considered"))
    if not seen or int(seen.group(1)) != entries:
        problems.append(f"'## History considered' must say 'Entries reviewed: {entries}'")
    problems += dissent_problems(text, list(tally_result.get("dissenters", [])))
    heading: str | None = REQUIRED_LIST.get(decision or "")
    if heading and not re.search(r"^\s*- \S", section(text, heading), re.MULTILINE):
        problems.append(f"{decision} needs at least one item under '{heading}'")
    return {"ok": not problems, "decision": decision, "problems": problems}


def reasons(text: str) -> str:
    """A ballot's findings and notes: everything after the VOTE line, minus the dissent brief."""
    body: str = text.strip().split("\n", 1)[1] if "\n" in text.strip() else ""
    cut: int = body.find(BRIEF_HEADING)
    return (body[:cut] if cut >= 0 else body).strip() or "(no findings given)"


def seat_block(path: Path) -> str:
    text: str = path.read_text(encoding="utf-8")
    ballot: dict[str, Any] = read_ballot(path)
    brief: str = section(text, BRIEF_HEADING)
    lines: list[str] = [f"#### {ballot['seat']}: {ballot['vote'] or 'NO VALID VOTE'}", "", "Reasons:", "", reasons(text)]
    if brief:
        lines += ["", "Dissent brief:", "", brief]
    return "\n".join(lines) + "\n"


def write_ledger(ballots_dir: Path, tally_result: dict[str, Any], decision_path: Path,
                 step: str, stamp: str, out: Path) -> dict[str, Any]:
    text: str = decision_path.read_text(encoding="utf-8")
    match = DECISION_LINE.match(first_line(text))
    decision: str = match.group(1) if match else "NONE"
    seats: list[Path] = sorted(p for p in ballots_dir.glob("*.md") if p.is_file())
    parts: list[str] = [
        f"\n## Council {stamp} — step {step}\n",
        f"- Vote: {tally_result.get('approve', 0)} approve, {tally_result.get('reject', 0)} reject "
        f"(majority {tally_result.get('majority', '?')}); dissenters: {', '.join(tally_result.get('dissenters', [])) or 'none'}",
        f"- Decision: {decision}",
        f"- Record: {decision_path}\n",
        "### Members' votes and reasons\n",
        *[seat_block(p) for p in seats],
        "### Head of council brief\n", section(text, HEAD_BRIEF) or "(missing)", "",
    ]
    for heading in ("## Dissent responses", "## Fixes", "## Struck", "## History considered"):
        body: str = section(text, heading)
        if body:
            parts += [f"### {heading[3:]}\n", body, ""]
    existing: str = out.read_text(encoding="utf-8") if out.exists() else DECISIONS_HEADER
    atomic_write(out, existing + "\n".join(parts) + "\n")
    return {"ok": bool(seats) and decision != "NONE", "decision": decision, "seats": len(seats), "out": str(out)}


def parse_council_config(text: str) -> dict[str, list[str]]:
    """Read only a top-level `council:` block of `key: [a, b]` lines (order, exclude, models)."""
    found: dict[str, list[str]] = {}
    in_block: bool = False
    for raw in text.splitlines():
        line: str = raw.split("#", 1)[0].strip()
        if raw and not raw.startswith((" ", "\t")):
            in_block = line == "council:"
            continue
        if in_block and ":" in line:
            key, value = line.split(":", 1)
            found[key.strip()] = [part.strip() for part in value.strip().strip("[]").split(",") if part.strip()]
    return found


def read_profile(provider: str) -> dict[str, Any]:
    path: Path = PROFILE_DIR / f"{provider}.json"
    if not path.is_file():
        return {}
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def council_models(provider: str) -> dict[str, Any]:
    block: Any = read_profile(provider).get("councilModels")
    return block if isinstance(block, dict) else {}


def id_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def frontier_model(provider: str) -> str | None:
    return read_profile(provider).get("models", {}).get("frontier")


def candidates(provider: str, extra: list[str], failed: set[str]) -> list[str]:
    block: dict[str, Any] = council_models(provider)
    models: list[str] = [m for m in (frontier_model(provider), *id_list(block.get("alternates")), *extra) if m]
    unique: list[str] = list(dict.fromkeys(models))
    head: set[str] = set(id_list(block.get("head")))
    return [m for m in unique if m not in head and f"{provider}:{m}" not in failed]


def model_freshness(provider: str, today: date) -> dict[str, Any]:
    """Age of the provider's council model ids. A missing or malformed `checked` date counts as stale."""
    block: dict[str, Any] = council_models(provider)
    limit: Any = block.get("maxAgeDays")
    max_age: int = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else DEFAULT_MAX_AGE_DAYS
    try:
        checked: date = date.fromisoformat(str(block.get("checked")))
    except ValueError:
        return {"provider": provider, "checked": None, "age_days": None, "max_age_days": max_age, "stale": True}
    age: int = (today - checked).days
    return {"provider": provider, "checked": checked.isoformat(), "age_days": age, "max_age_days": max_age,
            "stale": age > max_age or age < 0}


def seat_entry(provider: str, model: str) -> dict[str, str]:
    via: str = "roster-command"
    if provider == "claude":
        via = "agent-tool" if model in CLAUDE_AGENT_ALIASES else "claude-cli"
    name: str = model if model.lower().startswith(provider) else f"{provider}-{model}"
    slug: str = re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")
    return {"seat": slug, "provider": provider, "model": model, "via": via}


def pick_seats(usable: list[str], config: dict[str, list[str]], failed: set[str], today: date | None = None) -> dict[str, Any]:
    order: list[str] = list(dict.fromkeys([*config.get("order", DEFAULT_ORDER), *usable]))
    excluded: set[str] = set(config.get("exclude", []))
    extra: dict[str, list[str]] = {}
    for item in config.get("models", []):
        provider, _, model = item.partition(":")
        extra.setdefault(provider.strip(), []).append(model.strip())
    pools: list[tuple[str, list[str]]] = [(p, candidates(p, extra.get(p, []), failed))
                                         for p in order if p in usable and p not in excluded]
    pools = [(p, models) for p, models in pools if models]
    ranked: list[dict[str, str]] = [seat_entry(p, models[depth]) for depth in range(max((len(m) for _, m in pools), default=0))
                                    for p, models in pools if depth < len(models)]
    seats: list[dict[str, str]] = ranked[:COUNCIL_SEATS]
    providers: list[str] = sorted({s["provider"] for s in seats})
    doubled: list[str] = sorted({s["provider"] for s in seats if sum(x["provider"] == s["provider"] for x in seats) > 1})
    problems: list[str] = [] if len(seats) == COUNCIL_SEATS else [
        f"need {COUNCIL_SEATS} distinct provider/model seats, only {len(seats)} available"]
    fresh: list[dict[str, Any]] = [model_freshness(p, today or date.today()) for p in providers if council_models(p)]
    return {"ok": not problems, "seats": seats, "bench": ranked[COUNCIL_SEATS:], "providers": providers,
            "doubled": doubled, "problems": problems, "freshness": fresh,
            "stale": [f["provider"] for f in fresh if f["stale"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eligible")
    e.add_argument("--votes-dir", required=True)
    d = sub.add_parser("dossier")
    d.add_argument("--votes-dir", required=True)
    d.add_argument("--out", required=True)
    t = sub.add_parser("tally")
    t.add_argument("ballots", nargs="+")
    c = sub.add_parser("check-decision")
    c.add_argument("decision")
    c.add_argument("--tally", required=True)
    c.add_argument("--entries", required=True, type=int)
    led = sub.add_parser("ledger")
    for flag in ("--ballots-dir", "--tally", "--decision", "--step", "--stamp", "--out"):
        led.add_argument(flag, required=True)
    st = sub.add_parser("seats")
    st.add_argument("--usable", required=True, help="comma-separated usable providers from the roster probe")
    st.add_argument("--config", default=".harness/config.yaml")
    st.add_argument("--failed", default="", help="provider:model seats that failed and must not be reseated")
    args = parser.parse_args()
    if args.cmd == "seats":
        config_path: Path = Path(args.config)
        config: dict[str, list[str]] = parse_council_config(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        usable: list[str] = [u.strip() for u in args.usable.split(",") if u.strip()]
        failed: set[str] = {f.strip() for f in args.failed.split(",") if f.strip()}
        print(json.dumps(pick_seats(usable, config, failed)))
        return 0
    if args.cmd == "eligible":
        print(json.dumps(eligibility(Path(args.votes_dir))))
        return 0
    if args.cmd == "dossier":
        result: dict[str, Any] = build_dossier(Path(args.votes_dir), Path(args.out))
    elif args.cmd == "tally":
        result = tally([Path(p) for p in args.ballots])
    elif args.cmd == "ledger":
        tally_json: dict[str, Any] = json.loads(Path(args.tally).read_text(encoding="utf-8"))
        result = write_ledger(Path(args.ballots_dir), tally_json, Path(args.decision), args.step, args.stamp, Path(args.out))
    else:
        tally_result: dict[str, Any] = json.loads(Path(args.tally).read_text(encoding="utf-8"))
        result = check_decision(Path(args.decision), tally_result, args.entries)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
