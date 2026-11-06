"""Deterministic incident detectors for the agent telemetry hooks. Pure functions: no I/O, no model calls.

Categories follow the MAST failure taxonomy (plus infra codes); see incidents.py for where the rows are written."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Final

PREFIX: Final[str] = "dt:"
UNKNOWN_CLASS: Final[str] = "agent"

# category -> (MAST code, default severity)
CATEGORIES: Final[dict[str, tuple[str, str]]] = {
    "bad-brief": ("1.1/2.2", "near-miss"),
    "no-report": ("3.1", "incident"),
    "partial": ("1.5", "incident"),
    "report-incomplete": ("3.2", "near-miss"),
    "rework-other-agent": ("1.2/2.3", "incident"),
    "hung-spawn": ("1.3", "blocking"),
    "api-error": ("infra", "blocking"),
    "permission-denied": ("infra", "incident"),
    "son-park": ("infra", "incident"),
}
SON_PARK_REASONS: Final[frozenset[str]] = frozenset({"stalled", "timeout", "loops", "no-final-status"})

NO_REPORT_CHARS: Final[int] = 20
PARTIAL_PREFIX: Final[str] = "PARTIAL:"
EDIT_TOOLS: Final[frozenset[str]] = frozenset({"Edit", "Write", "MultiEdit"})
GOAL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(goal|objective|task|your job|implement|fix|add|build|create|write|review|verify|investigate|find|update|refactor|"
    r"check|audit|research|summari[sz]e|migrate|remove|rename)\b", re.I)
SCOPE_RE: Final[re.Pattern[str]] = re.compile(r"\b(scope|files?|paths?|directory|folder|module|only touch|do not touch)\b", re.I)
DONE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(done when|definition of done|acceptance|success criteria|finished when|return|report|deliver|output|"
    r"end with|must pass|should pass)\b", re.I)
PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w/:.-])(?:[\w.-]+/)+[\w.*-]+|(?<![\w/.-])[\w-]+\.(?:py|js|ts|tsx|jsx|md|json|ya?ml|sh|toml|go|rs|java|css|html)\b")
LESSONS_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*Lessons:\s*(?P<body>.+)$", re.M | re.I)
LESSON_VERDICT: Final[re.Pattern[str]] = re.compile(r"(?P<id>[A-Za-z]-[A-Za-z0-9]+)\W+(?P<verdict>not-helpful|helpful|unused)\b", re.I)
VERDICTS: Final[frozenset[str]] = frozenset({"helpful", "not-helpful", "unused"})
CAT_FIELD: Final[re.Pattern[str]] = re.compile(r"\{cat(?:egory)?:\s*(?P<cat>[a-z-]+)\s*\}")
AGENTS_FIELD: Final[re.Pattern[str]] = re.compile(r"\{agents:\s*(?P<names>[^}]*)\}")
MAX_PATHS: Final[int] = 12


def agent_class(agent_type: Any) -> str:
    """`builder` for `dt:builder`; other agent names are kept as given."""
    name: str = str(agent_type or "").strip().removeprefix(PREFIX)
    return name or UNKNOWN_CLASS


def sha_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def brief_paths(text: str) -> list[str]:
    """File-looking tokens in a brief, in order, de-duplicated (URLs are skipped by the pattern)."""
    seen: dict[str, None] = {}
    for token in PATH_RE.findall(text or ""):
        cleaned: str = token.strip(".,;:)(`'\"")
        if cleaned and "://" not in cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)[:MAX_PATHS]


def brief_problems(text: str, min_chars: int) -> list[str]:
    """What is wrong with a spawn brief: too short, or no goal, file scope or done-definition. Empty when it is fine."""
    body: str = (text or "").strip()
    problems: list[str] = []
    if len(body) < min_chars:
        problems.append(f"under {min_chars} chars ({len(body)})")
    if not GOAL_RE.search(body):
        problems.append("no goal")
    if not SCOPE_RE.search(body) and not brief_paths(body):
        problems.append("no file scope")
    if not DONE_RE.search(body):
        problems.append("no done-definition")
    return problems


def report_findings(text: str, kind: str, required: dict[str, tuple[str, ...]], missing_fn: Any) -> dict[str, Any]:
    """Quality of a final report: chars, partial, ok and the missing `## ` sections (only for agents with a contract)."""
    body: str = (text or "").strip()
    partial: bool = body.startswith(PARTIAL_PREFIX)
    missing: list[str] = list(missing_fn(body, kind)) if kind in required and len(body) >= NO_REPORT_CHARS else []
    return {"report_chars": len(body), "no_report": len(body) < NO_REPORT_CHARS, "partial": partial,
            "missing_sections": missing, "report_ok": len(body) >= NO_REPORT_CHARS and not partial and not missing}


def parse_lessons_line(text: str) -> dict[str, str]:
    """`Lessons: L-012 helpful, K-abc1 not-helpful` -> {id: verdict}; ids keep the case they were injected in, the last mention wins."""
    out: dict[str, str] = {}
    for line in LESSONS_LINE.finditer(text or ""):
        for hit in LESSON_VERDICT.finditer(line.group("body")):
            out[hit.group("id")] = hit.group("verdict").lower()
    return out


def lesson_category(line: str) -> str | None:
    """The incident category a lesson targets: its `{cat: x}` field, else a category name in its text."""
    field: re.Match[str] | None = CAT_FIELD.search(line)
    if field and field.group("cat") in CATEGORIES:
        return field.group("cat")
    for name in CATEGORIES:
        if name in line:
            return name
    return None


def lesson_agents(line: str) -> list[str]:
    field: re.Match[str] | None = AGENTS_FIELD.search(line)
    return [part.strip() for part in field.group("names").split(",") if part.strip()] if field else []


def top_glob(paths: list[str]) -> str:
    """The coarse path glob an incident belongs to: `src/**` for src/a/b.py, `*` for a root file or no path."""
    for path in paths:
        parts: list[str] = [p for p in path.strip("/").split("/") if p and p != "."]
        if len(parts) > 1:
            return f"{parts[0]}/**"
        if parts:
            return "*"
    return "*"


def signature(category: str, klass: str, paths: list[str]) -> str:
    return f"{category}|{klass}|{top_glob(paths)}"


def rework_owner(file_map: dict[str, str], path: str, agent_id: str) -> str | None:
    """The other agent id that wrote `path` earlier in this session, or None."""
    owner: str | None = file_map.get(path)
    return owner if owner and owner != agent_id else None
