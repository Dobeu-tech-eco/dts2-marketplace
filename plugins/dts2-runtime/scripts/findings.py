#!/usr/bin/env python3
"""Reviewer findings merged once (Q-21): parse each axis report, calibrate severities, dedupe by file:line keeping the higher
severity, and render the digest the final reviewer reads. Parallel axes repeat each other; this is the one place that merges them.

  merge  REPORT... [--repo R --base REF]    calibrated, deduped findings (markdown, or --json)
  digest REPORT... [--repo R --base REF]    the findings digest plus `git diff --stat` for the final whole-diff reviewer

A reviewer may rate a finding `### Pre-existing`: a problem already on the base ref, not introduced by the diff. Pre-existing
findings are reported in their own section and never count toward the verdict. With `--base`, each pre-existing label is checked
against the diff: one placed on a line the diff actually changes is refused and comes back as a HIGH finding on the change.

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
PRE_EXISTING: Final[str] = "PRE-EXISTING"              # the heading that marks a finding as already on the base ref
PRE_EXISTING_TITLE: Final[str] = "Pre-existing"        # how that section is rendered back
PRE_EXISTING_SEVERITY: Final[str] = "LOW"              # a reported-not-counted finding carries the lowest severity
REFUSED_LABEL_SEVERITY: Final[str] = "HIGH"            # a pre-existing label the diff contradicts becomes a real finding
HUNK: Final[re.Pattern[str]] = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
NEW_FILE: Final[str] = "+++ "                          # the `git diff` line that names the file a hunk belongs to
NO_FILE: Final[str] = "/dev/null"                      # a deleted file's +++ target


@dataclass(frozen=True)
class Finding:
    file: str | None
    line: int | None
    severity: str
    text: str
    axes: tuple[str, ...]
    note: str = ""
    pre_existing: bool = False

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
    """The bullets under the CRITICAL, HIGH, MEDIUM, LOW and Pre-existing headings of one reviewer report. Other sections
    end a severity block. A Pre-existing bullet is kept at the lowest severity and flagged, to be reported but not counted."""
    axes: tuple[str, ...] = (axis_name(axis) if axis else header_axis(report),)
    severity: str | None = None
    found: list[Finding] = []
    for raw in report.splitlines():
        heading: re.Match[str] | None = HEADING.match(raw)
        if heading:
            name: str = heading.group(1).strip().upper().replace(" ", "-")
            severity = name if name in (*SEVERITIES, PRE_EXISTING) else None
            continue
        bullet: re.Match[str] | None = BULLET.match(raw)
        if severity is None or bullet is None or bullet.group(3).strip().lower() in EMPTY_TEXT:
            continue
        place, number, text = bullet.group(1), bullet.group(2), bullet.group(3)
        old: bool = severity == PRE_EXISTING
        found.append(Finding(place.strip() if place else None, int(number) if number else None,
                             PRE_EXISTING_SEVERITY if old else severity, text, axes, pre_existing=old))
    return found


def parse_hunks(diff: str) -> dict[str, set[int]]:
    """The added or changed line numbers per file, read from `git diff -U0` hunk headers (the new-side start and count)."""
    lines: dict[str, set[int]] = {}
    current: str | None = None
    for raw in diff.splitlines():
        if raw.startswith(NEW_FILE):
            path = raw[len(NEW_FILE):].strip()
            current = None if path == NO_FILE else path[2:] if path.startswith("b/") else path
            continue
        hunk: re.Match[str] | None = HUNK.match(raw)
        if hunk and current is not None:
            start: int = int(hunk.group(1))
            count: int = int(hunk.group(2)) if hunk.group(2) else 1
            lines.setdefault(current, set()).update(range(start, start + max(count, 1)))
    return lines


def changed_lines(repo: str, base: str) -> dict[str, set[int] | None] | None:
    """Per file, the line numbers the diff from `base` adds or changes; an untracked file maps to None (treat every line as
    new). None overall means git failed, so no pre-existing label can be checked."""
    done = subprocess.run(["git", "-C", repo, "diff", "-U0", "--no-color", base], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return None
    changed: dict[str, set[int] | None] = dict(parse_hunks(done.stdout))
    untracked = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=False)
    if untracked.returncode == 0:
        for path in (line.strip() for line in untracked.stdout.splitlines() if line.strip()):
            changed[path] = None
    return changed


def touches(finding: Finding, changed: dict[str, set[int] | None]) -> bool:
    """True when the diff adds or changes the finding's cited line (or any line of an untracked file it names)."""
    if finding.file is None:
        return False
    for path, lines in changed.items():
        if path.endswith(finding.file) or finding.file.endswith(path):
            if lines is None or finding.line is None or finding.line in lines:
                return True
    return False


def check_label(finding: Finding, changed: dict[str, set[int] | None] | None, checked: bool) -> Finding:
    """Resolve a pre-existing label. No file:line: drop it and cap the finding (nothing to locate it on base). No --base:
    keep it unchecked. git failed: drop it unverified. The diff touches the cited line: refuse it, the diff owns that line,
    so it becomes a HIGH finding. Otherwise keep it as pre-existing."""
    if not finding.pre_existing:
        return finding
    if finding.key is None:
        return replace(finding, pre_existing=False, severity=UNPLACED_CAP, note="pre-existing label dropped: no file:line")
    if not checked:
        return finding
    if changed is None:
        return replace(finding, pre_existing=False, severity=UNPLACED_CAP, note="pre-existing label unverified: git diff failed")
    if touches(finding, changed):
        return replace(finding, pre_existing=False, severity=REFUSED_LABEL_SEVERITY,
                       note="pre-existing label refused: the diff changes this line")
    return finding


def calibrate(finding: Finding) -> Finding:
    """Cap by dimension, then cap a finding with no file:line. Notes record why a severity moved. A pre-existing finding
    keeps its own severity and is never capped here."""
    if finding.pre_existing:
        return finding
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
    """Two findings on one file:line: the higher severity's text and severity, the union of the axes. A diff-introduced
    finding outranks a pre-existing one, so the change is never hidden behind a pre-existing label on the same line."""
    if first.pre_existing != other.pre_existing:
        winner, loser = (first, other) if other.pre_existing else (other, first)
    else:
        winner, loser = (other, first) if rank(other.severity) < rank(first.severity) else (first, other)
    axes: tuple[str, ...] = tuple(dict.fromkeys((*winner.axes, *loser.axes)))
    return replace(winner, axes=axes)


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """One finding per file:line (the higher severity wins). A finding with no file:line is only merged with an identical
    text. Pre-existing findings sort after the counted ones."""
    placed: dict[tuple[str, int] | tuple[str, str], Finding] = {}
    for finding in findings:
        key: tuple[str, int] | tuple[str, str] = finding.key or ("text", finding.text.strip().lower())
        placed[key] = merged(placed[key], finding) if key in placed else finding
    return sorted(placed.values(), key=lambda f: (f.pre_existing, rank(f.severity), f.file or "", f.line or 0))


def merge_reports(reports: Iterable[tuple[str, str | None]], changed: dict[str, set[int] | None] | None = None,
                  checked: bool = False) -> list[Finding]:
    """(report text, axis or None) pairs -> calibrated, deduped findings, worst first. With `changed` line data (from
    `--base`), each pre-existing label is checked against the diff before calibration."""
    labelled = (check_label(f, changed, checked) for text, axis in reports for f in parse_findings(text, axis))
    return dedupe(calibrate(f) for f in labelled)


def weighed(findings: list[Finding]) -> list[Finding]:
    """The findings that count toward the verdict: pre-existing ones are reported but never block a change."""
    return [f for f in findings if not f.pre_existing]


def verdict(findings: list[Finding]) -> str:
    counted: list[Finding] = weighed(findings)
    if any(f.severity in DIGEST_FULL for f in counted):
        return "BLOCK"
    return "APPROVE_WITH_CHANGES" if counted else "APPROVE"


def bullet(finding: Finding) -> str:
    where: str = f"{finding.file}:{finding.line}" if finding.key else (finding.file or "no location")
    tag: str = f" (axes: {', '.join(finding.axes)})" if len(finding.axes) > 1 else ""
    return f"- [{where}] {finding.text}{tag}"


def render(findings: list[Finding]) -> str:
    counted: list[Finding] = weighed(findings)
    lines: list[str] = []
    for severity in SEVERITIES:
        lines.append(f"### {severity}")
        lines += [bullet(f) for f in counted if f.severity == severity]
    pre: list[Finding] = [f for f in findings if f.pre_existing]
    if pre:
        lines.append(f"### {PRE_EXISTING_TITLE}")
        lines += [bullet(f) for f in pre]
    return "\n".join([*lines, f"### Verdict: {verdict(findings)}"]) + "\n"


def digest(findings: list[Finding], diff_stat: str) -> str:
    """The final reviewer's input: counts, every CRITICAL and HIGH in full, the rest as counts per file, then the diff
    stat. Pre-existing findings are summed on their own line and never count toward the verdict."""
    counted: list[Finding] = weighed(findings)
    counts: str = ", ".join(f"{sum(1 for f in counted if f.severity == s)} {s}" for s in SEVERITIES)
    lines: list[str] = [f"Findings so far: {counts}", ""]
    full: list[Finding] = [f for f in counted if f.severity in DIGEST_FULL]
    lines += [f"- {f.severity} [{f.file}:{f.line}] {f.text}" if f.key else f"- {f.severity} {f.text}" for f in full]
    rest: dict[str, int] = {}
    for f in (x for x in counted if x.severity not in DIGEST_FULL):
        rest[f.file or "no location"] = rest.get(f.file or "no location", 0) + 1
    lines += [f"- {n} lower finding(s) in {path}" for path, n in sorted(rest.items())]
    pre_count: int = sum(1 for f in findings if f.pre_existing)
    if pre_count:
        lines.append(f"- {pre_count} pre-existing finding(s), not counted toward the verdict")
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
    return [{"file": f.file, "line": f.line, "severity": f.severity, "text": f.text, "axes": list(f.axes),
             "note": f.note, "pre_existing": f.pre_existing} for f in findings]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge_p = sub.add_parser("merge")
    merge_p.add_argument("reports", nargs="+")
    merge_p.add_argument("--json", action="store_true")
    merge_p.add_argument("--repo", default=".")
    merge_p.add_argument("--base", default=None, help="the run's base ref; when given, pre-existing labels are checked against the diff")
    digest_p = sub.add_parser("digest")
    digest_p.add_argument("reports", nargs="+")
    digest_p.add_argument("--repo", default=".")
    digest_p.add_argument("--base", default=None, help="the run's base ref; omit to print the digest without a diff stat")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        reports: list[tuple[str, str | None]] = load_reports(args.reports)
    except OSError as error:
        print(f"findings error: {error}", file=sys.stderr)
        return 1
    base: str | None = getattr(args, "base", None)
    changed: dict[str, set[int] | None] | None = changed_lines(args.repo, base) if base else None
    found: list[Finding] = merge_reports(reports, changed, checked=bool(base))
    if args.command == "merge":
        print(json.dumps(as_json(found)) if args.json else render(found), end="" if not args.json else "\n")
        return 0
    print(digest(found, diff_stat(args.repo, base) if base else ""), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
