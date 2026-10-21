#!/usr/bin/env python3
"""Headless dts2 harness run on the Claude Agent SDK.

Phases: plan -> plan checkpoint -> build -> walkthrough -> review -> ship checkpoint (receipt).
The lead plans, the builder builds, the reviewer and verifier (which runs the walkthrough) run
in parallel, then receipt.md is written. The runner never pushes; it commits only with --ship
when DTS2_SHIP_BRANCH names the current branch and the verdict is VERIFIED. A roster agent in
handoff mode needs a person, so the run stops (exit 2) unless --live-only is given.
Outputs land in <repo>/.harness/runs/<stamp>/. Reviewer lesson candidates go to
<repo>/.harness/lessons-inbox.md for the learn skill to consolidate.

Auth order (first match wins, keys are never printed):
  1. --api-key-env NAME   read the key from that environment variable
  2. ANTHROPIC_API_KEY    already exported
  3. DTS2_KEY_COMMAND     a command you trust that prints a key to stdout
                          (for example your Anthropic CLI's key command)
  4. existing Claude login the SDK finds through the installed Claude Code CLI
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
AGENTS_DIR: Final[Path] = PLUGIN_ROOT / "agents"
KEY_ENV: Final[str] = "ANTHROPIC_API_KEY"
KEY_COMMAND_ENV: Final[str] = "DTS2_KEY_COMMAND"
KEY_COMMAND_TIMEOUT_S: Final[int] = 20
SECOND_OPINION_TIMEOUT_S: Final[int] = 600
FRONTMATTER: Final[re.Pattern[str]] = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
SHIP_BRANCH_ENV: Final[str] = "DTS2_SHIP_BRANCH"
DEFAULT_CONFIG: Final[str] = ".harness/config.yaml"
RECEIPT_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "receipt.md"
PROFILES_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
HANDOFF_MODE: Final[str] = "handoff"
EXIT_NEEDS_PERSON: Final[int] = 2
STATUS_ROW: Final[re.Pattern[str]] = re.compile(r"^\|[^|\n]*\|\s*(PASS|FAIL|SKIP)\s*\|", re.M)
SECOND_OPINION_COMMANDS: Final[dict[str, list[str]]] = {
    "codex": ["codex", "exec"],
    "gemini": ["gemini", "-p"],
}


def count_statuses(verify: str) -> tuple[int, int, int]:
    found: list[str] = STATUS_ROW.findall(verify)
    return found.count("PASS"), found.count("FAIL"), found.count("SKIP")


def replace_section(text: str, title: str, body: str) -> str:
    pattern = re.compile(rf"(### {re.escape(title)}\n\n).*?(?=\n### |\Z)", re.S)
    return pattern.sub(lambda m: m.group(1) + body + "\n", text, count=1)


def build_receipt(verify: str, review: str, approver: str, rollback: str) -> str:
    passed, failed, skipped = count_statuses(verify)
    verdict: str = "changes requested" if "BLOCK" in review else "approved"
    bodies: dict[str, str] = {
        "Tests run": ("| Command | Pass | Fail | Skip |\n|---|---|---|---|\n"
                      f"| verifier checks | {passed} | {failed} | {skipped} |\n"),
        "Review verdict": f"{verdict} (reviewer, {datetime.now():%Y-%m-%d})\n",
        "Approved by": f"{approver}, {datetime.now():%Y-%m-%d}\n",
        "Rollback point": f"{rollback}\n",
    }
    text: str = RECEIPT_TEMPLATE.read_text(encoding="utf-8")
    for title, body in bodies.items():
        text = replace_section(text, title, body.rstrip("\n"))
    return text


def ship_allowed(args: argparse.Namespace, branch: str) -> bool:
    return bool(args.ship) and os.environ.get(SHIP_BRANCH_ENV) == branch


def parse_roster_config(text: str) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    in_block: bool = False
    for raw in text.splitlines():
        line: str = raw.strip()
        if line and not raw.startswith((" ", "\t")):
            in_block = line == "roster:"
        elif in_block and line.startswith("- name:"):
            entries.append({"name": line[len("- name:"):].strip()})
        elif in_block and line.startswith("mode:") and entries:
            entries[-1]["mode"] = line[len("mode:"):].strip()
    return {"roster": entries}


def profile_invocation(name: str) -> str:
    path: Path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        return ""
    return str(json.loads(path.read_text(encoding="utf-8")).get("invocation", ""))


def handoff_lanes(roster: dict[str, Any]) -> list[str]:
    entries: list[dict[str, str]] = roster.get("roster", [])
    return [e["name"] for e in entries
            if e.get("mode", profile_invocation(e["name"])) == HANDOFF_MODE]


def read_roster_config(repo: Path, config: Path) -> dict[str, Any]:
    path: Path = config if config.is_absolute() else repo / config
    if not path.exists():
        return {"roster": []}
    return parse_roster_config(path.read_text(encoding="utf-8"))


def git_out(repo: Path, *cmd: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *cmd], capture_output=True, text=True).stdout.strip()


def commit_changes(repo: Path, task: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", f"feat: {task[:60]}"], check=True)


def resolve_auth(api_key_env: str | None) -> str:
    if api_key_env and os.environ.get(api_key_env):
        os.environ[KEY_ENV] = os.environ[api_key_env]
        return f"API key from ${api_key_env}"
    if os.environ.get(KEY_ENV):
        return f"API key from ${KEY_ENV}"
    command: str | None = os.environ.get(KEY_COMMAND_ENV)
    if command:
        return key_from_command(command)
    return "existing Claude Code login (no API key set)"


def key_from_command(command: str) -> str:
    result = subprocess.run(shlex.split(command), capture_output=True, text=True,
                            timeout=KEY_COMMAND_TIMEOUT_S)
    key: str = result.stdout.strip()
    if result.returncode != 0 or not key:
        raise SystemExit(f"{KEY_COMMAND_ENV} failed (exit {result.returncode}). No key was set.")
    os.environ[KEY_ENV] = key
    return f"API key from {KEY_COMMAND_ENV}"


def load_agent(name: str) -> dict[str, object]:
    match = FRONTMATTER.match((AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"Agent file {name}.md has no frontmatter.")
    meta: dict[str, str] = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    tools: list[str] = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    return {"prompt": match.group(2), "tools": tools, "model": meta.get("model", "").strip() or None}


async def run_agent(name: str, task: str, repo: Path, write: bool) -> str:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    agent: dict[str, object] = load_agent(name)
    options = ClaudeAgentOptions(system_prompt=str(agent["prompt"]), allowed_tools=list(agent["tools"]),
                                 cwd=str(repo), model=agent["model"],
                                 permission_mode="acceptEdits" if write else "default")
    parts: list[str] = []
    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            parts += [block.text for block in message.content if isinstance(block, TextBlock)]
    return "\n".join(parts)


def second_opinion(backend: str, diff: str, repo: Path) -> str:
    command: list[str] | None = SECOND_OPINION_COMMANDS.get(backend)
    if command is None or shutil.which(command[0]) is None:
        return f"(second opinion skipped: {backend} CLI not found)"
    prompt: str = f"Review this diff. List CRITICAL/HIGH/MEDIUM/LOW findings with file:line.\n\n{diff}"
    result = subprocess.run(command + [prompt], cwd=repo, capture_output=True, text=True,
                            timeout=SECOND_OPINION_TIMEOUT_S)
    return result.stdout or result.stderr


def git_diff(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "diff", "HEAD"], capture_output=True, text=True).stdout


def approve(plan: str, assume_yes: bool) -> bool:
    print(plan)
    if assume_yes:
        return True
    return input("\nApprove this plan? [y/N] ").strip().lower() == "y"


def save(run_dir: Path, name: str, text: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{name}.md").write_text(text, encoding="utf-8")


def collect_lessons(review: str, repo: Path) -> None:
    section = re.search(r"### Lesson candidates\n(.*?)(\n### |\Z)", review, re.S)
    lines: list[str] = [l for l in (section.group(1).splitlines() if section else []) if l.strip("- ").strip()]
    lines = [l for l in lines if l.strip("- ").strip().lower() != "none"]
    if lines:
        with (repo / ".harness" / "lessons-inbox.md").open("a", encoding="utf-8") as inbox:
            inbox.write(f"\n## {datetime.now():%Y-%m-%d %H:%M}\n" + "\n".join(lines) + "\n")


async def review_and_verify(task: str, plan: str, repo: Path) -> tuple[str, str]:
    brief: str = f"Task: {task}\n\nApproved plan:\n{plan}\n\nReview the current uncommitted diff."
    return await asyncio.gather(run_agent("reviewer", brief, repo, write=False),
                                run_agent("verifier", brief, repo, write=False))


def ship_checkpoint(args: argparse.Namespace, repo: Path, run_dir: Path, review: str, verify: str,
                    rollback: str) -> int:
    approver: str = git_out(repo, "config", "user.name") or "unknown"
    save(run_dir, "receipt", build_receipt(verify, review, approver, rollback))
    receipt_path: Path = run_dir / "receipt.md"
    if handoff_lanes(read_roster_config(repo, args.config)) and not args.live_only:
        print(f"Handoff lane needs a person; receipt at {receipt_path}")
        return EXIT_NEEDS_PERSON
    verified: bool = "VERIFIED" in verify and "BLOCK" not in review
    branch: str = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if verified and ship_allowed(args, branch):
        commit_changes(repo, args.task)
        print(f"Committed on {branch}. Nothing was pushed. Receipt: {receipt_path}")
        return 0
    print(f"Nothing was committed or pushed. Receipt: {receipt_path}")
    return 0 if verified else EXIT_NEEDS_PERSON


async def pipeline(args: argparse.Namespace, repo: Path, run_dir: Path) -> int:
    rollback: str = git_out(repo, "rev-parse", "HEAD")
    plan: str = await run_agent("lead", args.task, repo, write=False)
    save(run_dir, "1-plan", plan)
    if not approve(plan, args.yes):
        print("Plan not approved. Stopping before any edits.")
        return 1
    build: str = await run_agent("builder", f"Implement this plan.\n\n{plan}", repo, write=True)
    save(run_dir, "2-build", build)
    review, verify = await review_and_verify(args.task, plan, repo)
    save(run_dir, "3-review", review)
    save(run_dir, "4-verify", verify)
    if args.second_opinion != "none":
        save(run_dir, f"5-{args.second_opinion}", second_opinion(args.second_opinion, git_diff(repo), repo))
    collect_lessons(review, repo)
    print(f"\n{verify}\n\nRun saved to {run_dir}.")
    return ship_checkpoint(args, repo, run_dir, review, verify, rollback)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--yes", action="store_true", help="Skip the plan approval prompt")
    parser.add_argument("--api-key-env", help="Name of an env var holding the key")
    parser.add_argument("--second-opinion", choices=["none", "codex", "gemini"], default="none")
    parser.add_argument("--ship", action="store_true",
                        help=f"Commit when verified and ${SHIP_BRANCH_ENV} names the current branch")
    parser.add_argument("--live-only", action="store_true", help="Ignore handoff-mode roster agents")
    parser.add_argument("--config", type=Path, default=Path(DEFAULT_CONFIG))
    args = parser.parse_args()
    repo: Path = args.repo.resolve()
    print(f"Auth: {resolve_auth(args.api_key_env)}")
    run_dir: Path = repo / ".harness" / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}"
    return asyncio.run(pipeline(args, repo, run_dir))


if __name__ == "__main__":
    sys.exit(main())
