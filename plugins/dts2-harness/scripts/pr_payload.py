#!/usr/bin/env python3
"""Payload helpers for the PR-receipt hook, one python process per hook run (AC-5).

parse           hook payload on stdin -> session id and PR selector, one per line (nothing, exit 1, when the command is not
                a Bash `gh pr create|edit`)
view            `gh pr view --json` output on stdin -> number, head branch, cross-repo flag, one per line; the body goes to
                --body-out
body            --body-file and --receipt-file -> the PR body with the receipt appended, on stdout
payload         JSON object for `gh api --input -` from key=value arguments (one builder, so quoting lives in one place)"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Final

PR_CMD: Final[re.Pattern[str]] = re.compile(r"(?:^|[;&|\n])[ \t]*gh pr (create|edit)\b([^;&|\n]*)")
VALUE_FLAGS: Final[frozenset[str]] = frozenset({
    "--title", "-t", "--body", "-b", "--body-file", "-F", "--base", "-B", "--head", "-H", "--label", "-l", "--assignee",
    "-a", "--reviewer", "-r", "--milestone", "-m", "--project", "-p", "--template", "-T", "--add-label",
    "--remove-label", "--add-assignee", "--remove-assignee", "--add-reviewer", "--remove-reviewer", "--add-project",
    "--remove-project"})
SELECTOR: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._/#:@%~+-]+$")
PR_URL: Final[re.Pattern[str]] = re.compile(r"https://[^\s]+/pull/\d+")
SESSION_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]")
NO_SESSION: Final[str] = "nosession"


def selector_from(kind: str, argument_text: str) -> str:
    """The PR selector named on a `gh pr create|edit` line: the --head value for create, the first positional for edit."""
    try:
        tokens: list[str] = shlex.split(argument_text)
    except ValueError:
        tokens = []
    selector: str = ""
    previous: str = ""
    skip: bool = False
    for token in tokens:
        if skip:
            skip = False
            if kind == "create" and previous in ("--head", "-H"):
                selector = token
            continue
        if token.startswith("-"):
            previous = token
            skip = "=" not in token and token in VALUE_FLAGS
            if token.startswith("--head=") and kind == "create":
                selector = token.split("=", 1)[1]
            continue
        if kind == "edit" and not selector:
            selector = token
    return selector if SELECTOR.match(selector) else ""


def parse_payload(data: Any) -> tuple[str, str] | None:
    """(session, selector) for a Bash `gh pr create|edit` payload, else None."""
    if not isinstance(data, dict):
        return None
    tool_input: Any = data.get("tool_input")
    command: str = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    match = PR_CMD.search(command) if data.get("tool_name") == "Bash" else None
    if not match:
        return None
    kind: str = match.group(1)
    selector: str = selector_from(kind, match.group(2))
    response: Any = data.get("tool_response")
    text: Any = response.get("stdout", "") if isinstance(response, dict) else (response or "")
    url = PR_URL.search(str(text))
    if kind == "create" and not selector and url:
        selector = url.group(0)
    return SESSION_UNSAFE.sub("", str(data.get("session_id", ""))) or NO_SESSION, selector


def view_fields(raw: Any) -> dict[str, str] | None:
    """number, body, branch, cross from `gh pr view --json` output; None when it does not parse or has no number."""
    if not isinstance(raw, dict) or raw.get("number") in (None, ""):
        return None
    cross: Any = raw.get("isCrossRepository")
    return {"number": str(raw["number"]), "body": str(raw.get("body") or ""), "branch": str(raw.get("headRefName") or ""),
            "cross": str(cross).lower() if isinstance(cross, bool) else str(cross or "")}


def body_with_receipt(body: str, receipt: str) -> str:
    return (f"{body}\n\n" if body else "") + receipt


def api_payload(pairs: list[str]) -> str:
    """A JSON object from `key=value` strings; a value is always a string, so nothing is evaluated or re-quoted."""
    fields: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        fields[key] = value
    return json.dumps(fields)


def load(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("parse")
    view_p = sub.add_parser("view")
    view_p.add_argument("--body-out", required=True)
    body_p = sub.add_parser("body")
    body_p.add_argument("--body-file", required=True)
    body_p.add_argument("--receipt-file", required=True)
    sub.add_parser("payload").add_argument("pairs", nargs="*")
    args = parser.parse_args()
    if args.command == "parse":
        parsed = parse_payload(load(sys.stdin.read()))
        if parsed is None:
            return 1
        print(parsed[0])
        print(parsed[1])
        return 0
    if args.command == "view":
        fields = view_fields(load(sys.stdin.read()))
        if fields is None:
            return 1
        Path(args.body_out).write_text(fields["body"], encoding="utf-8")
        print(fields["number"], fields["branch"], fields["cross"], sep="\n")
        return 0
    if args.command == "body":
        sys.stdout.write(body_with_receipt(Path(args.body_file).read_text(encoding="utf-8"),
                                           Path(args.receipt_file).read_text(encoding="utf-8")))
        return 0
    try:
        print(api_payload(args.pairs))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
