#!/usr/bin/env python3
"""Split a large review by path group (AA-7). Up to the line threshold the axis reviewers each read the whole diff. Above it, each
reviewer takes one path group and runs every axis on that slice, so no reviewer re-reads the whole diff. Read-only.

  plan --repo R --base REF [--threshold N] [--max-reviewers K]    JSON: split or not, and the slice for each reviewer

The final whole-diff reviewer is not split: it gets the findings digest (findings.py digest) and `git diff --stat`."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any, Final

LINE_THRESHOLD: Final[int] = 800
GROUP_DEPTH: Final[int] = 2
DEFAULT_MAX_REVIEWERS: Final[int] = 3
ROOT_GROUP: Final[str] = "."
BINARY_MARK: Final[str] = "-"
RENAME_BRACES: Final[re.Pattern[str]] = re.compile(r"\{[^}]*? => ([^}]*)\}")


def parse_numstat(text: str) -> list[tuple[str, int]]:
    """(path, changed lines) from `git diff --numstat`; a binary file counts 0 and a rename shows its new path."""
    stats: list[tuple[str, int]] = []
    for row in text.splitlines():
        parts: list[str] = row.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        lines: int = 0 if BINARY_MARK in (added, deleted) else int(added) + int(deleted)
        stats.append((new_path(path), lines))
    return stats


def new_path(path: str) -> str:
    """The path after a rename: `src/{old => new}.py` -> `src/new.py`, `old.py => new.py` -> `new.py`."""
    if "{" in path:
        return RENAME_BRACES.sub(r"\1", path).replace("//", "/")
    return path.split(" => ")[-1]


def path_group(path: str) -> str:
    """The first GROUP_DEPTH folders of the path, or the root group for a top-level file."""
    parts: tuple[str, ...] = PurePosixPath(path).parts
    return "/".join(parts[:GROUP_DEPTH]) if len(parts) > 1 else ROOT_GROUP


def group_stats(stats: list[tuple[str, int]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for path, lines in stats:
        entry: dict[str, Any] = groups.setdefault(path_group(path), {"files": [], "lines": 0})
        entry["files"].append(path)
        entry["lines"] += lines
    return groups


def pack(groups: dict[str, dict[str, Any]], slots: int) -> list[dict[str, Any]]:
    """Largest group first into the lightest slot, so the reviewers carry about the same number of lines."""
    bins: list[dict[str, Any]] = [{"groups": [], "files": [], "lines": 0} for _ in range(max(1, slots))]
    for name, entry in sorted(groups.items(), key=lambda kv: (-kv[1]["lines"], kv[0])):
        target: dict[str, Any] = min(bins, key=lambda b: b["lines"])
        target["groups"].append(name)
        target["files"].extend(sorted(entry["files"]))
        target["lines"] += entry["lines"]
    return [{**b, "reviewer": n} for n, b in enumerate((b for b in bins if b["files"]), start=1)]


def plan_review(stats: list[tuple[str, int]], threshold: int = LINE_THRESHOLD, max_reviewers: int = DEFAULT_MAX_REVIEWERS) -> dict[str, Any]:
    """`split` is true only when the diff is above the threshold and holds more than one path group."""
    total: int = sum(lines for _, lines in stats)
    groups: dict[str, dict[str, Any]] = group_stats(stats)
    if total <= threshold or len(groups) < 2:
        return {"split": False, "total_lines": total, "threshold": threshold, "groups": sorted(groups), "slices": [],
                "note": "reviewers read the whole diff, one axis each"}
    slices: list[dict[str, Any]] = pack(groups, min(max_reviewers, len(groups)))
    return {"split": True, "total_lines": total, "threshold": threshold, "groups": sorted(groups), "slices": slices,
            "note": "one reviewer per slice, every axis on its own files; the final reviewer gets the findings digest and the diff stat"}


def numstat(repo: str, base: str) -> list[tuple[str, int]]:
    done = subprocess.run(["git", "-C", repo, "diff", "--numstat", f"{base}..HEAD"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"git diff --numstat failed: {done.stderr.strip()}")
    return parse_numstat(done.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--repo", default=".")
    plan_p.add_argument("--base", required=True)
    plan_p.add_argument("--threshold", type=int, default=LINE_THRESHOLD)
    plan_p.add_argument("--max-reviewers", type=int, default=DEFAULT_MAX_REVIEWERS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(plan_review(numstat(args.repo, args.base), args.threshold, args.max_reviewers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
