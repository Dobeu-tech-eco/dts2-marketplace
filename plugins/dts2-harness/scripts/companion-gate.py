#!/usr/bin/env python3
"""Run-count gates for two costly companion skills.

  check  --repo DIR --skill NAME [--base REF]   print {"skill", "run", "reason", ...} as JSON
  record --repo DIR --skill NAME                remember that NAME ran once for this repo

setup-pre-commit runs once per repo: `check` says run until `record` has stored it.
improve-codebase-architecture runs only when the work changes more than 150 lines against --base
(default: the repo's default branch, else `main`). The count covers uncommitted and untracked work
against the merge base, since the pass runs before the builder commits. A diff that cannot be
measured runs the pass, since a skipped review costs more than an extra one.
State lives in .harness/companions-ran.json, written with state_io.atomic_write.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

ONCE_PER_REPO: Final[str] = "setup-pre-commit"
BY_DIFF_SIZE: Final[str] = "improve-codebase-architecture"
MIN_CHANGED_LINES: Final[int] = 150  # the pass runs when the diff is over this many lines
STATE_FILE: Final[str] = "companions-ran.json"
SAFE_REF: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][\w./-]{0,99}", re.ASCII)
TIMEOUT_S: Final[int] = 30
FALLBACK_BASE: Final[str] = "main"
MAX_UNTRACKED_BYTES: Final[int] = 2_000_000


def git_cmd() -> list[str]:
    value: str = os.environ.get("DTS2_GIT_BIN", "git")
    return [sys.executable, value] if value.endswith(".py") else [value]


def state_path(repo: Path) -> Path:
    return repo / ".harness" / STATE_FILE


def read_state(repo: Path) -> dict[str, str]:
    try:
        data: Any = json.loads(state_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}


def run_git(repo: Path, *args: str) -> str | None:
    """Stdout of one git call in `repo`; None on failure, timeout or a missing binary."""
    try:
        done = subprocess.run([*git_cmd(), *args], cwd=str(repo), capture_output=True, text=True,
                              timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch(repo: Path) -> str:
    """The repo's default branch from origin/HEAD, or `main` when git cannot say."""
    out: str | None = run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    name: str = out.strip().removeprefix("refs/remotes/origin/") if out else ""
    return name if SAFE_REF.fullmatch(name) else FALLBACK_BASE


def untracked_lines(repo: Path) -> int | None:
    """Line count of untracked, non-ignored text files; binary, oversized and symlinked files count zero."""
    out: str | None = run_git(repo, "ls-files", "-z", "--others", "--exclude-standard")
    if out is None:
        return None
    total: int = 0
    for rel in filter(None, out.split("\0")):
        path: Path = repo / rel
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_UNTRACKED_BYTES:
                continue
            data: bytes = path.read_bytes()
        except OSError:
            continue
        if b"\0" not in data[:8192]:
            total += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return total


def numstat_total(text: str) -> int:
    total: int = 0
    for line in text.splitlines():
        added, _, rest = line.partition("\t")
        deleted = rest.partition("\t")[0]
        total += (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
    return total


def changed_lines(repo: Path, base: str) -> int | None:
    """Added plus deleted lines of the working tree against the merge base of `base` and HEAD, plus the
    lines of untracked files, so a builder's uncommitted work counts. Binary files count zero. None when
    git cannot say."""
    if not SAFE_REF.fullmatch(base):
        return None
    mb: str | None = run_git(repo, "merge-base", base, "HEAD")
    merge_base: str = mb.strip() if mb else ""
    if not SAFE_REF.fullmatch(merge_base):
        return None
    stat: str | None = run_git(repo, "diff", "--numstat", merge_base)
    extra: int | None = untracked_lines(repo)
    return None if stat is None or extra is None else numstat_total(stat) + extra


def check(repo: Path, skill: str, base: str | None = None) -> dict[str, Any]:
    if skill == ONCE_PER_REPO:
        ran: str | None = read_state(repo).get(skill)
        return {"skill": skill, "run": ran is None, "reason": "first-run" if ran is None else "already-ran", "ran_on": ran}
    if skill == BY_DIFF_SIZE:
        base = base or default_branch(repo)
        lines: int | None = changed_lines(repo, base)
        if lines is None:
            return {"skill": skill, "run": True, "reason": "diff-unmeasurable", "changed_lines": None, "base": base}
        return {"skill": skill, "run": lines > MIN_CHANGED_LINES,
                "reason": "diff-over-threshold" if lines > MIN_CHANGED_LINES else "diff-small",
                "changed_lines": lines, "threshold": MIN_CHANGED_LINES, "base": base}
    return {"skill": skill, "run": True, "reason": "ungated"}


def record(repo: Path, skill: str) -> dict[str, Any]:
    if skill != ONCE_PER_REPO:
        return {"skill": skill, "recorded": False, "reason": "only setup-pre-commit is recorded"}
    state: dict[str, str] = read_state(repo)
    state.setdefault(skill, date.today().isoformat())
    atomic_write(state_path(repo), json.dumps(state, indent=2, sort_keys=True) + "\n")
    return {"skill": skill, "recorded": True, "ran_on": state[skill]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".")
        p.add_argument("--skill", required=True)
    sub.choices["check"].add_argument("--base", default=None, help="default: the repo's default branch, else main")
    args = parser.parse_args()
    repo: Path = Path(args.repo).resolve()
    print(json.dumps(check(repo, args.skill, args.base) if args.cmd == "check" else record(repo, args.skill)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
