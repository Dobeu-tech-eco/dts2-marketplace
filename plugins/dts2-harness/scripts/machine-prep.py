#!/usr/bin/env python3
"""Audit a machine against a blueprint profile and, with apply, prune Claude Code plugins.

audit  : read-only inventory and budget check (exit 1 when over budget)
plan   : show the exact settings.json change apply would make
apply  : back up settings.json, then write the change

Plugins come from two places and both are handled:
  marketplace plugins  -> enabledPlugins keys such as name@marketplace
  claude.ai account    -> synced into ~/.claude/plugins/synced/ and loaded as name@synced
                          on every session start, which is why they keep coming back

Never deletes plugins, agents, skills, or credentials. Every change is reversible.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
DEFAULT_DAYS: Final[int] = 30
DEFAULT_PROFILE: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "blueprint.json"
FORBIDDEN_SCRIPT_DIRS: Final[tuple[str, ...]] = (".codex", ".claude")
CODEX_ENABLED_LINE: Final[str] = "enabled = true"
INSTALL_RECORDS: Final[str] = "installed_plugins.json"


def load_tiers() -> object:
    spec = importlib.util.spec_from_file_location("prep_tiers", SCRIPT_DIR / "prep-tiers.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["prep_tiers"] = module
    spec.loader.exec_module(module)
    return module


tiers = load_tiers()
SYNCED_SUFFIX: Final[str] = tiers.SYNCED_SUFFIX
SYNC_KEY: Final[str] = tiers.SYNC_KEY
REQUIRED_PREFERENCE: Final[str] = tiers.REQUIRED_PREFERENCE


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


def synced_plugin(folder: Path) -> dict[str, str]:
    meta: dict = load_json(folder.with_suffix(".meta.json"))
    name: str = load_json(folder / ".claude-plugin" / "plugin.json").get("name", folder.name)
    return {"id": f"{name}{SYNCED_SUFFIX}", "root": str(folder),
            "preference": meta.get("installation_preference", "unknown")}


def synced_plugins(claude_home: Path) -> list[dict[str, str]]:
    root: Path = claude_home / "plugins" / "synced"
    folders: list[Path] = sorted(p for p in root.glob("*/*") if p.is_dir()) if root.exists() else []
    return [synced_plugin(f) for f in folders]


def agent_count(plugin_root: Path) -> int:
    return count_entries(plugin_root / "agents", "**/*.md")


def marketplace_root(claude_home: Path, plugin_id: str, record: dict) -> Path:
    name, _, market = plugin_id.partition("@")
    return claude_home / "plugins" / "cache" / market / name / str(record.get("version", ""))


def marketplace_agents(claude_home: Path, enabled: list[str]) -> dict[str, int]:
    records: dict = load_json(claude_home / "plugins" / INSTALL_RECORDS).get("plugins") or {}
    roots = {p: marketplace_root(claude_home, p, (records.get(p) or [{}])[0]) for p in enabled}
    return {p: agent_count(r) for p, r in roots.items() if agent_count(r)}


def synced_agents(synced: list[dict[str, str]], loading: list[str]) -> dict[str, int]:
    return {s["id"]: agent_count(Path(s["root"])) for s in synced
            if s["id"] in loading and agent_count(Path(s["root"]))}


def bad_symlinks(claude_home: Path, targets: list[str]) -> list[str]:
    found: list[str] = []
    for folder in (claude_home / "skills", claude_home / "agents"):
        links = [p for p in folder.glob("*") if p.is_symlink()] if folder.exists() else []
        found += [f"{p} -> {p.readlink()}" for p in links if any(t in str(p.readlink()) for t in targets)]
    return found


def project_overrides(project: Path) -> list[str]:
    shared: dict[str, bool] = load_json(project / ".claude" / "settings.json").get("enabledPlugins") or {}
    local: dict[str, bool] = load_json(project / ".claude" / "settings.local.json").get("enabledPlugins") or {}
    return sorted(k for k, v in shared.items() if v and local.get(k) is not False)


def loaded_synced(settings: dict, synced: list[dict[str, str]]) -> list[str]:
    if settings.get(SYNC_KEY) is False:
        return []
    plugins: dict[str, bool] = settings.get("enabledPlugins") or {}
    return [s["id"] for s in synced if plugins.get(s["id"]) is not False or s["preference"] == REQUIRED_PREFERENCE]


def read_usage(claude_home: Path, days: int) -> dict[str, int]:
    cmd: list[str] = [sys.executable, "-I", str(SCRIPT_DIR / "usage-scan.py"),
                      "--claude-home", str(claude_home), "--days", str(days)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return json.loads(result.stdout).get("plugins", {}) if result.returncode == 0 else {}


def plugin_roots(claude_home: Path, enabled: list[str], synced: list[dict[str, str]], loading: list[str]) -> dict[str, Path]:
    records: dict = load_json(claude_home / "plugins" / INSTALL_RECORDS).get("plugins") or {}
    roots: dict[str, Path] = {p: marketplace_root(claude_home, p, (records.get(p) or [{}])[0]) for p in enabled}
    return {**roots, **{s["id"]: Path(s["root"]) for s in synced if s["id"] in loading}}


def inventory(home: Path, claude_home: Path, project: Path, days: int = DEFAULT_DAYS) -> dict[str, object]:
    settings: dict = load_json(claude_home / "settings.json")
    plugins: dict[str, bool] = settings.get("enabledPlugins") or {}
    synced: list[dict[str, str]] = synced_plugins(claude_home)
    claude_md: Path = claude_home / "CLAUDE.md"
    enabled: list[str] = sorted(k for k, v in plugins.items() if v and not k.endswith(SYNCED_SUFFIX))
    overrides: list[str] = project_overrides(project)
    loading: list[str] = loaded_synced(settings, synced)
    plugin_agents: dict[str, int] = {**marketplace_agents(claude_home, sorted(set(enabled + overrides))),
                                     **synced_agents(synced, loading)}
    usage: dict[str, int] = read_usage(claude_home, days)
    roots: dict[str, Path] = plugin_roots(claude_home, sorted(set(enabled + overrides)), synced, loading)
    return {
        "enabledPlugins": enabled,
        "usage": usage,
        "redundantAgentPacks": tiers.redundant_packs(synced, usage),
        "duplicateSkillNames": tiers.duplicate_skills(roots),
        "syncClaudeAiPlugins": settings.get(SYNC_KEY, "unset (syncing on)"),
        "syncedPluginsOnDisk": len(synced),
        "syncedPluginsLoading": loading,
        "syncedRequiredByOrg": [s["id"] for s in synced if s["preference"] == REQUIRED_PREFERENCE],
        "projectEnablesOverridingYou": overrides,
        "claudeUserAgents": count_entries(claude_home / "agents", "*.md"),
        "claudePluginAgents": sum(plugin_agents.values()),
        "pluginAgentsBySource": plugin_agents,
        "syncClaudeAiSkills": settings.get("syncClaudeAiSkills", "unset (syncing on)"),
        "syncedSkillsOnDisk": count_entries(claude_home / "skills" / "synced", "*"),
        "claudeSkillEntries": len([p for p in (claude_home / "skills").glob("*") if p.name != "synced"])
                              if (claude_home / "skills").exists() else 0,
        "claudeMdBytes": claude_md.stat().st_size if claude_md.exists() else 0,
        "codexEnabledPlugins": codex_enabled(home),
        "codexAgents": count_entries(home / ".codex" / "agents", "*.toml"),
    }


def budget_findings(inv: dict[str, object], profile: dict) -> list[str]:
    budget: dict[str, int] = profile.get("budget", {})
    loading: int = len(inv["enabledPlugins"]) + len(inv["syncedPluginsLoading"])
    actual: dict[str, int] = {**{k: v for k, v in inv.items() if isinstance(v, int)},
                              "claudeEnabledPlugins": loading}
    return [f"{key}={actual[key]} (max {limit})" for key, limit in budget.items()
            if actual.get(key, 0) > limit]


def boundary_findings(home: Path, claude_home: Path, profile: dict) -> list[str]:
    rules: dict = profile.get("boundaries", {})
    found: list[str] = bad_symlinks(claude_home, rules.get("forbiddenSymlinkTargets", []))
    for name in rules.get("forbiddenScripts", []):
        found += [str(home / d / name) for d in FORBIDDEN_SCRIPT_DIRS if (home / d / name).exists()]
    return found


def diff_settings(before: dict, after: dict, protected: list[str] | None = None) -> list[str]:
    lines: list[str] = []
    for key in (SYNC_KEY, tiers.SKILLS_SYNC_KEY):
        if before.get(key) != after.get(key):
            lines.append(f"{key}: {before.get(key, 'unset')} -> {after.get(key)}")
    old: dict[str, bool] = before.get("enabledPlugins") or {}
    new: dict[str, bool] = after.get("enabledPlugins") or {}
    guarded: set[str] = set(protected or [])
    suffix: str = f" {tiers.PROTECTED_NOTE}"
    return lines + [f"{k}: {old.get(k, 'absent')} -> {v}{suffix if k in guarded else ''}"
                    for k, v in sorted(new.items()) if old.get(k) != v or k in guarded]


def backup(path: Path) -> Path:
    folder: Path = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target: Path = folder / f"settings.{datetime.now():%Y%m%d-%H%M%S}.json"
    shutil.copy2(path, target)
    return target


def run_audit(args: argparse.Namespace, claude_home: Path, profile: dict) -> int:
    home, project = args.home, args.project
    inv: dict[str, object] = inventory(home, claude_home, project, args.days)
    issues: list[str] = budget_findings(inv, profile) + boundary_findings(home, claude_home, profile)
    issues += [f"{p} is enabled by {project}/.claude/settings.json and overrides your user setting"
               for p in inv["projectEnablesOverridingYou"]]
    keep: set[str] = set(profile["claude"]["enabledPlugins"])
    report = {"claudeHome": str(claude_home), "inventory": inv, "issues": issues,
              "toDisable": sorted(set(inv["enabledPlugins"]) - keep),
              "missingFromKeepSet": sorted(keep - set(inv["enabledPlugins"]))}
    print(json.dumps(report, indent=2))
    return 1 if issues else 0


def run_change(args: argparse.Namespace, claude_home: Path, profile: dict, apply: bool) -> int:
    path: Path = claude_home / "settings.json"
    settings: dict = load_json(path)
    usage: dict[str, int] = read_usage(claude_home, args.days)
    result: dict = tiers.tier_plan(settings, profile, synced_plugins(claude_home), usage, args.tier)
    planned: dict = result["settings"]
    changes: list[str] = diff_settings(settings, planned, result["protected"])
    print("\n".join(changes) if changes else "Already matches the profile.")
    if not apply or not changes:
        return 0
    saved: str = str(backup(path)) if path.exists() else "none (no settings.json existed)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(planned, indent=2) + "\n", encoding="utf-8")
    print(f"Applied. Backup: {saved}. Restart Claude Code to load the change.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["audit", "plan", "apply"])
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--claude-home", type=Path, help="Override, e.g. /mnt/c/Users/<you>/.claude from WSL")
    parser.add_argument("--tier", choices=list(tiers.TIERS), help="Default: profile claude.defaultTier")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Usage window for the usage counts")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Repo to check for project overrides")
    args = parser.parse_args()
    profile: dict = load_json(args.profile)
    claude_home: Path = args.claude_home or args.home / ".claude"
    if args.command == "audit":
        return run_audit(args, claude_home, profile)
    return run_change(args, claude_home, profile, apply=args.command == "apply")


if __name__ == "__main__":
    sys.exit(main())
