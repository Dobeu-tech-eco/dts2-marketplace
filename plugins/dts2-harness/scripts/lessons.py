#!/usr/bin/env python3
"""Read and maintain .harness/lessons.md: match paths: globs, record promotions and regressions, drop stale lessons.

Commands (JSON on stdout): promote, regress, stats, prune. Example: lessons.py <repo> promote L-014 --lives-at .harness/checks.sh
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

LESSONS_PATH: Final[str] = ".harness/lessons.md"
MAX_LESSONS: Final[int] = 5
GIT_TIMEOUT_S: Final[int] = 5
HARNESS_PREFIX: Final[str] = ".harness/"
LESSON_LINE: Final[re.Pattern[str]] = re.compile(r"^- \[(?P<id>[A-Z]-\d+)\]\s")
PATHS_FIELD: Final[re.Pattern[str]] = re.compile(r"\{paths:\s*(?P<globs>[^}]*)\}")
LEASE_GLOB: Final[str] = ".harness/runs/*/*/lease.json"
ACTIVE: Final[str] = "active"
DEFAULT_STALE_DAYS: Final[int] = 90
META: Final[re.Pattern[str]] = re.compile(r"\((?P<meta>(?:seen|last|source|promoted_at|regressed|lives)[^)]*)\)")
LAST_SEEN: Final[re.Pattern[str]] = re.compile(r"\blast (\d{4}-\d{2}-\d{2})")
PROMOTED_AT: Final[re.Pattern[str]] = re.compile(r"promoted_at:\s*(\d{4}-\d{2}-\d{2})")
REGRESSED: Final[re.Pattern[str]] = re.compile(r"regressed:\s*(\d+)")
LIVES_AT: Final[re.Pattern[str]] = re.compile(r"lives at \S+")


def lesson_globs(line: str) -> list[str]:
    """The paths: globs on a lesson line; an empty list means the lesson applies everywhere."""
    found: re.Match[str] | None = PATHS_FIELD.search(line)
    if found is None:
        return []
    return [part.strip() for part in found.group("globs").split(",") if part.strip()]


def glob_regex(glob: str) -> re.Pattern[str]:
    """`**` crosses directories, `*` and `?` stay inside one path segment."""
    out: list[str] = []
    index: int = 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def line_matches(line: str, files: list[str]) -> bool:
    globs: list[str] = lesson_globs(line)
    if not globs:
        return True
    patterns: list[re.Pattern[str]] = [glob_regex(glob) for glob in globs]
    return any(pattern.match(name) for pattern in patterns for name in files)


def lesson_lines(repo: Path) -> list[str]:
    path: Path = repo / LESSONS_PATH
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if LESSON_LINE.match(line)]


def active_lease_files(repo: Path) -> list[str]:
    names: list[str] = []
    for lease in sorted(repo.glob(LEASE_GLOB)):
        try:
            record: Any = json.loads(lease.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("status") == ACTIVE and isinstance(record.get("files"), list):
            names += [str(name) for name in record["files"]]
    return names


def changed_files(repo: Path) -> list[str]:
    """Paths git reports as modified or untracked, plus files held by active lane leases. Harness state is skipped."""
    try:
        done: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "status", "--porcelain", "-uall"], cwd=str(repo), capture_output=True, text=True, check=False,
            timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return active_lease_files(repo)
    names: list[str] = []
    for row in done.stdout.splitlines() if done.returncode == 0 else []:
        name: str = row[3:].split(" -> ")[-1].strip().strip('"')
        if name:
            names.append(name)
    return [name for name in [*names, *active_lease_files(repo)] if not name.startswith(HARNESS_PREFIX)]


def is_promoted(line: str) -> bool:
    return PROMOTED_AT.search(line) is not None


def regressed_count(line: str) -> int:
    found: re.Match[str] | None = REGRESSED.search(line)
    return int(found.group(1)) if found else 0


def is_enforced(line: str) -> bool:
    """A promoted lesson that has not regressed is held by its check, so it is not injected into context."""
    return is_promoted(line) and regressed_count(line) == 0


def matching_lessons(repo: Path, files: list[str] | None = None, limit: int = MAX_LESSONS) -> list[str]:
    """Newest `limit` lessons whose paths: globs match a changed file; lessons without globs always match.
    Promoted lessons that have not regressed are left out."""
    names: list[str] = changed_files(repo) if files is None else files
    matched: list[str] = [line for line in lesson_lines(repo) if not is_enforced(line) and line_matches(line, names)]
    return matched[-limit:] if limit > 0 else []


def line_id(line: str) -> str:
    found: re.Match[str] | None = LESSON_LINE.match(line)
    return found.group("id") if found else ""


def with_meta(line: str, edit: Any) -> str:
    """Apply `edit(meta) -> meta` to the metadata parenthetical; add one when the line has none."""
    found: re.Match[str] | None = META.search(line)
    if found is None:
        return f"{line} ({edit('').lstrip(', ')})"
    return line[:found.start("meta")] + edit(found.group("meta")) + line[found.end("meta"):]


def rewrite(repo: Path, edit_line: Any) -> dict[str, Any]:
    path: Path = repo / LESSONS_PATH
    lines: list[str] = path.read_text(encoding="utf-8", errors="replace").split("\n") if path.is_file() else []
    result: dict[str, Any] = {"ok": False}
    out: list[str] = []
    for line in lines:
        replaced: tuple[str | None, dict[str, Any]] = edit_line(line)
        if replaced[0] is None:
            result.update(replaced[1])
            continue
        if replaced[1]:
            result.update(replaced[1])
        out.append(replaced[0])
    if result.get("ok"):
        atomic_write(path, "\n".join(out))
    return result


def promote(repo: Path, lesson: str, lives_at: str | None, today: date) -> dict[str, Any]:
    def edit(meta: str) -> str:
        meta = PROMOTED_AT.sub("", meta).rstrip(", ")
        meta += f", promoted_at: {today.isoformat()}"
        if lives_at and not LIVES_AT.search(meta):
            meta += f", lives at {lives_at}"
        return meta

    def edit_line(line: str) -> tuple[str | None, dict[str, Any]]:
        if line_id(line) != lesson:
            return line, {}
        return with_meta(line, edit), {"ok": True, "id": lesson, "promoted_at": today.isoformat()}

    return rewrite(repo, edit_line)


def regress(repo: Path, lesson: str) -> dict[str, Any]:
    def edit_line(line: str) -> tuple[str | None, dict[str, Any]]:
        if line_id(line) != lesson:
            return line, {}
        if not is_promoted(line):
            return line, {"ok": False, "id": lesson, "detail": "not promoted; nothing can regress"}
        count: int = regressed_count(line) + 1
        edited: str = with_meta(line, lambda meta: REGRESSED.sub("", meta).rstrip(", ") + f", regressed: {count}")
        return edited, {"ok": True, "id": lesson, "regressed": count}

    result: dict[str, Any] = rewrite(repo, edit_line)
    return result if "id" in result else {"ok": False, "id": lesson, "detail": "no such lesson"}


def is_stale(line: str, today: date, stale_days: int) -> bool:
    found: re.Match[str] | None = LAST_SEEN.search(line)
    if found is None or is_promoted(line):
        return False
    try:
        seen: date = date.fromisoformat(found.group(1))
    except ValueError:
        return False
    return today - seen > timedelta(days=stale_days)


def prune(repo: Path, today: date, stale_days: int) -> dict[str, Any]:
    dropped: list[str] = []

    def edit_line(line: str) -> tuple[str | None, dict[str, Any]]:
        if LESSON_LINE.match(line) and is_stale(line, today, stale_days):
            dropped.append(line_id(line))
            return None, {"ok": True}
        return line, {}

    rewrite(repo, edit_line)
    return {"ok": True, "dropped": dropped, "stale_days": stale_days}


def stats(repo: Path) -> dict[str, Any]:
    lines: list[str] = lesson_lines(repo)
    return {"lessons": len(lines), "promoted": sum(1 for line in lines if is_promoted(line)),
            "regressed": sum(1 for line in lines if regressed_count(line) > 0)}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("promote", "regress"):
        cmd: argparse.ArgumentParser = sub.add_parser(name)
        cmd.add_argument("lesson", help="lesson id such as L-014")
        cmd.add_argument("--today", default=None, help="ISO date (default: today)")
        if name == "promote":
            cmd.add_argument("--lives-at", default=None, help="where the check lives")
    sub.add_parser("stats")
    pruner: argparse.ArgumentParser = sub.add_parser("prune")
    pruner.add_argument("--today", default=None)
    pruner.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    args: argparse.Namespace = parser.parse_args()
    repo: Path = Path(args.repo)
    today: date = date.fromisoformat(args.today) if getattr(args, "today", None) else date.today()
    if args.command == "promote":
        result: dict[str, Any] = promote(repo, args.lesson, args.lives_at, today)
        if not result.get("ok"):
            result = {"ok": False, "id": args.lesson, "detail": "no such lesson"}
    elif args.command == "regress":
        result = regress(repo, args.lesson)
    elif args.command == "prune":
        result = prune(repo, today, args.stale_days)
    else:
        result = stats(repo)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
