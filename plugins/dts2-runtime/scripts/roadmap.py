#!/usr/bin/env python3
"""The roadmap: a deterministic view of `.harness/end-state.md`.

The scope is the list of sections and acceptance criteria. Statuses are not part of the scope, so finishing work never
changes its hash; adding, removing or renaming a section or criterion does. The person approves a scope by listing its
12-character key under `roadmap` in `.claude/settings.local.json` (see approvals.py).

Subcommands:
    status   print the roadmap status as JSON (counts, scope key, whether the person approved it)
    hash     print the full scope hash; print nothing and exit 1 when there is no scope
    build    write the Markdown view to `.harness/roadmap.md`; exit 1 when there is no end state"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approvals  # noqa: E402
import contracts  # noqa: E402
import state_io  # noqa: E402

ROADMAP_REL: Final[str] = state_io.rel("roadmap.md")
APPROVAL_KIND: Final[str] = "roadmap"
KEY_LENGTH: Final[int] = 12
PLACEHOLDER_PREFIX: Final[str] = "<"
DONE_STATUS: Final[str] = "done"
LINE_SEPARATOR: Final[str] = "\n"
WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
NO_KEY_LABEL: Final[str] = "none"
EXIT_FAILURE: Final[int] = 1


def clean(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip()


def section_rows(end_state: str) -> list[contracts.SectionRow]:
    rows: list[contracts.SectionRow] | contracts.Invalid = contracts.parse_sections(end_state)
    if isinstance(rows, contracts.Invalid):
        return []
    return [row for row in rows if not row.name.startswith(PLACEHOLDER_PREFIX)]


def acceptance_rows(end_state: str) -> list[contracts.Acceptance]:
    found: list[contracts.Acceptance] | contracts.Invalid = contracts.parse_acceptance(end_state)
    if isinstance(found, contracts.Invalid):
        return []
    return [item for item in found if not item.text.startswith(PLACEHOLDER_PREFIX)]


def scope_lines(end_state: str) -> list[str]:
    lines: list[str] = [f"section|{row.number}|{clean(row.name)}" for row in section_rows(end_state)]
    lines += [f"acceptance|{clean(item.text)}" for item in acceptance_rows(end_state)]
    return lines


def scope_hash(end_state: str) -> str | None:
    lines: list[str] = scope_lines(end_state)
    if not lines:
        return None
    return hashlib.sha256(LINE_SEPARATOR.join(lines).encode("utf-8")).hexdigest()


def read_end_state(repo: Path) -> str | None:
    path: Path = repo / state_io.END_STATE_REL
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def approve_with(key: str | None, approved: bool) -> str | None:
    if key is None or approved:
        return None
    return json.dumps({approvals.APPROVALS_KEY: {APPROVAL_KIND: [key]}})


def status(repo: Path) -> dict[str, Any]:
    text: str | None = read_end_state(repo)
    body: str = text or ""
    sections: list[contracts.SectionRow] = section_rows(body)
    acceptance: list[contracts.Acceptance] = acceptance_rows(body)
    digest: str | None = scope_hash(body)
    key: str | None = digest[:KEY_LENGTH] if digest else None
    approved: bool = key is not None and approvals.is_human_approved(APPROVAL_KIND, key, repo)
    return {
        "end_state": text is not None,
        "sections": len(sections),
        "sections_outstanding": sum(1 for row in sections if row.status != DONE_STATUS),
        "acceptance": len(acceptance),
        "acceptance_outstanding": sum(1 for item in acceptance if not item.done),
        "hash": digest,
        "key": key,
        "approved": approved,
        "approve_with": approve_with(key, approved),
    }


def section_table(end_state: str) -> list[str]:
    lines: list[str] = ["| # | section | status |", "|---|---|---|"]
    lines += [f"| {row.number} | {clean(row.name)} | {row.status} |" for row in section_rows(end_state)]
    return lines


def acceptance_list(end_state: str) -> list[str]:
    return [f"- [{'x' if item.done else ' '}] {clean(item.text)}" for item in acceptance_rows(end_state)]


def render(repo: Path) -> str:
    end_state: str = read_end_state(repo) or ""
    info: dict[str, Any] = status(repo)
    lines: list[str] = [
        "# Roadmap", "",
        f"- scope key: {info['key'] or NO_KEY_LABEL}",
        f"- approved: {'yes' if info['approved'] else 'no'}", "",
        "## Sections", "", *section_table(end_state), "",
        "## Acceptance criteria", "", *acceptance_list(end_state),
    ]
    return LINE_SEPARATOR.join(lines) + LINE_SEPARATOR


def build(repo: Path) -> tuple[dict[str, str], int]:
    if read_end_state(repo) is None:
        return {"error": "no end state"}, EXIT_FAILURE
    target: Path = state_io.atomic_write(repo / ROADMAP_REL, render(repo))
    return {"written": str(target)}, 0


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repo root (default: the current folder)")
    sub: Any = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print the roadmap status as JSON")
    sub.add_parser("hash", help="print the full scope hash")
    sub.add_parser("build", help="write .harness/roadmap.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    repo: Path = Path(args.repo)
    if args.command == "status":
        sys.stdout.write(json.dumps(status(repo)) + LINE_SEPARATOR)
        return 0
    if args.command == "hash":
        digest: str | None = scope_hash(read_end_state(repo) or "")
        if digest is None:
            return EXIT_FAILURE
        sys.stdout.write(digest + LINE_SEPARATOR)
        return 0
    result, code = build(repo)
    sys.stdout.write(json.dumps(result) + LINE_SEPARATOR)
    return code


if __name__ == "__main__":
    sys.exit(main())
