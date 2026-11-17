#!/usr/bin/env python3
"""One context scrub for every rostered agent: find duplicate plugins, skills, agents and MCP servers.

inventory : list each rostered agent's plugins, skills, agents and MCP servers from its home config
plan      : find duplicates and print ONE plan (keep one copy, disable the others), same rules for every agent
apply     : dry run by default; with --yes back up each touched config file, then disable the planned copies

Inspected agents: claude (Claude Code), codex, cursor. Any other roster name is reported as not inspectable.
Rules: a copy listed in .harness/keep.yaml wins, then the marketplace-managed copy, then the first one found.
Copies in keep.yaml are never disabled. Disable only: a flag is flipped, a list entry is appended or a file is moved
to a sibling `<folder>-disabled` folder. Nothing is deleted and keep.yaml is never written.
Duplicates are found inside one agent; `--cross-agent` also pairs copies across agents (off by default, because the
same server in two agents is two separate contexts, not one wasted one).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import state_io  # noqa: E402
from state_io import atomic_write  # noqa: E402

HOME_ENV: Final[str] = "DTS2_HOME"
CATEGORIES: Final[tuple[str, ...]] = ("plugins", "skills", "agents", "mcp")
DEFAULT_ROSTER: Final[tuple[str, ...]] = ("claude",)
API_SUFFIX: Final[str] = "-api"
SYNCED_SUFFIX: Final[str] = "@synced"
DISABLED_SUFFIX: Final[str] = "-disabled"
BACKUP_INFIX: Final[str] = ".bak-"
STAMP_FORMAT: Final[str] = "%Y%m%d-%H%M%S"
INSTALL_RECORDS: Final[str] = "installed_plugins.json"
SYNCED_DIR: Final[str] = "synced"
MCP_DISABLE_KEY: Final[str] = "disabledMcpjsonServers"
KEEP_PLUGINS_KEY: Final[str] = "plugins"
NOT_INSPECTABLE: Final[str] = "not inspectable: no known config location for this agent"
CODEX_HEADER: Final[re.Pattern[str]] = re.compile(r'^\[(mcp_servers|plugins)\.(?:"([^"]+)"|([\w-]+))\]\s*$')
TOML_VALUE: Final[re.Pattern[str]] = re.compile(r"^(\w+)\s*=\s*(.+?)\s*$")
TOML_STRING: Final[re.Pattern[str]] = re.compile(r'"([^"]*)"')
OP_PLUGIN_OFF: Final[str] = "plugin-off"
OP_LIST_APPEND: Final[str] = "list-append"
OP_JSON_FLAG: Final[str] = "json-flag"
OP_TOML_OFF: Final[str] = "toml-off"
OP_MOVE: Final[str] = "move"
OP_MANUAL: Final[str] = "manual"


@dataclass
class Item:
    agent: str
    category: str
    name: str
    source: str
    key: str = ""
    target: str = ""
    managed: bool = False
    enabled: bool = True
    op: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.key = self.key or normalize(self.name)


def normalize(name: str) -> str:
    """Lower-case name without a marketplace suffix or file extension."""
    return Path(name.split("@", 1)[0]).stem.lower() if name.endswith((".md", ".toml", ".mdc")) else name.split("@", 1)[0].lower()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def children(folder: Path, pattern: str = "*") -> list[Path]:
    return sorted(folder.glob(pattern)) if folder.is_dir() else []


def move_op(path: Path) -> dict[str, Any]:
    return {"kind": OP_MOVE, "path": str(path), "to": str(path.parent.with_name(path.parent.name + DISABLED_SUFFIX) / path.name)}


def manual_op(note: str) -> dict[str, Any]:
    return {"kind": OP_MANUAL, "note": note}


def mcp_target(spec: Any) -> str:
    if not isinstance(spec, dict):
        return ""
    command: str = " ".join([str(spec.get("command", "")), *map(str, spec.get("args") or [])]).strip()
    return command or str(spec.get("url", ""))


# ---- Claude Code --------------------------------------------------------------------------------------------------

def plugin_root(claude_home: Path, plugin_id: str, records: dict[str, Any]) -> Path:
    name, _, market = plugin_id.partition("@")
    record: Any = (records.get(plugin_id) or [{}])[0]
    return claude_home / "plugins" / "cache" / market / name / str(record.get("version", ""))


def claude_plugin_items(claude_home: Path, settings: dict[str, Any]) -> list[Item]:
    path: Path = claude_home / "settings.json"
    plugins: dict[str, Any] = settings.get("enabledPlugins") or {}
    return [Item("claude", "plugins", pid, pid, managed=not pid.endswith(SYNCED_SUFFIX), enabled=bool(on),
                 op={"kind": OP_PLUGIN_OFF, "file": str(path), "id": pid}) for pid, on in sorted(plugins.items())]


def claude_bundled_items(claude_home: Path, settings: dict[str, Any]) -> list[Item]:
    records: dict[str, Any] = load_json(claude_home / "plugins" / INSTALL_RECORDS).get("plugins") or {}
    found: list[Item] = []
    for pid, on in sorted((settings.get("enabledPlugins") or {}).items()):
        root: Path = plugin_root(claude_home, pid, records)
        note: dict[str, Any] = manual_op(f"disable plugin {pid} (it ships this copy)")
        found += [Item("claude", "skills", p.name, pid, managed=True, op=note) for p in children(root / "skills") if on and p.is_dir()]
        found += [Item("claude", "agents", p.stem, pid, managed=True, op=note) for p in children(root / "agents", "**/*.md") if on]
    return found


def claude_file_items(claude_home: Path) -> list[Item]:
    skills: list[Path] = [p for p in children(claude_home / "skills") if p.name != SYNCED_DIR]
    agents: list[Path] = children(claude_home / "agents", "*.md")
    return ([Item("claude", "skills", p.name, str(p), op=move_op(p)) for p in skills]
            + [Item("claude", "agents", p.stem, str(p), op=move_op(p)) for p in agents])


def claude_mcp_items(project: Path) -> list[Item]:
    servers: dict[str, Any] = load_json(project / ".mcp.json").get("mcpServers") or {}
    settings_path: Path = project / ".claude" / "settings.json"
    off: list[str] = load_json(settings_path).get(MCP_DISABLE_KEY) or []
    return [Item("claude", "mcp", name, str(project / ".mcp.json"), target=mcp_target(spec), enabled=name not in off,
                 op={"kind": OP_LIST_APPEND, "file": str(settings_path), "key": MCP_DISABLE_KEY, "value": name})
            for name, spec in sorted(servers.items())]


def collect_claude(home: Path, claude_home: Path, project: Path) -> list[Item]:
    settings: dict[str, Any] = load_json(claude_home / "settings.json")
    return (claude_plugin_items(claude_home, settings) + claude_bundled_items(claude_home, settings)
            + claude_file_items(claude_home) + claude_mcp_items(project))


# ---- Codex --------------------------------------------------------------------------------------------------------

def parse_codex_sections(text: str) -> dict[tuple[str, str], dict[str, str]]:
    """{(kind, name): {key: raw value}} for `[mcp_servers.x]` and `[plugins."x@m"]` tables."""
    sections: dict[tuple[str, str], dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped: str = line.strip()
        header = CODEX_HEADER.match(stripped)
        if header:
            current = sections.setdefault((header.group(1), header.group(2) or header.group(3)), {})
        elif stripped.startswith("["):
            current = None
        elif current is not None and (pair := TOML_VALUE.match(stripped)):
            current[pair.group(1)] = pair.group(2)
    return sections


def codex_target(table: dict[str, str]) -> str:
    parts: list[str] = TOML_STRING.findall(table.get("command", "")) + TOML_STRING.findall(table.get("args", ""))
    return " ".join(parts) or (TOML_STRING.findall(table.get("url", "")) or [""])[0]


def codex_config_items(config: Path) -> list[Item]:
    if not config.exists():
        return []
    items: list[Item] = []
    for (kind, name), table in parse_codex_sections(config.read_text(encoding="utf-8")).items():
        op: dict[str, Any] = {"kind": OP_TOML_OFF, "file": str(config), "section": kind, "name": name}
        enabled: bool = table.get("enabled", "true") != "false"
        if kind == "plugins":
            items.append(Item("codex", "plugins", name, name, managed=True, enabled=enabled, op=op))
        else:
            items.append(Item("codex", "mcp", name, str(config), target=codex_target(table), enabled=enabled, op=op))
    return items


def collect_codex(home: Path, claude_home: Path, project: Path) -> list[Item]:
    root: Path = home / ".codex"
    skills: list[Item] = [Item("codex", "skills", p.name, str(p), op=move_op(p)) for p in children(root / "skills") if p.is_dir()]
    agents: list[Item] = [Item("codex", "agents", p.stem, str(p), op=move_op(p)) for p in children(root / "agents", "*.toml")]
    return codex_config_items(root / "config.toml") + skills + agents


# ---- Cursor -------------------------------------------------------------------------------------------------------

def cursor_mcp_items(path: Path) -> list[Item]:
    servers: dict[str, Any] = load_json(path).get("mcpServers") or {}
    return [Item("cursor", "mcp", name, str(path), target=mcp_target(spec), enabled=not (isinstance(spec, dict) and spec.get("disabled")),
                 op={"kind": OP_JSON_FLAG, "file": str(path), "name": name}) for name, spec in sorted(servers.items())]


def collect_cursor(home: Path, claude_home: Path, project: Path) -> list[Item]:
    rules: list[Path] = [p for p in children(project / ".cursor" / "rules") if p.is_file()]
    skills: list[Path] = [p for p in children(home / ".cursor" / "skills")]
    agents: list[Path] = children(home / ".cursor" / "agents", "*.md")
    return (cursor_mcp_items(home / ".cursor" / "mcp.json") + cursor_mcp_items(project / ".cursor" / "mcp.json")
            + [Item("cursor", "skills", p.stem if p.is_file() else p.name, str(p), op=move_op(p)) for p in rules + skills]
            + [Item("cursor", "agents", p.stem, str(p), op=move_op(p)) for p in agents])


COLLECTORS: Final[dict[str, Any]] = {"claude": collect_claude, "codex": collect_codex, "cursor": collect_cursor}


def base_agent(name: str) -> str:
    """`codex-api` reads the same home as `codex`."""
    return name[: -len(API_SUFFIX)] if name.endswith(API_SUFFIX) else name


def inventory(roster: list[str], home: Path, claude_home: Path, project: Path) -> tuple[list[Item], list[str]]:
    items: list[Item] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for name in roster:
        base: str = base_agent(name)
        if base not in COLLECTORS:
            skipped.append(name)
        elif base not in seen:
            seen.add(base)
            items += COLLECTORS[base](home, claude_home, project)
    return items, skipped


# ---- keep.yaml and the roster ---------------------------------------------------------------------------------------

def keep_names(project: Path) -> dict[str, set[str]]:
    """Names per category from .harness/keep.yaml (plugins, skills, agents, mcp; strings or `name:` entries).

    A plugin entry with a marketplace (`name@market`) protects only that id; a bare name protects every copy."""
    path: Path = project / state_io.KEEP_REL
    data: Any = miniyaml.parse(path.read_text(encoding="utf-8")) if path.exists() else {}
    keep: dict[str, set[str]] = {category: set() for category in CATEGORIES}
    for category in CATEGORIES:
        entries: Any = data.get(category) if isinstance(data, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            raw: Any = entry.get("name") if isinstance(entry, dict) else entry
            if raw:
                keep[category].add(str(raw).lower() if category == KEEP_PLUGINS_KEY and "@" in str(raw) else normalize(str(raw)))
    return keep


def roster_names(project: Path, given: str | None) -> list[str]:
    if given:
        return [n.strip() for n in given.split(",") if n.strip()]
    config: Path = project / state_io.HARNESS / "config.yaml"
    data: Any = miniyaml.parse(config.read_text(encoding="utf-8")) if config.exists() else {}
    entries: Any = data.get("roster") if isinstance(data, dict) else None
    names: list[str] = [str(e["name"]) for e in entries if isinstance(e, dict) and e.get("name")
                        and str(e.get("included", "true")).lower() != "false"] if isinstance(entries, list) else []
    return names or list(DEFAULT_ROSTER)


# ---- plan -----------------------------------------------------------------------------------------------------------

def group_items(items: list[Item], cross_agent: bool) -> list[list[Item]]:
    """Duplicate groups: copies sharing a name, or (MCP) a command target, in one agent (or all with cross_agent)."""
    live: list[Item] = [i for i in items if i.enabled]
    parent: list[int] = list(range(len(live)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple[str, ...], int] = {}
    for index, item in enumerate(live):
        scope: str = "" if cross_agent else item.agent
        for tag, value in (("name", item.key), ("target", item.target)):
            if value:
                other: int = seen.setdefault((item.category, scope, tag, value), index)
                parent[find(index)] = find(other)
    groups: dict[int, list[Item]] = {}
    for index, item in enumerate(live):
        groups.setdefault(find(index), []).append(item)
    return [g for g in groups.values() if len(g) > 1]


def is_kept(item: Item, keep: dict[str, set[str]]) -> bool:
    return item.key in keep[item.category] or (item.category == KEEP_PLUGINS_KEY and item.source.lower() in keep[item.category])


def plan_group(group: list[Item], keep: dict[str, set[str]]) -> dict[str, Any]:
    ordered: list[Item] = sorted(group, key=lambda i: (not is_kept(i, keep), not i.managed))
    winner: Item = ordered[0]
    losers: list[Item] = ordered[1:]
    return {"category": winner.category, "name": winner.key, "keep": asdict(winner),
            "disable": [asdict(i) for i in losers if not is_kept(i, keep)],
            "protected": [asdict(i) for i in losers if is_kept(i, keep)]}


def build_plan(roster: list[str], home: Path, claude_home: Path, project: Path, cross_agent: bool) -> dict[str, Any]:
    items, skipped = inventory(roster, home, claude_home, project)
    keep: dict[str, set[str]] = keep_names(project)
    groups: list[dict[str, Any]] = [plan_group(g, keep) for g in group_items(items, cross_agent)]
    return {"roster": roster, "notInspectable": [{"agent": a, "note": NOT_INSPECTABLE} for a in skipped],
            "crossAgent": cross_agent, "groups": groups,
            "disableCount": sum(len(g["disable"]) for g in groups)}


def describe(item: dict[str, Any]) -> str:
    return f"{item['agent']}:{item['source']}"


def plan_table(plan: dict[str, Any]) -> str:
    lines: list[str] = [f"Context scrub plan for: {', '.join(plan['roster'])}"]
    lines += [f"  {n['agent']}: {n['note']}" for n in plan["notInspectable"]]
    if not plan["groups"]:
        return "\n".join(lines + ["No duplicates found."])
    lines.append("category | name | keep | disable")
    for group in plan["groups"]:
        gone: str = "; ".join(f"{describe(i)} [{i['op'].get('kind')}]" for i in group["disable"]) or "(nothing; copies are in keep.yaml)"
        lines.append(f"{group['category']} | {group['name']} | {describe(group['keep'])} | {gone}")
    return "\n".join(lines + [f"{plan['disableCount']} copies to disable. Nothing is deleted."])


# ---- apply ----------------------------------------------------------------------------------------------------------

def backup_file(path: Path, stamp: str) -> Path:
    target: Path = path.with_name(path.name + BACKUP_INFIX + stamp)
    shutil.copy2(path, target)
    return target


def edit_json(path: Path, ops: list[dict[str, Any]]) -> None:
    data: dict[str, Any] = load_json(path)
    for op in ops:
        if op["kind"] == OP_PLUGIN_OFF:
            data.setdefault("enabledPlugins", {})[op["id"]] = False
        elif op["kind"] == OP_LIST_APPEND:
            values: list[Any] = data.setdefault(op["key"], [])
            values += [op["value"]] if op["value"] not in values else []
        elif op["kind"] == OP_JSON_FLAG:
            data["mcpServers"][op["name"]]["disabled"] = True
    atomic_write(path, json.dumps(data, indent=2) + "\n")


def toml_disable(text: str, section: str, name: str) -> str:
    lines: list[str] = text.splitlines(keepends=True)
    start: int | None = next((i for i, line in enumerate(lines) if (m := CODEX_HEADER.match(line.strip()))
                              and m.group(1) == section and (m.group(2) or m.group(3)) == name), None)
    if start is None:
        return text
    end: int = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    flag: int | None = next((i for i in range(start + 1, end) if re.match(r"\s*enabled\s*=", lines[i])), None)
    if flag is None:
        lines.insert(start + 1, "enabled = false\n")
    else:
        lines[flag] = "enabled = false\n"
    return "".join(lines)


def edit_toml(path: Path, ops: list[dict[str, Any]]) -> None:
    text: str = path.read_text(encoding="utf-8")
    for op in ops:
        text = toml_disable(text, op["section"], op["name"])
    atomic_write(path, text)


def move_aside(op: dict[str, Any]) -> bool:
    source, target = Path(op["path"]), Path(op["to"])
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return True


def apply_plan(plan: dict[str, Any], stamp: str) -> dict[str, Any]:
    ops: list[dict[str, Any]] = [i["op"] for g in plan["groups"] for i in g["disable"]]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for op in ops:
        if "file" in op:
            by_file.setdefault(op["file"], []).append(op)
    backups: list[str] = []
    for file, file_ops in sorted(by_file.items()):
        path: Path = Path(file)
        if path.exists():
            backups.append(str(backup_file(path, stamp)))
        path.parent.mkdir(parents=True, exist_ok=True)
        (edit_toml if file_ops[0]["kind"] == OP_TOML_OFF else edit_json)(path, file_ops)
    moved: list[str] = [op["to"] for op in ops if op["kind"] == OP_MOVE and move_aside(op)]
    manual: list[str] = [op["note"] for op in ops if op["kind"] == OP_MANUAL]
    return {"backups": backups, "moved": moved, "manual": manual}


# ---- CLI ------------------------------------------------------------------------------------------------------------

def inventory_report(roster: list[str], home: Path, claude_home: Path, project: Path) -> dict[str, Any]:
    items, skipped = inventory(roster, home, claude_home, project)
    agents: dict[str, Any] = {}
    for item in items:
        bucket: dict[str, list[dict[str, Any]]] = agents.setdefault(item.agent, {c: [] for c in CATEGORIES})
        bucket[item.category].append({"name": item.name, "source": item.source, "enabled": item.enabled})
    return {"roster": roster, "agents": agents, "notInspectable": [{"agent": a, "note": NOT_INSPECTABLE} for a in skipped]}


def inventory_table(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for agent, buckets in report["agents"].items():
        lines.append(f"{agent}: " + ", ".join(f"{len(buckets[c])} {c}" for c in CATEGORIES))
    return "\n".join(lines + [f"{n['agent']}: {n['note']}" for n in report["notInspectable"]])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["inventory", "plan", "apply"])
    parser.add_argument("--roster", help="comma-separated agent names; default: the roster in .harness/config.yaml, else claude")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get(HOME_ENV) or Path.home()))
    parser.add_argument("--claude-home", type=Path, help="Default: <home>/.claude")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--cross-agent", action="store_true", help="also pair duplicates across agents")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--yes", action="store_true", help="apply: make the changes (without it, a dry run)")
    args = parser.parse_args()
    claude_home: Path = args.claude_home or args.home / ".claude"
    roster: list[str] = roster_names(args.project, args.roster)
    if args.command == "inventory":
        report: dict[str, Any] = inventory_report(roster, args.home, claude_home, args.project)
        print(json.dumps(report, indent=2) if args.json else inventory_table(report))
        return 0
    plan: dict[str, Any] = build_plan(roster, args.home, claude_home, args.project, args.cross_agent)
    if args.command == "plan" or not args.yes:
        print(json.dumps(plan, indent=2) if args.json else plan_table(plan) + ("\nDry run: pass --yes to apply." if args.command == "apply" else ""))
        return 0
    result: dict[str, Any] = apply_plan(plan, datetime.now().strftime(STAMP_FORMAT))
    print(json.dumps({**result, "disabled": plan["disableCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
