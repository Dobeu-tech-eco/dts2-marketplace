#!/usr/bin/env python3
"""Install the harness hooks (hooks/hooks.json) into an agent's own hook config, with absolute paths to the hook scripts.

The hook scripts resolve their plugin root themselves, so any agent that can run a shell command can call them.
This script writes the entries each agent reads: Claude Code, Codex, Cursor, Google Antigravity, Grok Build and Muse.
It merges and never clobbers: other entries stay, a re-run changes nothing, and --uninstall removes only the entries it wrote.
Stdlib only; prints one JSON object on stdout. Exit codes: 0 ok, 1 a file it will not overwrite, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
HOOKS_DIR: Final[Path] = PLUGIN_ROOT / "hooks"
HOOKS_JSON: Final[Path] = HOOKS_DIR / "hooks.json"
ROOT_VAR: Final[str] = "${CLAUDE_PLUGIN_ROOT}"
NESTED: Final[str] = "nested"
FLAT: Final[str] = "flat"
ALL: Final[str] = "all"
# Claude's own event names, which hooks.json uses; every agent table below maps them to the agent's name or leaves them out.
CLAUDE_EVENTS: Final[tuple[str, ...]] = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolBatch", "Stop", "StopFailure",
    "PermissionDenied", "SubagentStart", "SubagentStop", "PreCompact",
)
SAME_NAME: Final[dict[str, str]] = {event: event for event in CLAUDE_EVENTS}
# Claude tool names in matchers. None means the agent has no such tool, so that alternative is dropped.
CLAUDE_TOOLS: Final[tuple[str, ...]] = (
    "Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep", "WebFetch", "WebSearch", "Agent",
)
SAME_TOOLS: Final[dict[str, str | None]] = {tool: tool for tool in CLAUDE_TOOLS}
# A matcher alternative that names these (plugin subagent types, the SubagentHandback tool) only exists under Claude Code.
CLAUDE_ONLY_MATCHER: Final[re.Pattern[str]] = re.compile(r"^dt:|^SubagentHandback$")
# The hook scripts that refuse tool calls. For an agent with deny_exit_code set they get a flag telling them to exit with it.
DENY_HOOKS: Final[re.Pattern[str]] = re.compile(r"[/\\]hooks[/\\](?:merge-guard|policy-gate)\.sh\b")


@dataclass(frozen=True)
class AgentSpec:
    """Where an agent keeps hooks and how it spells them. Every field is a documented fact or a marked assumption."""

    name: str
    project_path: tuple[str, ...]  # under --repo
    user_path: tuple[str, ...]  # under the home directory
    layout: str  # NESTED: {"hooks": {Event: [{"matcher", "hooks": [...]}]}}; FLAT: {"version": 1, "hooks": {event: [{...}]}}
    events: dict[str, str]  # Claude event name to this agent's event name
    tools: dict[str, str | None]  # Claude tool name to this agent's tool name
    keeps_if: bool  # whether the agent understands the per-hook `if` filter
    verified: bool  # False: the format below is an assumption to check against the agent's docs
    source: str  # where the format comes from, or the assumption made
    notes: tuple[str, ...] = ()
    user_defaults: tuple[tuple[str, Any], ...] = ()  # top-level keys a user-scope file must carry, set only when missing
    deny_exit_code: int = 0  # 2: the refusing hooks exit 2 instead of 0 (the agent ignores a JSON deny); no other value is used


# One table row per agent. Change a path, a layout or an event name here and nothing else needs to move.
AGENTS: Final[dict[str, AgentSpec]] = {
    "claude": AgentSpec(
        name="claude",
        # settings.local.json, not settings.json: the entries carry this machine's absolute paths, so they should not be committed.
        project_path=(".claude", "settings.local.json"), user_path=(".claude", "settings.json"),
        layout=NESTED, events=SAME_NAME, tools=SAME_TOOLS, keeps_if=True, verified=True,
        source="Claude Code settings: top-level `hooks`, event -> [{matcher, hooks: [{type, command, timeout, if}]}].",
        notes=("If the dts2-runtime plugin is also enabled in Claude Code, its own hooks.json already registers these hooks; "
               "use this for a checkout that runs without the plugin.",),
    ),
    "codex": AgentSpec(
        name="codex",
        project_path=(".codex", "hooks.json"), user_path=(".codex", "hooks.json"),
        layout=NESTED,
        events={e: e for e in ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
                               "SubagentStart", "SubagentStop", "PreCompact")},
        tools={"Bash": "Bash", "Edit": "apply_patch", "Write": "apply_patch", "MultiEdit": "apply_patch",
               "NotebookEdit": "apply_patch", "Read": None, "Glob": None, "Grep": None, "WebFetch": None, "WebSearch": None,
               "Agent": None},
        keeps_if=False, verified=False,
        source=("ASSUMPTION: Codex reads a hooks.json whose shape matches Claude's (nested matcher groups, `command` handlers, "
                "timeout in seconds), at .codex/hooks.json or ~/.codex/hooks.json, and edits arrive as the apply_patch tool."),
        notes=("Codex only runs hooks when its hooks feature is on (config.toml `features.hooks = true`); this script does not edit config.toml.",),
    ),
    "cursor": AgentSpec(
        name="cursor",
        project_path=(".cursor", "hooks.json"), user_path=(".cursor", "hooks.json"),
        layout=FLAT,
        events={"SessionStart": "sessionStart", "SessionEnd": "sessionEnd", "UserPromptSubmit": "beforeSubmitPrompt",
                "PreToolUse": "preToolUse", "PostToolUse": "postToolUse", "Stop": "stop", "SubagentStart": "subagentStart",
                "SubagentStop": "subagentStop", "PreCompact": "preCompact"},
        tools={"Bash": "Shell", "Edit": "Write", "Write": "Write", "MultiEdit": "Write", "NotebookEdit": "Write", "Read": "Read",
               "Glob": "Grep", "Grep": "Grep", "WebFetch": None, "WebSearch": None, "Agent": "Task"},
        keeps_if=False, verified=True,
        source=("Cursor hooks.json: {version: 1, hooks: {camelCaseEvent: [{command, timeout, matcher}]}}. "
                "The tool names in matchers (Shell, Write, Read, Grep, Task) are from Cursor's hook docs; check them when Cursor changes."),
    ),
    "antigravity": AgentSpec(
        name="antigravity",
        project_path=(".agents", "hooks.json"), user_path=(".gemini", "config", "hooks.json"),
        layout=NESTED,
        # Antigravity has no prompt-submit or session events under Claude's names; PreInvocation runs before each model turn.
        events={"UserPromptSubmit": "PreInvocation", "PreToolUse": "PreToolUse"},
        tools=SAME_TOOLS, keeps_if=False, verified=False,
        source=("Google Antigravity IDE (not the Gemini CLI) reads hooks from <project>/.agents/hooks.json and "
                "~/.gemini/config/hooks.json, with PreInvocation and PreToolUse events. ASSUMPTION: the per-file shape and "
                "tool names match Claude's."),
        notes=("Antigravity expects a JSON decision on stdout. The dts2 hooks print one only when they refuse, so an "
               "allowed call relies on Antigravity treating empty output as allow.",),
    ),
    "grok": AgentSpec(
        name="grok",
        # Grok Build loads every *.json in these folders, so we own one file and never touch the user's other hook files.
        project_path=(".grok", "hooks", "dts2.json"), user_path=(".grok", "hooks", "dts2.json"),
        layout=NESTED,
        events={e: e for e in CLAUDE_EVENTS if e != "PostToolBatch"},
        tools=SAME_TOOLS, keeps_if=False, verified=False,
        source=("Grok Build reads ~/.grok/hooks/*.json and <project>/.grok/hooks/*.json with Claude's event names "
                "(docs.x.ai/build/features/hooks). ASSUMPTION: the per-file shape matches Claude's and tool names match too."),
    ),
    "muse": AgentSpec(
        name="muse",
        # User scope is the hooks block inside Muse's own settings file; every other key there is left alone.
        project_path=(".muse", "hooks.json"), user_path=(".config", "muse", "settings.json"),
        layout=NESTED,
        events={e: e for e in ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")},
        tools=SAME_TOOLS, keeps_if=False, verified=False,
        source=("Muse Code (Meta) reads Claude-shaped hooks from <project>/.muse/hooks.json (trusted folders only) and from "
                "the hooks block of ~/.config/muse/settings.json (schema_version 1). Handler keys: type, command, timeout. "
                "ASSUMPTION: tool names match Claude's."),
        notes=("Muse clears the environment to USER and HOME, so commands use absolute paths (this installer always does).",
               "Muse honours a refusal only with exit code 2, so the merge guard and policy gate get --deny-exit-code=2: "
               "they then exit 2 on a refusal and print the reason on stderr."),
        user_defaults=(("schema_version", 1),),
        deny_exit_code=2,
    ),
}


class InstallError(Exception):
    """A file this script will not overwrite, or an agent it does not know."""


def load_source(path: Path = HOOKS_JSON) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    return {event: groups for event, groups in hooks.items() if isinstance(groups, list)}


def posix(path: Path) -> str:
    """Forward slashes, also for `C:\\...`: bash reads `C:/...` and a backslash inside quotes is an escape."""
    return path.as_posix()


def script_marker() -> re.Pattern[str]:
    """Matches a command that runs one of this plugin's hook scripts.

    The path must sit under this plugin's root or under a folder named after a dts2 plugin (a cached
    version directory, say), so a user's own `./hooks/session-end.sh` is never treated as ours.
    """
    names = sorted({p.stem for p in HOOKS_DIR.glob("*.sh")}) or ["session-lessons"]
    script = r"[/\\]hooks[/\\](?:" + "|".join(re.escape(n) for n in names) + r")\.sh\b"
    root = re.escape(posix(PLUGIN_ROOT))
    return re.compile(r"(?:" + root + r"|dts2-(?:runtime|harness)\b[^\s\"']*)" + script)


MARKER: Final[re.Pattern[str]] = script_marker()


def is_ours(command: Any) -> bool:
    """The tag: a command that runs a hook script from this plugin by absolute path. Entries using the plugin variable are not ours."""
    return isinstance(command, str) and ROOT_VAR not in command and MARKER.search(command) is not None


def map_matcher(spec: AgentSpec, matcher: str | None) -> tuple[bool, str | None]:
    """Return (keep, matcher). A group whose matcher has no equivalent in this agent is dropped."""
    if not matcher:
        return True, None
    if matcher == "auto|manual":  # PreCompact trigger names are Claude's
        return (True, matcher) if spec.name in ("claude", "grok") else (True, None)
    mapped: list[str] = []
    for part in matcher.split("|"):
        if spec.name != "claude" and CLAUDE_ONLY_MATCHER.search(part):
            continue
        tool = spec.tools.get(part, part if spec.tools is SAME_TOOLS else None)
        if tool and tool not in mapped:
            mapped.append(tool)
    return (True, "|".join(mapped)) if mapped else (False, None)


def render(spec: AgentSpec, root: Path, source: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Translate hooks.json into this agent's entries. Returns (event -> entries, skipped events with a reason)."""
    out: dict[str, list[dict[str, Any]]] = {}
    skipped: list[dict[str, str]] = []
    root_text = posix(root)
    for event, groups in source.items():
        target = spec.events.get(event)
        if target is None:
            skipped.append({"event": event, "reason": f"{spec.name} has no equivalent event"})
            continue
        seen: set[tuple[str, str, Any]] = set()
        for group in groups:
            keep, matcher = map_matcher(spec, group.get("matcher"))
            if not keep:
                skipped.append({"event": event, "reason": f"matcher {group.get('matcher')!r} has no equivalent in {spec.name}"})
                continue
            hooks: list[dict[str, Any]] = []
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict) or hook.get("type") != "command" or not isinstance(hook.get("command"), str):
                    continue
                command = hook["command"].replace(ROOT_VAR, root_text)
                if spec.deny_exit_code == 2 and DENY_HOOKS.search(command):  # the hooks accept only 2
                    command += f" --deny-exit-code={spec.deny_exit_code}"
                key = (matcher or "", command, hook.get("if") if spec.keeps_if else None)
                if key in seen:  # without the `if` filter, copies of one command collapse into one
                    continue
                seen.add(key)
                item: dict[str, Any] = {"type": "command", "command": command}
                if "timeout" in hook:
                    item["timeout"] = hook["timeout"]
                if spec.keeps_if and "if" in hook:
                    item["if"] = hook["if"]
                hooks.append(item)
            if not hooks:
                continue
            if spec.layout == NESTED:
                entry: dict[str, Any] = {"matcher": matcher} if matcher else {}
                entry["hooks"] = hooks
                out.setdefault(target, []).append(entry)
            else:
                for item in hooks:
                    flat: dict[str, Any] = {"command": item["command"]}
                    if "timeout" in item:
                        flat["timeout"] = item["timeout"]
                    if matcher:
                        flat["matcher"] = matcher
                    out.setdefault(target, []).append(flat)
    return out, skipped


DENY_FLAG: Final[re.Pattern[str]] = re.compile(r" --deny-exit-code=\d+$")


def command_key(command: Any) -> Any:
    """A command without the deny-exit-code flag, so an install with and without the flag is the same entry."""
    return DENY_FLAG.sub("", command) if isinstance(command, str) else command


def entry_key(layout: str, entry: dict[str, Any]) -> tuple[Any, ...]:
    if layout == NESTED:
        return (entry.get("matcher"), tuple(command_key(h.get("command")) for h in entry.get("hooks", []) if isinstance(h, dict)))
    return (entry.get("matcher"), command_key(entry.get("command")))


def ours_hooks(layout: str, entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if layout == NESTED:
        return any(isinstance(h, dict) and is_ours(h.get("command")) for h in entry.get("hooks", []))
    return is_ours(entry.get("command"))


def strip_entry(layout: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Remove our hooks from one entry, keeping the rest. None when nothing is left."""
    if layout != NESTED:
        return None
    rest = [h for h in entry.get("hooks", []) if not (isinstance(h, dict) and is_ours(h.get("command")))]
    return {**entry, "hooks": rest} if rest else None


def merge_event(layout: str, existing: list[Any], desired: list[dict[str, Any]]) -> list[Any]:
    """Keep every foreign entry, update ours in place, drop stale ours, append what is missing."""
    wanted = {entry_key(layout, d): d for d in desired}
    placed: set[tuple[Any, ...]] = set()
    out: list[Any] = []
    for entry in existing:
        if not ours_hooks(layout, entry):
            out.append(entry)
            continue
        key = entry_key(layout, entry)
        pure = layout == FLAT or all(isinstance(h, dict) and is_ours(h.get("command")) for h in entry.get("hooks", []))
        if pure and key in wanted:
            if key not in placed:
                out.append(copy.deepcopy(wanted[key]))
                placed.add(key)
            continue
        rest = strip_entry(layout, entry)
        if rest is not None:
            out.append(rest)
    out.extend(copy.deepcopy(d) for k, d in wanted.items() if k not in placed)
    return out


def strip_event(layout: str, existing: list[Any]) -> list[Any]:
    out: list[Any] = []
    for entry in existing:
        if not ours_hooks(layout, entry):
            out.append(entry)
            continue
        rest = strip_entry(layout, entry)
        if rest is not None:
            out.append(rest)
    return out


def read_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix or move it, nothing was changed") from exc
    if not isinstance(doc, dict):
        raise InstallError(f"{path} does not hold a JSON object; nothing was changed")
    hooks = doc.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise InstallError(f"{path}: `hooks` is not an object; nothing was changed")
    return doc


def build_doc(spec: AgentSpec, original: dict[str, Any], desired: dict[str, list[dict[str, Any]]], uninstall: bool) -> dict[str, Any]:
    doc = copy.deepcopy(original)
    hooks: dict[str, Any] = doc.get("hooks") or {}
    if uninstall:
        for event in list(hooks):
            if isinstance(hooks[event], list):
                kept = strip_event(spec.layout, hooks[event])
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
    else:
        for event in list(hooks):  # an event we no longer register: drop stale ours
            if event not in desired and isinstance(hooks[event], list):
                kept = strip_event(spec.layout, hooks[event])
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
        for event, entries in desired.items():
            current = hooks.get(event)
            hooks[event] = merge_event(spec.layout, current if isinstance(current, list) else [], entries)
    if hooks:
        doc["hooks"] = hooks
    else:
        doc.pop("hooks", None)
    if spec.layout == FLAT and not uninstall:
        doc.setdefault("version", 1)
    return doc


def is_blank(spec: AgentSpec, doc: dict[str, Any]) -> bool:
    return not doc or (spec.layout == FLAT and doc == {"version": 1})


def count_entries(doc: dict[str, Any]) -> int:
    hooks = doc.get("hooks") or {}
    return sum(len(v) for v in hooks.values() if isinstance(v, list))


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".hooks-install-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as tmp:
            tmp.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def target_path(spec: AgentSpec, repo: Path, home: Path, user: bool) -> Path:
    return home.joinpath(*spec.user_path) if user else repo.joinpath(*spec.project_path)


def run_agent(name: str, repo: Path, home: Path, user: bool, dry_run: bool, uninstall: bool,
              source: dict[str, list[dict[str, Any]]] | None = None, root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    spec = AGENTS.get(name)
    if spec is None:
        raise InstallError(f"unknown agent {name!r}; choose one of {', '.join(AGENTS)} or {ALL}")
    path = target_path(spec, repo, home, user)
    desired, skipped = render(spec, root, source if source is not None else load_source())
    original = read_doc(path)
    new_doc = build_doc(spec, original, desired, uninstall)
    if user and not uninstall:
        for key, value in spec.user_defaults:
            new_doc.setdefault(key, value)
    changed = new_doc != original
    # A user-scope file with defaults is the agent's own settings file: strip our hooks but never delete it.
    keep_file = user and bool(spec.user_defaults)
    remove_file = uninstall and changed and not keep_file and is_blank(spec, new_doc) and path.is_file()
    before, after = count_entries(original), count_entries(new_doc)
    if not changed:
        action = "unchanged"
    elif uninstall:
        action = "removed"
    else:
        action = "created" if not path.is_file() else "updated"
    wrote = False
    if changed and not dry_run:
        if remove_file:
            path.unlink()
        else:
            write_atomic(path, new_doc)
        wrote = True
    result: dict[str, Any] = {
        "agent": name, "scope": "user" if user else "project", "path": str(path), "action": action, "wrote": wrote,
        "entriesBefore": before, "entriesAfter": after, "skipped": [] if uninstall else skipped,
        "verified": spec.verified, "source": spec.source, "notes": list(spec.notes),
    }
    if dry_run:
        result["dryRun"] = True
        result["wouldWrite"] = None if remove_file else new_doc
        result["wouldDelete"] = remove_file
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hooks_install.py",
        description="Write the dts2 hooks into an agent's own hook config using absolute script paths. Merges; never clobbers.")
    parser.add_argument("--agent", required=True, choices=[*AGENTS, ALL], help="which agent's config to write, or all")
    parser.add_argument("--repo", default=".", help="project folder for project scope (default: current folder)")
    parser.add_argument("--user", action="store_true", help="write the user-level config under the home folder instead")
    parser.add_argument("--home", default=None, help="home folder for --user (default: the current user's home)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be written and change nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove only the entries this script wrote")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    home = Path(args.home).expanduser().resolve() if args.home else Path.home()
    names = list(AGENTS) if args.agent == ALL else [args.agent]
    results: list[dict[str, Any]] = []
    status = 0
    source = load_source()
    for name in names:
        try:
            results.append(run_agent(name, repo, home, args.user, args.dry_run, args.uninstall, source))
        except InstallError as exc:
            results.append({"agent": name, "action": "error", "error": str(exc), "wrote": False})
            status = 1
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
