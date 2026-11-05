#!/usr/bin/env python3
"""Spawn dry run as a PreToolUse hook: print the composed brief and the exact command, start nothing.

  Bash   `lanes.py spawn <manifest> --lane L --worktree W --dry-run`   the command is denied (it would not run anyway: the
         CLI has no such flag) and the reason carries the exact son command, env names, prefix and prompt byte counts
         (briefs.dry_run, the 7B work) plus the son brief text that `briefs.py son-brief` would write.
  Agent  with `--agent-dry-run` (setting `spawn_dry_run: true`): the dispatch is denied and the reason carries the prompt.

Reads the hook JSON on stdin, prints PreToolUse JSON only when it intercepts, always exits 0."""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefs  # noqa: E402
import state_io  # noqa: E402

DRY_FLAG: Final[str] = "--dry-run"
SPAWN_WORDS: Final[tuple[str, str]] = ("lanes.py", "spawn")
VALUE_FLAGS: Final[frozenset[str]] = frozenset({"--lane", "--worktree"})
FIRST_EPOCH: Final[int] = 1
PROMPT_PREVIEW_CHARS: Final[int] = 4000
HEADER: Final[str] = "dts2-harness spawn dry run: nothing was started."


def flag_value(tokens: list[str], flag: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == flag and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def first_positional(words: list[str]) -> list[str]:
    """The words that are neither flags nor the value of --lane / --worktree."""
    kept: list[str] = []
    skip: bool = False
    for word in words:
        if skip:
            skip = False
        elif word in VALUE_FLAGS:
            skip = True
        elif not word.startswith("-"):
            kept.append(word)
    return kept


def spawn_args(command: str) -> tuple[str, str, str] | None:
    """(manifest, lane, worktree) when `command` is a `lanes.py spawn ... --dry-run`, else None."""
    try:
        tokens: list[str] = shlex.split(command)
    except ValueError:
        return None
    if DRY_FLAG not in tokens:
        return None
    for index, token in enumerate(tokens[:-1]):
        if token.endswith(SPAWN_WORDS[0]) and tokens[index + 1] == SPAWN_WORDS[1]:
            rest: list[str] = tokens[index + 2:]
            positional: list[str] = first_positional(rest)
            lane, worktree = flag_value(rest, "--lane"), flag_value(rest, "--worktree")
            return (positional[0], lane, worktree) if positional and lane and worktree else None
    return None


def lease_epoch(cwd: Path, manifest: dict[str, Any], lane: str) -> int:
    try:
        return max(FIRST_EPOCH, state_io.epoch_of(state_io.State(state_io.FileStore(cwd)).lease(manifest.get("stamp"), lane)))
    except (state_io.StateError, ValueError):
        return FIRST_EPOCH


def bash_report(command: str, cwd: Path) -> str | None:
    parsed: tuple[str, str, str] | None = spawn_args(command)
    if parsed is None:
        return None
    manifest_path, lane, worktree = parsed
    try:
        manifest: dict[str, Any] = briefs.load_json(cwd / manifest_path)
        plan: dict[str, Any] = briefs.dry_run(manifest, lane, cwd / worktree, cwd)
        brief: str = briefs.son_brief(manifest, lane, lease_epoch(cwd, manifest, lane))
    except briefs.BriefError as exc:
        return f"{HEADER} It could not be composed: {exc}"
    summary: dict[str, Any] = {k: plan[k] for k in ("lane", "cwd", "command", "env_allowlist", "prompt", "prompt_bytes", "prefix_bytes", "prefix_sha256")}
    return f"{HEADER}\n{json.dumps(summary, indent=2)}\n\n--- brief.md ---\n{brief}"


def agent_report(tool_input: dict[str, Any]) -> str:
    prompt: str = str(tool_input.get("prompt") or "")
    shown: str = prompt[:PROMPT_PREVIEW_CHARS] + ("\n[cut]" if len(prompt) > PROMPT_PREVIEW_CHARS else "")
    return (f"{HEADER}\nsubagent_type: {tool_input.get('subagent_type') or 'general-purpose'}; "
            f"prompt bytes: {len(prompt.encode('utf-8'))}\n\n--- prompt ---\n{shown}")


def intercept(payload: dict[str, Any], agent_dry_run: bool) -> str | None:
    tool_input: Any = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if payload.get("tool_name") == "Bash":
        cwd: Path = Path(str(payload.get("cwd") or ".")).resolve()
        return bash_report(str(tool_input.get("command") or ""), cwd)
    if payload.get("tool_name") == "Agent" and agent_dry_run:
        return agent_report(tool_input)
    return None


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-dry-run", action="store_true")
    args: argparse.Namespace = parser.parse_args()
    try:
        payload: Any = json.load(sys.stdin)
        reason: str | None = intercept(payload, args.agent_dry_run) if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 - a dry-run hook must never break a real dispatch
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
