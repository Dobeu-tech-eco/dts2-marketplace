#!/usr/bin/env python3
"""Collect the fixed FLAGS block of a builder report into .harness/runs/<stamp>/flags.md (AA-9).

The builder ends its report with `FLAGS:` and one `- KIND: text` line per flag (KIND is one of KINDS), or
`FLAGS: none`. The report comes in on stdin or --report-file; each call appends one `## Builder N` block."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import RUNS_REL, append_text  # noqa: E402

KINDS: Final[tuple[str, ...]] = ("SECRET", "OUTSIDE_FILE", "CONCERN", "ASSUMPTION", "SKIPPED")
HEADER: Final[str] = "# Flags\n"
FLAGS_LINE: Final[re.Pattern[str]] = re.compile(r"^FLAGS:\s*(.*)$")
FLAG_ITEM: Final[re.Pattern[str]] = re.compile(r"^-\s+([A-Za-z_]+):\s*(.*)$")


def parse(report: str) -> list[dict[str, str]]:
    """Flags from a builder report. `FLAGS: none` gives []; no FLAGS block gives one MISSING entry so the gap shows."""
    lines: list[str] = report.splitlines()
    for index, line in enumerate(lines):
        match = FLAGS_LINE.match(line.strip())
        if not match:
            continue
        if match.group(1).strip().lower() == "none":
            return []
        flags: list[dict[str, str]] = []
        for item in lines[index + 1:]:
            parsed = FLAG_ITEM.match(item.strip())
            if not parsed:
                break
            kind, text = parsed.group(1).upper(), parsed.group(2).strip()
            if kind in KINDS:
                flags.append({"kind": kind, "text": text})
            else:
                flags.append({"kind": "CONCERN", "text": f"{parsed.group(1)}: {text}"})
        return flags
    return [{"kind": "MISSING", "text": "report has no FLAGS block"}]


def render(builder: str, flags: list[dict[str, str]]) -> str:
    body: str = "\n".join(f"- {f['kind']}: {f['text']}" for f in flags) if flags else "- none"
    return f"\n## Builder {builder}\n{body}\n"


def collect(repo: Path, stamp: str, builder: str, report: str) -> tuple[Path, int]:
    flags: list[dict[str, str]] = parse(report)
    path: Path = repo / RUNS_REL / stamp / "flags.md"
    append_text(path, render(builder, flags), header=HEADER)
    return path, len(flags)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--builder", required=True)
    parser.add_argument("--report-file", default=None, help="read the report here instead of stdin")
    args = parser.parse_args()
    report: str = Path(args.report_file).read_text(encoding="utf-8") if args.report_file else sys.stdin.read()
    path, count = collect(Path(args.repo), args.stamp, args.builder, report)
    print(f"{path}: {count} flags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
