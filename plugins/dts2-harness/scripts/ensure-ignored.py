#!/usr/bin/env python3
"""Append missing harness entries to a repo's .gitignore. Idempotent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

IGNORED_PATHS: Final[tuple[str, ...]] = (
    ".harness/runs/",
    ".harness/lessons-inbox.md",
    ".harness.bak-*/",
    ".claude/*.local.md",
    ".harness/review/screens/",
    ".harness/gtm/*/screens/",
)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def append_entries(path: Path, entries: list[str]) -> None:
    if not entries:
        return
    existing: str = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix: str = "\n" if existing and not existing.endswith("\n") else ""
    path.write_text(existing + prefix + "\n".join(entries) + "\n", encoding="utf-8")


def ensure_ignored(repo: Path, extra: list[str]) -> dict[str, list[str]]:
    gitignore: Path = repo / ".gitignore"
    have: set[str] = {line.strip() for line in read_lines(gitignore)}
    wanted: list[str] = list(dict.fromkeys([*IGNORED_PATHS, *extra]))
    added: list[str] = [w for w in wanted if w not in have]
    present: list[str] = [w for w in wanted if w in have]
    append_entries(gitignore, added)
    return {"added": added, "present": present}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--extra", nargs="*", default=[])
    args = parser.parse_args()
    print(json.dumps(ensure_ignored(Path(args.repo), args.extra)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
