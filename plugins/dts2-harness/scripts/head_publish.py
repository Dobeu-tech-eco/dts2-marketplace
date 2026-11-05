#!/usr/bin/env python3
"""The head publishes, a son only commits (G-64, G-65, G-66; rulings Q1, Q12).

A son hands over a committed branch. This module is what the head runs afterwards:

  publish    check the lane diff for protected files, push the lane branch, open (or adopt) one PR for the lane
  merge      merge the PR once the verifier passed and the unattended-merge preconditions hold
  bootstrap  install dependencies for a lane once and write the lane's sanitized env file

Intended wiring (the lead adds it to lanes.py): `lanes.py publish <stamp> --lane <lane> ...` calls `publish_lane`,
`lanes.py publish --merge` calls `merge_pr`, and `lanes.py spawn` calls `bootstrap_lane` before it starts a son.

Merge preconditions (G-65): zero reported checks counts as red; a merge into the default branch needs required checks and a
review, or a merge queue; a merge that deploys production needs the person's yes for that PR (`approvals.py`, kind `merge`);
after such a merge the walkthrough is read-only (`DTS2_WALKTHROUGH_READONLY=1`)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import state_io  # noqa: E402
from approvals import is_human_approved  # noqa: E402
from model_call import read_block  # noqa: E402
from proc import binary  # noqa: E402
from protected import diff_touches_protected, park_decision  # noqa: E402
from son_launch import allowed_env  # noqa: E402

TIMEOUT_S: Final[int] = 120
INSTALL_TIMEOUT_S: Final[int] = 900
EXIT_START_FAILED: Final[int] = 127
GOOD_CONCLUSIONS: Final[frozenset[str]] = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
PENDING_STATES: Final[frozenset[str]] = frozenset({"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "EXPECTED", ""})
WALKTHROUGH_READONLY_VAR: Final[str] = "DTS2_WALKTHROUGH_READONLY"
SON_MARKER_VAR: Final[str] = "DTS2_SON"  # set in every son's env (son_launch.SON_MARKER)
MERGE_BLOCK: Final[str] = "merge"
DEFAULT_BRANCH_KEY: Final[str] = "default_branch"
FALLBACK_BRANCH: Final[str] = "main"
STATE_OPEN: Final[str] = "OPEN"
DEPLOYS_KEY: Final[str] = "deploys_production"
SECRET_NAME: Final[re.Pattern[str]] = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASS|CREDENTIAL|PRIVATE|CERT|DSN|AUTH|SALT|SIGNING|WEBHOOK|CONN|DATABASE_URL)", re.I)
ENV_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
EXAMPLE_NAMES: Final[tuple[str, ...]] = (".env.example", ".env.sample", ".env.template")
SON_ENV_NAME: Final[str] = "son.env"
BOOTSTRAP_MARK: Final[str] = "bootstrap.done"
SECRETS_GROUP: Final[str] = "Secrets"
INSTALLERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("pnpm-lock.yaml", ("pnpm", "install", "--frozen-lockfile")),
    ("yarn.lock", ("yarn", "install", "--frozen-lockfile")),
    ("package-lock.json", ("npm", "ci")),
    ("uv.lock", ("uv", "sync", "--frozen")),
    ("requirements.txt", ("python3", "-m", "pip", "install", "-r", "requirements.txt")),
)
LOCKFILES: Final[tuple[str, ...]] = tuple(name for name, _ in INSTALLERS)

Runner = Callable[[list[str], Path], tuple[int, str]]


def run_tool(argv: list[str], cwd: Path) -> tuple[int, str]:
    """(exit code, stdout) of one head-side command; a start failure is 127 and a timeout 124, never an exception."""
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return EXIT_START_FAILED, str(exc)
    return done.returncode, done.stdout


def git(repo: Path, *args: str, runner: Runner = run_tool) -> tuple[int, str]:
    return runner([*binary("DTS2_GIT_BIN", "git"), *args], repo)


def gh(repo: Path, *args: str, runner: Runner = run_tool) -> tuple[int, str]:
    return runner([*binary("DTS2_GH_BIN", "gh"), *args], repo)


def json_of(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def diff_names(repo: Path, base: str, branch: str, runner: Runner = run_tool) -> list[str] | None:
    """File names the lane branch changes against its base; None when git cannot say (the caller parks, never pushes blind)."""
    code, out = git(repo, "diff", "--name-only", "--no-renames", f"{base}...{branch}", runner=runner)
    return [line for line in out.splitlines() if line.strip()] if code == 0 else None


def lane_pr(repo: Path, branch: str, runner: Runner = run_tool) -> dict[str, Any] | None:
    """The PR still open for this lane branch, so a retried publish never opens a second one. A closed or merged PR is not adopted."""
    code, out = gh(repo, "pr", "list", "--head", branch, "--state", "open", "--json", "number,state", runner=runner)
    rows: Any = json_of(out) if code == 0 else None
    open_rows: list[dict[str, Any]] = [r for r in rows if isinstance(r, dict) and str(r.get("state", STATE_OPEN)).upper() == STATE_OPEN] \
        if isinstance(rows, list) else []
    return open_rows[0] if open_rows else None


def son_refusal(action: str) -> dict[str, Any]:
    """Only the head publishes or merges: inside a son's process the answer is a refusal, whatever the allowlist says."""
    return {"ok": False, "merged": False, "reason": f"{action} is the head's step; a son only commits a branch",
            "blockers": [f"{action} refused inside a son"]}


def inside_son() -> bool:
    return bool(os.environ.get(SON_MARKER_VAR))


def publish_lane(repo: Path, lane: str, branch: str, base: str, title: str, body: str, runner: Runner = run_tool) -> dict[str, Any]:
    """Protected-file check, push, one PR per lane. A protected path parks the lane as a Decisions item and pushes nothing."""
    if inside_son():
        return son_refusal("publishing")
    names: list[str] | None = diff_names(repo, base, branch, runner)
    if names is None:
        return {"ok": False, "reason": f"cannot read the diff {base}...{branch}; nothing was pushed"}
    touched: list[str] = diff_touches_protected(names, repo)
    if touched:
        return {"ok": False, "reason": "protected files changed", **park_decision(repo, lane, touched)}
    code, out = git(repo, "push", "origin", f"{branch}:{branch}", runner=runner)
    if code != 0:
        return {"ok": False, "reason": f"git push failed: {out.strip()[:200]}"}
    held: dict[str, Any] | None = lane_pr(repo, branch, runner)
    if held is not None:
        return {"ok": True, "pr": held["number"], "state": held.get("state"), "adopted": True}
    code, out = gh(repo, "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body, runner=runner)
    return {"ok": code == 0, "pr": out.strip().rsplit("/", 1)[-1] if code == 0 else None, "adopted": False,
            **({} if code == 0 else {"reason": f"gh pr create failed: {out.strip()[:200]}"})}


def check_state(item: dict[str, Any]) -> str:
    """good, pending or bad for one entry of `statusCheckRollup` (a check run has `conclusion`, a status has `state`)."""
    value: str = str(item.get("conclusion") or item.get("state") or "").upper()
    if value in GOOD_CONCLUSIONS:
        return "good"
    return "pending" if value in PENDING_STATES else "bad"


def check_blockers(checks: list[dict[str, Any]]) -> list[str]:
    """Zero reported checks is red, not green (G-65)."""
    if not checks:
        return ["no checks reported on the PR; zero checks counts as red"]
    states: list[str] = [check_state(c) for c in checks]
    problems: list[str] = []
    if "bad" in states:
        problems.append(f"{states.count('bad')} check(s) failed")
    if "pending" in states:
        problems.append(f"{states.count('pending')} check(s) still running")
    return problems


def merge_blockers(facts: dict[str, Any], default_branch: str, deploys_production: bool, pr: str,
                   repo: Path | None = None) -> list[str]:
    """Every reason the head must not merge this PR unattended; an empty list means the preconditions hold."""
    problems: list[str] = check_blockers(list(facts.get("checks") or []))
    if facts.get("base") == default_branch:
        protected: bool = bool(facts.get("required_checks")) and facts.get("review") == "APPROVED"
        if not (protected or facts.get("merge_queue")):
            problems.append(f"{default_branch} needs required checks and a review, or a merge queue, before an unattended merge")
    if deploys_production and not is_human_approved("merge", pr, repo):
        problems.append(f"merging PR {pr} deploys production; add \"{pr}\" under dts2_approvals.merge in .claude/settings.local.json")
    return problems


def pr_facts(repo: Path, pr: str, runner: Runner = run_tool) -> dict[str, Any]:
    """What the merge check needs, read once through gh: base, check results, review state, protection and merge queue."""
    code, out = gh(repo, "pr", "view", pr, "--json", "baseRefName,headRefOid,reviewDecision,statusCheckRollup", runner=runner)
    view: Any = json_of(out) if code == 0 else None
    view = view if isinstance(view, dict) else {}
    base: str = str(view.get("baseRefName") or "")
    prot_code, prot = gh(repo, "api", f"repos/{{owner}}/{{repo}}/branches/{base}/protection", runner=runner)
    protection: Any = json_of(prot) if prot_code == 0 else None
    rules_code, rules = gh(repo, "api", f"repos/{{owner}}/{{repo}}/rules/branches/{base}", runner=runner)
    listed: Any = json_of(rules) if rules_code == 0 else None
    contexts: Any = (protection or {}).get("required_status_checks") if isinstance(protection, dict) else None
    return {
        "base": base, "head": view.get("headRefOid"), "checks": [c for c in view.get("statusCheckRollup") or [] if isinstance(c, dict)],
        "review": view.get("reviewDecision"), "required_checks": bool(contexts),
        "merge_queue": isinstance(listed, list) and any(isinstance(r, dict) and r.get("type") == "merge_queue" for r in listed),
        "readable": code == 0,
    }


def deploys_production(repo: Path) -> bool:
    """`merge: deploys_production: true` in .harness/config.yaml says a merge to the default branch ships to production."""
    return read_block(repo, MERGE_BLOCK).get(DEPLOYS_KEY, "false").lower() == "true"


def default_branch_of(repo: Path) -> str:
    """`merge: default_branch:` from .harness/config.yaml, as deploys_production reads it; "main" when unset."""
    return read_block(repo, MERGE_BLOCK).get(DEFAULT_BRANCH_KEY) or FALLBACK_BRANCH


def merge_pr(repo: Path, pr: str, verifier_ok: bool, default_branch: str | None = None, production: bool | None = None,
             runner: Runner = run_tool) -> dict[str, Any]:
    """Merge after the verifier passed and every precondition holds. Anything else returns the reasons and merges nothing."""
    if inside_son():
        return son_refusal("merging")
    if not verifier_ok:
        return {"ok": False, "merged": False, "blockers": ["the verifier has not passed on this head"]}
    default_branch = default_branch or default_branch_of(repo)
    facts: dict[str, Any] = pr_facts(repo, pr, runner)
    if not facts["readable"]:
        return {"ok": False, "merged": False, "blockers": [f"cannot read PR {pr}; failing closed"]}
    prod: bool = deploys_production(repo) if production is None else production
    blockers: list[str] = merge_blockers(facts, default_branch, prod, pr, repo)
    if blockers:
        return {"ok": False, "merged": False, "blockers": blockers}
    args: list[str] = ["pr", "merge", pr, "--squash", *(["--match-head-commit", str(facts["head"])] if facts["head"] else [])]
    code, out = gh(repo, *args, runner=runner)
    return {"ok": code == 0, "merged": code == 0, "blockers": [] if code == 0 else [out.strip()[:200]],
            "walkthrough_read_only": prod, "walkthrough_env": walkthrough_env(prod)}


def walkthrough_env(production: bool) -> dict[str, str]:
    """Environment for the post-merge walkthrough: read-only against production (no form submits, no writes)."""
    return {WALKTHROUGH_READONLY_VAR: "1"} if production else {}


def install_command(worktree: Path) -> list[str] | None:
    """The one install command for the first lockfile found, or None (nothing to install)."""
    for name, argv in INSTALLERS:
        if (worktree / name).is_file():
            return list(argv)
    return None


def lockfile_stamp(worktree: Path) -> str:
    """Names and content hashes of the lockfiles; the install step is skipped while this is unchanged (a same-size edit counts)."""
    return ";".join(f"{n}:{hashlib.sha256((worktree / n).read_bytes()).hexdigest()}" for n in LOCKFILES if (worktree / n).is_file())


def env_example(worktree: Path) -> str:
    for name in EXAMPLE_NAMES:
        path: Path = worktree / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def split_env(example: str) -> tuple[dict[str, str], list[str]]:
    """(non-secret defaults, secret names) from an env example. A secret's value is never kept, not even a placeholder."""
    plain: dict[str, str] = {}
    secrets: list[str] = []
    for line in example.splitlines():
        match = ENV_LINE.match(line)
        if match is None or line.lstrip().startswith("#"):
            continue
        name, value = match.group(1), match.group(2).strip("\"'")
        if SECRET_NAME.search(name):
            secrets.append(name)
        else:
            plain[name] = value
    return plain, secrets


def son_env_text(plain: dict[str, str], host: dict[str, str]) -> str:
    """Env file lines: the example's defaults, with the host's value for any non-secret name it sets."""
    merged: dict[str, str] = {k: host.get(k, v) for k, v in plain.items()}
    return "".join(f"{k}={v}\n" for k, v in sorted(merged.items()))


def ledger_missing_secrets(repo: Path, lane: str, names: list[str], today: date | None = None) -> list[str]:
    """One Secrets row per name not already listed; values are never written. Returns the names added."""
    items = _load.load("action-items")
    path: Path = Path(repo) / items.ITEMS_PATH
    lines: list[str] = items.read_lines(path)
    added: list[str] = []
    for name in names:
        if any(name in line for line in lines):
            continue
        items.add_row(lines, SECRETS_GROUP, f"{name} (lane {lane} needs it; the son never receives it)", today or date.today())
        added.append(name)
    if added:
        items.write_lines(path, lines)
    return added


def bootstrap_lane(repo: Path, worktree: Path, stamp: str, lane: str, host: dict[str, str] | None = None,
                   installer: Callable[[list[str], Path, dict[str, str]], int] | None = None) -> dict[str, Any]:
    """Idempotent per-lane bootstrap run by the head: install once per lockfile state, write the sanitized env file,
    ledger the secrets the lane lacks. Never writes into the lane's branch."""
    lane_dir: Path = Path(repo) / state_io.lane_rel(stamp, lane)
    lane_dir.mkdir(parents=True, exist_ok=True)
    source: dict[str, str] = dict(os.environ) if host is None else host
    plain, secrets = split_env(env_example(worktree))
    env_path: Path = lane_dir / SON_ENV_NAME
    state_io.atomic_write(env_path, son_env_text(plain, source))
    missing: list[str] = ledger_missing_secrets(repo, lane, secrets)
    mark: Path = lane_dir / BOOTSTRAP_MARK
    stamp_now: str = lockfile_stamp(worktree)
    command: list[str] | None = install_command(worktree)
    installed: bool = False
    if command is not None and (not mark.is_file() or mark.read_text(encoding="utf-8") != stamp_now):
        code: int = (installer or run_install)(command, worktree, allowed_env(source))
        if code != 0:
            return {"ok": False, "reason": f"{' '.join(command)} failed (exit {code})", "env_file": str(env_path), "missing_secrets": missing}
        state_io.atomic_write(mark, stamp_now)
        installed = True
    return {"ok": True, "installed": installed, "env_file": str(env_path), "secrets_ledgered": missing,
            "env_keys": sorted(plain)}


def run_install(command: list[str], worktree: Path, env: dict[str, str]) -> int:
    try:
        return subprocess.run(command, cwd=worktree, env=env, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S,
                              stdin=subprocess.DEVNULL, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return EXIT_START_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pub = sub.add_parser("publish")
    for flag in ("--lane", "--branch", "--base", "--title"):
        pub.add_argument(flag, required=True)
    pub.add_argument("--body", default="")
    mrg = sub.add_parser("merge")
    mrg.add_argument("pr")
    mrg.add_argument("--verifier-ok", action="store_true", help="the verifier passed on the PR head")
    mrg.add_argument("--default-branch", default=None, help="overrides merge.default_branch from the config")
    mrg.add_argument("--deploys-production", action="store_true", default=None)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--stamp", required=True)
    boot.add_argument("--lane", required=True)
    boot.add_argument("--worktree", required=True)
    args = parser.parse_args(argv)
    repo: Path = Path(args.repo)
    if args.cmd == "publish":
        result = publish_lane(repo, args.lane, args.branch, args.base, args.title, args.body)
    elif args.cmd == "merge":
        result = merge_pr(repo, args.pr, args.verifier_ok, args.default_branch, args.deploys_production)
    else:
        result = bootstrap_lane(repo, Path(args.worktree), args.stamp, args.lane)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
