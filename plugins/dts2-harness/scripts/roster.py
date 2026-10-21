#!/usr/bin/env python3
"""Detect installed coding agents and resolve the configured roster into role assignments."""
from __future__ import annotations

import argparse
import json
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

    Only a top-level `roster:` block is read; each item is `- name: X` optionally
    followed by `roles: [a, b]`. Anything else is ignored. Missing block -> default.
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
    return {"enabled": enabled, "assignments": assignments, "handoff": handoff, "live": live}


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


def is_installed(profile: dict[str, Any], project: Path) -> bool:
    name: str = profile["name"]
    if name == "claude":
        return True
    if name == "copilot":
        return copilot_installed()
    if name in IDE_MARKERS:
        return (project / IDE_MARKERS[name]).exists()
    command: list[str] | None = profile["command"]
    return bool(command) and shutil.which(command[0]) is not None


def detect(project: Path) -> dict[str, Any]:
    installed: list[str] = [n for n, p in load_profiles().items() if is_installed(p, project)]
    installed.sort(key=lambda n: (n != "claude", list(load_profiles()).index(n)))
    return {"installed": installed, "claudeOnly": installed == ["claude"]}


def run_resolve(config: Path) -> int:
    try:
        result: dict[str, Any] = resolve(read_roster(config), load_profiles())
    except RosterError as error:
        print(f"roster error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    det = sub.add_parser("detect")
    det.add_argument("--project", default=".")
    res = sub.add_parser("resolve")
    res.add_argument("--config", default=".harness/config.yaml")
    args = parser.parse_args()
    if args.command == "detect":
        print(json.dumps(detect(Path(args.project))))
        return 0
    return run_resolve(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
