#!/usr/bin/env python3
"""Add the harness planning and PR rules to a user's CLAUDE.md, once.

plan  : print the unified diff apply would make; writes nothing
apply : back up CLAUDE.md, then write the marked block (replaced in place on a rerun)
check : exit 0 when the block is present and current, 1 when missing or stale

The block sits between its own markers, so a rerun never duplicates it and text
outside the markers is never touched. Default target is ~/.claude/CLAUDE.md;
--claude-home points at another folder (tests, a project .claude, a second home).
"""
from __future__ import annotations

import argparse
import difflib
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402,F401
from state_io import atomic_write  # noqa: E402

START: Final[str] = "<!-- dts2-plan-rules:start -->"
END: Final[str] = "<!-- dts2-plan-rules:end -->"
TARGET_NAME: Final[str] = "CLAUDE.md"
BODY: Final[str] = """## Plans, checks and pull requests (dts2 harness)

- Plans shown to me are for scanning: concise bullets, no restated request, empty sections omitted.
- Each plan step names the files it changes, how it is verified (command or check) and any one-way door.
- End every plan with **Assumptions** (what you assumed without asking) and numbered **Unresolved questions**, each with your recommended default.
- Worker briefs, handoff docs and run state stay complete and explicit; the terse style is for plans shown to me only.
- When a mistake or review comment recurs, propose a deterministic check (lint rule, test or hook) instead of a new prose rule. Prose rules are for judgement calls only. Delete steering lines that change nothing.
- Every pull request states `Merge danger: one-way | two-way door — blast radius: <who or what breaks>` and an Evidence section with a before and after.
- Use the repository's GLOSSARY.md terms in code, plans and reviews when it has one."""


def block() -> str:
    return f"{START}\n{BODY}\n{END}\n"


def merged(current: str) -> str:
    """The file text with exactly one current block: replaced in place, or appended."""
    start: int = current.find(START)
    end: int = current.find(END)
    if start >= 0 and end > start:
        tail: str = current[end + len(END):]
        return current[:start] + block().rstrip("\n") + tail
    if not current:
        return block()
    separator: str = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
    return current + separator + block()


def diff(path: Path, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=str(path), tofile=f"{path} (after apply)",
    )
    return "".join(lines)


def backup(path: Path, claude_home: Path) -> Path:
    folder: Path = claude_home / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target: Path = folder / f"{TARGET_NAME}.{datetime.now():%Y%m%d-%H%M%S-%f}"
    shutil.copy2(path, target)
    return target


def run(command: str, claude_home: Path) -> int:
    path: Path = claude_home / TARGET_NAME
    before: str = path.read_text(encoding="utf-8") if path.is_file() else ""
    after: str = merged(before)
    if command == "check":
        print("current" if before == after else ("stale" if START in before else "missing"))
        return 0 if before == after else 1
    if before == after:
        print(f"{path}: already current, nothing to do")
        return 0
    if command == "plan":
        print(diff(path, before, after), end="")
        return 0
    if path.is_file():
        print(f"backup: {backup(path, claude_home)}")
    atomic_write(path, after)
    print(f"wrote: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "apply", "check"))
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    args = parser.parse_args(argv)
    return run(args.command, args.claude_home.expanduser())


if __name__ == "__main__":
    sys.exit(main())
