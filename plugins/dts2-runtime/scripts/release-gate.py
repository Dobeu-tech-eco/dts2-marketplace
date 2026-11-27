#!/usr/bin/env python3
"""Release gate: a runtime change that reaches main must carry a version bump.

Claude Code updates an installed plugin only when its version changes, so a change under plugins/dts2-runtime/ that
lands on main without a plugin.json bump never reaches anyone. This script compares the base ref with HEAD: when any
shipped file under the runtime folder changed (tests/ and changelog.d/ are not shipped behavior), the plugin.json
version at HEAD must be greater than the one at the base, and the runtime CHANGELOG.md at HEAD must hold a
`## [X.Y.Z]` heading for that version. Exit 0 when the gate passes or does not apply, 1 when it
fails, 2 on a usage or git error. JSON on stdout. Read-only: it never writes, fetches, or changes a ref.

With --pr-body PATH the verdict also fails when the PR body lacks the Loop gate block (see pr_loop.py verify-body).

Usage: release-gate.py --base origin/main [--head HEAD] [--pr-body PATH]"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_loop import body_problems  # noqa: E402

RUNTIME_PREFIX: Final[str] = "plugins/dts2-runtime/"
MANIFEST: Final[str] = "plugins/dts2-runtime/.claude-plugin/plugin.json"
CHANGELOG: Final[str] = "plugins/dts2-runtime/CHANGELOG.md"
UNSHIPPED: Final[tuple[str, ...]] = (
    "plugins/dts2-runtime/tests/",
    "plugins/dts2-runtime/changelog.d/",
)
SEMVER: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
EXIT_PASS: Final[int] = 0
EXIT_FAIL: Final[int] = 1
EXIT_ERROR: Final[int] = 2


def git(*args: str) -> str:
    done: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout


def parse_version(text: str) -> tuple[int, int, int]:
    match: re.Match[str] | None = SEMVER.match(text.strip())
    if match is None:
        raise ValueError(f"not a semver version: {text!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def manifest_version(ref: str) -> str:
    data: dict[str, object] = json.loads(git("show", f"{ref}:{MANIFEST}"))
    return str(data.get("version", ""))


def changelog_text(ref: str) -> str:
    try:
        return git("show", f"{ref}:{CHANGELOG}")
    except RuntimeError:
        return ""


def has_entry(changelog: str, version: str) -> bool:
    heading: re.Pattern[str] = re.compile(
        rf"^## \[{re.escape(version)}\]", re.MULTILINE
    )
    return heading.search(changelog) is not None


def shipped_changes(paths: list[str]) -> list[str]:
    in_runtime: list[str] = [p for p in paths if p.startswith(RUNTIME_PREFIX)]
    return [p for p in in_runtime if not p.startswith(UNSHIPPED)]


def verdict_reason(bumped: bool, logged: bool, head_version: str) -> str:
    if not bumped:
        return "runtime changed without a plugin.json version bump"
    if not logged:
        return f"version bumped but {CHANGELOG} has no ## [{head_version}] entry"
    return "version bumped and changelog entry present"


def evaluate(
    changed: list[str], base_version: str, head_version: str, changelog: str
) -> dict[str, object]:
    shipped: list[str] = shipped_changes(changed)
    if not shipped:
        return {"verdict": "pass", "reason": "no shipped runtime change", "changed": 0}
    base: tuple[int, int, int] = parse_version(base_version)
    head: tuple[int, int, int] = parse_version(head_version)
    bumped: bool = head > base
    logged: bool = has_entry(changelog, head_version)
    return {
        "verdict": "pass" if bumped and logged else "fail",
        "reason": verdict_reason(bumped, logged, head_version),
        "changed": len(shipped),
        "sample": shipped[:5],
        "base_version": base_version,
        "head_version": head_version,
    }


def body_missing(path: str) -> list[str]:
    try:
        text: str = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read PR body {path}: {exc}") from exc
    return body_problems(text)


def with_body(result: dict[str, object], missing: list[str]) -> dict[str, object]:
    if not missing:
        return result
    reason: str = "PR body fails the Loop gate: " + "; ".join(missing)
    if result["verdict"] == "fail":
        reason = f"{result['reason']}; {reason}"
    return {**result, "verdict": "fail", "reason": reason, "pr_body_missing": missing}


def main(argv: list[str] | None = None) -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--base", required=True, help="base ref, for example origin/main"
    )
    parser.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    parser.add_argument(
        "--pr-body", default=None, help="file holding the PR body; must carry the Loop gate block"
    )
    args: argparse.Namespace = parser.parse_args(argv)
    try:
        changed: list[str] = git(
            "diff", "--name-only", f"{args.base}...{args.head}"
        ).split()
        result: dict[str, object] = evaluate(
            changed,
            manifest_version(args.base),
            manifest_version(args.head),
            changelog_text(args.head),
        )
        if args.pr_body is not None:
            result = with_body(result, body_missing(args.pr_body))
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "error", "reason": str(exc)}))
        return EXIT_ERROR
    print(json.dumps(result))
    return EXIT_PASS if result["verdict"] == "pass" else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
