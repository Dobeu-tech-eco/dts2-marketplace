#!/usr/bin/env python3
"""Settings parsed once. Reads .harness/config.yaml (budget, supervisor) and the .claude/dts2-harness.local.md frontmatter,
checks each value against a schema, fills defaults, and keeps the result in .harness/settings.cache.json keyed by the
sources' mtime and size. A hook or script reads the cache instead of parsing the files again. The cache is gitignored
and written 0600 (it can echo local settings). A stale or damaged cache is rebuilt, never trusted."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import state_io  # noqa: E402
from state_io import atomic_write  # noqa: E402

CONFIG_FILE: Final[str] = state_io.CONFIG_REL
LOCAL_FILE: Final[str] = ".claude/dts2-harness.local.md"
CACHE_FILE: Final[str] = state_io.SETTINGS_CACHE_REL
CACHE_MODE: Final[int] = 0o600
SCHEMA_VERSION: Final[int] = 2
# section -> key -> (type, default). The defaults are the ones model_call.py and lanes.py already used.
SCHEMA: Final[dict[str, dict[str, tuple[type, Any]]]] = {
    "budget": {
        "max_turns": (int, 80), "max_rounds": (int, 4), "max_fullauto_loops": (int, 3),
        "max_wall_minutes": (float, 90.0), "max_usd": (float, 0.0),
    },
    "supervisor": {
        "max_model_calls": (int, 4), "stall_minutes": (int, 10), "retry_max": (int, 4),
        "backoff_base_s": (float, 2.0), "backoff_cap_s": (float, 60.0), "fallback_models": (str, "sonnet"),
    },
    "local": {
        "enabled": (bool, True), "max_builders": (int, 6), "max_reviewers": (int, 4),
        "son_permission_mode": (str, "bypassPermissions"), "lead_provider": (str, "claude"),
        "son_model": (str, "opus"),
    },
}
DEFAULTS: Final[dict[str, dict[str, Any]]] = {
    section: {key: default for key, (_, default) in keys.items()} for section, keys in SCHEMA.items()
}


def source_key(repo: Path) -> dict[str, list[int]]:
    key: dict[str, list[int]] = {}
    for name in (CONFIG_FILE, LOCAL_FILE):
        try:
            info = (repo / name).stat()
            key[name] = [info.st_mtime_ns, info.st_size]
        except OSError:
            key[name] = [0, 0]
    return key


def typed(raw: dict[str, Any], key: str, kind: type, default: Any) -> Any:
    if kind is int:
        value: Any = miniyaml.get_int(raw, key, default)
        return value if value > 0 else default
    if kind is float:
        number: float = miniyaml.get_float(raw, key, default)
        return number if number >= 0 else default
    if kind is bool:
        return miniyaml.get_bool(raw, key, default)
    text: str = miniyaml.get_str(raw, key, "")
    return text if key in raw and isinstance(raw.get(key), str) else default


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build(repo: Path) -> dict[str, dict[str, Any]]:
    config: dict[str, Any] = miniyaml.parse(read_text(repo / CONFIG_FILE))
    local: dict[str, Any] = miniyaml.parse_frontmatter(read_text(repo / LOCAL_FILE))
    sources: dict[str, dict[str, Any]] = {
        "budget": config.get("budget") if isinstance(config.get("budget"), dict) else {},
        "supervisor": config.get("supervisor") if isinstance(config.get("supervisor"), dict) else {},
        "local": local,
    }
    return {
        section: {key: typed(sources[section], key, kind, default) for key, (kind, default) in keys.items()}
        for section, keys in SCHEMA.items()
    }


def read_cache(repo: Path, key: dict[str, list[int]]) -> dict[str, dict[str, Any]] | None:
    try:
        data: Any = json.loads((repo / CACHE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != SCHEMA_VERSION or data.get("key") != key:
        return None
    settings: Any = data.get("settings")
    return settings if isinstance(settings, dict) and set(settings) == set(SCHEMA) else None


def write_cache(repo: Path, key: dict[str, list[int]], settings: dict[str, dict[str, Any]]) -> None:
    if not state_io.harness_path(repo).is_dir():
        return  # no harness here: nothing to cache into
    target: Path = repo / CACHE_FILE
    try:
        atomic_write(target, json.dumps({"v": SCHEMA_VERSION, "key": key, "settings": settings}, indent=2) + "\n")
        os.chmod(target, CACHE_MODE)
    except OSError:
        pass  # a read-only checkout still gets correct settings, just uncached


def load(repo: Path | str) -> dict[str, dict[str, Any]]:
    root: Path = Path(repo)
    key: dict[str, list[int]] = source_key(root)
    cached: dict[str, dict[str, Any]] | None = read_cache(root, key)
    if cached is not None:
        return cached
    settings: dict[str, dict[str, Any]] = build(root)
    write_cache(root, key, settings)
    return settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--get", default=None, help="one dotted setting, e.g. budget.max_turns")
    args = parser.parse_args()
    settings = load(args.repo)
    out: Any = miniyaml.get(settings, args.get) if args.get else settings
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
