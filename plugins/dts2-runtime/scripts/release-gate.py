#!/usr/bin/env python3
"""Release gate: a runtime change that reaches main must carry a version bump.

Claude Code updates an installed plugin only when its version changes, so a change under plugins/dts2-runtime/ that
lands on main without a plugin.json bump never reaches anyone. This script compares the base ref with HEAD: when any
shipped file under the runtime folder changed (tests/ and changelog.d/ are not shipped behavior), the plugin.json
version at HEAD must be greater than the one at the base. Exit 0 when the gate passes or does not apply, 1 when it
fails, 2 on a usage or git error. JSON on stdout. Read-only: it never writes, fetches, or changes a ref.

Usage: release-gate.py --base origin/main [--head HEAD]"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Final

RUNTIME_PREFIX: Final[str] = "plugins/dts2-runtime/"
MANIFEST: Final[str] = "plugins/dts2-runtime/.claude-plugin/plugin.json"
UNSHIPPED: Final[tuple[str, ...]] = ("plugins/dts2-runtime/tests/", "plugins/dts2-runtime/changelog.d/")
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


def shipped_changes(paths: list[str]) -> list[str]:
    in_runtime: list[str] = [p for p in paths if p.startswith(RUNTIME_PREFIX)]
    return [p for p in in_runtime if not p.startswith(UNSHIPPED)]


def evaluate(changed: list[str], base_version: str, head_version: str) -> dict[str, object]:
    shipped: list[str] = shipped_changes(changed)
    if not shipped:
        return {"verdict": "pass", "reason": "no shipped runtime change", "changed": 0}
    base: tuple[int, int, int] = parse_version(base_version)
    head: tuple[int, int, int] = parse_version(head_version)
    bumped: bool = head > base
    return {
        "verdict": "pass" if bumped else "fail",
        "reason": "version bumped" if bumped else "runtime changed without a plugin.json version bump",
        "changed": len(shipped),
        "sample": shipped[:5],
        "base_version": base_version,
        "head_version": head_version,
    }


def main(argv: list[str] | None = None) -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="base ref, for example origin/main")
    parser.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    args: argparse.Namespace = parser.parse_args(argv)
    try:
        changed: list[str] = git("diff", "--name-only", f"{args.base}...{args.head}").split()
        result: dict[str, object] = evaluate(changed, manifest_version(args.base), manifest_version(args.head))
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "error", "reason": str(exc)}))
        return EXIT_ERROR
    print(json.dumps(result))
    return EXIT_PASS if result["verdict"] == "pass" else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
