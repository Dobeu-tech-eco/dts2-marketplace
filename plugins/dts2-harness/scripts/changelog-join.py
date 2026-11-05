#!/usr/bin/env python3
"""Join changelog.d/ fragments into the README changelog.

Each batch writes its own fragment (changelog.d/batch-<n>.md: bullets starting with "- ", optional indented continuation
lines, optional `#` headings), so two pull requests never edit the same README lines. The README keeps its newest
lines directly under `## Unreleased` and the version history (`- 3.1.0 ...` down to the first release) below them in the
same section. The joined bullets are inserted right after the `## Unreleased` heading, newest batch first (descending
batch number; lines of one fragment keep their order). With --version, only the lines above the first `- <semver>`
history bullet move into a new `## <version> (<date>)` section, opened under a fresh empty `## Unreleased`; the history
is left alone. Any other non-blank fragment line (prose that is neither a bullet, a continuation nor a heading) is
reported as `dropped`, and --apply then refuses (exit 1, nothing written, nothing deleted). Dry run unless --apply;
--apply also deletes the joined fragments. JSON on stdout."""
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
MD_HEADING: Final[re.Pattern[str]] = re.compile(r"^#+\s")
HEADING: Final[re.Pattern[str]] = re.compile(r"^## ", re.MULTILINE)
NUMBER: Final[re.Pattern[str]] = re.compile(r"(\d+)")
BULLET: Final[str] = "- "
HISTORY: Final[re.Pattern[str]] = re.compile(r"^- \d+\.\d+\.\d+", re.MULTILINE)
VERSION: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")


def fragment_key(path: Path) -> tuple[int, str]:
    match: re.Match[str] | None = NUMBER.search(path.stem)
    return (int(match.group(1)) if match else 0, path.name)


def fragments(folder: Path) -> list[Path]:
    """Newest batch first (descending batch number)."""
    return sorted(folder.glob(FRAGMENT_GLOB), key=fragment_key, reverse=True)


def parse_fragment(path: Path) -> tuple[list[str], list[str]]:
    """Bullets (indented continuation lines joined on) and the non-blank lines that fit nowhere."""
    lines: list[str] = []
    dropped: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line: str = raw.rstrip()
        if not line.strip() or MD_HEADING.match(line):
            continue
        if line.startswith(BULLET):
            lines.append(line)
        elif line[0] in " \t" and lines:
            lines[-1] += " " + line.strip()
        else:
            dropped.append(f"{path.name}: {line.strip()}")
    return lines, dropped


def unreleased_bounds(text: str) -> tuple[int, int]:
    """Start of the `## Unreleased` heading and the start of the next `## ` heading (or end of text)."""
    start: int = text.find(UNRELEASED + "\n")
    if start < 0:
        raise ValueError("README has no `## Unreleased` heading")
    later: re.Match[str] | None = HEADING.search(text, start + len(UNRELEASED))
    return start, later.start() if later else len(text)


def join(readme: str, lines: list[str], version: str | None, today: str) -> str:
    start, end = unreleased_bounds(readme)
    body: str = readme[start + len(UNRELEASED):end].strip("\n")
    if lines:
        body = "\n".join(lines) + ("\n" + body if body else "")
    tail: str = readme[end:]
    if not version:
        return readme[:start] + f"{UNRELEASED}\n\n{body}\n" + ("\n" + tail if tail else "")
    history: re.Match[str] | None = HISTORY.search(body)
    cut: int = history.start() if history else len(body)
    newest: str = body[:cut].rstrip("\n")
    older: str = body[cut:]
    section: str = f"## {version} ({today})\n\n{newest}\n" + ("\n" + older.rstrip("\n") + "\n" if older else "")
    return readme[:start] + f"{UNRELEASED}\n\n" + section + ("\n" + tail if tail else "")


def run(root: Path, version: str | None, apply: bool, today: str) -> dict[str, Any]:
    if version is not None and not VERSION.match(version):
        raise ValueError(f"version must look like 1.2.3, got {version!r}")
    folder: Path = root / FRAGMENT_DIR
    found: list[Path] = fragments(folder) if folder.is_dir() else []
    lines: list[str] = []
    dropped: list[str] = []
    for path in found:
        kept, lost = parse_fragment(path)
        lines += kept
        dropped += lost
    readme_path: Path = root / "README.md"
    joined: str = join(readme_path.read_text(encoding="utf-8"), lines, version, today)
    result: dict[str, Any] = {"applied": False, "fragments": [p.name for p in found], "bullets": len(lines), "version": version,
                              "dropped": dropped}
    if apply and dropped:
        result["error"] = "refusing --apply: fragment lines that are not bullets, continuations or headings would be lost"
        return result
    if apply:
        atomic_write(readme_path, joined)
        for path in found:
            path.unlink()
        result["applied"] = True
    return result


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PLUGIN_ROOT), help="plugin root holding README.md and changelog.d/")
    parser.add_argument("--version", help="release version; moves the newest lines into a new version section")
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
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
