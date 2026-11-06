"""Lesson selection, helpful/harmful counters and tier promotion for the incident hooks.

Lessons stay in lessons.md (tier 2 project, tier 3 ~/.dts2/lessons.md); the counters live in sidecar JSON files so the
lesson files are never rewritten here. Tier 4 goes through knowledge.py when it exists and a store is set up.
Tier 5 (the marketplace) is never touched: `harness:` lines go through `evolve`."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import incidents_detect as detect  # noqa: E402
import lessons  # noqa: E402
import state_io  # noqa: E402

ENV_HOME: Final[str] = "DTS2_HOME"
ENV_KNOWLEDGE_SCRIPT: Final[str] = "DTS2_KNOWLEDGE_SCRIPT"
ENV_KNOWLEDGE_STORE: Final[str] = "DTS2_KNOWLEDGE_STORE"
ENV_FLEET_SCRIPT: Final[str] = "DTS2_FLEET_SCRIPT"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
HOME_LESSONS: Final[str] = "lessons.md"
HOME_STATS: Final[str] = "lesson-stats.json"
KNOWLEDGE_STATS: Final[str] = "lesson-stats-knowledge.json"
HOME_LEDGER: Final[str] = "ledgers/harness.jsonl"
PROJECT_STATS: Final[str] = state_io.rel("lesson-stats.json")
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
TIER_PROJECT: Final[int] = 2
TIER_HARNESS: Final[int] = 3
TIER_KNOWLEDGE: Final[int] = 4
DEMOTE_MARGIN: Final[int] = 2
EXPIRE_UNUSED_STREAK: Final[int] = 10
EXPIRE_IDLE_DAYS: Final[int] = 30
SECONDS_PER_DAY: Final[int] = 86400
KNOWLEDGE_TIMEOUT_S: Final[int] = 2
FLEET_TIMEOUT_S: Final[int] = 2
TEXT_MAX_CHARS: Final[int] = 240
HEADER: Final[str] = "# Lessons\n\nOne rule per line: `- [H-nnn] <rule> {paths: glob} {cat: category} (source: ..., last YYYY-MM-DD)`.\n\n"
FIELDS_RE: Final[re.Pattern[str]] = re.compile(r"\{[^}]*\}")
HOME_ID_RE: Final[re.Pattern[str]] = re.compile(r"^- \[H-(\d+)\]", re.M)
INTRO: Final[str] = "dts2 lessons from earlier incidents (short; follow them where they apply):"
OUTRO: Final[str] = "End your final report with one line: `Lessons: {ids}` (one verdict per lesson: helpful, not-helpful or unused)."
EMPTY_STATS: Final[dict[str, Any]] = {"helpful": 0, "harmful": 0, "unused": 0, "unused_streak": 0, "injected": 0,
                                      "last_used": None, "first_injected": None}


def home_dir() -> Path:
    explicit: str | None = os.environ.get(ENV_HOME)
    return Path(explicit) if explicit else Path.home() / DEFAULT_HOME_DIR


class Sidecar:
    """A counters file `{"lessons": {id: entry}}` read and updated under the store's lock."""

    def __init__(self, root: Path, name: str) -> None:
        self.state: state_io.State = state_io.State(state_io.FileStore(root))
        self.name: str = name

    def entries(self) -> dict[str, dict[str, Any]]:
        record: dict[str, Any] = self.state.read_record(self.name) or {}
        found: Any = record.get("lessons")
        return found if isinstance(found, dict) else {}

    def update(self, edit: Callable[[dict[str, dict[str, Any]]], None]) -> None:
        with self.state.store.lock(self.name):
            record: dict[str, Any] = self.state.read_record(self.name) or {}
            found: Any = record.get("lessons")
            table: dict[str, dict[str, Any]] = found if isinstance(found, dict) else {}
            edit(table)
            self.state.write_record(self.name, {**record, "lessons": table})


def sidecar_for(tier: int, repo: Path) -> Sidecar:
    if tier == TIER_PROJECT:
        return Sidecar(repo, PROJECT_STATS)
    return Sidecar(home_dir(), HOME_STATS if tier == TIER_HARNESS else KNOWLEDGE_STATS)


def entry_of(table: dict[str, dict[str, Any]], lesson_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = table.setdefault(lesson_id, {})
    for key, value in EMPTY_STATS.items():
        entry.setdefault(key, value)
    return entry


def apply_verdict(entry: dict[str, Any], verdict: str, now: int) -> None:
    """ACE counters: helpful and not-helpful mean the agent used the lesson; unused extends the unused streak."""
    if verdict == "unused":
        entry["unused"] += 1
        entry["unused_streak"] += 1
        return
    entry["unused_streak"] = 0
    entry["last_used"] = now
    entry["helpful" if verdict == "helpful" else "harmful"] += 1


def apply_injected(entry: dict[str, Any], now: int) -> None:
    entry["injected"] += 1
    entry["first_injected"] = entry["first_injected"] or now


def record_injected(table: dict[str, dict[str, Any]], lesson_id: str, now: int) -> None:
    apply_injected(entry_of(table, lesson_id), now)


def record_verdict(table: dict[str, dict[str, Any]], lesson_id: str, verdict: str, now: int) -> None:
    apply_verdict(entry_of(table, lesson_id), verdict, now)


def record_harmful(table: dict[str, dict[str, Any]], lesson_id: str) -> None:
    entry_of(table, lesson_id)["harmful"] += 1


def lesson_status(entry: dict[str, Any] | None, now: int) -> str:
    """active, demoted (harmful >= helpful + 2: flagged for review, never injected) or expired (unused 10 in a row, or
    30 days without use since first injected)."""
    if not entry:
        return "active"
    if entry.get("harmful", 0) >= entry.get("helpful", 0) + DEMOTE_MARGIN:
        return "demoted"
    if entry.get("unused_streak", 0) >= EXPIRE_UNUSED_STREAK:
        return "expired"
    reference: Any = entry.get("last_used") or entry.get("first_injected")
    if reference and now - int(reference) > EXPIRE_IDLE_DAYS * SECONDS_PER_DAY:
        return "expired"
    return "active"


def lesson_text(line: str) -> str:
    """The rule itself: no id, no `{...}` fields, no trailing metadata parenthetical."""
    body: str = lessons.LESSON_LINE.sub("", line, count=1)
    body = FIELDS_RE.sub("", body)
    body = lessons.META.sub("", body).replace("()", "")
    return " ".join(body.split())[:TEXT_MAX_CHARS]


def knowledge_script() -> Path | None:
    override: str | None = os.environ.get(ENV_KNOWLEDGE_SCRIPT)
    path: Path = Path(override) if override else SCRIPT_DIR / "knowledge.py"
    return path if path.is_file() else None


def knowledge_ready() -> bool:
    """knowledge.py exists and a store is set up (env var or a knowledge file under the home folder)."""
    if knowledge_script() is None:
        return False
    home: Path = home_dir()
    return bool(os.environ.get(ENV_KNOWLEDGE_STORE)) or (home / "knowledge.json").exists() or (home / "knowledge").exists()


def knowledge_lines(query: str) -> list[str]:
    """Tier 4 candidates as lesson lines `- [K-key] text`; any failure returns nothing."""
    script: Path | None = knowledge_script()
    if script is None or not knowledge_ready():
        return []
    try:
        done = subprocess.run([sys.executable, "-I", str(script), "find", query, "--kind", "learning", "--json"],
                              capture_output=True, text=True, timeout=KNOWLEDGE_TIMEOUT_S, check=False)
        rows: Any = json.loads(done.stdout) if done.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    out: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key: str = re.sub(r"[^A-Za-z0-9]+", "", str(row.get("key") or row.get("id") or ""))[:16]
        text: str = " ".join(str(row.get("text") or row.get("value") or "").split())
        if key and text:
            out.append(f"- [K-{key}] {text}")
    return out


def home_lesson_lines() -> list[str]:
    path: Path = home_dir() / HOME_LESSONS
    if not path.is_file():
        return []
    return [row for row in path.read_text(encoding="utf-8", errors="replace").splitlines() if lessons.LESSON_LINE.match(row)]


def line_id(line: str) -> str:
    found: re.Match[str] | None = re.match(r"^- \[(?P<id>[A-Z]-[A-Za-z0-9]+)\]", line)
    return found.group("id") if found else ""


def tier_rows(tier: int, repo: Path, query: str) -> list[str]:
    if tier == TIER_PROJECT:
        return [row for row in lessons.lesson_lines(repo) if not lessons.is_enforced(row)]
    if tier == TIER_HARNESS:
        return [row for row in home_lesson_lines() if not lessons.is_enforced(row)]
    return knowledge_lines(query)


def select(repo: Path, klass: str, paths: list[str], limit: int, now: int, query: str = "") -> list[dict[str, Any]]:
    """Up to `limit` active lessons for an agent class and the brief's paths; the closest tier wins a repeated id."""
    if limit <= 0:
        return []
    tables: dict[int, dict[str, dict[str, Any]]] = {t: sidecar_for(t, repo).entries()
                                                    for t in (TIER_PROJECT, TIER_HARNESS, TIER_KNOWLEDGE)}
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tier in (TIER_PROJECT, TIER_HARNESS, TIER_KNOWLEDGE):
        if len(chosen) >= limit:
            break
        candidates: list[dict[str, Any]] = []
        for index, row in enumerate(tier_rows(tier, repo, query)):
            lid: str = line_id(row)
            agents: list[str] = detect.lesson_agents(row)
            if not lid or lid in seen or (agents and klass not in agents) or not lessons.line_matches(row, paths):
                continue
            if lesson_status(tables[tier].get(lid), now) != "active":
                continue
            has_globs: bool = bool(lessons.lesson_globs(row))
            candidates.append({"id": lid, "tier": tier, "text": lesson_text(row), "category": detect.lesson_category(row),
                               "reason": "matches brief paths" if has_globs else "applies everywhere", "rank": (not has_globs, -index)})
        for item in sorted(candidates, key=lambda c: c["rank"]):
            if len(chosen) < limit and item["id"] not in seen:
                seen.add(item["id"])
                chosen.append({k: v for k, v in item.items() if k != "rank"})
    return chosen


def injection_block(selected: list[dict[str, Any]]) -> str:
    """The additionalContext text: the lessons and the line asking for per-lesson feedback. Empty when nothing was selected."""
    if not selected:
        return ""
    rows: list[str] = [f"- [{item['id']}] {item['text']}" for item in selected]
    ids: str = ", ".join(f"{item['id']} helpful|not-helpful|unused" for item in selected)
    return "\n".join([INTRO, *rows, OUTRO.format(ids=ids)])


def next_home_id() -> str:
    path: Path = home_dir() / HOME_LESSONS
    text: str = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    numbers: list[int] = [int(n) for n in HOME_ID_RE.findall(text)]
    return f"H-{(max(numbers) + 1 if numbers else 1):03d}"


def find_project_line(repo: Path, ref: str) -> str | None:
    for row in lessons.lesson_lines(repo):
        if line_id(row) == ref:
            return row
    return None


def fleet_broadcast(text: str) -> bool:
    """Tell the fleet about a promoted lesson when scripts/fleet.py exists. Every failure is ignored."""
    override: str | None = os.environ.get(ENV_FLEET_SCRIPT)
    script: Path = Path(override) if override else SCRIPT_DIR / "fleet.py"
    if not script.is_file():
        return False
    try:
        done = subprocess.run([sys.executable, "-I", str(script), "broadcast", "--kind", "knowledge", "--text", text],
                              capture_output=True, text=True, timeout=FLEET_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def resolve_source(repo: Path, ref: str, text: str | None) -> tuple[str, str, str] | None:
    """(source label, rule text, extra `{...}` fields) for a lesson id or a signature; None when it cannot be resolved."""
    line: str | None = find_project_line(repo, ref)
    if line is not None:
        return ref, lesson_text(line), " ".join(FIELDS_RE.findall(line))
    if "|" in ref:
        category, klass, glob = (ref.split("|") + ["", "", ""])[:3]
        rule: str = text or f"Recurring {category} incidents for {klass} agents on {glob}; check the brief and scope before starting."
        return ref, rule, f"{{cat: {category}}}" if category in detect.CATEGORIES else ""
    return None


def promote_harness(repo: Path, ref: str, text: str | None, today: date) -> dict[str, Any]:
    """Tier 2 -> 3: copy a project lesson (or a trend signature) into ~/.dts2/lessons.md and log it on the harness ledger."""
    resolved: tuple[str, str, str] | None = resolve_source(repo, ref, text)
    if resolved is None:
        return {"ok": False, "detail": f"no lesson or signature {ref!r}"}
    source, rule, fields = resolved
    home: Path = home_dir()
    state: state_io.State = state_io.State(state_io.FileStore(home))
    new_id: str = next_home_id()
    event: dict[str, Any] = state_io.make_event("promote", id=state_io.event_id("promote", str(repo.resolve()), source),
                                                lesson=new_id, source=source, project=str(repo.resolve()), tier=TIER_HARNESS)
    if not state.append_event(HOME_LEDGER, event):
        return {"ok": True, "duplicate": True, "tier": "harness", "source": source}
    line: str = f"- [{new_id}] {rule} {fields} (source: promoted from {repo.name} {source}, last {today.isoformat()})".replace("  ", " ")
    path: Path = home / HOME_LESSONS
    state_io.append_text(path, line + "\n", header=HEADER)
    broadcast: bool = fleet_broadcast(f"[{new_id}] {rule}")
    return {"ok": True, "tier": "harness", "id": new_id, "source": source, "path": str(path), "fleet_broadcast": broadcast}


def promote_knowledge(repo: Path, ref: str, text: str | None) -> dict[str, Any]:
    """Tier 3/2 -> 4 via knowledge.py; skipped with a note when it is missing or no store is set up."""
    script: Path | None = knowledge_script()
    if script is None or not knowledge_ready():
        return {"ok": False, "skipped": True, "detail": "knowledge store not available (knowledge.py missing or no store set up); tier 4 skipped"}
    resolved: tuple[str, str, str] | None = resolve_source(repo, ref, text)
    if resolved is None:
        for row in home_lesson_lines():
            if line_id(row) == ref:
                resolved = (ref, lesson_text(row), "")
    if resolved is None:
        return {"ok": False, "detail": f"no lesson or signature {ref!r}"}
    source, rule, _ = resolved
    key: str = "incident-" + re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-").lower()
    try:
        done = subprocess.run([sys.executable, "-I", str(script), "set", key, rule, "--kind", "learning", "--tags", "incident"],
                              capture_output=True, text=True, timeout=KNOWLEDGE_TIMEOUT_S * 2, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "skipped": True, "detail": f"knowledge.py failed: {error}"}
    if done.returncode != 0:
        return {"ok": False, "skipped": True, "detail": f"knowledge.py exited {done.returncode}"}
    state_io.State(state_io.FileStore(home_dir())).append_event(HOME_LEDGER, state_io.make_event(
        "promote", id=state_io.event_id("promote-knowledge", str(repo.resolve()), source), source=source, key=key,
        tier=TIER_KNOWLEDGE, project=str(repo.resolve())))
    return {"ok": True, "tier": "knowledge", "key": key, "fleet_broadcast": fleet_broadcast(f"[{key}] {rule}")}
