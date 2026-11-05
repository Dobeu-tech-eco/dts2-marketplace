#!/usr/bin/env python3
"""Read .harness/lessons.md: parse lesson lines, match their paths: globs against changed files, pick the newest few."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Final

LESSONS_PATH: Final[str] = ".harness/lessons.md"
MAX_LESSONS: Final[int] = 5
GIT_TIMEOUT_S: Final[int] = 5
HARNESS_PREFIX: Final[str] = ".harness/"
LESSON_LINE: Final[re.Pattern[str]] = re.compile(r"^- \[(?P<id>[A-Z]-\d+)\]\s")
PATHS_FIELD: Final[re.Pattern[str]] = re.compile(r"\{paths:\s*(?P<globs>[^}]*)\}")
LEASE_GLOB: Final[str] = ".harness/runs/*/*/lease.json"
ACTIVE: Final[str] = "active"


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


def matching_lessons(repo: Path, files: list[str] | None = None, limit: int = MAX_LESSONS) -> list[str]:
    """Newest `limit` lessons whose paths: globs match a changed file; lessons without globs always match."""
    names: list[str] = changed_files(repo) if files is None else files
    matched: list[str] = [line for line in lesson_lines(repo) if line_matches(line, names)]
    return matched[-limit:] if limit > 0 else []
