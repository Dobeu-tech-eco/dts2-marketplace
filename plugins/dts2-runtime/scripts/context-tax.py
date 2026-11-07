#!/usr/bin/env python3
"""Measure the always-loaded metadata tax: skill and agent name + description (+ when_to_use) text.

Tokens are approximated as characters / 4 (no tokenizer is bundled, so this is an estimate that errs
a little high for English). Skills with `disable-model-invocation: true` keep their description out of context, so they
are left out of the total and listed under `user_only` with their own token figure. Exit 1 when the total exceeds --budget or a single description exceeds --max-description.
JSON on stdout: {"ok", "tokens", "budget", "entries": [...], "user_only": [...], "problems": [...]}."""
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
BLOCK_MARKERS: Final[str] = ">|"
MALFORMED_START: Final[str] = "[>|"
KEY_LINE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")


def frontmatter(text: str) -> dict[str, str]:
    """Top-level keys of the leading --- block. A key whose value is empty or starts with `>` or `|` gathers the
    indented lines after it (joined with spaces), so folded descriptions and block lists are measured whole."""
    lines: list[str] = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    key: str | None = None
    gather: bool = False
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        match: re.Match[str] | None = KEY_LINE.match(line)
        if match:
            key = match.group(1)
            found[key] = match.group(2).strip()
            gather = not found[key] or found[key][0] in BLOCK_MARKERS
            if gather:
                found[key] = ""
        elif key is not None and gather and line[:1] in (" ", "\t") and line.strip():
            found[key] = (found[key] + " " + line.strip()).strip()
    return {}


def raw_values(text: str) -> dict[str, str]:
    """First-line value of each top-level key, exactly as written."""
    found: dict[str, str] = {}
    lines: list[str] = text.split("\n")
    for line in lines[1:] if lines and lines[0].strip() == "---" else []:
        if line.strip() == "---":
            break
        match: re.Match[str] | None = KEY_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def metadata_files(root: Path) -> list[Path]:
    return sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("agents/*.md"))


def tokens_of(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN)


def measure(root: Path, max_description: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    user_only: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in metadata_files(root):
        text: str = path.read_text(encoding="utf-8")
        meta: dict[str, str] = frontmatter(text)
        rel: str = str(path.relative_to(root))
        for key, raw in raw_values(text).items():
            if key in LISTED_KEYS and (not raw or raw[0] in MALFORMED_START):
                problems.append(f"{rel}: `{key}` is written as {raw[:2] or 'an empty value'!r}, use a one-line value so the size gate counts it")
        if not meta.get("description"):
            problems.append(f"{rel}: no description")
        listed: str = " ".join(meta.get(key, "") for key in LISTED_KEYS).strip()
        if len(meta.get("description", "")) > max_description:
            problems.append(f"{rel}: description is {len(meta['description'])} chars, over {max_description}")
        row: dict[str, Any] = {"file": rel, "chars": len(listed), "tokens": tokens_of(len(listed))}
        (user_only if meta.get("disable-model-invocation") == "true" else entries).append(row)
    return entries, user_only, problems


def report(root: Path, budget: int, max_description: int) -> dict[str, Any]:
    entries, user_only, problems = measure(root, max_description)
    total: int = sum(entry["tokens"] for entry in entries)
    if total > budget:
        problems.append(f"always-loaded metadata is about {total} tokens, over the {budget} budget")
    return {"ok": not problems, "tokens": total, "budget": budget, "method": "chars/4", "entries": entries, "user_only": user_only, "problems": problems}


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
