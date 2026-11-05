#!/usr/bin/env python3
"""Audit one builder's result against its owned files (thin CLI over ownership_audit.audit). Read-only.

Exit 0 when clean, 1 on a violation. Prints JSON with `ok`, `violations`, `changed` and `action`
(accept | redispatch | blocked, from --attempt: how many re-dispatches already happened)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ownership_audit import audit, next_action  # noqa: E402


def git(repo: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True, help="commit the builder started from")
    parser.add_argument("--owned", required=True, help="comma-separated files, dir/ prefixes or globs")
    parser.add_argument("--claimed-sha", default=None)
    parser.add_argument("--status", default="DONE")
    parser.add_argument("--attempt", type=int, default=0, help="re-dispatches already made")
    args = parser.parse_args()
    head: str = git(args.repo, "rev-parse", "HEAD").strip()
    changed: list[str] = git(args.repo, "diff", "--name-only", f"{args.base}..HEAD").splitlines()
    committed_only: set[str] = set(changed)
    dirty: list[str] = [line[3:] for line in git(args.repo, "status", "--porcelain").splitlines() if line]
    owned: list[str] = [o.strip() for o in args.owned.split(",") if o.strip()]
    result = audit(sorted(committed_only | set(dirty)), owned, args.claimed_sha, head=head, status=args.status)
    result["action"] = next_action(result, args.attempt)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
