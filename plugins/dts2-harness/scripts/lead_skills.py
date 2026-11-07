#!/usr/bin/env python3
"""Replicate the orchestrator's current dt plugin and skill list onto another agent.

Claude is the source. Codex reads its own plugin cache under ~/.codex, so a lead
switch used to leave it on an older dts2-harness install. `gaps` names agents that
lack the current plugin, marketplace repo, or skill names. `sync` writes that
snapshot into the agent's backend and turns the legacy plugin ids off. It does
not ask, and it does not change Claude's own install.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
MARKETPLACE: Final[str] = "dts2"
SOURCE_AGENT: Final[str] = "claude"
LEGACY_NAMES: Final[tuple[str, ...]] = tuple(
    plugin_id.split("@", 1)[0] for plugin_id in state_io.LEGACY_HARNESS_PLUGINS
)
SKIP_DIRS: Final[set[str]] = {"__pycache__", ".git", ".pytest_cache", "tests", "evals"}
AGENT_NAME: Final[str] = r"^[a-z0-9][a-z0-9-]{0,31}$"


def plugin_identity(plugin_root: Path) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    name: str = str(meta["name"])
    repo: str = str(meta.get("repository") or "")
    return {
        "name": name,
        "plugin": f"{name}@{MARKETPLACE}",
        "version": str(meta["version"]),
        "repo": repo,
        "source": github_source(repo),
        "skills": skill_names(plugin_root / "skills"),
    }


def github_source(repo: str) -> str:
    marker: str = "github.com/"
    if marker in repo:
        return repo.split(marker, 1)[1].strip("/")
    return repo


def skill_names(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    names: list[str] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "SKILL.md").is_file():
            names.append(path.name)
    return names


def user_home_skills(home: Path) -> list[str]:
    return skill_names(home / ".claude" / "skills")


def agent_root(home: Path, agent: str) -> Path:
    if agent == "codex":
        override: str = os.environ.get("DTS2_CODEX_HOME", "")
        return Path(override) if override else home / ".codex"
    if agent == SOURCE_AGENT:
        return home / ".claude"
    return home / ".dts2" / "agent-plugins" / agent


def cache_dir(root: Path, name: str, version: str) -> Path:
    return root / "plugins" / "cache" / MARKETPLACE / name / version


def read_plugin_json(path: Path) -> dict[str, Any] | None:
    target: Path = path / ".claude-plugin" / "plugin.json"
    if not target.is_file():
        return None
    try:
        loaded: Any = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def installed_copies(root: Path) -> list[dict[str, Any]]:
    base: Path = root / "plugins" / "cache" / MARKETPLACE
    found: list[dict[str, Any]] = []
    if not base.is_dir():
        return found
    for plugin_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for version_dir in sorted(p for p in plugin_dir.iterdir() if p.is_dir()):
            meta: dict[str, Any] | None = read_plugin_json(version_dir)
            if meta is None:
                continue
            found.append({
                "folder": plugin_dir.name,
                "name": str(meta.get("name") or plugin_dir.name),
                "version": str(meta.get("version") or version_dir.name),
                "repo": str(meta.get("repository") or ""),
                "skills": skill_names(version_dir / "skills"),
                "path": version_dir,
            })
    return found


def current_copy(copies: list[dict[str, Any]], identity: dict[str, Any]) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = [c for c in copies if c["name"] == identity["name"] and c["version"] == identity["version"]]
    return matches[-1] if matches else None


def gap_for(agent: str, home: Path, identity: dict[str, Any], orchestrator_skills: list[str]) -> dict[str, Any] | None:
    if agent == SOURCE_AGENT:
        return None
    root: Path = agent_root(home, agent)
    copies: list[dict[str, Any]] = installed_copies(root)
    current: dict[str, Any] | None = current_copy(copies, identity)
    present: set[str] = set(current["skills"]) if current else set()
    present.update(skill_names(root / "skills"))
    missing: list[str] = [name for name in orchestrator_skills if name not in present]
    legacy: list[str] = sorted({c["name"] for c in copies if c["name"] in LEGACY_NAMES or c["folder"] in LEGACY_NAMES})
    if current is None:
        installed: str = ", ".join(f"{copy['name']} {copy['version']}" for copy in copies) or "not installed"
        reason = f"plugin is {installed}, not {identity['plugin']} {identity['version']}"
    elif current["repo"] and identity["repo"] and current["repo"] != identity["repo"]:
        reason = f"marketplace repo is {current['repo']}, not {identity['repo']}"
    elif missing:
        reason = "missing skills: " + ", ".join(missing)
    else:
        return None
    return {"agent": agent, "reason": reason, "missing_skills": missing, "legacy": legacy}


def orchestrator_skill_list(plugin_root: Path, home: Path) -> list[str]:
    identity: dict[str, Any] = plugin_identity(plugin_root)
    return list(dict.fromkeys([*identity["skills"], *user_home_skills(home)]))


def ignore_copy(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS or name.endswith(".pyc")}


def copy_plugin(plugin_root: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plugin_root, dest, ignore=ignore_copy)
    overlay: Path = dest / ".codex-plugin"
    overlay.mkdir(exist_ok=True)
    name: str = str(plugin_identity(plugin_root)["name"])
    (overlay / "plugin.json").write_text(json.dumps({"name": name}) + "\n", encoding="utf-8")


def copy_user_skills(home: Path, root: Path) -> None:
    source: Path = home / ".claude" / "skills"
    if not source.is_dir():
        return
    for name in skill_names(source):
        dest: Path = root / "skills" / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source / name, dest, ignore=ignore_copy)


def upsert_table(text: str, header: str, values: dict[str, str]) -> str:
    lines: list[str] = text.splitlines()
    start: int | None = None
    end: int = len(lines)
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            for follow in range(index + 1, len(lines)):
                if lines[follow].startswith("["):
                    end = follow
                    break
            break
    body: list[str] = [f"{key} = {value}" for key, value in values.items()]
    if start is None:
        addition: list[str] = ([] if not lines or lines[-1] == "" else [""]) + [header, *body]
        merged: list[str] = [*lines, *addition]
    else:
        merged = [*lines[: start + 1], *body, *lines[end:]]
    rendered: str = "\n".join(merged)
    return rendered + ("\n" if rendered else "")


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_config(root: Path, identity: dict[str, Any]) -> None:
    path: Path = root / "config.toml"
    text: str = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = upsert_table(text, f'[plugins."{identity["plugin"]}"]', {"enabled": "true"})
    for legacy in state_io.LEGACY_HARNESS_PLUGINS:
        text = upsert_table(text, f'[plugins."{legacy}"]', {"enabled": "false"})
    if identity["source"]:
        text = upsert_table(text, f"[marketplaces.{MARKETPLACE}]", {
            "source_type": quote("git"),
            "source": quote(str(identity["source"])),
            "ref": quote("main"),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_manifest(home: Path, agent: str, identity: dict[str, Any], skills: list[str]) -> None:
    folder: Path = home / ".dts2" / "lead-skills"
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "agent": agent,
        "plugin": identity["plugin"],
        "version": identity["version"],
        "repo": identity["repo"],
        "skills": skills,
        "synced_from": SOURCE_AGENT,
    }
    (folder / f"{agent}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sync_agent(agent: str, home: Path, plugin_root: Path) -> dict[str, Any]:
    if agent == SOURCE_AGENT:
        return {"agent": agent, "updated": False, "reason": "orchestrator"}
    identity: dict[str, Any] = plugin_identity(plugin_root)
    skills: list[str] = orchestrator_skill_list(plugin_root, home)
    before: dict[str, Any] | None = gap_for(agent, home, identity, skills)
    root: Path = agent_root(home, agent)
    if before is None and cache_dir(root, identity["name"], identity["version"]).is_dir():
        return {"agent": agent, "updated": False, "reason": "already current"}
    copy_plugin(plugin_root, cache_dir(root, identity["name"], identity["version"]))
    copy_user_skills(home, root)
    write_config(root, identity)
    write_manifest(home, agent, identity, skills)
    return {"agent": agent, "updated": True, "plugin": identity["plugin"], "version": identity["version"], "skills": skills}


def valid_agent(name: str) -> bool:
    return re.fullmatch(AGENT_NAME, name) is not None


def parse_agents(text: str) -> list[str]:
    names: list[str] = [part.strip() for part in text.split(",") if part.strip()]
    bad: list[str] = [name for name in names if not valid_agent(name)]
    if bad or not names:
        raise SystemExit(f"agent names must be lowercase kebab-case, got {text!r}")
    return list(dict.fromkeys(names))


def main(argv: list[str] | None = None) -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Match an agent's skills to the orchestrator")
    parser.add_argument("command", choices=("gaps", "sync"))
    parser.add_argument("--agents", required=True, help="comma-separated agent names")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--plugin-root", type=Path, default=PLUGIN_ROOT)
    args: argparse.Namespace = parser.parse_args(argv)
    home: Path = args.home
    plugin_root: Path = args.plugin_root
    agents: list[str] = parse_agents(args.agents)
    identity: dict[str, Any] = plugin_identity(plugin_root)
    skills: list[str] = orchestrator_skill_list(plugin_root, home)
    if args.command == "gaps":
        behind: list[dict[str, Any]] = []
        for agent in agents:
            row: dict[str, Any] | None = gap_for(agent, home, identity, skills)
            if row is not None:
                behind.append(row)
        json.dump({"orchestrator": {**identity, "skills": skills}, "behind": behind}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    results: list[dict[str, Any]] = [sync_agent(agent, home, plugin_root) for agent in agents]
    json.dump({"updated": results}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
