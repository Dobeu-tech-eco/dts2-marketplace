#!/usr/bin/env python3
"""Bump or verify the plugin version across the four places it is recorded.

Usage: bump-version.py X.Y.Z [--root <repo root>] [--check]
Prints JSON {ok, version, files}. With --check nothing is written; exit 1 when any
location differs from X.Y.Z or lacks a version.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

SEMVER: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")
PLUGIN_NAME: Final[str] = "dt"
MARKETPLACE: Final[str] = ".claude-plugin/marketplace.json"
PLUGIN_JSON: Final[str] = "plugins/dts2-runtime/.claude-plugin/plugin.json"
TEXT_CONTRACTS: Final[str] = "plugins/dts2-runtime/tests/test_text_contracts.py"
UPGRADE_CHECK: Final[str] = "plugins/dts2-runtime/tests/test_upgrade_check.py"
JSON_INDENT: Final[int] = 2
EXIT_FAIL: Final[int] = 1
REPO_ROOT_INDEX: Final[int] = 3
PY_CONSTANTS: Final[dict[str, str]] = {
    TEXT_CONTRACTS: "VERSION",
    UPGRADE_CHECK: "RELEASE",
}


def py_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        r'^(?P<head>[ \t]*' + name + r'\s*(?::[^=\n]+)?=\s*")(?P<ver>[^"]*)(?P<tail>")',
        re.MULTILINE,
    )


def json_slots(data: dict[str, Any], rel: str) -> list[dict[str, Any]]:
    """Dicts inside this JSON file that hold the plugin version."""
    if rel == PLUGIN_JSON:
        return [data]
    slots: list[dict[str, Any]] = []
    if "version" in data:
        slots.append(data)
    for plugin in data.get("plugins", []):
        if isinstance(plugin, dict) and plugin.get("name") == PLUGIN_NAME:
            slots.append(plugin)
    return slots


def read_json_versions(path: Path, rel: str) -> list[str | None]:
    slots = json_slots(json.loads(path.read_text(encoding="utf-8")), rel)
    if not slots:
        return [None]
    return [s.get("version") for s in slots]


def read_py_version(path: Path, name: str) -> list[str | None]:
    match = py_pattern(name).search(path.read_text(encoding="utf-8"))
    return [match.group("ver") if match else None]


def current_versions(root: Path) -> dict[str, list[str | None]]:
    found: dict[str, list[str | None]] = {}
    for rel in (MARKETPLACE, PLUGIN_JSON):
        found[rel] = read_json_versions(root / rel, rel)
    for rel, name in PY_CONSTANTS.items():
        found[rel] = read_py_version(root / rel, name)
    return found


def write_json(path: Path, rel: str, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for slot in json_slots(data, rel):
        slot["version"] = version
    atomic_write(path, json.dumps(data, indent=JSON_INDENT, ensure_ascii=False) + "\n")


def write_py(path: Path, name: str, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = py_pattern(name).subn(
        lambda m: m.group("head") + version + m.group("tail"), text, count=1
    )
    if count:
        atomic_write(path, new)


def mismatches(root: Path, version: str) -> list[str]:
    return [
        rel
        for rel, versions in current_versions(root).items()
        if any(v != version for v in versions)
    ]


def missing_locations(root: Path) -> list[str]:
    return [
        rel
        for rel, versions in current_versions(root).items()
        if any(v is None for v in versions)
    ]


def apply(root: Path, version: str) -> None:
    write_json(root / MARKETPLACE, MARKETPLACE, version)
    write_json(root / PLUGIN_JSON, PLUGIN_JSON, version)
    for rel, name in PY_CONSTANTS.items():
        write_py(root / rel, name, version)


def emit(payload: dict[str, Any], code: int) -> int:
    print(json.dumps(payload))
    return code


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[REPO_ROOT_INDEX]))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not SEMVER.match(args.version):
        return emit(
            {"ok": False, "version": args.version,
             "error": "invalid semver, expected MAJOR.MINOR.PATCH", "files": []},
            EXIT_FAIL,
        )
    root = Path(args.root)
    if args.check:
        bad = mismatches(root, args.version)
        return emit({"ok": not bad, "version": args.version, "files": bad}, EXIT_FAIL if bad else 0)
    missing = missing_locations(root)
    if missing:
        return emit({"ok": False, "version": args.version, "files": missing}, EXIT_FAIL)
    apply(root, args.version)
    bad = mismatches(root, args.version)
    files = [MARKETPLACE, PLUGIN_JSON, *PY_CONSTANTS]
    return emit({"ok": not bad, "version": args.version, "files": files}, EXIT_FAIL if bad else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
