#!/usr/bin/env python3
"""Detect where a session sits: workspace root, workspace member, single repo, or none. Always exits 0."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lessons import matching_lessons  # noqa: E402

MANIFEST_NAME: Final[str] = ".harness-workspace.yaml"
REPO_CONFIG: Final[str] = ".harness/config.yaml"
END_STATE: Final[str] = ".harness/end-state.md"
MAX_LEVELS: Final[int] = 8
ADVICE_MEMBER: Final[str] = "Run from {root}; this folder is a member repo of that workspace."
ADVICE_SINGLE: Final[str] = "Single-repo harness."
ADVICE_ROOT: Final[str] = "Workspace root."
ADVICE_NONE: Final[str] = "No harness here; run /dts2-harness:setup."


def find_ancestor_manifest(start: Path) -> Path | None:
    current: Path = start
    for _ in range(MAX_LEVELS):
        parent: Path = current.parent
        if parent == current:
            return None
        if (parent / MANIFEST_NAME).is_file():
            return parent
        current = parent
    return None


def optional_file(path: Path) -> str | None:
    return str(path) if path.is_file() else None


def build(scope: str, cwd: Path, root: Path | None, advice: str) -> dict[str, Any]:
    effective: Path = root if root is not None else cwd
    return {
        "scope": scope,
        "cwd": str(cwd),
        "workspaceRoot": str(root) if root is not None else None,
        "manifest": optional_file(root / MANIFEST_NAME) if root is not None else None,
        "repoConfig": optional_file(cwd / REPO_CONFIG),
        "endState": (effective / END_STATE).is_file(),
        "advice": advice,
    }


def detect(path: Path) -> dict[str, Any]:
    cwd: Path = path.resolve()
    if (cwd / MANIFEST_NAME).is_file():
        return build("workspace-root", cwd, cwd, ADVICE_ROOT)
    root: Path | None = find_ancestor_manifest(cwd)
    if root is not None:
        return build("workspace-member", cwd, root, ADVICE_MEMBER.format(root=root))
    if (cwd / REPO_CONFIG).is_file():
        return build("single", cwd, None, ADVICE_SINGLE)
    return build("none", cwd, None, ADVICE_NONE)


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="folder to inspect")
    parser.add_argument("--lessons", action="store_true", help="add the lessons whose paths: globs match the changed files (newest 5)")
    parser.add_argument("--files", help="with --lessons: comma-separated files to match instead of the git changes")
    args: argparse.Namespace = parser.parse_args()
    try:
        result: dict[str, Any] = detect(Path(args.path))
    except OSError:
        result = build("none", Path(args.path), None, ADVICE_NONE)
    if args.lessons:
        result["lessons"] = matching_lessons(Path(args.path).resolve(), args.files.split(",") if args.files else None)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
