#!/usr/bin/env python3
"""Detect installed coding agents and resolve the configured roster into role assignments."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "agents"
DEFAULT_ROSTER: Final[list[dict[str, Any]]] = [{"name": "claude"}]
COPILOT_TIMEOUT_SECONDS: Final[int] = 10
IDE_MARKERS: Final[dict[str, str]] = {
    "cursor": ".cursor",
    "antigravity": ".agents/antigravity.md",
}
ITEM_PREFIX: Final[str] = "- name:"
PROBE_TIMEOUT_S: Final[int] = 10
PROBE_PATH_ENV: Final[str] = "DTS2_PROBE_PATH"
BIN_OVERRIDE_PREFIX: Final[str] = "DTS2_BIN_"
BINARY_EXTS: Final[tuple[str, ...]] = ("", ".cmd", ".exe", ".ps1", ".bat")
BUDGET_HEADER: Final[str] = "budget:"
STATUS_PREFIX: Final[str] = "status:"
AUTH_PREFIX: Final[str] = "auth:"
INCLUDED_PREFIX: Final[str] = "included:"
EXCLUDED_REASON: Final[str] = "excluded by user"
AUTH_SUBSCRIPTION: Final[str] = "subscription"
AUTH_API_KEY: Final[str] = "api-key"
AUTH_NONE: Final[str] = "none"
AUTH_UNVERIFIED: Final[str] = "installed (unverified)"
STATUS_FAILED: Final[str] = "status check failed"
NOT_OPTED_IN: Final[str] = (
    "no subscription login; API key present but not opted in (included: true)"
)
SECOND_OPINION: Final[str] = "second-opinion"
BUDGET_UNKNOWN: Final[str] = "unknown"
MODEL_TIERS: Final[tuple[str, ...]] = ("frontier", "standard", "economy")
PROMPT_TOKEN: Final[str] = "{prompt}"
MODEL_TOKEN: Final[str] = "{model}"
REVIEWER: Final[str] = "reviewer"


class RosterError(Exception):
    """Raised when the roster names an unknown agent or an unsupported role."""


def load_profiles() -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        profiles[data["name"]] = data
    return profiles


def parse_roles(value: str) -> list[str]:
    inner: str = value.strip().strip("[]")
    return [part.strip() for part in inner.split(",") if part.strip()]


def parse_roster(text: str) -> list[dict[str, Any]]:
    """Minimal parser for exactly this shape (no general YAML support):

        roster:
          - name: claude
          - name: codex
            roles: [builder, second-opinion]
            auth: api-key
            included: false

    Only a top-level `roster:` block is read; each item is `- name: X` optionally
    followed by `roles: [a, b]`, `auth: <mode>` (`subscription` or `api-key`) and `included: true|false`. Anything else is ignored. Missing block -> default.
    """
    entries: list[dict[str, Any]] = []
    in_block: bool = False
    for raw in text.splitlines():
        line: str = raw.strip()
        if not raw.startswith((" ", "\t")) and line:
            in_block = line == "roster:"
            continue
        if not in_block or not line or line.startswith("#"):
            continue
        if line.startswith(ITEM_PREFIX):
            entries.append({"name": line[len(ITEM_PREFIX):].strip()})
        elif line.startswith("roles:") and entries:
            entries[-1]["roles"] = parse_roles(line[len("roles:"):])
        elif line.startswith(AUTH_PREFIX) and entries:
            entries[-1]["auth"] = line[len(AUTH_PREFIX):].strip()
        elif line.startswith(INCLUDED_PREFIX) and entries:
            entries[-1]["included"] = line[len(INCLUDED_PREFIX):].strip().lower() != "false"
    return entries or [dict(item) for item in DEFAULT_ROSTER]


def read_roster(config: Path) -> list[dict[str, Any]]:
    if not config.exists():
        return [dict(item) for item in DEFAULT_ROSTER]
    return parse_roster(config.read_text(encoding="utf-8"))


def entry_roles(entry: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    roles: list[str] = entry.get("roles") or list(profile["roles"])
    for role in roles:
        if role not in profile["roles"]:
            raise RosterError(f"role '{role}' is not supported by agent '{entry['name']}'")
    return roles


def resolve(roster: list[dict[str, Any]], profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    enabled: list[str] = []
    assignments: dict[str, list[str]] = {}
    for entry in roster:
        name: str = entry["name"]
        if name not in profiles:
            raise RosterError(f"unknown agent '{name}'")
        enabled.append(name)
        for role in entry_roles(entry, profiles[name]):
            assignments.setdefault(role, []).append(name)
    handoff: list[str] = [n for n in enabled if profiles[n]["invocation"] == "handoff"]
    live: list[str] = [n for n in enabled if profiles[n]["invocation"] == "live"]
    cost_order: list[str] = sorted(enabled, key=lambda n: profiles[n]["costTier"])
    return {
        "enabled": enabled, "assignments": assignments, "handoff": handoff,
        "live": live, "costOrder": cost_order,
    }


def parse_budget(text: str) -> dict[str, str]:
    """Minimal parser for a top-level `budget:` block of `<agent>:` / `status: <value>` pairs."""
    budget: dict[str, str] = {}
    in_block: bool = False
    current: str = ""
    for raw in text.splitlines():
        line: str = raw.strip()
        if not raw.startswith((" ", "\t")) and line:
            in_block = line == BUDGET_HEADER
            current = ""
            continue
        if not in_block or not line or line.startswith("#"):
            continue
        if line.startswith(STATUS_PREFIX) and current:
            budget[current] = line[len(STATUS_PREFIX):].strip()
        elif line.endswith(":"):
            current = line[:-1].strip()
    return budget


def read_budget(config: Path) -> dict[str, str]:
    if not config.exists():
        return {}
    return parse_budget(config.read_text(encoding="utf-8"))


def probe_env() -> dict[str, str]:
    override: str | None = os.environ.get(PROBE_PATH_ENV)
    env: dict[str, str] = dict(os.environ)
    if override is not None:
        env["PATH"] = override
    return env


def override_key(binary: str) -> str:
    """Env var a user sets to point at a binary the harness cannot find, e.g. DTS2_BIN_AGY."""
    return BIN_OVERRIDE_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", binary).upper()


def expand(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def resolve_binary(binary: str, env: dict[str, str], search_paths: list[str]) -> str | None:
    """Find a binary off PATH: an explicit override wins, then PATH, then the profile's searchPaths.

    The override `DTS2_BIN_<NAME>` may be the binary itself or a directory holding it; search
    paths and the override directory try the common executable extensions so Windows shims match.
    """
    override: str | None = env.get(override_key(binary))
    dirs: list[Path] = [expand(p) for p in search_paths]
    if override:
        target: Path = expand(override)
        if target.is_file():
            return str(target)
        dirs.insert(0, target)
    found: str | None = shutil.which(binary, path=env.get("PATH", ""))
    if found:
        return found
    for directory in dirs:
        for ext in BINARY_EXTS:
            candidate: Path = directory / (binary + ext)
            if candidate.is_file():
                return str(candidate)
    return None


def search_paths_of(profile: dict[str, Any]) -> list[str]:
    return list(profile.get("searchPaths") or [])


def command_ok(command: list[str], env: dict[str, str], search_paths: list[str]) -> bool:
    resolved: str | None = resolve_binary(command[0], env, search_paths)
    if resolved is None:
        return False
    try:
        result = subprocess.run(
            [resolved, *command[1:]], capture_output=True,
            timeout=PROBE_TIMEOUT_S, check=False, env=env,
        )
    except Exception:
        return False
    return result.returncode == 0


def availability(profile: dict[str, Any], env: dict[str, str]) -> tuple[bool, str]:
    command: list[str] | None = profile["statusCommand"]
    search_paths: list[str] = search_paths_of(profile)
    if command is None:
        return True, "ok"
    if resolve_binary(command[0], env, search_paths) is None:
        return False, "not installed"
    return (True, "ok") if command_ok(command, env, search_paths) else (False, STATUS_FAILED)


def has_api_key(profile: dict[str, Any], env: dict[str, str]) -> bool:
    key_env: str | None = profile.get("apiKeyEnv")
    return bool(key_env and env.get(key_env))


def unverified_auth(
    profile: dict[str, Any], env: dict[str, str], declared: str | None,
) -> str:
    if declared == AUTH_SUBSCRIPTION:
        return AUTH_SUBSCRIPTION
    if declared == AUTH_API_KEY and has_api_key(profile, env):
        return AUTH_API_KEY
    return AUTH_UNVERIFIED


def auth_mode(
    profile: dict[str, Any], env: dict[str, str], available: bool, declared: str | None,
) -> str:
    """Subscription login wins; an API key counts only when no login is found. Presence only."""
    if profile["statusCommand"] is None:
        return AUTH_NONE
    login: list[str] | None = profile.get("loginCommand")
    if login is not None and command_ok(login, env, search_paths_of(profile)):
        return AUTH_SUBSCRIPTION
    if login is None and available:
        return unverified_auth(profile, env, declared)
    return AUTH_API_KEY if has_api_key(profile, env) else AUTH_NONE


def opt_in_override(
    entry: dict[str, Any], available: bool, reason: str, auth: str,
) -> tuple[bool, str]:
    if available or reason != STATUS_FAILED or auth != AUTH_API_KEY:
        return available, reason
    if entry.get("included") is True:
        return True, "ok"
    return False, NOT_OPTED_IN


def probe_entry(
    entry: dict[str, Any], profile: dict[str, Any], budget: str, env: dict[str, str],
) -> dict[str, Any]:
    available, reason = availability(profile, env)
    auth: str = auth_mode(profile, env, available, entry.get("auth"))
    available, reason = opt_in_override(entry, available, reason, auth)
    roles: list[str] = entry_roles(entry, profile)
    if entry.get("included") is False:
        return {
            "available": False, "reason": EXCLUDED_REASON, "budget": budget or BUDGET_UNKNOWN,
            "costTier": profile["costTier"], "roles": [], "auth": AUTH_NONE,
        }
    if available and budget == "exhausted":
        available, reason = False, "budget exhausted"
    if available and budget == "low":
        roles = [r for r in roles if r == SECOND_OPINION]
        if not roles:
            available, reason = False, "budget low"
    return {
        "available": available, "reason": reason, "budget": budget or BUDGET_UNKNOWN,
        "costTier": profile["costTier"], "roles": roles if available else [], "auth": auth,
    }


def probe(
    roster: list[dict[str, Any]], profiles: dict[str, dict[str, Any]], budgets: dict[str, str],
) -> dict[str, Any]:
    env: dict[str, str] = probe_env()
    agents: dict[str, dict[str, Any]] = {}
    for entry in roster:
        name: str = entry["name"]
        if name not in profiles:
            raise RosterError(f"unknown agent '{name}'")
        agents[name] = probe_entry(entry, profiles[name], budgets.get(name, ""), env)
    usable: list[str] = [n for n, a in agents.items() if a["available"]]
    dropped: list[dict[str, str]] = [
        {"name": n, "reason": a["reason"]} for n, a in agents.items() if not a["available"]
    ]
    return {"agents": agents, "usable": usable, "dropped": dropped}


def copilot_installed() -> bool:
    if shutil.which("gh") is None:
        return False
    try:
        result = subprocess.run(
            ["gh", "copilot", "--help"], capture_output=True,
            timeout=COPILOT_TIMEOUT_SECONDS, check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def is_installed(profile: dict[str, Any], project: Path, env: dict[str, str]) -> bool:
    name: str = profile["name"]
    if name == "claude":
        return True
    if name == "copilot":
        return copilot_installed()
    if name in IDE_MARKERS:
        return (project / IDE_MARKERS[name]).exists()
    command: list[str] | None = profile["command"]
    if not command:
        return False
    return resolve_binary(command[0], env, search_paths_of(profile)) is not None


def detect(project: Path) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = load_profiles()
    env: dict[str, str] = probe_env()
    installed: list[str] = [n for n, p in profiles.items() if is_installed(p, project, env)]
    installed.sort(key=lambda n: (n != "claude", list(profiles).index(n)))
    auth: dict[str, str] = {
        n: auth_mode(profiles[n], env, availability(profiles[n], env)[0], None) for n in installed
    }
    api_key: dict[str, bool] = {n: has_api_key(profiles[n], env) for n in installed}
    return {
        "installed": installed, "claudeOnly": installed == ["claude"],
        "auth": auth, "apiKey": api_key,
    }


def run_resolve(config: Path) -> int:
    try:
        result: dict[str, Any] = resolve(read_roster(config), load_profiles())
    except RosterError as error:
        print(f"roster error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def run_probe(config: Path) -> int:
    try:
        result: dict[str, Any] = probe(read_roster(config), load_profiles(), read_budget(config))
    except RosterError as error:
        print(f"roster error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def base_role(role: str) -> str:
    return role.split(":", 1)[0]


def supports_role(profile: dict[str, Any], role: str) -> bool:
    return role in profile["roles"] or base_role(role) in {base_role(r) for r in profile["roles"]}


def role_template(profile: dict[str, Any], role: str) -> list[str]:
    """Pick the argv template for a seat: the exact role, then its base (`reviewer:security` ->
    `reviewer`), then `reviewer` for a second opinion, then the profile `command` plus prompt."""
    templates: dict[str, list[str]] = profile.get("roleCommands") or {}
    keys: list[str] = [role, base_role(role)] + ([REVIEWER] if role == SECOND_OPINION else [])
    for key in keys:
        if key in templates:
            return list(templates[key])
    command: list[str] | None = profile["command"]
    if not command:
        raise RosterError(f"agent '{profile['name']}' has no command (invocation {profile['invocation']})")
    flag: list[str] = [profile["headlessFlag"]] if profile.get("headlessFlag") else []
    return [*command, *flag, PROMPT_TOKEN]


def fill_model(template: list[str], model: str | None) -> list[str]:
    """Replace `{model}`; with no model, drop the token and the flag in front of it."""
    argv: list[str] = []
    for part in template:
        if part != MODEL_TOKEN:
            argv.append(part)
        elif model:
            argv.append(model)
        elif argv and argv[-1].startswith("-"):
            argv.pop()
    return argv


def resolve_command(profile: dict[str, Any], role: str, tier: str) -> dict[str, Any]:
    if not supports_role(profile, role):
        raise RosterError(f"role '{role}' is not supported by agent '{profile['name']}'")
    model: str | None = profile["models"][tier]
    return {
        "agent": profile["name"], "role": role, "model": model,
        "argv": fill_model(role_template(profile, role), model),
        "notes": list(profile.get("notes") or []),
    }


def run_command(agent: str, role: str, tier: str) -> int:
    profile: dict[str, Any] | None = load_profiles().get(agent)
    try:
        if profile is None:
            raise RosterError(f"unknown agent '{agent}'")
        result: dict[str, Any] = resolve_command(profile, role, tier)
    except RosterError as error:
        print(f"roster error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def run_model(agent: str, tier: str) -> int:
    profile: dict[str, Any] | None = load_profiles().get(agent)
    if profile is None:
        print(f"roster error: unknown agent '{agent}'", file=sys.stderr)
        return 1
    model: str | None = profile["models"][tier]
    print(model if model else "null")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    det = sub.add_parser("detect")
    det.add_argument("--project", default=".")
    res = sub.add_parser("resolve")
    res.add_argument("--config", default=".harness/config.yaml")
    prb = sub.add_parser("probe")
    prb.add_argument("--config", default=".harness/config.yaml")
    mdl = sub.add_parser("model")
    mdl.add_argument("--agent", required=True)
    mdl.add_argument("--tier", required=True, choices=MODEL_TIERS)
    cmd = sub.add_parser("command", help="argv for one seat; the caller replaces {prompt}")
    cmd.add_argument("--agent", required=True)
    cmd.add_argument("--role", required=True)
    cmd.add_argument("--tier", default="standard", choices=MODEL_TIERS)
    args = parser.parse_args()
    if args.command == "detect":
        print(json.dumps(detect(Path(args.project))))
        return 0
    if args.command == "probe":
        return run_probe(Path(args.config))
    if args.command == "model":
        return run_model(args.agent, args.tier)
    if args.command == "command":
        return run_command(args.agent, args.role, args.tier)
    return run_resolve(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
