#!/usr/bin/env python3
"""ask-expert helpers: the goal clarity gate, the decision-memo check, the sweep ledger and the guarded repo cleanups.

Every subcommand prints one JSON object.
  clarity       --answers FILE [--asked N] [--threshold T]   score the owner's answers against the slot rubric (exit 3 below the bar)
  goal record   --repo NAME --answers FILE [--root DIR]       store the answers once clarity passes (exit 3 otherwise)
  check-report  FILE                                          validate the decision memo (exit 1 with the errors)
  scorecard     --report FILE [--goal G | --repo NAME]        parse the memo's scorecard, weight it by goal, compare with the stated overall
  sweep add     [--ledger FILE] --repo NAME --verdict V --confidence C --score N --reason TEXT --salvage TEXT [--report PATH]
  sweep show    --ledger FILE                                 the ledger rows (best score first) plus a markdown table
  archive       --repo OWNER/NAME                             gh repo archive (reversible)
  panel-tally   --plans SEAT=FILE ... [--votes SEAT=FILE ...]   three-seat panel: majority verdict and cross-review votes
  backup        --repo OWNER/NAME [--dest DIR]                mirror clone, git bundle, bundle verify
  delete        --repo OWNER/NAME --confirm NAME --bundle PATH  one repo per call; refused without the typed name and a verified bundle
gh and git run through DTS2_GH_BIN and DTS2_GIT_BIN."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intake  # noqa: E402
import mdparse  # noqa: E402
import miniyaml  # noqa: E402
import state_io  # noqa: E402
from proc import binary  # noqa: E402

ENCODING: Final[str] = "utf-8"
EXIT_OK: Final[int] = 0
EXIT_REPORT: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
EXIT_NOT_CLEAR: Final[int] = 3
DEFAULT_THRESHOLD: Final[int] = 95
THRESHOLD_KEY: Final[str] = "ask_expert.clarity_threshold"
QUESTION_CAP: Final[int] = 8
GOALS: Final[frozenset[str]] = frozenset({"money", "passion", "learning", "portfolio"})
NONE_WORD: Final[str] = "none"
JUST_ME: Final[str] = "just me"
FULL: Final[str] = "full"
PARTIAL: Final[str] = "partial"
MISSING: Final[str] = "missing"
# (slot, weight) in tie-break order.
SLOTS: Final[tuple[tuple[str, int], ...]] = (
    ("goal", 25), ("unsure", 15), ("outcome", 15), ("budget", 10), ("fold_targets", 10), ("audience", 10),
    ("restatement_confirmed", 15))
VERDICTS: Final[tuple[str, ...]] = ("KEEP", "FOLD", "TEMPLATE", "ARCHIVE", "DELETE")
CONFIDENCES: Final[tuple[str, ...]] = ("high", "moderate", "low")
VERDICT_LINE: Final[re.Pattern[str]] = re.compile(r"^VERDICT:\s*(\w+)\s*$")
FOLD_TARGET_LINE: Final[re.Pattern[str]] = re.compile(r"^FOLD_TARGET:\s*(\S.*?)\s*$", re.MULTILINE)
CONFIDENCE_LINE: Final[re.Pattern[str]] = re.compile(r"^CONFIDENCE:\s*(\w+)\s*$", re.MULTILINE)
URL: Final[re.Pattern[str]] = re.compile(r"https?://\S+")
PRICE_RANGE: Final[re.Pattern[str]] = re.compile(r"\$\s?\d[\d,.]*[kK]?\s*(?:-|\u2013|\u2014|to)\s*\$?\s?\d")
NOT_SELLABLE: Final[str] = "not sellable:"
NUMBER_LABELS: Final[tuple[str, ...]] = ("sourced", "estimated", "assumed")
WHY_BULLETS: Final[int] = 3
H_WHY: Final[str] = "## Why"
H_NUMBERS: Final[str] = "## Numbers that mattered"
H_TEMPLATE: Final[str] = "## Template path"
H_SCORECARD: Final[str] = "## Scorecard"
FACTORS: Final[tuple[str, ...]] = (
    "security", "code_health", "product_viability", "market_size", "revenue_potential", "time_to_profit", "projections",
    "moat", "upkeep_cost")
SCORECARD_HEADER: Final[tuple[str, ...]] = ("factor", "score", "method", "evidence")
SCORE_MAX: Final[int] = 10
OVERALL_LINE: Final[re.Pattern[str]] = re.compile(r"^Overall:\s*(\d+)/100\s*$", re.MULTILINE)
OVERALL_TOLERANCE: Final[int] = 1
_MONEY: Final[tuple[int, ...]] = (10, 10, 15, 15, 15, 15, 10, 5, 5)
_PORTFOLIO: Final[tuple[int, ...]] = (15, 25, 20, 5, 5, 5, 5, 5, 15)
_PASSION: Final[tuple[int, ...]] = (15, 20, 20, 5, 5, 5, 5, 5, 20)
# Weights per goal, in FACTORS order; each sums to 100. A template sale is a money goal.
GOAL_WEIGHTS: Final[dict[str, dict[str, int]]] = {
    goal: dict(zip(FACTORS, weights)) for goal, weights in (
        ("money", _MONEY), ("template", _MONEY), ("portfolio", _PORTFOLIO), ("passion", _PASSION), ("learning", _PASSION))}
DEFAULT_GOAL: Final[str] = "money"
SECTIONS: Final[tuple[str, ...]] = (
    H_WHY, "## What your goal means", H_NUMBERS, H_TEMPLATE, "## Salvage list", "## What would change the answer", "## Next step")
REPO_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
STAMP_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"
ENV_GH: Final[str] = "DTS2_GH_BIN"
ENV_GIT: Final[str] = "DTS2_GIT_BIN"
ENV_HOME: Final[str] = "DTS2_HOME"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
BACKUP_DIR: Final[str] = "repo-backups"
GOAL_FILE: Final[str] = "goal.json"
TAIL_CHARS: Final[int] = 400


def stamp() -> str:
    return datetime.now(timezone.utc).strftime(STAMP_FORMAT)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def read_json(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text(encoding=ENCODING))
    return data if isinstance(data, dict) else {}


# ---- clarity -------------------------------------------------------------------------------------------------------

def text_status(value: Any, weight: int) -> tuple[int, str]:
    """Free text: full when it passes the intake clarity score, half when only present, nothing when empty."""
    text: str = value.strip() if isinstance(value, str) else ""
    if not text:
        return 0, MISSING
    if intake.clarity_score(text) >= intake.CLARITY_THRESHOLD:
        return weight, FULL
    return weight // 2, PARTIAL


def slot_status(name: str, weight: int, answers: dict[str, Any]) -> tuple[int, str]:
    value: Any = answers.get(name)
    if name == "goal":
        ok: bool = isinstance(value, str) and value.strip().lower() in GOALS
        return (weight, FULL) if ok else (0, MISSING)
    if name == "fold_targets":
        listed: bool = isinstance(value, list) and any(isinstance(v, str) and v.strip() for v in value)
        ok = listed or (isinstance(value, str) and value.strip().lower() == NONE_WORD)
        return (weight, FULL) if ok else (0, MISSING)
    if name == "restatement_confirmed":
        return (weight, FULL) if value is True else (0, MISSING)
    if name == "audience" and isinstance(value, str) and value.strip().lower() == JUST_ME:
        return weight, FULL
    return text_status(value, weight)


def next_slot(slots: dict[str, dict[str, Any]]) -> str | None:
    open_slots: list[tuple[float, int, str]] = [
        (s["earned"] / s["max"], index, name) for index, (name, _) in enumerate(SLOTS) if (s := slots[name])["status"] != FULL]
    return min(open_slots)[2] if open_slots else None


def clarity(answers: dict[str, Any], asked: int, threshold: int) -> dict[str, Any]:
    slots: dict[str, dict[str, Any]] = {}
    for name, weight in SLOTS:
        earned, status = slot_status(name, weight, answers)
        slots[name] = {"earned": earned, "max": weight, "status": status}
    score: int = sum(s["earned"] for s in slots.values())
    return {"score": score, "threshold": threshold, "passed": score >= threshold, "slots": slots,
            "next_slot": next_slot(slots), "budget_exhausted": asked >= QUESTION_CAP}


def configured_threshold(flag: int | None, config: Path) -> int:
    if flag is not None:
        return flag
    if config.is_file():
        return miniyaml.get_int(miniyaml.parse(config.read_text(encoding=ENCODING)), THRESHOLD_KEY, DEFAULT_THRESHOLD)
    return DEFAULT_THRESHOLD


def cmd_clarity(args: argparse.Namespace) -> int:
    result: dict[str, Any] = clarity(read_json(Path(args.answers)), args.asked, configured_threshold(args.threshold, Path(args.config)))
    emit(result)
    return EXIT_OK if result["passed"] else EXIT_NOT_CLEAR


def goal_path(root: Path, repo: str) -> Path:
    return root / state_io.ASK_EXPERT_REL / repo / GOAL_FILE


def cmd_goal_record(args: argparse.Namespace) -> int:
    if not NAME_PATTERN.match(args.repo):
        emit({"ok": False, "error": f"bad repo name: {args.repo!r}"})
        return EXIT_REFUSED
    answers: dict[str, Any] = read_json(Path(args.answers))
    result: dict[str, Any] = clarity(answers, 0, configured_threshold(args.threshold, Path(args.config)))
    if not result["passed"]:
        emit({"ok": False, "error": "clarity has not passed; keep asking", "score": result["score"],
              "threshold": result["threshold"], "next_slot": result["next_slot"]})
        return EXIT_NOT_CLEAR
    record: dict[str, Any] = {"repo": args.repo, "answers": answers, "score": result["score"],
                              "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    target: Path = state_io.atomic_write(goal_path(Path(args.root), args.repo), json.dumps(record, indent=2) + "\n")
    emit({"ok": True, "path": str(target), "score": result["score"]})
    return EXIT_OK


# ---- decision memo -------------------------------------------------------------------------------------------------

def header_problems(text: str) -> list[str]:
    match = VERDICT_LINE.match(mdparse.first_line(text))
    verdict: str | None = match.group(1) if match else None
    if verdict not in VERDICTS:
        return [f"first line must be 'VERDICT: {'|'.join(VERDICTS)}'"]
    problems: list[str] = []
    if verdict == "FOLD" and not FOLD_TARGET_LINE.search(text):
        problems.append("VERDICT: FOLD needs a 'FOLD_TARGET: <repo>' line")
    confidence = CONFIDENCE_LINE.search(text)
    if not confidence or confidence.group(1) not in CONFIDENCES:
        problems.append(f"needs a 'CONFIDENCE: {'|'.join(CONFIDENCES)}' line")
    return problems


def number_problems(body: str) -> list[str]:
    data_rows: list[tuple[str, ...]] = mdparse.rows(body)[1:]
    if not data_rows:
        return [f"'{H_NUMBERS}' needs a table with at least one data row"]
    problems: list[str] = []
    for cells in data_rows:
        labels: list[str] = [c.lower() for c in cells if c.lower() in NUMBER_LABELS]
        if not labels:
            problems.append(f"number row has no sourced|estimated|assumed label: {' | '.join(cells)}")
        elif labels[0] == "sourced" and not URL.search(" ".join(cells)):
            problems.append(f"sourced number has no http(s) URL: {' | '.join(cells)}")
    return problems


def template_problems(body: str) -> list[str]:
    if not body:
        return []
    if PRICE_RANGE.search(body) or NOT_SELLABLE in body.lower():
        return []
    return [f"'{H_TEMPLATE}' needs a price range like $X-$Y or the phrase '{NOT_SELLABLE}'"]


def parse_scorecard(text: str) -> tuple[dict[str, tuple[int, str]], int | None, list[str]]:
    """({factor: (score, evidence)}, stated overall, problems) from the `## Scorecard` section."""
    body: str = mdparse.section(text, H_SCORECARD)
    if not body:
        return {}, None, [f"missing or empty section '{H_SCORECARD}'"]
    rows: list[tuple[str, ...]] = mdparse.rows(body)
    problems: list[str] = []
    if not rows or tuple(c.lower() for c in rows[0]) != SCORECARD_HEADER:
        problems.append("scorecard header must be '| Factor | Score | Method | Evidence |'")
    data: list[tuple[str, ...]] = rows[1:]
    if [r[0].lower() for r in data] != list(FACTORS):
        problems.append(f"scorecard needs exactly these factor rows in order: {', '.join(FACTORS)}")
    factors: dict[str, tuple[int, str]] = {}
    for cells in data:
        name: str = cells[0].lower()
        score: str = cells[1] if len(cells) > 1 else ""
        evidence: str = cells[3].lower() if len(cells) > 3 else ""
        if not (score.isdigit() and int(score) <= SCORE_MAX):
            problems.append(f"{name}: score must be an integer 0-{SCORE_MAX}, got {score!r}")
        elif evidence not in NUMBER_LABELS:
            problems.append(f"{name}: evidence must be sourced|estimated|assumed, got {evidence!r}")
        else:
            factors[name] = (int(score), evidence)
    stated = OVERALL_LINE.search(body)
    if not stated:
        problems.append("scorecard needs a line 'Overall: N/100'")
    return factors, int(stated.group(1)) if stated else None, problems


def overall(factors: dict[str, tuple[int, str]], goal: str) -> int:
    weights: dict[str, int] = GOAL_WEIGHTS[goal]
    return (sum(score * weights[name] for name, (score, _) in factors.items()) + 5) // 10


def scorecard(text: str, goal: str) -> dict[str, Any]:
    factors, stated, problems = parse_scorecard(text)
    computed: int | None = overall(factors, goal) if set(factors) == set(FACTORS) else None
    if computed is not None and stated is not None and abs(computed - stated) > OVERALL_TOLERANCE:
        problems.append(f"stated Overall {stated}/100 does not match the {goal} weighting, which gives {computed}/100")
    return {"ok": not problems, "goal": goal, "factors": {k: {"score": v[0], "evidence": v[1]} for k, v in factors.items()},
            "weights": GOAL_WEIGHTS[goal], "overall": computed, "stated": stated, "errors": problems}


def report_goal(args: argparse.Namespace) -> str | None:
    """The goal for weighting: --goal, else the stored goal.json of --repo, else money. None when it is not a known goal."""
    goal: str = args.goal or ""
    if not goal and args.repo:
        path: Path = goal_path(Path(args.root), args.repo)
        goal = str(read_json(path).get("answers", {}).get("goal", "")) if path.is_file() else ""
    goal = (goal or DEFAULT_GOAL).lower()
    return goal if goal in GOAL_WEIGHTS else None


def cmd_scorecard(args: argparse.Namespace) -> int:
    goal: str | None = report_goal(args)
    if goal is None:
        emit({"ok": False, "errors": [f"goal must be one of {', '.join(GOAL_WEIGHTS)}"]})
        return EXIT_REFUSED
    result: dict[str, Any] = scorecard(Path(args.report).read_text(encoding=ENCODING), goal)
    emit(result)
    return EXIT_OK if result["ok"] else EXIT_REPORT


def report_problems(text: str, goal: str = DEFAULT_GOAL) -> list[str]:
    problems: list[str] = header_problems(text)
    problems += scorecard(text, goal)["errors"]
    for heading in SECTIONS:
        body: str = mdparse.section(text, heading)
        if not body:
            problems.append(f"missing or empty section '{heading}'")
        elif heading == H_WHY and len(mdparse.bullets(body)) != WHY_BULLETS:
            problems.append(f"'{H_WHY}' needs exactly {WHY_BULLETS} bullet lines")
        elif heading == H_NUMBERS:
            problems += number_problems(body)
        elif heading == H_TEMPLATE:
            problems += template_problems(body)
    return problems


def cmd_check_report(args: argparse.Namespace) -> int:
    goal: str | None = report_goal(args)
    if goal is None:
        emit({"ok": False, "errors": [f"goal must be one of {', '.join(GOAL_WEIGHTS)}"]})
        return EXIT_REFUSED
    problems: list[str] = report_problems(Path(args.file).read_text(encoding=ENCODING), goal)
    emit({"ok": not problems, "errors": problems})
    return EXIT_OK if not problems else EXIT_REPORT


# ---- sweep ledger --------------------------------------------------------------------------------------------------

def cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def read_rows(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.is_file():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding=ENCODING).splitlines() if line.strip()]


def sweep_table(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = ["| Repo | Verdict | Confidence | Score | Reason | Salvage |", "|---|---|---|---|---|---|"]
    lines += [f"| {cell(r['repo'])} | {cell(r['verdict'])} | {cell(r['confidence'])} | {cell(r.get('score', ''))} | "
              f"{cell(r['reason'])} | {cell(r['salvage'])} |"
              for r in rows]
    return "\n".join(lines)


def cmd_sweep_add(args: argparse.Namespace) -> int:
    ledger: Path = Path(args.ledger) if args.ledger else Path(args.root) / state_io.ASK_EXPERT_REL / f"sweep-{stamp()}.jsonl"
    if args.verdict not in VERDICTS or args.confidence not in CONFIDENCES or not 0 <= args.score <= 100:
        emit({"ok": False, "error": f"verdict is one of {'|'.join(VERDICTS)}; confidence one of {'|'.join(CONFIDENCES)}; score 0-100"})
        return EXIT_REFUSED
    row: dict[str, Any] = {"repo": args.repo, "verdict": args.verdict, "confidence": args.confidence, "score": args.score,
                           "reason": args.reason,
                           "salvage": args.salvage, "report": args.report,
                           "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    state_io.append_text(ledger, json.dumps(row) + "\n")
    emit({"ok": True, "ledger": str(ledger), "row": row})
    return EXIT_OK


def cmd_sweep_show(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = sorted(read_rows(Path(args.ledger)), key=lambda r: -int(r.get("score", -1)))
    emit({"ok": True, "rows": rows, "table": sweep_table(rows)})
    return EXIT_OK


# ---- archive / backup / delete -------------------------------------------------------------------------------------

def tail(text: str) -> str:
    return text.strip()[-TAIL_CHARS:]


def run_tool(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, cwd=str(cwd) if cwd else None)


def repo_parts(repo: str) -> tuple[str, str] | None:
    if not REPO_PATTERN.match(repo):
        return None
    owner, name = repo.split("/", 1)
    return owner, name


def bad_repo(repo: str) -> int:
    emit({"ok": False, "error": f"repo must be OWNER/NAME, got {repo!r}"})
    return EXIT_REFUSED


def verify_bundle(bundle: Path) -> tuple[bool, str]:
    """`git bundle verify` needs a repository; run it in a scratch one so it works from any cwd. The bare skeleton is written
    directly (HEAD, objects, refs) because git accepts it as a repo and it needs no extra git call."""
    scratch: Path = Path(tempfile.mkdtemp(prefix="dts2-verify-"))
    try:
        (scratch / "objects").mkdir()
        (scratch / "refs").mkdir()
        (scratch / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        done = run_tool([*binary(ENV_GIT, "git"), "bundle", "verify", str(bundle.absolute())], cwd=scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return done.returncode == 0, tail(done.stderr or done.stdout)


def cmd_archive(args: argparse.Namespace) -> int:
    if repo_parts(args.repo) is None:
        return bad_repo(args.repo)
    done = run_tool([*binary(ENV_GH, "gh"), "repo", "archive", args.repo, "--yes"])
    emit({"ok": done.returncode == 0, "repo": args.repo, "output": tail(done.stderr or done.stdout)})
    return EXIT_OK if done.returncode == 0 else EXIT_REPORT


def backup_dest(flag: str | None) -> Path:
    if flag:
        return Path(flag).expanduser().resolve()
    home: str = os.environ.get(ENV_HOME) or str(Path.home() / DEFAULT_HOME_DIR)
    return (Path(home).expanduser() / BACKUP_DIR).resolve()


def cmd_backup(args: argparse.Namespace) -> int:
    parts = repo_parts(args.repo)
    if parts is None:
        return bad_repo(args.repo)
    owner, name = parts
    dest: Path = backup_dest(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    bundle: Path = dest / f"{owner}__{name}-{stamp()}.bundle"
    git: list[str] = binary(ENV_GIT, "git")
    work: Path = Path(tempfile.mkdtemp(prefix="dts2-backup-"))
    try:
        mirror: Path = work / f"{name}.git"
        cloned = run_tool([*git, "clone", "--mirror", f"https://github.com/{args.repo}.git", str(mirror)])
        if cloned.returncode != 0:
            emit({"ok": False, "error": "git clone --mirror failed", "output": tail(cloned.stderr)})
            return EXIT_REPORT
        made = run_tool([*git, "bundle", "create", str(bundle), "--all"], cwd=mirror)
        if made.returncode != 0:
            emit({"ok": False, "error": "git bundle create failed", "output": tail(made.stderr)})
            return EXIT_REPORT
    finally:
        shutil.rmtree(work, ignore_errors=True)
    verified, detail = verify_bundle(bundle)
    emit({"ok": verified, "bundle": str(bundle), "verified": verified, "output": detail})
    return EXIT_OK if verified else EXIT_REPORT


def delete_refusal(owner: str, name: str, confirm: str, bundle: Path) -> str | None:
    if confirm != name:
        return f"--confirm must equal the repo name {name!r} exactly"
    if not bundle.is_file():
        return f"backup bundle not found: {bundle}"
    if not bundle.name.startswith(f"{owner}__{name}-"):
        return f"bundle name must start with '{owner}__{name}-', got {bundle.name!r}"
    verified, detail = verify_bundle(bundle)
    return None if verified else f"git bundle verify failed: {detail}"


def cmd_delete(args: argparse.Namespace) -> int:
    parts = repo_parts(args.repo)
    if parts is None:
        return bad_repo(args.repo)
    refusal: str | None = delete_refusal(parts[0], parts[1], args.confirm, Path(args.bundle))
    if refusal:
        emit({"ok": False, "refused": True, "error": refusal})
        return EXIT_REFUSED
    done = run_tool([*binary(ENV_GH, "gh"), "repo", "delete", args.repo, "--yes"])
    emit({"ok": done.returncode == 0, "repo": args.repo, "bundle": args.bundle, "output": tail(done.stderr or done.stdout)})
    return EXIT_OK if done.returncode == 0 else EXIT_REPORT


# ---- panel ---------------------------------------------------------------------------------------------------------

PLAN_LINE: Final[re.Pattern[str]] = re.compile(
    r"^VERDICT:\s*(KEEP|FOLD(?:\s+INTO\b.*)?|(?:SELL\s+AS\s+)?TEMPLATE|ARCHIVE|DELETE)\s*$", re.IGNORECASE)
VOTE_LINE: Final[re.Pattern[str]] = re.compile(r"^VOTE\s+([A-Za-z0-9_.-]+):\s*(AGREE|DISAGREE)\s*$", re.IGNORECASE | re.MULTILINE)
NO_MAJORITY: Final[str] = "no-majority"
PANEL_MIN: Final[int] = 2


def plan_verdict(text: str) -> str | None:
    """The plan's first line as one of VERDICTS ("FOLD INTO x" is FOLD, "SELL AS TEMPLATE" is TEMPLATE), or None."""
    match = PLAN_LINE.match(mdparse.first_line(text))
    return None if match is None else ("FOLD" if match.group(1).upper().startswith("FOLD") else match.group(1).upper().split()[-1])


def seat_files(pairs: list[str]) -> tuple[dict[str, Path], list[str]]:
    files: dict[str, Path] = {}
    problems: list[str] = []
    for pair in pairs:
        seat, sep, path = pair.partition("=")
        if not sep or not NAME_PATTERN.match(seat) or not path:
            problems.append(f"expected SEAT=FILE, got {pair!r}")
        elif seat in files:
            problems.append(f"seat {seat!r} given twice")
        else:
            files[seat] = Path(path)
    return files, problems


def panel_tally(plans: dict[str, Path], votes: dict[str, Path]) -> dict[str, Any]:
    """Majority verdict of the panel plans (a plan counts only with a strict first-line VERDICT) and, when given, the cross-review
    votes: every seat casts one `VOTE <seat>: AGREE|DISAGREE` line per other plan. The round passes when the plans are unanimous
    and nobody disagrees."""
    problems: list[str] = [] if len(plans) >= PANEL_MIN else [f"need at least {PANEL_MIN} plans, got {len(plans)}"]
    verdicts: dict[str, str] = {}
    for seat, path in plans.items():
        verdict: str | None = plan_verdict(path.read_text(encoding=ENCODING)) if path.is_file() else None
        if verdict is None:
            problems.append(f"plan of {seat!r} has no strict first line 'VERDICT: KEEP|FOLD INTO <repo>|SELL AS TEMPLATE|ARCHIVE|DELETE'")
        else:
            verdicts[seat] = verdict
    agree = disagree = 0
    if votes:
        for voter in plans:
            if voter not in votes:
                problems.append(f"no vote file for seat {voter!r}")
        for voter, path in votes.items():
            cast = VOTE_LINE.findall(path.read_text(encoding=ENCODING)) if path.is_file() and voter in plans else []
            targets: list[str] = sorted(seat for seat, _ in cast)
            if targets != sorted(seat for seat in plans if seat != voter):
                problems.append(f"votes of {voter!r} must name each other seat exactly once, got {targets}")
                continue
            agree += sum(1 for _, how in cast if how.upper() == "AGREE")
            disagree += sum(1 for _, how in cast if how.upper() == "DISAGREE")
    if problems:
        return {"ok": False, "problems": problems}
    counts: dict[str, int] = {v: list(verdicts.values()).count(v) for v in VERDICTS if v in verdicts.values()}
    top: str = max(counts, key=lambda v: counts[v])
    majority: bool = counts[top] * 2 > len(verdicts) and sum(1 for n in counts.values() if n == counts[top]) == 1
    unanimous: bool = len(counts) == 1
    return {"ok": True, "verdict": top if majority else NO_MAJORITY, "unanimous": unanimous, "counts": counts, "plans": verdicts,
            "agree": agree, "disagree": disagree, "pass": bool(votes) and unanimous and disagree == 0}


def cmd_panel_tally(args: argparse.Namespace) -> int:
    plans, bad_plans = seat_files(args.plans)
    votes, bad_votes = seat_files(args.votes or [])
    if bad_plans or bad_votes:
        emit({"ok": False, "problems": bad_plans + bad_votes})
        return EXIT_REFUSED
    result: dict[str, Any] = panel_tally(plans, votes)
    emit(result)
    return EXIT_OK if result["ok"] else EXIT_REFUSED


# ---- CLI -----------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clarity")
    c.add_argument("--answers", required=True)
    c.add_argument("--asked", type=int, default=0)
    c.add_argument("--threshold", type=int, default=None)
    c.add_argument("--config", default=state_io.CONFIG_REL)
    g = sub.add_parser("goal").add_subparsers(dest="goal_cmd", required=True).add_parser("record")
    g.add_argument("--repo", required=True)
    g.add_argument("--answers", required=True)
    g.add_argument("--root", default=".")
    g.add_argument("--threshold", type=int, default=None)
    g.add_argument("--config", default=state_io.CONFIG_REL)
    cr = sub.add_parser("check-report")
    cr.add_argument("file")
    sc = sub.add_parser("scorecard")
    sc.add_argument("--report", required=True)
    for each in (cr, sc):
        each.add_argument("--goal", default=None)
        each.add_argument("--repo", default=None)
        each.add_argument("--root", default=".")
    sweep = sub.add_parser("sweep").add_subparsers(dest="sweep_cmd", required=True)
    add = sweep.add_parser("add")
    add.add_argument("--ledger", default=None)
    add.add_argument("--root", default=".")
    for flag in ("repo", "verdict", "confidence", "reason", "salvage"):
        add.add_argument(f"--{flag}", required=True)
    add.add_argument("--score", type=int, required=True)
    add.add_argument("--report", default=None)
    sweep.add_parser("show").add_argument("--ledger", required=True)
    pt = sub.add_parser("panel-tally")
    pt.add_argument("--plans", nargs="+", required=True)
    pt.add_argument("--votes", nargs="+", default=None)
    sub.add_parser("archive").add_argument("--repo", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--repo", required=True)
    b.add_argument("--dest", default=None)
    d = sub.add_parser("delete")
    for flag in ("repo", "confirm", "bundle"):
        d.add_argument(f"--{flag}", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "clarity":
        return cmd_clarity(args)
    if args.cmd == "goal":
        return cmd_goal_record(args)
    if args.cmd == "check-report":
        return cmd_check_report(args)
    if args.cmd == "scorecard":
        return cmd_scorecard(args)
    if args.cmd == "sweep":
        return cmd_sweep_add(args) if args.sweep_cmd == "add" else cmd_sweep_show(args)
    if args.cmd == "panel-tally":
        return cmd_panel_tally(args)
    if args.cmd == "archive":
        return cmd_archive(args)
    if args.cmd == "backup":
        return cmd_backup(args)
    return cmd_delete(args)


if __name__ == "__main__":
    sys.exit(main())
