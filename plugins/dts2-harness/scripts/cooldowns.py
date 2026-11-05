#!/usr/bin/env python3
"""Shared agent cooldown registry.

When an agent or model runs out of usage, its reset date is recorded once in a user-level file and nobody calls it
again until that date. Usage limits belong to the account, so the file is shared by every session on the machine
(DTS2_AGENT_STATUS, else $DTS2_HOME/agent-status.json, else ~/.dts2/agent-status.json).

Library: record / is_cooling / cooling_names / clear / expire / parse_reset / detect / record_detection.
CLI: python3 cooldowns.py set|clear|list|check|detect|expire|session-note (see main)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

ENV_STATUS: Final[str] = "DTS2_AGENT_STATUS"
ENV_HOME: Final[str] = "DTS2_HOME"
STATUS_FILE: Final[str] = "agent-status.json"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
ENCODING: Final[str] = "utf-8"
SCHEMA_VERSION: Final[int] = 1
STATE_COOLDOWN: Final[str] = "cooldown"
DEFAULT_PROVISIONAL: Final[timedelta] = timedelta(hours=5)
MIN_COOLDOWN: Final[timedelta] = timedelta(minutes=15)
SOURCES: Final[frozenset[str]] = frozenset({"error", "user", "manual", "assumed"})
FORCING_SOURCES: Final[frozenset[str]] = frozenset({"user", "manual"})
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ISO_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
UTC_NOTE_FORMAT: Final[str] = "%Y-%m-%d %H:%M UTC"
LOCAL_NOTE_FORMAT: Final[str] = "%Y-%m-%d %H:%M %Z"
PLAIN_RATE_REASONS: Final[frozenset[str]] = frozenset({
    "Anthropic API rate limit", "Rate limit exceeded", "HTTP 429 rate limit",
})
TAIL_CHARS: Final[int] = 800
REASON_MAX: Final[int] = 120
EXIT_OK: Final[int] = 0
EXIT_BAD_INPUT: Final[int] = 2
EXIT_COOLING: Final[int] = 3
SECONDS_PER_UNIT: Final[dict[str, int]] = {"d": 86400, "h": 3600, "m": 60, "s": 1}
MONTHS: Final[dict[str, int]] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_NAMES: Final[str] = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
)
UNIT_NAMES: Final[str] = r"(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)"
EPOCH_RE: Final[re.Pattern[str]] = re.compile(r"\|(\d{10})\b")
ISO_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?"
)
DURATION_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:try again in|retry after|retry in|again in|resets? in|available in|\bin)\s+"
    rf"(\d+\s*{UNIT_NAMES}\b(?:[\s,]*(?:and\s+)?\d+\s*{UNIT_NAMES}\b)*)",
    re.I,
)
DURATION_PART_RE: Final[re.Pattern[str]] = re.compile(rf"(\d+)\s*({UNIT_NAMES})\b", re.I)
DATE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:try again at|resets?(?:\s+on|\s+at)?)\s*({MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"(?:,?\s+(\d{{4}}))?(?:,?\s+(?:at\s+)?(\d{{1,2}})(?::(\d{{2}}))?\s*([ap])\.?m\b)?",
    re.I,
)
TIME_RE: Final[re.Pattern[str]] = re.compile(
    r"resets?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", re.I,
)
# (pattern, provider, reason); the first match wins, so provider-specific phrases come before generic ones.
LIMIT_PATTERNS: Final[tuple[tuple[re.Pattern[str], str | None, str], ...]] = tuple(
    (re.compile(pattern, re.I), provider, reason)
    for pattern, provider, reason in (
        (r"claude ai usage limit reached", "claude", "Claude usage limit reached"),
        (r"5-hour limit reached", "claude", "Claude 5-hour limit reached"),
        (r"\bweekly limit\b", "claude", "Claude weekly limit"),
        (r"hit your limit", "claude", "Claude usage limit hit"),
        (r"limit will reset at", "claude", "Claude usage limit"),
        (r"credit balance is too low", "anthropic-api", "Anthropic API credit balance too low"),
        (r"rate_limit_error", "anthropic-api", "Anthropic API rate limit"),
        (r"hit your usage limit", "openai", "OpenAI usage limit hit"),
        (r"exceeded your current quota", "openai", "OpenAI quota exceeded"),
        (r"insufficient_quota", "openai", "OpenAI insufficient quota"),
        (r"monthly spending limit", "xai", "xAI monthly spending limit"),
        (r"credits? (?:are |is )?exhausted", "xai", "xAI credits exhausted"),
        (r"rate limit exceeded", "xai", "Rate limit exceeded"),
        (r"resource_exhausted", "gemini", "Gemini resource exhausted"),
        (r"quota exceeded", None, "Quota exceeded"),
        (r"usage limit reached", "claude", "Usage limit reached"),
        (r"usage limit", None, "Usage limit"),
        (r"out of credits", None, "Out of credits"),
        (r"(?:http|status|code|error)[\s:=]*429\b|\b429\s+(?:too many|rate|error)|too many requests", None,
         "HTTP 429 rate limit"),
    )
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(text: Any) -> datetime | None:
    """Strict reader for stored timestamps (Z suffix or an offset; naive means UTC)."""
    if not isinstance(text, str):
        return None
    try:
        moment: datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def clean_name(name: str) -> str:
    lowered: str = str(name).strip().lower()
    if not NAME_PATTERN.match(lowered):
        raise ValueError(f"invalid agent name: {name!r}")
    return lowered


def status_path() -> Path:
    explicit: str | None = os.environ.get(ENV_STATUS)
    if explicit:
        return Path(explicit)
    home: str | None = os.environ.get(ENV_HOME)
    base: Path = Path(home) if home else Path.home() / DEFAULT_HOME_DIR
    return base / STATUS_FILE


def empty_document() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "agents": {}}


def load(path: Path | None = None) -> dict[str, Any]:
    """The whole document, normalized. A missing or corrupt file reads as empty; this never raises."""
    target: Path = path or status_path()
    try:
        raw: Any = json.loads(target.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return empty_document()
    agents: Any = raw.get("agents") if isinstance(raw, dict) else None
    if not isinstance(agents, dict):
        return empty_document()
    kept: dict[str, Any] = {
        name: entry for name, entry in agents.items()
        if isinstance(name, str) and isinstance(entry, dict) and parse_iso(entry.get("reset_at")) is not None
    }
    return {"version": SCHEMA_VERSION, "agents": kept}


def save(document: dict[str, Any], path: Path | None = None) -> Path:
    """Atomic write: temp file in the same folder, fsync, os.replace."""
    target: Path = path or status_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding=ENCODING) as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def is_cooling(name: str, path: Path | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    entry: Any = load(path)["agents"].get(clean_name(name))
    if entry is None:
        return None
    reset: datetime | None = parse_iso(entry.get("reset_at"))
    moment: datetime = now or utc_now()
    return entry if reset is not None and reset > moment else None


def cooling_names(path: Path | None = None, now: datetime | None = None) -> list[str]:
    moment: datetime = now or utc_now()
    agents: dict[str, Any] = load(path)["agents"]
    return sorted(name for name, entry in agents.items() if parse_iso(entry["reset_at"]) > moment)  # type: ignore[operator]


def record(
    name: str, reset_at: datetime | None, source: str, set_by: str, reason: str,
    provider: str | None = None, path: Path | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Store a cooldown. No date means a provisional 5h cooldown flagged needs_date. An active cooldown is never
    shortened unless the source is user/manual; a confirmed date does replace a provisional guess."""
    key: str = clean_name(name)
    if source not in SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    moment: datetime = now or utc_now()
    provisional: bool = reset_at is None
    until: datetime = (moment + DEFAULT_PROVISIONAL) if reset_at is None else reset_at.astimezone(timezone.utc)
    entry: dict[str, Any] = {
        "state": STATE_COOLDOWN, "reset_at": to_iso(until), "source": "assumed" if provisional else source,
        "set_by": set_by, "reason": reason, "set_at": to_iso(moment), "provider": provider,
        "needs_date": provisional,
    }
    document: dict[str, Any] = load(path)
    existing: dict[str, Any] | None = document["agents"].get(key)
    if existing is not None and keeps_existing(existing, entry, source, moment):
        return existing
    document["agents"][key] = entry
    save(document, path)
    return entry


def keeps_existing(existing: dict[str, Any], new: dict[str, Any], source: str, now: datetime) -> bool:
    """True when the stored cooldown is active, later than the new one, and the new one may not shorten it."""
    if source in FORCING_SOURCES:
        return False
    old_reset: datetime | None = parse_iso(existing.get("reset_at"))
    new_reset: datetime = parse_iso(new["reset_at"])  # type: ignore[assignment]
    if old_reset is None or old_reset <= now or old_reset <= new_reset:
        return False
    return not (existing.get("needs_date") and not new["needs_date"])


def clear(name: str, path: Path | None = None) -> bool:
    key: str = clean_name(name)
    document: dict[str, Any] = load(path)
    if key not in document["agents"]:
        return False
    del document["agents"][key]
    save(document, path)
    return True


def expire(path: Path | None = None, now: datetime | None = None) -> list[str]:
    moment: datetime = now or utc_now()
    document: dict[str, Any] = load(path)
    due: list[str] = sorted(
        name for name, entry in document["agents"].items() if parse_iso(entry["reset_at"]) <= moment  # type: ignore[operator]
    )
    if not due:
        return []
    for name in due:
        del document["agents"][name]
    save(document, path)
    return due


def parse_epoch(text: str, now: datetime) -> datetime | None:
    match: re.Match[str] | None = EPOCH_RE.search(text)
    return datetime.fromtimestamp(int(match.group(1)), timezone.utc) if match else None


def parse_iso_text(text: str, now: datetime) -> datetime | None:
    match: re.Match[str] | None = ISO_RE.search(text)
    if match is None:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        moment: datetime = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        return None
    if zone and zone != "Z":
        sign: int = -1 if zone[0] == "-" else 1
        digits: str = zone[1:].replace(":", "")
        offset: timedelta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        return (moment - sign * offset).replace(tzinfo=timezone.utc)
    return moment.replace(tzinfo=timezone.utc)


def parse_relative(text: str, now: datetime) -> datetime | None:
    match: re.Match[str] | None = DURATION_RE.search(text)
    if match is None:
        return None
    seconds: int = sum(
        int(amount) * SECONDS_PER_UNIT[unit[0].lower()] for amount, unit in DURATION_PART_RE.findall(match.group(1))
    )
    return now + timedelta(seconds=seconds)


def clock(hour: str | None, minute: str | None, meridiem: str | None) -> tuple[int, int] | None:
    """12-hour clock to (hour, minute) in 24-hour form; no hour means midnight; None when out of range."""
    if hour is None or meridiem is None:
        return (0, 0) if hour is None else None
    value: int = int(hour)
    if not 1 <= value <= 12:
        return None
    return value % 12 + (12 if meridiem.lower() == "p" else 0), int(minute or 0)


def parse_month_date(text: str, now: datetime) -> datetime | None:
    match: re.Match[str] | None = DATE_RE.search(text)
    if match is None:
        return None
    month_text, day, year, hour, minute, meridiem = match.groups()
    time_of_day: tuple[int, int] | None = clock(hour, minute, meridiem)
    if time_of_day is None:
        return None
    month: int = MONTHS[month_text[:3].lower()]
    try:
        moment: datetime = datetime(int(year or now.year), month, int(day), *time_of_day, tzinfo=timezone.utc)
        if year is None and moment <= now:
            moment = moment.replace(year=now.year + 1)
    except ValueError:
        return None
    return moment


def parse_time_only(text: str, now: datetime) -> datetime | None:
    match: re.Match[str] | None = TIME_RE.search(text)
    if match is None:
        return None
    time_of_day: tuple[int, int] | None = clock(*match.groups())
    if time_of_day is None:
        return None
    moment: datetime = now.replace(hour=time_of_day[0], minute=time_of_day[1], second=0, microsecond=0)
    return moment if moment > now else moment + timedelta(days=1)


def parse_reset(text: str, now: datetime) -> datetime | None:
    """The reset moment a limit message names (tz-aware UTC), or None. First matching pattern wins."""
    anchor: datetime = now.astimezone(timezone.utc)
    for parser in (parse_epoch, parse_iso_text, parse_relative, parse_month_date, parse_time_only):
        moment: datetime | None = parser(text, anchor)
        if moment is not None:
            return moment
    return None


def short(text: str) -> str:
    return " ".join(text.split())[:REASON_MAX]


def detect(
    text: str, exit_code: int | None, agent: str, provider: str | None = None, now: datetime | None = None,
) -> dict[str, Any] | None:
    """Recognise a usage/quota/rate limit in agent output. A clean exit (0) is judged on the tail only, so a
    transcript that merely discusses limits is not mistaken for one."""
    moment: datetime = (now or utc_now()).astimezone(timezone.utc)
    haystack: str = text[-TAIL_CHARS:] if exit_code == 0 else text
    hits: list[tuple[str | None, str]] = [
        (pattern_provider, reason) for pattern, pattern_provider, reason in LIMIT_PATTERNS if pattern.search(haystack)
    ]
    if not hits:
        return None
    pattern_provider, reason = hits[0]
    plain_rate: bool = all(hit_reason in PLAIN_RATE_REASONS for _, hit_reason in hits)
    reset: datetime | None = parse_reset(haystack, moment)
    short_wait: bool = reset is not None and reset - moment < MIN_COOLDOWN
    return {
        "agent": agent, "provider": provider or pattern_provider,
        "reset_at": to_iso(reset) if reset else None, "reason": short(reason),
        # a plain rate limit with no known reset is ordinary backoff, never a cooldown
        "transient": short_wait or (plain_rate and reset is None),
    }


def record_detection(
    det: dict[str, Any], set_by: str, path: Path | None = None, now: datetime | None = None,
) -> dict[str, Any] | None:
    """Record a detection unless it is transient (plain retry/backoff covers a wait under 15 minutes)."""
    if det.get("transient"):
        return None
    reset: datetime | None = parse_iso(det.get("reset_at"))
    return record(
        det["agent"], reset, "error" if reset else "assumed", set_by, det.get("reason", ""),
        det.get("provider"), path, now,
    )


def parse_user_date(text: str, now: datetime) -> datetime | None:
    return parse_reset(text, now) or parse_reset(f"resets {text}", now)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True))


def cmd_set(args: argparse.Namespace) -> int:
    now: datetime = utc_now()
    reset: datetime | None = (
        parse_reset(f"try again in {args.in_text}", now) if args.in_text else parse_user_date(args.until, now)
    )
    if reset is None:
        print_json({"error": "cannot parse date", "text": args.in_text or args.until})
        return EXIT_BAD_INPUT
    entry: dict[str, Any] = record(args.agent, reset, args.source, args.by, args.reason, args.provider, now=now)
    print_json({"agent": clean_name(args.agent), **entry})
    return EXIT_OK


def cmd_clear(args: argparse.Namespace) -> int:
    print_json({"cleared": clear(args.agent)})
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    now: datetime = utc_now()
    agents: dict[str, Any] = load()["agents"]
    rows: list[dict[str, Any]] = [
        {"name": name, **entry} for name, entry in sorted(agents.items())
        if args.all or parse_iso(entry["reset_at"]) > now  # type: ignore[operator]
    ]
    print_json({"cooling": rows, "now": to_iso(now)})
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    entry: dict[str, Any] | None = is_cooling(args.agent)
    if entry is None:
        print_json({"agent": clean_name(args.agent), "cooling": False})
        return EXIT_OK
    print_json({
        "agent": clean_name(args.agent), "cooling": True, "reset_at": entry["reset_at"],
        "reason": entry.get("reason"), "needs_date": bool(entry.get("needs_date")),
    })
    return EXIT_COOLING


def cmd_detect(args: argparse.Namespace) -> int:
    det: dict[str, Any] | None = detect(sys.stdin.read(), args.exit_code, args.agent, args.provider)
    if det is None:
        print_json({"limited": False})
        return EXIT_OK
    result: dict[str, Any] = {"limited": True, **det, "needs_date": det["reset_at"] is None, "recorded": False}
    if args.record:
        result["recorded"] = record_detection(det, args.by) is not None
    print_json(result)
    return EXIT_OK


def cmd_expire(args: argparse.Namespace) -> int:
    print_json({"expired": expire()})
    return EXIT_OK


def note_line(name: str, entry: dict[str, Any]) -> str:
    reset: datetime = parse_iso(entry["reset_at"])  # type: ignore[assignment]
    when: str = f"{reset.astimezone().strftime(LOCAL_NOTE_FORMAT)} / {reset.strftime(UTC_NOTE_FORMAT)}"
    reason: str = entry.get("reason") or "usage limit"
    tail: str = "; date unconfirmed, ask the user" if entry.get("needs_date") else ""
    return f"dts2: cooling down, do not call: {name} until {when} ({reason}){tail}"


def session_note(now: datetime | None = None) -> str:
    moment: datetime = now or utc_now()
    lines: list[str] = []
    back: list[str] = expire(now=moment)
    if back:
        lines.append(f"dts2: re-enabled {', '.join(back)} (cooldown ended).")
    agents: dict[str, Any] = load()["agents"]
    lines.extend(note_line(name, agents[name]) for name in cooling_names(now=moment))
    return "\n".join(lines)


def cmd_session_note(args: argparse.Namespace) -> int:
    try:
        text: str = session_note()
    except Exception:  # a hook must never fail a session start
        return EXIT_OK
    if text:
        print(text)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared agent cooldown registry.")
    commands = parser.add_subparsers(dest="command", required=True)
    set_cmd = commands.add_parser("set", help="record a cooldown")
    set_cmd.add_argument("agent")
    when = set_cmd.add_mutually_exclusive_group(required=True)
    when.add_argument("--until", default="")
    when.add_argument("--in", dest="in_text", default="")
    set_cmd.add_argument("--reason", default="usage limit")
    set_cmd.add_argument("--by", default="user")
    set_cmd.add_argument("--provider", default=None)
    set_cmd.add_argument("--source", choices=sorted(FORCING_SOURCES), default="manual")
    set_cmd.set_defaults(run=cmd_set)
    clear_cmd = commands.add_parser("clear", help="remove a cooldown")
    clear_cmd.add_argument("agent")
    clear_cmd.set_defaults(run=cmd_clear)
    list_cmd = commands.add_parser("list", help="show cooldowns")
    list_cmd.add_argument("--all", action="store_true")
    list_cmd.set_defaults(run=cmd_list)
    check_cmd = commands.add_parser("check", help="exit 3 when the agent is cooling")
    check_cmd.add_argument("agent")
    check_cmd.set_defaults(run=cmd_check)
    detect_cmd = commands.add_parser("detect", help="read output on stdin, detect a limit")
    detect_cmd.add_argument("--agent", required=True)
    detect_cmd.add_argument("--provider", default=None)
    detect_cmd.add_argument("--exit-code", type=int, default=None)
    detect_cmd.add_argument("--record", action="store_true")
    detect_cmd.add_argument("--by", default="detect")
    detect_cmd.set_defaults(run=cmd_detect)
    commands.add_parser("expire", help="drop ended cooldowns").set_defaults(run=cmd_expire)
    commands.add_parser("session-note", help="SessionStart hook text").set_defaults(run=cmd_session_note)
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        return int(args.run(args))
    except ValueError as error:
        print_json({"error": str(error)})
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
