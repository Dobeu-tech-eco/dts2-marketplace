#!/usr/bin/env python3
"""Plan gate (AA-5): PASS or FAIL for a lead plan before the checkpoint. Read-only.

Checks: a `## Foundation` section, exclusive file ownership across Foundation, builders and integration, a valid
`complexity:` per builder (which fixes model and effort; no frontier builder), and prints an estimated token
count. Exit 0 on PASS, 1 on FAIL."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Final

EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
MODEL: Final[dict[str, str]] = {"mechanical": "haiku", "normal": "sonnet", "design": "sonnet"}
TOKENS_PER_TASK: Final[dict[str, int]] = {"mechanical": 15_000, "normal": 40_000, "design": 80_000}
TOKENS_PER_REVIEW_AXIS: Final[int] = 25_000
FOUNDATION_DEFAULT: Final[str] = "normal"
GLOB_CHARS: Final[tuple[str, ...]] = ("*", "?", "[")
FRONTIER_WORDS: Final[re.Pattern[str]] = re.compile(r"\b(opus|frontier)\b", re.IGNORECASE)
HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{2,3})\s+(.*)$")
BUILDER_HEADING: Final[re.Pattern[str]] = re.compile(r"^Builder\s+(\d+)\b")
OWNS: Final[re.Pattern[str]] = re.compile(r"\|\s*owns:\s*([^|]*)")
COMPLEXITY: Final[re.Pattern[str]] = re.compile(r"^complexity:\s*(\w+)", re.MULTILINE)
TASK_LINE: Final[re.Pattern[str]] = re.compile(r"^-\s+T\d+\b", re.MULTILINE)


def split_blocks(plan: str) -> list[tuple[str, str]]:
    """(heading text, body) for every `##` / `###` block, in order."""
    blocks: list[tuple[str, list[str]]] = []
    for line in plan.splitlines():
        match = HEADING.match(line)
        if match:
            blocks.append((match.group(2).strip(), [line]))
        elif blocks:
            blocks[-1][1].append(line)
    return [(title, "\n".join(body)) for title, body in blocks]


def owns_of(body: str) -> list[str]:
    paths: list[str] = []
    for match in OWNS.finditer(body):
        paths.extend(p.strip().strip("`") for p in match.group(1).split(",") if p.strip())
    return paths


def overlaps(a: str, b: str) -> bool:
    """Two ownership entries collide when equal, one is a dir/ prefix of the other, or a glob matches the other."""
    if a == b:
        return True
    for left, right in ((a, b), (b, a)):
        if left.endswith("/") and right.startswith(left):
            return True
        if any(ch in left for ch in GLOB_CHARS) and fnmatch.fnmatchcase(right, left):
            return True
    return False


def evaluate(plan: str) -> dict[str, object]:
    blocks: list[tuple[str, str]] = split_blocks(plan)
    failures: list[str] = []
    owners: list[tuple[str, str]] = []
    dispatches: list[dict[str, object]] = []
    tokens: int = 0
    has_foundation: bool = False
    for title, body in blocks:
        if title.startswith("Foundation"):
            has_foundation = True
            label: str = "Foundation"
            owners.extend((label, p) for p in owns_of(body))
            if TASK_LINE.search(body):
                tokens += TOKENS_PER_TASK[FOUNDATION_DEFAULT] * len(TASK_LINE.findall(body))
        elif title.startswith("Integration"):
            owners.extend(("Integration", p) for p in owns_of(body))
            tokens += TOKENS_PER_TASK[FOUNDATION_DEFAULT] * max(1, len(TASK_LINE.findall(body)))
        elif BUILDER_HEADING.match(title):
            label = "Builder " + BUILDER_HEADING.match(title).group(1)  # type: ignore[union-attr]
            owners.extend((label, p) for p in owns_of(body))
            found = COMPLEXITY.search(body)
            if not found or found.group(1) not in EFFORT:
                failures.append(f"{label}: missing or invalid complexity (mechanical|normal|design)")
                continue
            complexity: str = found.group(1)
            if FRONTIER_WORDS.search(title) or re.search(r"model:\s*(opus|frontier)", body, re.IGNORECASE):
                failures.append(f"{label}: a builder never runs a frontier model")
            count: int = max(1, len(TASK_LINE.findall(body)))
            estimate: int = TOKENS_PER_TASK[complexity] * count
            tokens += estimate
            dispatches.append({"builder": label, "complexity": complexity, "model": MODEL[complexity],
                               "effort": EFFORT[complexity], "tokens": estimate})
    if not has_foundation:
        failures.append("missing ## Foundation section (wave: 0)")
    if not dispatches:
        failures.append("no ### Builder sections found")
    reported: set[tuple[str, str, str]] = set()
    for i, (owner_a, path_a) in enumerate(owners):
        for owner_b, path_b in owners[i + 1:]:
            if owner_a != owner_b and overlaps(path_a, path_b):
                key = (path_a, owner_a, owner_b)
                if key not in reported:
                    reported.add(key)
                    failures.append(f"ownership: {path_a} is owned by both {owner_a} and {owner_b} ({path_b})")
    axes = re.search(r"^Axes:\s*([^;\n]*)", plan, re.MULTILINE)
    axis_count: int = len([a for a in axes.group(1).split(",") if a.strip()]) if axes else 0
    tokens += axis_count * TOKENS_PER_REVIEW_AXIS
    return {"verdict": "FAIL" if failures else "PASS", "failures": failures, "dispatches": dispatches,
            "estimated_tokens": tokens, "review_axes": axis_count}


def render(report: dict[str, object]) -> str:
    lines: list[str] = []
    for d in report["dispatches"]:  # type: ignore[attr-defined]
        lines.append(f"{d['builder']}: {d['complexity']} -> {d['model']}, effort {d['effort']} (~{d['tokens']:,} tokens)")
    lines.append(f"Estimated tokens: ~{report['estimated_tokens']:,} (builders plus {report['review_axes']} review axes)")
    for failure in report["failures"]:  # type: ignore[attr-defined]
        lines.append(f"FAIL: {failure}")
    lines.append(f"PLAN GATE: {report['verdict']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="path to the lead's plan markdown")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate(Path(args.plan).read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
