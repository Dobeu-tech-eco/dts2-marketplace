#!/usr/bin/env python3
"""Audit a machine against a blueprint profile and, with --apply, prune Claude plugins.

audit  : read-only inventory and budget check (exit 1 when over budget)
plan   : show the exact settings.json change apply would make
apply  : back up settings.json, then disable plugins outside the keep set

Never deletes plugins, agents, skills, or credentials. Disabling is reversible.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

DEFAULT_PROFILE: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "blueprint.json"
FORBIDDEN_SCRIPT_DIRS: Final[tuple[str, ...]] = (".codex", ".claude")
CODEX_ENABLED_LINE: Final[str] = "enabled = true"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def count_entries(folder: Path, pattern: str) -> int:
    return len(list(folder.glob(pattern))) if folder.exists() else 0


def codex_enabled(home: Path) -> int:
    config: Path = home / ".codex" / "config.toml"
    if not config.exists():
        return 0
    lines: list[str] = config.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() == CODEX_ENABLED_LINE)


def bad_symlinks(claude_home: Path, targets: list[str]) -> list[str]:
    found: list[str] = []
    for folder in (claude_home / "skills", claude_home / "agents"):
        links = [p for p in folder.glob("*") if p.is_symlink()] if folder.exists() else []
        found += [f"{p} -> {p.readlink()}" for p in links if any(t in str(p.readlink()) for t in targets)]
    return found


def inventory(home: Path, claude_home: Path) -> dict[str, object]:
    settings: dict = load_json(claude_home / "settings.json")
    plugins: dict[str, bool] = settings.get("enabledPlugins") or {}
    claude_md: Path = claude_home / "CLAUDE.md"
    return {
        "enabledPlugins": sorted(k for k, v in plugins.items() if v),
        "disabledPlugins": sorted(k for k, v in plugins.items() if not v),
        "claudeUserAgents": count_entries(claude_home / "agents", "*.md"),
        "claudeSkillEntries": count_entries(claude_home / "skills", "*"),
        "claudeMdBytes": claude_md.stat().st_size if claude_md.exists() else 0,
        "codexEnabledPlugins": codex_enabled(home),
        "codexAgents": count_entries(home / ".codex" / "agents", "*.toml"),
    }


def budget_findings(inv: dict[str, object], profile: dict) -> list[str]:
    budget: dict[str, int] = profile.get("budget", {})
    actual: dict[str, int] = {**{k: v for k, v in inv.items() if isinstance(v, int)},
                              "claudeEnabledPlugins": len(inv["enabledPlugins"])}
    return [f"{key}={actual[key]} (max {limit})" for key, limit in budget.items()
            if actual.get(key, 0) > limit]


def boundary_findings(home: Path, claude_home: Path, profile: dict) -> list[str]:
    rules: dict = profile.get("boundaries", {})
    found: list[str] = bad_symlinks(claude_home, rules.get("forbiddenSymlinkTargets", []))
    for name in rules.get("forbiddenScripts", []):
        found += [str(home / d / name) for d in FORBIDDEN_SCRIPT_DIRS if (home / d / name).exists()]
    return found


def plan_plugins(current: dict[str, bool], profile: dict) -> dict[str, bool]:
    keep: set[str] = set(profile["claude"]["enabledPlugins"])
    planned: dict[str, bool] = {key: key in keep for key in current}
    for key in keep:
        planned.setdefault(key, True)
    return planned


def diff_plugins(current: dict[str, bool], planned: dict[str, bool]) -> list[str]:
    return [f"{key}: {current.get(key, 'absent')} -> {value}"
            for key, value in sorted(planned.items()) if current.get(key) != value]


def backup(path: Path) -> Path:
    folder: Path = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target: Path = folder / f"settings.{datetime.now():%Y%m%d-%H%M%S}.json"
    shutil.copy2(path, target)
    return target


def run_audit(home: Path, claude_home: Path, profile: dict) -> int:
    inv: dict[str, object] = inventory(home, claude_home)
    issues: list[str] = budget_findings(inv, profile) + boundary_findings(home, claude_home, profile)
    keep: set[str] = set(profile["claude"]["enabledPlugins"])
    report = {"claudeHome": str(claude_home), "inventory": inv, "issues": issues,
              "toDisable": sorted(set(inv["enabledPlugins"]) - keep),
              "missingFromKeepSet": sorted(keep - set(inv["enabledPlugins"]))}
    print(json.dumps(report, indent=2))
    return 1 if issues else 0


def run_change(claude_home: Path, profile: dict, apply: bool) -> int:
    path: Path = claude_home / "settings.json"
    if not path.exists():
        print(f"No settings.json at {path}. Nothing to change.")
        return 0
    settings: dict = load_json(path)
    current: dict[str, bool] = settings.get("enabledPlugins") or {}
    planned: dict[str, bool] = plan_plugins(current, profile)
    changes: list[str] = diff_plugins(current, planned)
    print("\n".join(changes) if changes else "Already matches the profile.")
    if not apply or not changes:
        return 0
    saved: Path = backup(path)
    path.write_text(json.dumps({**settings, "enabledPlugins": planned}, indent=2) + "\n", encoding="utf-8")
    print(f"Applied. Backup: {saved}. Restart Claude Code to load the change.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["audit", "plan", "apply"])
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--claude-home", type=Path, help="Override, e.g. /mnt/c/Users/<you>/.claude from WSL")
    args = parser.parse_args()
    profile: dict = load_json(args.profile)
    claude_home: Path = args.claude_home or args.home / ".claude"
    if args.command == "audit":
        return run_audit(args.home, claude_home, profile)
    return run_change(claude_home, profile, apply=args.command == "apply")


if __name__ == "__main__":
    sys.exit(main())
