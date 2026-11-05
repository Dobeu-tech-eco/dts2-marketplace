#!/usr/bin/env python3
"""The run's rollback anchor (AA-10): a real ref, `refs/dts2/<stamp>/base`, at the commit the run started from, and the one-line
Rollback command a human can run. A bare SHA in the receipt can be garbage-collected or mistyped; a ref cannot be lost that way.
Nothing here ever rolls anything back.

  create --stamp S [--repo R] [--sha SHA]    point the ref at SHA (default HEAD); idempotent for the same SHA
  line   --stamp S [--repo R]                the Rollback line for the receipt and the handoff"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_ids import Stamp  # noqa: E402

REF_FORMAT: Final[str] = "refs/dts2/{stamp}/base"
LINE_PREFIX: Final[str] = "Rollback (human-run, never run by the harness)"
SHORT_SHA: Final[int] = 12


def git(repo: str, *args: str) -> tuple[int, str]:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    return done.returncode, (done.stdout or done.stderr).strip()


def ref_name(stamp: str) -> str:
    return REF_FORMAT.format(stamp=Stamp.parse(stamp).value)


def resolve(repo: str, rev: str) -> str | None:
    code, out = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return out if code == 0 and out else None


def create_ref(repo: str, stamp: str, sha: str | None = None) -> dict[str, Any]:
    """Point the base ref at `sha` (default HEAD). An existing ref at another commit is never moved."""
    ref: str = ref_name(stamp)
    target: str | None = resolve(repo, sha or "HEAD")
    if target is None:
        return {"ok": False, "ref": ref, "error": f"cannot resolve {sha or 'HEAD'}"}
    existing: str | None = resolve(repo, ref)
    if existing and existing != target:
        return {"ok": False, "ref": ref, "sha": existing, "error": f"{ref} already points at {existing[:SHORT_SHA]}; it is not moved"}
    if existing is None:
        code, out = git(repo, "update-ref", ref, target)
        if code != 0:
            return {"ok": False, "ref": ref, "error": out}
    return {"ok": True, "ref": ref, "sha": target, "line": rollback_line(stamp, target)}


def rollback_line(stamp: str, sha: str) -> str:
    """One line: put the tree back as it was at the base, as a new commit. Safe on a branch other people have pulled."""
    ref: str = ref_name(stamp)
    return (f"{LINE_PREFIX}: git restore --source={ref} --staged --worktree -- :/ && git commit -m \"Roll back run {stamp}\" "
            f"(base {sha[:SHORT_SHA]})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "line"):
        p = sub.add_parser(name)
        p.add_argument("--stamp", required=True)
        p.add_argument("--repo", default=".")
        if name == "create":
            p.add_argument("--sha", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "create":
        result: dict[str, Any] = create_ref(args.repo, args.stamp, args.sha)
    else:
        sha: str | None = resolve(args.repo, ref_name(args.stamp))
        result = {"ok": sha is not None, "ref": ref_name(args.stamp), "sha": sha,
                  "line": rollback_line(args.stamp, sha) if sha else None}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
