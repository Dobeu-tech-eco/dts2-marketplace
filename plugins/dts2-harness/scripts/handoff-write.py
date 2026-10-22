#!/usr/bin/env python3
"""Render .harness/handoff/latest.md from state, action items, the deploy block and the latest receipt. Never reads .env."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Final

HARNESS: Final[str] = ".harness"
OUTPUT: Final[str] = ".harness/handoff/latest.md"
TEMPLATE: Final[Path] = Path(__file__).resolve().parent.parent / "templates" / "handoff-latest.md"
ACTION_ITEMS_SCRIPT: Final[Path] = Path(__file__).resolve().parent / "action-items.py"
RECEIPT_PLACEHOLDER: Final[str] = "(filled at the ship checkpoint)"
RESUME_COMMAND: Final[str] = "/dts2-harness:run resume"
NEW_TASK: Final[str] = "No open items. Start a new task with `/dts2-harness:run <task>`."
MAX_STATE_ITEMS: Final[int] = 5
LEAD_LINE: Final[str] = "lead: claude (frontier)"
DEFAULT_COMPLEXITY: Final[str] = "normal"
COMPLEXITY_ORDER: Final[tuple[str, ...]] = ("mechanical", "normal", "design")
# Builders are execution seats: they never run a frontier model, harder work raises effort instead.
COMPLEXITY_TIER: Final[dict[str, str]] = {"mechanical": "economy", "normal": "standard", "design": "standard"}
COMPLEXITY_EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
COMPLEXITY: Final[re.Pattern[str]] = re.compile(r"complexity:\s*(mechanical|normal|design)")
SECRET_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=\S+")
DEPLOY_FIELD: Final[str] = r"^\s*{name}:\s*(\S+)"
SECTION_END: Final[re.Pattern[str]] = re.compile(r"^#{2,3} ", re.MULTILINE)
SECTIONS_HEADING: Final[str] = "## Sections"
BLOCKED_STATUS: Final[str] = "blocked"
ACTION_ID_SUFFIX: Final[re.Pattern[str]] = re.compile(r"^(.*?)\s*\(([A-Z]\d+)\)\s*$")
NO_ACTION_ID: Final[str] = "no action item"
SECTION_NUMBER_COL: Final[int] = 0
SECTION_NAME_COL: Final[int] = 1
SECTION_STATUS_COL: Final[int] = -1


def load_action_items() -> ModuleType:
    spec = importlib.util.spec_from_file_location("action_items", ACTION_ITEMS_SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["action_items"] = module
    spec.loader.exec_module(module)
    return module


def redact(text: str) -> str:
    return SECRET_ASSIGNMENT.sub(r"\1=<redacted>", text)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def section_bullets(text: str, heading: str) -> list[str]:
    start: int = text.find(f"## {heading}")
    if start < 0:
        return []
    body: str = text[start + len(heading) + 3:]
    end: re.Match[str] | None = SECTION_END.search(body)
    block: str = body[: end.start()] if end else body
    return [line for line in block.splitlines() if line.startswith("- ")]


def latest_run(repo: Path) -> Path | None:
    runs: list[Path] = sorted(p for p in (repo / HARNESS / "runs").glob("*") if p.is_dir())
    return runs[-1] if runs else None


def receipt_verdict(receipt: str) -> str:
    start: int = receipt.find("### Review verdict")
    if start < 0:
        return "unknown"
    lines: list[str] = receipt[start:].splitlines()[1:]
    for line in lines:
        if line.startswith("#"):
            break
        if line.strip():
            return line.strip()
    return "unknown"


def deploy_summary(end_state: str) -> str:
    fields: dict[str, str] = {}
    for name in ("provider", "productionUrl", "status"):
        match: re.Match[str] | None = re.search(DEPLOY_FIELD.format(name=name), end_state, re.MULTILINE)
        fields[name] = match.group(1) if match else "unset"
    return f"deploy: {fields['provider']}, {fields['productionUrl']}, status {fields['status']}"


def state_summary(repo: Path, run: Path | None) -> str:
    state: str = read(repo / HARNESS / "state.md")
    decisions: list[str] = section_bullets(state, "Decisions")
    failures: list[str] = section_bullets(state, "Failures and escalations")
    receipt: str = read(run / "receipt.md") if run else ""
    lines: list[str] = [
        f"- Last decision: {decisions[-1][2:] if decisions else 'none'}",
        f"- Last failure: {failures[-1][2:] if failures else 'none'}",
        f"- Review verdict: {receipt_verdict(receipt) if receipt else 'no receipt yet'}",
        f"- {deploy_summary(read(repo / HARNESS / 'end-state.md'))}",
    ]
    return redact("\n".join(lines))


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def blocked_sections(end_state: str) -> list[str]:
    start: int = end_state.find(SECTIONS_HEADING)
    if start < 0:
        return []
    body: str = end_state[start + len(SECTIONS_HEADING):]
    end: re.Match[str] | None = SECTION_END.search(body)
    rows: list[list[str]] = [table_cells(line) for line in (body[: end.start()] if end else body).splitlines() if line.startswith("|")]
    return [section_line(row) for row in rows if len(row) > 1 and row[SECTION_STATUS_COL] == BLOCKED_STATUS]


def section_line(row: list[str]) -> str:
    match: re.Match[str] | None = ACTION_ID_SUFFIX.match(row[SECTION_NAME_COL])
    name: str = match.group(1) if match else row[SECTION_NAME_COL]
    item_id: str = match.group(2) if match else NO_ACTION_ID
    return f"section {row[SECTION_NUMBER_COL]} {name} — blocked ({item_id})"


def format_item(item: dict[str, Any]) -> str:
    age: str = "age unknown" if item["age_days"] is None else f"{item['age_days']}d"
    owner: str = item["owner"] or "unassigned"
    return f"- {item['id']} {item['group']}: {item['item']} (owner {owner}, {age}) -> {item['resolve_command']}"


def open_items_text(items: list[dict[str, Any]], repo: Path) -> str:
    state_open: list[str] = section_bullets(read(repo / HARNESS / "state.md"), "Open items")
    lines: list[str] = [format_item(item) for item in items]
    lines += [f"- {line}" for line in blocked_sections(read(repo / HARNESS / "end-state.md"))]
    lines += [f"- state: {line[2:]}" for line in state_open[-MAX_STATE_ITEMS:]]
    return redact("\n".join(lines)) if lines else "none"


def next_action(items: list[dict[str, Any]], receipt: str, end_state: str) -> str:
    if items:
        return f"Resolve {items[0]['id']} ({items[0]['item']}): `{items[0]['resolve_command']}`"
    if receipt and RECEIPT_PLACEHOLDER in receipt:
        return "The latest receipt is not approved yet; finish the ship checkpoint with `/dts2-harness:run resume`."
    if re.search(r"status:\s*planned", end_state):
        return "The production target is planned but not built; run `/dts2-harness:run` to build it."
    return NEW_TASK


def highest_complexity(run: Path | None) -> str:
    found: list[str] = []
    for path in sorted(run.glob("*plan*.md")) if run else []:
        found += COMPLEXITY.findall(read(path))
    return max(found, key=COMPLEXITY_ORDER.index) if found else DEFAULT_COMPLEXITY


def recommended_agent(run: Path | None) -> str:
    complexity: str = highest_complexity(run)
    tier: str = COMPLEXITY_TIER[complexity]
    return (
        f"{LEAD_LINE}\nbuilder: claude ({tier}), effort {COMPLEXITY_EFFORT[complexity]}, "
        f"by the last plan's top complexity ({complexity})"
    )


def render(repo: Path, items: list[dict[str, Any]]) -> str:
    run: Path | None = latest_run(repo)
    receipt: str = read(run / "receipt.md") if run else ""
    values: dict[str, str] = {
        "<run>": run.name if run else "none",
        "<state>": state_summary(repo, run),
        "<open_items>": open_items_text(items, repo),
        "<next_action>": next_action(items, receipt, read(repo / HARNESS / "end-state.md")),
        "<recommended_agent>": recommended_agent(run),
    }
    text: str = TEMPLATE.read_text(encoding="utf-8")
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def write_handoff(repo: Path) -> dict[str, Any]:
    if not (repo / HARNESS).is_dir():
        return {"written": False, "reason": "no .harness directory"}
    module: ModuleType = load_action_items()
    items: list[dict[str, Any]] = module.list_items(read(repo / module.ITEMS_PATH).splitlines(), date.today())
    path: Path = repo / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(repo, items), encoding="utf-8")
    return {"written": True, "path": OUTPUT, "open_items": len(items), "resume": RESUME_COMMAND}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    args: argparse.Namespace = parser.parse_args()
    json.dump(write_handoff(Path(args.repo)), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
