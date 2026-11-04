#!/usr/bin/env python3
"""Measure the always-loaded metadata tax: skill and agent name + description (+ when_to_use) text.

Tokens are approximated as characters / 4 (no tokenizer is bundled, so this is an estimate that errs
a little high for English). Exit 1 when the total exceeds --budget or a single description exceeds --max-description.
JSON on stdout: {"ok", "tokens", "budget", "entries": [...], "problems": [...]}."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CHARS_PER_TOKEN: Final[int] = 4
DEFAULT_BUDGET: Final[int] = 6000
DEFAULT_MAX_DESCRIPTION: Final[int] = 300
LISTED_KEYS: Final[tuple[str, ...]] = ("name", "description", "when_to_use")
KEY_LINE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")


def frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs of the leading --- block. Continuation lines are ignored."""
    lines: list[str] = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        match: re.Match[str] | None = KEY_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return {}


def metadata_files(root: Path) -> list[Path]:
    return sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("agents/*.md"))


def tokens_of(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN)


def measure(root: Path, max_description: int) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in metadata_files(root):
        meta: dict[str, str] = frontmatter(path.read_text(encoding="utf-8"))
        rel: str = str(path.relative_to(root))
        if not meta.get("description"):
            problems.append(f"{rel}: no description")
        listed: str = " ".join(meta.get(key, "") for key in LISTED_KEYS).strip()
        if len(meta.get("description", "")) > max_description:
            problems.append(f"{rel}: description is {len(meta['description'])} chars, over {max_description}")
        entries.append({"file": rel, "chars": len(listed), "tokens": tokens_of(len(listed))})
    return entries, problems


def report(root: Path, budget: int, max_description: int) -> dict[str, Any]:
    entries, problems = measure(root, max_description)
    total: int = sum(entry["tokens"] for entry in entries)
    if total > budget:
        problems.append(f"always-loaded metadata is about {total} tokens, over the {budget} budget")
    return {"ok": not problems, "tokens": total, "budget": budget, "method": "chars/4", "entries": entries, "problems": problems}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PLUGIN_ROOT), help="plugin root")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="max approximate tokens")
    parser.add_argument("--max-description", type=int, default=DEFAULT_MAX_DESCRIPTION, help="max chars per description")
    args: argparse.Namespace = parser.parse_args()
    result: dict[str, Any] = report(Path(args.root), args.budget, args.max_description)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
