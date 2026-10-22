#!/usr/bin/env python3
"""Compare the version recorded before an upgrade with the installed plugin version."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

PLUGIN_JSON: Final[Path] = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
VERSION_SEPARATOR: Final[str] = "."


def read_version(path: Path) -> str:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return str(data["version"])


def numeric_parts(version: str) -> tuple[int, ...] | None:
    """Integer segments of a version, or None when any segment is not a plain number."""
    parts: list[str] = version.strip().split(VERSION_SEPARATOR)
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def pad(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width: int = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))


def ordering(from_v: str, to_v: str) -> int:
    """-1, 0 or 1 for from_v older than, equal to, or newer than to_v. Never raises."""
    left, right = numeric_parts(from_v), numeric_parts(to_v)
    if left is not None and right is not None:
        left, right = pad(left, right)
        return (left > right) - (left < right)
    return (from_v > to_v) - (from_v < to_v)


def compare(from_v: str, to_v: str) -> dict[str, Any]:
    order: int = ordering(from_v, to_v)
    return {"from": from_v, "to": to_v, "advanced": order < 0, "same": order == 0}


def read_from_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    text: str = path.read_text(encoding="utf-8").strip()
    return text or None


def check(from_file: Path, plugin_json: Path) -> dict[str, Any]:
    installed: str = read_version(plugin_json)
    recorded: str | None = read_from_file(from_file)
    if recorded is None:
        return {"from": None, "to": installed, "advanced": False, "same": False}
    return compare(recorded, installed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", required=True)
    parser.add_argument("--plugin-json", default=str(PLUGIN_JSON))
    args = parser.parse_args()
    print(json.dumps(check(Path(args.from_file), Path(args.plugin_json))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
