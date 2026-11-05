#!/usr/bin/env python3
"""Protected paths (G-62): files a son must never change, however the diff reaches the head.

A son's tool deny list and sandbox stop most direct writes, but a committed branch is only data until the head publishes
it. The head asks `diff_touches_protected(names)` for every lane diff; a non-empty answer parks the lane and appends one
Decisions item for the user instead of pushing.

Protected: the resolved git common dir (config, info, hooks), `.gitattributes` (filter and diff drivers run commands),
`.github/workflows/**`, the checks script, CODEOWNERS files, the plugin's `hooks/`, the head-only shared `.harness`
records and every lane's `merge-go.md`."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import state_io  # noqa: E402
from son_launch import git_common_dir  # noqa: E402

GIT_DIR_ENTRIES: Final[tuple[str, ...]] = ("config", "info/**", "hooks/**", "modules/**")
WORKFLOW_GLOB: Final[str] = ".github/workflows/**"
ATTRIBUTES_GLOB: Final[str] = "**/.gitattributes"
CODEOWNERS_GLOBS: Final[tuple[str, ...]] = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
HOOKS_GLOB: Final[str] = "hooks/**"
MERGE_GO_GLOB: Final[str] = "**/merge-go.md"
HEAD_ONLY_RECORDS: Final[tuple[str, ...]] = (
    state_io.STATE_MD_REL, state_io.ACTION_ITEMS_REL, state_io.END_STATE_REL, state_io.HANDOFF_LATEST_REL,
    state_io.rel("council.md"), state_io.rel("lessons.md"), state_io.rel("autopilot", "latest.md"),
)
DECISIONS_GROUP: Final[str] = "Decisions"
SHOWN_PATHS: Final[int] = 5


def repo_globs() -> list[str]:
    """Repo-relative globs, `**` crossing folders, `*` staying inside one."""
    return [ATTRIBUTES_GLOB, WORKFLOW_GLOB, state_io.CHECKS_SH_REL, *CODEOWNERS_GLOBS, HOOKS_GLOB,
            *HEAD_ONLY_RECORDS, MERGE_GO_GLOB]


def protected_paths(repo: Path) -> list[str]:
    """Every protected location for this repo: absolute entries under the resolved git common dir, then repo-relative globs."""
    common: Path = git_common_dir(Path(repo))
    return [*(str(common / entry) for entry in GIT_DIR_ENTRIES), *repo_globs()]


def glob_regex(glob: str) -> re.Pattern[str]:
    """`**/` matches any folders (or none), `**` anything, `*` anything except `/`, `?` one character except `/`."""
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
    return re.compile("^" + "".join(out) + "$")


def clean_relative(path: str) -> str | None:
    """Forward slashes, no `./`, `..` folded away; None when the path climbs out of its root."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def relative_to(path: str, root: Path) -> str | None:
    """`path` as a clean repo-relative string; None when it is absolute and outside `root`."""
    if not path.startswith(("/", "\\")):
        return clean_relative(path)
    try:
        return clean_relative(str(Path(path).resolve().relative_to(root.resolve())))
    except ValueError:
        return None


def in_git_dir(path: str, repo: Path) -> bool:
    common: Path = git_common_dir(Path(repo))
    absolute: Path = Path(path) if path.startswith("/") else Path(repo).resolve() / path
    try:
        inside: str = absolute.resolve().relative_to(common).as_posix()
    except ValueError:
        return False
    return any(glob_regex(entry).match(inside) for entry in GIT_DIR_ENTRIES)


def is_protected(path: str | Path, repo: Path) -> bool:
    """True when a change to `path` (repo-relative or absolute) must go to the user."""
    text: str = str(path)
    if in_git_dir(text, repo):
        return True
    relative: str | None = relative_to(text, Path(repo))
    if relative is None:
        return False
    if relative.startswith(".git/"):
        inside: str = relative.removeprefix(".git/")
        return any(glob_regex(entry).match(inside) for entry in GIT_DIR_ENTRIES)
    return any(glob_regex(glob).match(relative) for glob in repo_globs())


def diff_touches_protected(diff_names: list[str], repo: Path) -> list[str]:
    """The names in a diff (`git diff --name-only`) that are protected, in order, without repeats."""
    seen: list[str] = []
    for name in diff_names:
        if name and name not in seen and is_protected(name, repo):
            seen.append(name)
    return seen


def park_item_text(lane: str, touched: list[str]) -> str:
    shown: str = ", ".join(touched[:SHOWN_PATHS]) + (f" (+{len(touched) - SHOWN_PATHS} more)" if len(touched) > SHOWN_PATHS else "")
    return f"Lane {lane} parked: its diff changes protected files ({shown}). Review the diff, then publish it by hand or re-plan the lane."


def park_decision(repo: Path, lane: str, touched: list[str], today: date | None = None) -> dict[str, Any]:
    """Append one Decisions item through the action-items writer; the head publishes nothing for this lane."""
    items = _load.load("action-items")
    path: Path = Path(repo) / items.ITEMS_PATH
    lines: list[str] = items.read_lines(path)
    row: dict[str, Any] = items.add_row(lines, DECISIONS_GROUP, park_item_text(lane, touched), today or date.today())
    items.write_lines(path, lines)
    return {"parked": True, "lane": lane, "touched": touched, "item": row["id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("paths")
    check = sub.add_parser("check", help="names on the command line (or one per line on stdin) that are protected")
    check.add_argument("names", nargs="*")
    args = parser.parse_args(argv)
    repo: Path = Path(args.repo)
    if args.cmd == "paths":
        print(json.dumps({"protected": protected_paths(repo)}))
        return 0
    names: list[str] = args.names or [line.strip() for line in sys.stdin if line.strip()]
    touched: list[str] = diff_touches_protected(names, repo)
    print(json.dumps({"touched": touched, "ok": not touched}))
    return 1 if touched else 0


if __name__ == "__main__":
    sys.exit(main())
