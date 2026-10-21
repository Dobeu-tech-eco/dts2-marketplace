"""Tier, redundancy and protection logic for machine-prep.py. Pure functions; no I/O except reading plugin folders."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

SYNCED_SUFFIX: Final[str] = "@synced"
SYNC_KEY: Final[str] = "syncClaudeAiPlugins"
SKILLS_SYNC_KEY: Final[str] = "syncClaudeAiSkills"
REQUIRED_PREFERENCE: Final[str] = "required"
DEFAULT_TIER: Final[str] = "standard"
DEFAULT_TOP_N: Final[int] = 5
TIERS: Final[tuple[str, ...]] = ("light", "standard", "strict")
PROTECTED_NOTE: Final[str] = "(requiredByHarness)"
SkillMap: Final = dict[str, list[str]]


def required_by_harness(plugin_id: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(plugin_id, p) for p in patterns)


def plugin_usage(plugin_id: str, usage: dict[str, int]) -> int:
    return usage.get(plugin_id.partition("@")[0], 0)


def agent_names(root: Path) -> list[str]:
    folder: Path = root / "agents"
    return sorted(p.name for p in folder.glob("**/*.md")) if folder.exists() else []


def agents_hash(names: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def pick_keep(ids: list[str], usage: dict[str, int]) -> str:
    return min(ids, key=lambda i: (-plugin_usage(i, usage), i))


def redundant_packs(synced: list[dict[str, str]], usage: dict[str, int]) -> list[dict[str, object]]:
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for plugin in synced:
        names: list[str] = agent_names(Path(plugin["root"]))
        if names:
            groups[agents_hash(names)].append((plugin["id"], len(names)))
    return [{"agentsHash": h, "plugins": sorted(i for i, _ in m), "agentCount": m[0][1],
             "keep": pick_keep([i for i, _ in m], usage)}
            for h, m in sorted(groups.items()) if len(m) > 1]


def skill_names(root: Path) -> list[str]:
    folder: Path = root / "skills"
    return sorted(p.parent.name for p in folder.glob("*/SKILL.md")) if folder.exists() else []


def duplicate_skills(roots: dict[str, Path]) -> SkillMap:
    seen: SkillMap = defaultdict(list)
    for plugin_id, root in sorted(roots.items()):
        for name in skill_names(root):
            seen[name].append(plugin_id)
    return {name: ids for name, ids in sorted(seen.items()) if len(ids) > 1}


def plan_marketplace(current: dict[str, bool], keep: set[str], add_missing: bool = True) -> dict[str, bool]:
    planned: dict[str, bool] = {k: (k in keep) for k in current if not k.endswith(SYNCED_SUFFIX)}
    for key in keep if add_missing else set():
        planned.setdefault(key, True)
    return planned


def switchable_ids(synced: list[dict[str, str]]) -> list[str]:
    return [s["id"] for s in synced if s["preference"] != REQUIRED_PREFERENCE]


def top_synced(synced: list[dict[str, str]], usage: dict[str, int], count: int) -> set[str]:
    used: list[str] = [i for i in switchable_ids(synced) if plugin_usage(i, usage) > 0]
    return set(sorted(used, key=lambda i: (-plugin_usage(i, usage), i))[:count])


def light_plugins(current: dict[str, bool], rules: dict, synced: list[dict[str, str]],
                  usage: dict[str, int]) -> dict[str, bool]:
    keep: set[str] = set(rules["enabledPlugins"]) | set(rules.get("keepSyncedPlugins", []))
    ids: set[str] = set(switchable_ids(synced)) | {i for i in current if not i.endswith(SYNCED_SUFFIX)}
    idle: list[str] = [i for i in sorted(ids) if plugin_usage(i, usage) == 0 and i not in keep]
    return {**current, **{i: False for i in idle}}


def standard_plugins(current: dict[str, bool], rules: dict, synced: list[dict[str, str]],
                     usage: dict[str, int]) -> dict[str, bool]:
    count: int = int(rules.get("keepSyncedTopN", DEFAULT_TOP_N))
    kept: set[str] = top_synced(synced, usage, count) | set(rules.get("keepSyncedPlugins", []))
    planned: dict[str, bool] = plan_marketplace(current, set(rules["enabledPlugins"]))
    kept_flags: dict[str, bool] = {i: (i in kept) for i in switchable_ids(synced)}
    kept_current: dict[str, bool] = {k: v for k, v in current.items() if k.endswith(SYNCED_SUFFIX)}
    return {**planned, **kept_current, **kept_flags}


def strict_plugins(current: dict[str, bool], rules: dict, synced: list[dict[str, str]]) -> dict[str, bool]:
    planned: dict[str, bool] = plan_marketplace(current, set(rules["enabledPlugins"]))
    kept_current: dict[str, bool] = {k: v for k, v in current.items() if k.endswith(SYNCED_SUFFIX)}
    per_id: dict[str, bool] = {i: False for i in switchable_ids(synced)}
    return {**planned, **kept_current, **per_id}


def required_synced(synced: list[dict[str, str]], patterns: list[str]) -> bool:
    return any(required_by_harness(s["id"], patterns) for s in synced)


def protect(plugins: dict[str, bool], synced: list[dict[str, str]], patterns: list[str],
            sync_off: bool) -> tuple[dict[str, bool], list[str]]:
    synced_ids: list[str] = [s["id"] for s in synced]
    candidates: set[str] = {k for k, v in plugins.items() if v is False} | (set(synced_ids) if sync_off else set())
    guarded: list[str] = sorted(i for i in candidates if required_by_harness(i, patterns))
    return {**plugins, **{i: True for i in guarded}}, guarded


def tier_plan(settings: dict, profile: dict, synced: list[dict[str, str]],
              usage: dict[str, int], tier: str | None = None) -> dict:
    """Return {"settings": planned settings, "protected": [ids kept on for requiredByHarness], "tier": name}.

    Strict turns syncClaudeAiPlugins off unless a requiredByHarness plugin is synced; then it
    disables the other synced plugins one by one so the required ones still load."""
    rules: dict = profile["claude"]
    patterns: list[str] = profile.get("requiredByHarness", [])
    chosen: str = tier or rules.get("defaultTier", DEFAULT_TIER)
    current: dict[str, bool] = settings.get("enabledPlugins") or {}
    plugins: dict[str, bool]
    extra: dict[str, bool] = {}
    sync_off: bool = False
    if chosen == "light":
        plugins = light_plugins(current, rules, synced, usage)
    elif chosen == "standard":
        plugins = standard_plugins(current, rules, synced, usage)
    else:
        plugins = strict_plugins(current, rules, synced)
        sync_off = not required_synced(synced, patterns)
        extra = {SKILLS_SYNC_KEY: False, **({SYNC_KEY: False} if sync_off else {})}
        extra.update({SYNC_KEY: True} if not sync_off and settings.get(SYNC_KEY) is False else {})
    final, guarded = protect(plugins, synced, patterns, sync_off)
    return {"settings": {**settings, **extra, "enabledPlugins": final}, "protected": guarded, "tier": chosen}
