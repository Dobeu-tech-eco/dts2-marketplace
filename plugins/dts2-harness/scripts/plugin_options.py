#!/usr/bin/env python3
"""G-86: per-user knobs and non-repo caches through the plugin mechanism.

Claude Code exports every `userConfig` option of an enabled plugin to hook processes as `CLAUDE_PLUGIN_OPTION_<KEY>` (the key
uppercased) and the plugin's persistent data directory as `CLAUDE_PLUGIN_DATA`. Per-user knobs read the first; caches that
must outlive a plugin update and do not belong in the repo go under the second. Per-repo settings stay in `.claude`
(`dts2-harness.local.md`): this module never reads or writes them. Values are never printed by `show` when the option is
sensitive.

Usage: plugin_options.py show | get KEY [--default V] | data-dir"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Final

OPTION_PREFIX: Final[str] = "CLAUDE_PLUGIN_OPTION_"
DATA_VAR: Final[str] = "CLAUDE_PLUGIN_DATA"
TRUE_WORDS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
EXIT_UNSET: Final[int] = 1


def option(key: str, default: str | None = None, env: dict[str, str] | None = None) -> str | None:
    """The user's value for `key`, else `default`. An empty string counts as unset."""
    source: dict[str, str] = dict(os.environ) if env is None else env
    return source.get(OPTION_PREFIX + key.upper()) or default


def option_bool(key: str, default: bool = False, env: dict[str, str] | None = None) -> bool:
    value: str | None = option(key, None, env)
    return default if value is None else value.strip().lower() in TRUE_WORDS


def data_dir(env: dict[str, str] | None = None) -> Path | None:
    """The plugin's persistent data directory, or None when Claude Code did not export it (run outside a plugin session)."""
    value: str | None = (dict(os.environ) if env is None else env).get(DATA_VAR)
    return Path(value) if value else None


def cache_path(name: str, env: dict[str, str] | None = None) -> Path | None:
    """A file under the data directory for a non-repo cache; None without one. `name` may not leave the directory."""
    base: Path | None = data_dir(env)
    if base is None or Path(name).is_absolute() or ".." in Path(name).parts:
        return None
    return base / name


def configured(env: dict[str, str] | None = None) -> list[str]:
    source: dict[str, str] = dict(os.environ) if env is None else env
    return sorted(k[len(OPTION_PREFIX):].lower() for k in source if k.startswith(OPTION_PREFIX) and source[k])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    sub.add_parser("data-dir")
    get_p = sub.add_parser("get")
    get_p.add_argument("key")
    get_p.add_argument("--default", default=None)
    args = parser.parse_args()
    if args.command == "show":
        print(json.dumps({"options": configured(), "data_dir": str(data_dir() or "")}))
        return 0
    if args.command == "data-dir":
        found: Path | None = data_dir()
        print(found or "")
        return 0 if found else EXIT_UNSET
    value: str | None = option(args.key, args.default)
    print(value if value is not None else "")
    return 0 if value is not None else EXIT_UNSET


if __name__ == "__main__":
    sys.exit(main())
