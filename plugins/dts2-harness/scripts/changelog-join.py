#!/usr/bin/env python3
"""Join changelog.d/ fragments into the README changelog.

Each batch writes its own fragment (changelog.d/batch-<n>.md, bullet lines starting with "- "), so two pull requests
never edit the same README lines. At release time the lead runs this: it appends every fragment's bullets, in batch
order, to the end of the `## Unreleased` section. With --version it then renames that section to `## <version> (<date>)`
and opens a fresh empty `## Unreleased` above it. Dry run unless --apply; --apply also deletes the joined fragments.
JSON on stdout."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FRAGMENT_DIR: Final[str] = "changelog.d"
FRAGMENT_GLOB: Final[str] = "batch-*.md"
UNRELEASED: Final[str] = "## Unreleased"
HEADING: Final[re.Pattern[str]] = re.compile(r"^## ", re.MULTILINE)
NUMBER: Final[re.Pattern[str]] = re.compile(r"(\d+)")
BULLET: Final[str] = "- "
VERSION: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")


def fragment_key(path: Path) -> tuple[int, str]:
    match: re.Match[str] | None = NUMBER.search(path.stem)
    return (int(match.group(1)) if match else 0, path.name)


def fragments(folder: Path) -> list[Path]:
    return sorted(folder.glob(FRAGMENT_GLOB), key=fragment_key)


def bullets(path: Path) -> list[str]:
    return [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(BULLET)]


def unreleased_bounds(text: str) -> tuple[int, int]:
    """Start of the `## Unreleased` heading and the start of the next `## ` heading (or end of text)."""
    start: int = text.find(UNRELEASED + "\n")
    if start < 0:
        raise ValueError("README has no `## Unreleased` heading")
    later: re.Match[str] | None = HEADING.search(text, start + len(UNRELEASED))
    return start, later.start() if later else len(text)


def join(readme: str, lines: list[str], version: str | None, today: str) -> str:
    start, end = unreleased_bounds(readme)
    body: str = readme[start:end].rstrip("\n")
    if lines:
        body += "\n" + "\n".join(lines)
    body += "\n\n"
    if version:
        body = f"{UNRELEASED}\n\n" + body.replace(UNRELEASED, f"## {version} ({today})", 1)
    return readme[:start] + body + readme[end:]


def run(root: Path, version: str | None, apply: bool, today: str) -> dict[str, Any]:
    if version is not None and not VERSION.match(version):
        raise ValueError(f"version must look like 1.2.3, got {version!r}")
    folder: Path = root / FRAGMENT_DIR
    found: list[Path] = fragments(folder) if folder.is_dir() else []
    lines: list[str] = [line for path in found for line in bullets(path)]
    readme_path: Path = root / "README.md"
    joined: str = join(readme_path.read_text(encoding="utf-8"), lines, version, today)
    if apply:
        atomic_write(readme_path, joined)
        for path in found:
            path.unlink()
    return {"applied": apply, "fragments": [p.name for p in found], "bullets": len(lines), "version": version}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PLUGIN_ROOT), help="plugin root holding README.md and changelog.d/")
    parser.add_argument("--version", help="release version; renames the Unreleased section")
    parser.add_argument("--apply", action="store_true", help="write the README and delete the fragments")
    parser.add_argument("--date", default=date.today().isoformat(), help="release date")
    args: argparse.Namespace = parser.parse_args()
    try:
        result: dict[str, Any] = run(Path(args.root), args.version, args.apply, args.date)
    except (OSError, ValueError) as error:
        json.dump({"applied": False, "error": str(error)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
