#!/usr/bin/env python3
"""Headless dts2 harness run on the Claude Agent SDK.

Phases: plan (lead) -> approval gate -> build (builder) -> review + verify in parallel.
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
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
AGENTS_DIR: Final[Path] = PLUGIN_ROOT / "agents"
KEY_ENV: Final[str] = "ANTHROPIC_API_KEY"
KEY_COMMAND_ENV: Final[str] = "DTS2_KEY_COMMAND"
KEY_COMMAND_TIMEOUT_S: Final[int] = 20
SECOND_OPINION_TIMEOUT_S: Final[int] = 600
FRONTMATTER: Final[re.Pattern[str]] = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
SECOND_OPINION_COMMANDS: Final[dict[str, list[str]]] = {
    "codex": ["codex", "exec"],
    "gemini": ["gemini", "-p"],
}


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


async def pipeline(args: argparse.Namespace, repo: Path, run_dir: Path) -> int:
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
    print(f"\n{verify}\n\nRun saved to {run_dir}. Nothing was committed or pushed.")
    return 0 if "VERIFIED" in verify and "BLOCK" not in review else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--yes", action="store_true", help="Skip the plan approval prompt")
    parser.add_argument("--api-key-env", help="Name of an env var holding the key")
    parser.add_argument("--second-opinion", choices=["none", "codex", "gemini"], default="none")
    args = parser.parse_args()
    repo: Path = args.repo.resolve()
    print(f"Auth: {resolve_auth(args.api_key_env)}")
    run_dir: Path = repo / ".harness" / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}"
    return asyncio.run(pipeline(args, repo, run_dir))


if __name__ == "__main__":
    sys.exit(main())
