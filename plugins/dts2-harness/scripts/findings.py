#!/usr/bin/env python3
"""Reviewer findings merged once (Q-21): parse each axis report, calibrate severities, dedupe by file:line keeping the higher
severity, and render the digest the final reviewer reads. Parallel axes repeat each other; this is the one place that merges them.

  merge  REPORT...                          calibrated, deduped findings (markdown, or --json)
  digest REPORT... [--repo R --base REF]    the findings digest plus `git diff --stat` for the final whole-diff reviewer

The DIMENSIONS table is the one list of review dimensions and how far each may rate a finding."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, Iterable

SEVERITIES: Final[tuple[str, ...]] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
ALL_AXES: Final[str] = "all"
DEFECT_MARKER: Final[str] = "hides a defect"
DIGEST_FULL: Final[tuple[str, ...]] = ("CRITICAL", "HIGH")
DIGEST_MAX_LINES: Final[int] = 25
# axis -> the highest severity that dimension may rate on its own (None: no cap). Style, simplify and optimize findings are
# advice unless they hide a defect; critique is design opinion.
DIMENSIONS: Final[dict[str, str | None]] = {
    "correctness": None, "security": None, "performance": "HIGH", "style": "MEDIUM", "completeness": None,
    "critique": "MEDIUM", "walkthrough-findings": None, "simplify": "MEDIUM", "optimize": "MEDIUM",
}
AXIS_ALIASES: Final[dict[str, str]] = {"style and scope": "style", "scope": "style", "walkthrough": "walkthrough-findings"}
UNPLACED_CAP: Final[str] = "MEDIUM"  # a finding that names no file:line cannot be CRITICAL or HIGH: nothing to check it against
HEADING: Final[re.Pattern[str]] = re.compile(r"^#{2,4}\s+(.+?)\s*$")
AXIS_IN_HEADER: Final[re.Pattern[str]] = re.compile(r"\(axis:\s*([^)]+?)\s*\)")
BULLET: Final[re.Pattern[str]] = re.compile(r"^\s*[-*]\s+(?:\[([^\]]+?)(?::(\d+))?\]\s*)?(.+?)\s*$")
EMPTY_TEXT: Final[frozenset[str]] = frozenset({"none", "n/a", "-"})


@dataclass(frozen=True)
class Finding:
    file: str | None
    line: int | None
    severity: str
    text: str
    axes: tuple[str, ...]
    note: str = ""

    @property
    def key(self) -> tuple[str, int] | None:
        return (self.file, self.line) if self.file and self.line is not None else None


def rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def axis_name(raw: str) -> str:
    lowered: str = raw.strip().lower()
    return AXIS_ALIASES.get(lowered, lowered)


def header_axis(report: str) -> str:
    match: re.Match[str] | None = AXIS_IN_HEADER.search(report)
    return axis_name(match.group(1)) if match else ALL_AXES


def parse_findings(report: str, axis: str | None = None) -> list[Finding]:
    """The bullets under the CRITICAL, HIGH, MEDIUM and LOW headings of one reviewer report. Other sections end a severity block."""
    axes: tuple[str, ...] = (axis_name(axis) if axis else header_axis(report),)
    severity: str | None = None
    found: list[Finding] = []
    for raw in report.splitlines():
        heading: re.Match[str] | None = HEADING.match(raw)
        if heading:
            name: str = heading.group(1).strip().upper()
            severity = name if name in SEVERITIES else None
            continue
        bullet: re.Match[str] | None = BULLET.match(raw)
        if severity is None or bullet is None or bullet.group(3).strip().lower() in EMPTY_TEXT:
            continue
        place, number, text = bullet.group(1), bullet.group(2), bullet.group(3)
        found.append(Finding(place.strip() if place else None, int(number) if number else None, severity, text, axes))
    return found


def calibrate(finding: Finding) -> Finding:
    """Cap by dimension, then cap a finding with no file:line. Notes record why a severity moved."""
    severity: str = finding.severity
    notes: list[str] = []
    cap: str | None = DIMENSIONS.get(finding.axes[0])
    if cap and DEFECT_MARKER not in finding.text.lower() and rank(severity) < rank(cap):
        severity = cap
        notes.append(f"capped at {cap} for {finding.axes[0]}")
    if finding.key is None and rank(severity) < rank(UNPLACED_CAP):
        severity = UNPLACED_CAP
        notes.append(f"no file:line, capped at {UNPLACED_CAP}")
    return replace(finding, severity=severity, note="; ".join(notes)) if severity != finding.severity else finding


def merged(first: Finding, other: Finding) -> Finding:
    """Two findings on one file:line: the higher severity's text and severity, the union of the axes."""
    winner, loser = (other, first) if rank(other.severity) < rank(first.severity) else (first, other)
    axes: tuple[str, ...] = tuple(dict.fromkeys((*winner.axes, *loser.axes)))
    return replace(winner, axes=axes)


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """One finding per file:line (the higher severity wins). A finding with no file:line is only merged with an identical text."""
    placed: dict[tuple[str, int] | tuple[str, str], Finding] = {}
    for finding in findings:
        key: tuple[str, int] | tuple[str, str] = finding.key or ("text", finding.text.strip().lower())
        placed[key] = merged(placed[key], finding) if key in placed else finding
    return sorted(placed.values(), key=lambda f: (rank(f.severity), f.file or "", f.line or 0))


def merge_reports(reports: Iterable[tuple[str, str | None]]) -> list[Finding]:
    """(report text, axis or None) pairs -> calibrated, deduped findings, worst first."""
    return dedupe(calibrate(f) for text, axis in reports for f in parse_findings(text, axis))


def verdict(findings: list[Finding]) -> str:
    if any(f.severity in DIGEST_FULL for f in findings):
        return "BLOCK"
    return "APPROVE_WITH_CHANGES" if findings else "APPROVE"


def render(findings: list[Finding]) -> str:
    lines: list[str] = []
    for severity in SEVERITIES:
        lines.append(f"### {severity}")
        for f in (x for x in findings if x.severity == severity):
            where: str = f"{f.file}:{f.line}" if f.key else (f.file or "no location")
            tag: str = f" (axes: {', '.join(f.axes)})" if len(f.axes) > 1 else ""
            lines.append(f"- [{where}] {f.text}{tag}")
    return "\n".join([*lines, f"### Verdict: {verdict(findings)}"]) + "\n"


def digest(findings: list[Finding], diff_stat: str) -> str:
    """The final reviewer's input: counts, every CRITICAL and HIGH in full, the rest as counts per file, then the diff stat."""
    counts: str = ", ".join(f"{sum(1 for f in findings if f.severity == s)} {s}" for s in SEVERITIES)
    lines: list[str] = [f"Findings so far: {counts}", ""]
    full: list[Finding] = [f for f in findings if f.severity in DIGEST_FULL]
    lines += [f"- {f.severity} [{f.file}:{f.line}] {f.text}" if f.key else f"- {f.severity} {f.text}" for f in full]
    rest: dict[str, int] = {}
    for f in (x for x in findings if x.severity not in DIGEST_FULL):
        rest[f.file or "no location"] = rest.get(f.file or "no location", 0) + 1
    lines += [f"- {n} lower finding(s) in {path}" for path, n in sorted(rest.items())]
    if len(lines) > DIGEST_MAX_LINES:
        dropped: int = len(lines) - (DIGEST_MAX_LINES - 1)
        lines = [*lines[:DIGEST_MAX_LINES - 1], f"- ... {dropped} more line(s) not shown"]
    return "\n".join([*lines, "", "git diff --stat:", diff_stat.rstrip() or "(empty)"]) + "\n"


def diff_stat(repo: str, base: str) -> str:
    done = subprocess.run(["git", "-C", repo, "diff", "--stat", f"{base}..HEAD"], capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else f"(git diff --stat failed: {done.stderr.strip()})"


def load_reports(paths: list[str]) -> list[tuple[str, str | None]]:
    return [(Path(p).read_text(encoding="utf-8"), None) for p in paths]


def as_json(findings: list[Finding]) -> list[dict[str, Any]]:
    return [{"file": f.file, "line": f.line, "severity": f.severity, "text": f.text, "axes": list(f.axes), "note": f.note}
            for f in findings]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge_p = sub.add_parser("merge")
    merge_p.add_argument("reports", nargs="+")
    merge_p.add_argument("--json", action="store_true")
    digest_p = sub.add_parser("digest")
    digest_p.add_argument("reports", nargs="+")
    digest_p.add_argument("--repo", default=".")
    digest_p.add_argument("--base", default=None, help="the run's base ref; omit to print the digest without a diff stat")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        found: list[Finding] = merge_reports(load_reports(args.reports))
    except OSError as error:
        print(f"findings error: {error}", file=sys.stderr)
        return 1
    if args.command == "merge":
        print(json.dumps(as_json(found)) if args.json else render(found), end="" if not args.json else "\n")
        return 0
    print(digest(found, diff_stat(args.repo, args.base) if args.base else ""), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
