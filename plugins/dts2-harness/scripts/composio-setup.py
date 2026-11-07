#!/usr/bin/env python3
"""Set up the hosted-tools (composio) integration and retire local tools it makes redundant.

status   : CLI, login, plugin and MCP-server state plus the saved decision and tool map (read-only)
decide   : record the user's one-time answer (account yes/no, always use, connection kind)
map      : cache the toolkit list and the connected toolkits, from the CLI or from a JSON file
           (connected accounts fall back to `composio connections list` when the dev project is not set up)
overlap  : list enabled plugins, MCP servers and user skills that duplicate a connected toolkit
disable  : turn such items off, always with a backup; skills are archived, never deleted

State lives at user level (DTS2_HOME, else ~/.dts2) and never holds credentials: the CLI keeps those in its own
directory, which this script only checks for existence. Every subcommand prints one JSON object."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
from state_io import atomic_write  # noqa: E402

ENV_HOME: Final[str] = "DTS2_HOME"
ENV_BIN: Final[str] = "DTS2_COMPOSIO_BIN"
ENV_CACHE: Final[str] = "COMPOSIO_CACHE_DIR"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
DECISION_FILE: Final[str] = "composio.json"
MAP_FILE: Final[str] = "composio-tools.json"
CREDENTIAL_DIR: Final[str] = ".composio"
BIN_NAME: Final[str] = "composio"
PLUGIN_PREFIX: Final[str] = "composio@"
SERVER_WORD: Final[str] = "composio"
ENCODING: Final[str] = "utf-8"
ISO_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
STAMP_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"
SCHEMA_VERSION: Final[int] = 1
DEFAULT_TIMEOUT: Final[int] = 60
WSL_TIMEOUT: Final[int] = 10
EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_BAD_INPUT: Final[int] = 2
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
PLUGIN_ROOT: Final[Path] = SCRIPT_DIR.parent
OVERLAP_PROFILE: Final[Path] = PLUGIN_ROOT / "profiles" / "composio-overlap.json"
DEFAULT_PROFILE: Final[Path] = PLUGIN_ROOT / "profiles" / "blueprint.json"
INSTALL_HINT: Final[str] = (
    "install the CLI (curl -fsSL https://composio.dev/install | sh), run `composio login`, or pass --from-json FILE"
)
LIST_KEYS: Final[tuple[str, ...]] = ("items", "data", "toolkits")
SLUG_KEYS: Final[tuple[str, ...]] = ("slug", "key", "toolkit", "name")
CONNECTED_KEYS: Final[tuple[str, ...]] = ("toolkit", "toolkit_slug", "appName", "app")
NAME_KEYS: Final[tuple[str, ...]] = ("name", "display_name", "displayName", "slug")
TOOL_COUNT_KEYS: Final[tuple[str, ...]] = ("tools", "tools_count", "toolsCount", "tool_count")
STATUS_KEY: Final[str] = "status"
ACTIVE_STATUS: Final[str] = "active"
WSL_NAME: Final[str] = "wsl"
WSL_LOOKUP: Final[tuple[str, ...]] = ("-e", "sh", "-lc", f"command -v {BIN_NAME}")
WSL_LABEL: Final[str] = "wsl:"
TOOLKITS_WORDS: Final[tuple[str, ...]] = ("dev", "toolkits", "list")
DEV_CONNECTED_WORDS: Final[tuple[str, ...]] = ("dev", "connected-accounts", "list")
CONNECTIONS_WORDS: Final[tuple[str, ...]] = ("connections", "list")
SOURCE_DEV: Final[str] = "dev-connected-accounts"
SOURCE_CONNECTIONS: Final[str] = "connections"
SOURCE_IMPORT: Final[str] = "import"
HEADER_TOKENS: Final[frozenset[str]] = frozenset({"slug", "name", "toolkit"})
RULE_STARTS: Final[tuple[str, ...]] = ("─", "-", "=", "|")
HARNESS_PLUGINS: Final[tuple[str, ...]] = ("dt@*", "dts2@*", "dts2-harness@*")  # the current id, then the 4.x and pre-4.0 ids
CLAUDE_DIR: Final[str] = ".claude"
SETTINGS_SCOPES: Final[tuple[tuple[str, str], ...]] = (
    ("settings.json", "project"), ("settings.local.json", "local"),
)
DISABLED_MCP_KEY: Final[str] = "disabledMcpjsonServers"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime(STAMP_FORMAT)


def state_home() -> Path:
    explicit: str | None = os.environ.get(ENV_HOME)
    return Path(explicit) if explicit else Path.home() / DEFAULT_HOME_DIR


def decision_path() -> Path:
    return state_home() / DECISION_FILE


def map_path() -> Path:
    return state_home() / MAP_FILE


def read_json(path: Path) -> Any:
    """Parsed JSON, or None when the file is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None


def read_dict(path: Path) -> dict[str, Any]:
    data: Any = read_json(path)
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2) + "\n")


def emit(payload: dict[str, Any], code: int = EXIT_OK) -> int:
    print(json.dumps(payload))
    return code


def fail(message: str, hint: str, code: int = EXIT_BAD_INPUT) -> int:
    return emit({"error": message, "hint": hint}, code)


def norm(text: str) -> str:
    """Case- and separator-insensitive form used for every pattern comparison."""
    return text.lower().replace("_", "-").replace(" ", "-")


def matches(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(norm(name), norm(pattern))


def is_windows() -> bool:
    return os.name == "nt" or sys.platform == "win32"


def wsl_binary() -> list[str] | None:
    """Command prefix for a CLI installed inside WSL, or None when WSL or the CLI is absent."""
    if shutil.which(WSL_NAME) is None:
        return None
    try:
        result = subprocess.run([WSL_NAME, *WSL_LOOKUP], capture_output=True, text=True,
                                timeout=WSL_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines: list[str] = result.stdout.strip().splitlines() if result.returncode == 0 else []
    return [WSL_NAME, "-e", lines[0].strip()] if lines else None


def find_binary() -> list[str] | None:
    """Command prefix that runs the CLI: the override, else PATH, else (Windows only) the copy inside WSL."""
    explicit: str | None = os.environ.get(ENV_BIN)
    if explicit:
        return [explicit] if os.path.isfile(explicit) and os.access(explicit, os.X_OK) else None
    found: str | None = shutil.which(BIN_NAME)
    if found:
        return [found]
    return wsl_binary() if is_windows() else None


def binary_label(binary: list[str] | None) -> str | None:
    """Readable form of a command prefix, e.g. /usr/bin/composio or wsl:/home/x/.local/bin/composio."""
    if not binary:
        return None
    return f"{WSL_LABEL}{binary[-1]}" if len(binary) > 1 and binary[0] == WSL_NAME else binary[0]


def credential_dir(home: Path) -> Path:
    explicit: str | None = os.environ.get(ENV_CACHE)
    return Path(explicit) if explicit else home / CREDENTIAL_DIR


# ---- Claude Code configuration readers ----------------------------------------------------------------------------

def settings_files(home: Path, cwd: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = [(home / CLAUDE_DIR / "settings.json", "user")]
    files += [(cwd / CLAUDE_DIR / name, scope) for name, scope in SETTINGS_SCOPES]
    return files


def enabled_plugins(home: Path, cwd: Path) -> list[tuple[str, str, Path]]:
    """(plugin id, scope, settings file) for every plugin set true in a user, project or local settings file."""
    found: list[tuple[str, str, Path]] = []
    for path, scope in settings_files(home, cwd):
        plugins: Any = read_dict(path).get("enabledPlugins")
        if isinstance(plugins, dict):
            found += [(key, scope, path) for key, value in plugins.items() if value is True]
    return found


def mcp_servers(home: Path, cwd: Path) -> list[tuple[str, str, Path]]:
    """(server name, scope, file) from the project .mcp.json, the user config and the user config's per-project entry."""
    found: list[tuple[str, str, Path]] = []
    sources: list[tuple[Path, str, Any]] = []
    project_file: Path = cwd / ".mcp.json"
    user_file: Path = home / ".claude.json"
    user: dict[str, Any] = read_dict(user_file)
    projects: Any = user.get("projects")
    local: Any = projects.get(str(cwd)) if isinstance(projects, dict) else None
    sources.append((project_file, "project", read_dict(project_file).get("mcpServers")))
    sources.append((user_file, "user", user.get("mcpServers")))
    sources.append((user_file, "local", local.get("mcpServers") if isinstance(local, dict) else None))
    for path, scope, servers in sources:
        if isinstance(servers, dict):
            found += [(name, scope, path) for name in servers]
    return found


def disabled_project_servers(cwd: Path) -> set[str]:
    names: set[str] = set()
    for path, _scope in settings_files(cwd, cwd)[1:]:
        listed: Any = read_dict(path).get(DISABLED_MCP_KEY)
        if isinstance(listed, list):
            names.update(str(n) for n in listed)
    return names


def user_skills(home: Path) -> list[str]:
    root: Path = home / CLAUDE_DIR / "skills"
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


# ---- status / decide ---------------------------------------------------------------------------------------------

def tool_map_summary() -> dict[str, Any]:
    path: Path = map_path()
    data: dict[str, Any] = read_dict(path)
    toolkits: Any = data.get("toolkits")
    connected: Any = data.get("connected")
    return {"path": str(path), "exists": path.is_file(), "generated_at": data.get("generated_at"),
            "toolkits": len(toolkits) if isinstance(toolkits, list) else 0,
            "connected": list(connected) if isinstance(connected, list) else []}


def cmd_status(args: argparse.Namespace) -> int:
    home, cwd = args.home, args.cwd
    binary: str | None = binary_label(find_binary())
    plugin_on: bool = any(pid.startswith(PLUGIN_PREFIX) for pid, _s, _p in enabled_plugins(home, cwd))
    servers: list[str] = sorted({n for n, _s, _p in mcp_servers(home, cwd) if SERVER_WORD in n.lower()})
    decision: Any = read_json(decision_path())
    return emit({
        "cli": binary is not None, "cli_path": binary,
        "logged_in": credential_dir(home).is_dir(),
        "plugin_enabled": plugin_on, "mcp_servers": servers,
        "duplicate_connection": plugin_on and bool(servers),
        "decision": decision if isinstance(decision, dict) else None,
        "tool_map": tool_map_summary(),
    })


def cmd_decide(args: argparse.Namespace) -> int:
    decision: dict[str, Any] = {"account": args.account, "always_use": bool(args.always_use),
                                "connection": args.connection, "decided_at": now_iso()}
    write_json(decision_path(), decision)
    return emit(decision)


# ---- map ---------------------------------------------------------------------------------------------------------

def first_key(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value: Any = item.get(key)
        if isinstance(value, dict):
            value = first_key(value, SLUG_KEYS)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def as_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in LIST_KEYS:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def is_skipped_line(line: str) -> bool:
    token: str = line.split()[0]
    return line.startswith(RULE_STARTS) or token.lower() in HEADER_TOKENS


def text_slugs(text: str) -> list[str]:
    lines: list[str] = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [ln.split()[0] for ln in lines if not is_skipped_line(ln)]


def parse_listing(text: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Rows as dicts with at least a slug. JSON first (list or wrapped list), else one row per text line."""
    try:
        data: Any = json.loads(text)
    except ValueError:
        return [{"slug": slug} for slug in text_slugs(text)]
    rows: list[dict[str, Any]] = []
    for item in as_list(data):
        if isinstance(item, str):
            rows.append({"slug": item})
        elif isinstance(item, dict):
            slug: str | None = first_key(item, keys)
            if slug:
                rows.append({**item, "slug": slug})
    return rows


def tool_count(item: dict[str, Any]) -> int | None:
    for key in TOOL_COUNT_KEYS:
        value: Any = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return None


def is_active(row: dict[str, Any]) -> bool:
    """True for rows whose status is "active" (any case) and for rows that carry no status at all."""
    status: Any = row.get(STATUS_KEY)
    return status is None or str(status).strip().lower() == ACTIVE_STATUS


def active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_active(row)]


def build_toolkits(rows: list[dict[str, Any]], connected: set[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        slug: str = str(row["slug"]).lower()
        if slug in seen:
            continue
        seen.add(slug)
        name: str = first_key(row, NAME_KEYS) or slug
        out.append({"slug": slug, "name": name, "connected": slug in connected, "tools": tool_count(row)})
    return out


def run_listing(binary: list[str], words: tuple[str, ...], timeout: int) -> str:
    result = subprocess.run([*binary, *words], capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"`composio {' '.join(words)}` exited {result.returncode}")
    return result.stdout


def import_listings(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data: Any = json.loads(path.read_text(encoding=ENCODING))
    if not isinstance(data, dict):
        raise ValueError("expected an object with toolkits and connected")
    return parse_listing(json.dumps(data.get("toolkits", [])), SLUG_KEYS), \
        parse_listing(json.dumps(data.get("connected", [])), CONNECTED_KEYS + SLUG_KEYS)


def connection_rows(text: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Rows from `composio connections list`. CLI 0.6 prints an object keyed by toolkit slug, each holding a list of
    accounts ({"github": [{"id": ..., "status": "ACTIVE"}, ...]}); that becomes one row per account carrying only the
    slug and status, so no account id or alias is kept. Any other shape goes through parse_listing."""
    try:
        data: Any = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or any(key in data for key in LIST_KEYS):
        return parse_listing(text, keys)
    rows: list[dict[str, Any]] = []
    for slug, accounts in data.items():
        for account in accounts if isinstance(accounts, list) else []:
            status: Any = account.get(STATUS_KEY) if isinstance(account, dict) else None
            rows.append({"slug": str(slug)} if status is None else {"slug": str(slug), STATUS_KEY: status})
    return rows


def fetch_connected(binary: list[str], timeout: int) -> tuple[list[dict[str, Any]], str]:
    """Connected rows and the command that produced them: the dev project first, else the global connections."""
    keys: tuple[str, ...] = CONNECTED_KEYS + SLUG_KEYS
    try:
        return parse_listing(run_listing(binary, DEV_CONNECTED_WORDS, timeout), keys), SOURCE_DEV
    except (RuntimeError, subprocess.TimeoutExpired) as dev_err:
        try:
            rows: list[dict[str, Any]] = connection_rows(run_listing(binary, CONNECTIONS_WORDS, timeout), keys)
        except (RuntimeError, subprocess.TimeoutExpired) as fallback_err:
            raise RuntimeError(f"{dev_err}; {fallback_err}") from fallback_err
        return active_rows(rows), SOURCE_CONNECTIONS


def cmd_map(args: argparse.Namespace) -> int:
    source: str = "import"
    connected_source: str = SOURCE_IMPORT
    try:
        if args.from_json:
            toolkit_rows, connected_rows = import_listings(Path(args.from_json))
        else:
            binary: list[str] | None = find_binary()
            if binary is None:
                return fail("composio CLI not found", INSTALL_HINT)
            source = "cli"
            toolkit_rows = parse_listing(run_listing(binary, TOOLKITS_WORDS, args.timeout), SLUG_KEYS)
            connected_rows, connected_source = fetch_connected(binary, args.timeout)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as err:
        return fail(f"map failed: {err}", "check the CLI login (`composio login`) or the JSON file", EXIT_FAILED)
    connected: list[str] = sorted({str(r["slug"]).lower() for r in connected_rows})
    toolkits: list[dict[str, Any]] = build_toolkits(toolkit_rows, set(connected))
    document: dict[str, Any] = {"version": SCHEMA_VERSION, "generated_at": now_iso(), "source": source,
                                "connected_source": connected_source, "toolkits": toolkits, "connected": connected}
    write_json(map_path(), document)
    return emit({"path": str(map_path()), "toolkits": len(toolkits), "connected": connected, "source": source,
                 "connected_source": connected_source})


# ---- overlap / disable -------------------------------------------------------------------------------------------

def keep_list_plugins(cwd: Path) -> list[str]:
    return list(_load.load("machine-prep").keep_list_plugins(cwd))


def required_patterns(profile: Path) -> list[str]:
    listed: Any = read_dict(profile).get("requiredByHarness")
    return [str(p) for p in listed] if isinstance(listed, list) else []


def exclusion_reason(item_id: str, required: list[str], keep: list[str]) -> str | None:
    if matches(f"{SERVER_WORD}*", item_id):
        return "composio"
    if any(matches(p, item_id) for p in HARNESS_PLUGINS):
        return "dts2"
    if any(matches(p, item_id) for p in required):
        return "requiredByHarness"
    if any(matches(p, item_id) for p in keep):
        return "keep.yaml"
    return None


def inventory(home: Path, cwd: Path) -> list[tuple[str, str, str]]:
    """(kind, id, scope) for everything currently enabled that could overlap a toolkit."""
    disabled: set[str] = disabled_project_servers(cwd)
    items: list[tuple[str, str, str]] = [("plugin", pid, scope) for pid, scope, _p in enabled_plugins(home, cwd)]
    items += [("mcp", name, scope) for name, scope, _p in mcp_servers(home, cwd)
              if not (scope == "project" and name in disabled)]
    items += [("skill", name, "user") for name in user_skills(home)]
    return items


def wanted_patterns(spec: dict[str, Any], kind: str) -> list[str]:
    listed: Any = spec.get({"plugin": "plugins", "mcp": "mcp", "skill": "skills"}[kind])
    return [str(p) for p in listed] if isinstance(listed, list) else []


def compute_overlap(args: argparse.Namespace) -> dict[str, Any] | None:
    tool_map: dict[str, Any] = read_dict(map_path())
    if not tool_map:
        return None
    wanted: set[str] = {str(s) for s in tool_map.get("connected", [])}
    if args.all:
        wanted |= {str(t.get("slug")) for t in tool_map.get("toolkits", []) if isinstance(t, dict)}
    toolkits: dict[str, Any] = read_dict(OVERLAP_PROFILE).get("toolkits", {})
    required: list[str] = required_patterns(Path(args.profile))
    keep: list[str] = keep_list_plugins(args.cwd)
    candidates: list[dict[str, str]] = []
    kept: dict[str, str] = {}
    for kind, item_id, scope in inventory(args.home, args.cwd):
        for slug in sorted(wanted):
            spec: Any = toolkits.get(slug)
            if not isinstance(spec, dict):
                continue
            if not any(matches(p, item_id) for p in wanted_patterns(spec, kind)):
                continue
            reason: str | None = exclusion_reason(item_id, required, keep)
            if reason:
                kept.setdefault(item_id, reason)
            else:
                candidates.append({"kind": kind, "id": item_id, "toolkit": slug, "scope": scope})
    return {"candidates": candidates, "kept": [{"id": i, "reason": r} for i, r in sorted(kept.items())]}


def missing_map() -> int:
    return fail("tool map missing", "run `composio-setup.py map` first (or `map --from-json FILE`)")


def cmd_overlap(args: argparse.Namespace) -> int:
    result: dict[str, Any] | None = compute_overlap(args)
    return missing_map() if result is None else emit(result)


def backup_file(path: Path, made: dict[Path, Path]) -> Path:
    if path in made:
        return made[path]
    target: Path = path.with_name(f"{path.name}.bak-{stamp()}")
    counter: int = 1
    while target.exists():
        target = path.with_name(f"{path.name}.bak-{stamp()}-{counter}")
        counter += 1
    shutil.copy2(path, target)
    made[path] = target
    return target


def archive_target(home: Path, name: str) -> Path:
    folder: Path = home / CLAUDE_DIR / "skills-archive"
    target: Path = folder / name
    return folder / f"{name}-{stamp()}" if target.exists() else target


class Disabler:
    """Applies (or, in a dry run, only reports) the changes for the chosen candidates."""

    def __init__(self, home: Path, cwd: Path, dry_run: bool) -> None:
        self.home, self.cwd, self.dry_run = home, cwd, dry_run
        self.changed: list[dict[str, str]] = []
        self.manual: list[str] = []
        self.skipped: list[str] = []
        self.backups: dict[Path, Path] = {}

    def edit_settings(self, path: Path, change: Any) -> None:
        if self.dry_run:
            return
        data: dict[str, Any] = read_dict(path)
        if path.is_file():
            backup_file(path, self.backups)
        change(data)
        write_json(path, data)

    def plugin(self, item_id: str) -> None:
        for pid, _scope, path in enabled_plugins(self.home, self.cwd):
            if pid == item_id:
                self.edit_settings(path, lambda d, k=item_id: d["enabledPlugins"].__setitem__(k, False))
                self.changed.append({"kind": "plugin", "id": item_id, "file": str(path)})

    def skill(self, name: str) -> None:
        source: Path = self.home / CLAUDE_DIR / "skills" / name
        target: Path = archive_target(self.home, name)
        if not self.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        self.changed.append({"kind": "skill", "id": name, "file": str(target)})

    def mcp(self, name: str, scope: str) -> None:
        if scope == "project":
            path: Path = self.cwd / CLAUDE_DIR / "settings.local.json"

            def add(data: dict[str, Any]) -> None:
                listed: list[Any] = data.get(DISABLED_MCP_KEY) if isinstance(data.get(DISABLED_MCP_KEY), list) else []
                data[DISABLED_MCP_KEY] = [*listed, name] if name not in listed else listed

            self.edit_settings(path, add)
            self.changed.append({"kind": "mcp", "id": name, "file": str(path)})
        else:
            step: str = f"claude mcp remove {name} --scope {scope}"
            if step not in self.manual:
                self.manual.append(step)

    def apply(self, kind: str, item_id: str, scope: str) -> None:
        {"plugin": lambda: self.plugin(item_id), "skill": lambda: self.skill(item_id),
         "mcp": lambda: self.mcp(item_id, scope)}[kind]()


def cmd_disable(args: argparse.Namespace) -> int:
    result: dict[str, Any] | None = compute_overlap(args)
    if result is None:
        return missing_map()
    wanted: list[str] = [i.strip() for i in args.ids.split(",") if i.strip()]
    known: list[tuple[str, str, str]] = list(dict.fromkeys(
        (c["kind"], c["id"], c["scope"]) for c in result["candidates"]))
    disabler = Disabler(args.home, args.cwd, args.dry_run)
    for item_id in wanted:
        hits: list[tuple[str, str, str]] = [key for key in known if key[1] == item_id]
        if not hits:
            disabler.skipped.append(item_id)
        for kind, _id, scope in hits:
            disabler.apply(kind, item_id, scope)
    return emit({"changed": disabler.changed, "manual": disabler.manual,
                 "backups": [str(p) for p in disabler.backups.values()],
                 "skipped": disabler.skipped, "dry_run": args.dry_run})


# ---- CLI ---------------------------------------------------------------------------------------------------------

def add_scope_args(parser: argparse.ArgumentParser, *, profile: bool = False) -> None:
    parser.add_argument("--home", type=Path, default=Path.home(), help="user home (holds .claude and .claude.json)")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="project directory")
    if profile:
        parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="profile with requiredByHarness")
        parser.add_argument("--all", action="store_true", help="consider every toolkit, not only connected ones")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    add_scope_args(sub.add_parser("status", help="show integration state"))
    decide = sub.add_parser("decide", help="record the user's decision")
    decide.add_argument("--account", required=True, choices=["yes", "no"])
    decide.add_argument("--always-use", action="store_true")
    decide.add_argument("--connection", choices=["plugin", "mcp", "cli"])
    mapper = sub.add_parser("map", help="cache the toolkit list and connected toolkits")
    mapper.add_argument("--from-json", help="import {toolkits, connected} instead of running the CLI")
    mapper.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    add_scope_args(sub.add_parser("overlap", help="list local tools a connected toolkit makes redundant"), profile=True)
    disable = sub.add_parser("disable", help="turn off overlapping tools, with backups")
    disable.add_argument("--ids", required=True, help="comma-separated candidate ids from overlap")
    disable.add_argument("--dry-run", action="store_true")
    add_scope_args(disable, profile=True)
    return parser


COMMANDS: Final[dict[str, Any]] = {
    "status": cmd_status, "decide": cmd_decide, "map": cmd_map, "overlap": cmd_overlap, "disable": cmd_disable,
}


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    return int(COMMANDS[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
