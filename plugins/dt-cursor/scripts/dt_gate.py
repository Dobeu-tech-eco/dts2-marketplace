"""Gates for the Cursor dt package. Standard library only.

This program writes a harness scaffold and checks approvals. It does not merge,
push, install packages, read credential files, broadcast to other sessions, or
spend a provider API. `--yes` and `--ship` are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

MISSING_END_STATE: Final[str] = "No end state yet; /dt-setup interviews to one."
KINDS: Final[frozenset[str]] = frozenset({"end-state", "plan", "ship"})
DECISIONS: Final[frozenset[str]] = frozenset({"approve", "edit", "stop"})
BLOCKED_ACTIONS: Final[dict[str, str]] = {
    "merge": "I approve merge",
    "sdk": "I approve sdk",
    "fleet-broadcast": "I approve fleet-broadcast",
    "hook-install": "I approve hook-install",
    "spend": "I approve spend",
}
BRIDGE: Final[dict[str, str]] = {
    "scope-check.py": "scope",
    "check-in.py": "check-in",
    "ensure-ignored.py": "ignore",
    "skills-check.py": "companions",
}
BLOCKED_SCRIPTS: Final[dict[str, str]] = {
    "hooks-setup.py": "hook-install",
    "fleet.py": "fleet-broadcast",
    "pr_sweep.py": "merge",
    "unattended.py": "hook-install",
}
PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FORBIDDEN_ARGS: Final[frozenset[str]] = frozenset({"--yes", "--ship", "--scaffold-only"})
IGNORE_BLOCK: Final[str] = (
    "# dt-cursor\n"
    ".harness/receipts/\n"
    ".harness/approvals.jsonl\n"
    ".harness/permissions.jsonl\n"
)


def _reject_grants(argv: list[str]) -> None:
    found = FORBIDDEN_ARGS.intersection(argv)
    if found:
        raise SystemExit(
            "rejected " + " ".join(sorted(found)) + ": not an approval and not a ship grant"
        )


def _repo(value: str) -> Path:
    return Path(value).resolve()


def _harness(repo: Path) -> Path:
    return repo / ".harness"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _end_state_status(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- status:", "status:")):
            return stripped.split(":", 1)[1].strip()
    return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise SystemExit(f"{path.name} row is not an object")
            rows.append(item)
    return rows


def _authorized(repo: Path, kind: str, digest: str) -> bool:
    for row in _read_jsonl(_harness(repo) / "approvals.jsonl"):
        if (
            row.get("kind") == kind
            and row.get("decision") == "approve"
            and row.get("sha256") == digest
        ):
            return True
    return False


def _subject(repo: Path, kind: str) -> Path:
    if kind == "end-state":
        return _harness(repo) / "end-state.md"
    if kind == "plan":
        return _harness(repo) / "plan.md"
    if kind == "ship":
        return _harness(repo) / "ship-summary.md"
    raise SystemExit(f"unknown kind {kind}")


def _stop_if_requested(repo: Path) -> None:
    if (_harness(repo) / "STOP").is_file():
        raise SystemExit("STOP file is present; the command ends")


def scope(path: Path) -> dict[str, Any]:
    cwd = path.resolve()
    manifest = ".harness-workspace.yaml"
    current = cwd
    for _ in range(8):
        parent = current.parent
        if parent == current:
            break
        if (parent / manifest).is_file():
            return {
                "scope": "workspace-member",
                "cwd": str(cwd),
                "workspaceRoot": str(parent),
                "advice": f"Run /dt-setup from {parent}.",
            }
        current = parent
    if (cwd / manifest).is_file():
        return {"scope": "workspace-root", "cwd": str(cwd), "workspaceRoot": str(cwd), "advice": "Workspace root."}
    if (cwd / ".harness" / "config.yaml").is_file():
        return {"scope": "single", "cwd": str(cwd), "workspaceRoot": None, "advice": "Single-repo harness."}
    return {"scope": "none", "cwd": str(cwd), "workspaceRoot": None, "advice": MISSING_END_STATE}


def check_in(repo: Path) -> str:
    end_state = _harness(repo) / "end-state.md"
    if not end_state.is_file():
        return MISSING_END_STATE
    items: list[tuple[str, str]] = []
    section = ""
    for line in end_state.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "Sections" and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[-1] not in {"todo", "in-progress", "blocked", "done"}:
                continue
            label = cells[1] if cells[0].isdigit() else cells[0]
            items.append((f"section: {label}", "complete" if cells[-1] == "done" else "outstanding"))
        elif section == "Acceptance criteria" and line.startswith("- ["):
            done = line.startswith(("- [x]", "- [X]"))
            label = line.split("]", 1)[-1].strip() or "acceptance"
            items.append((label, "complete" if done else "outstanding"))
    done_items = [name for name, status in items if status == "complete"]
    open_items = [name for name, status in items if status != "complete"]
    total = len(items)
    complete = len(done_items)
    percent = complete * 100 // total if total else 0
    lines = [f"{complete} of {total} complete ({percent}%)"]
    lines.extend(f"[x] {name}" for name in done_items)
    lines.extend(f"[ ] {name}" for name in open_items)
    if open_items:
        lines.append(f"Next: {open_items[0]}. Continue with /dt-run after a plan approval.")
    return "\n".join(lines)


def approve(repo: Path, kind: str, decision: str) -> dict[str, str]:
    if kind not in KINDS or decision not in DECISIONS:
        raise SystemExit("kind or decision is not one of the exact words")
    subject = _subject(repo, kind)
    if not subject.is_file():
        raise SystemExit(f"missing {subject.name}; nothing was recorded")
    if kind == "end-state" and decision == "approve" and _end_state_status(subject.read_text(encoding="utf-8")) != "approved":
        raise SystemExit("end state status is not approved; nothing was recorded")
    row = {"kind": kind, "decision": decision, "sha256": _sha256(subject)}
    path = _harness(repo) / "approvals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _write_if_absent(path: Path, text: str, wrote: list[str], kept: list[str]) -> None:
    if path.exists():
        kept.append(path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    wrote.append(path.name)


def scaffold(repo: Path) -> dict[str, Any]:
    _stop_if_requested(repo)
    end_state = _harness(repo) / "end-state.md"
    if not end_state.is_file():
        raise SystemExit(MISSING_END_STATE)
    if _end_state_status(end_state.read_text(encoding="utf-8")) != "approved":
        raise SystemExit("end state status is not approved")
    digest = _sha256(end_state)
    if not _authorized(repo, "end-state", digest):
        raise SystemExit("no end-state approval matches this file; kind alone is not authorization")
    templates = PLUGIN_ROOT / "templates"
    discipline = (templates / "discipline.md").read_text(encoding="utf-8")
    state = (templates / "state.md").read_text(encoding="utf-8")
    keep = (templates / "keep.yaml").read_text(encoding="utf-8")
    harness = _harness(repo)
    harness.mkdir(parents=True, exist_ok=True)
    wrote: list[str] = []
    kept: list[str] = []
    config = (
        f"project: {repo.name}\n"
        "commands:\n"
        "  test: \"\"\n"
        "  typecheck: \"\"\n"
        "  lint: \"\"\n"
        "  build: \"\"\n"
        "  quick: \"\"\n"
        "do_not_touch:\n"
        "  - .env\n"
        "  - .env.*\n"
        "  - secrets/**\n"
        "  - \"**/credentials*\"\n"
        "roster:\n"
        "  - name: cursor\n"
    )
    _write_if_absent(harness / "config.yaml", config, wrote, kept)
    _write_if_absent(harness / "discipline.md", discipline, wrote, kept)
    _write_if_absent(harness / "state.md", state, wrote, kept)
    _write_if_absent(harness / "keep.yaml", keep, wrote, kept)
    _write_if_absent(
        harness / "lessons.md",
        "# Lessons\n\n- [L-001] <rule> (source: <run or PR>)\n",
        wrote,
        kept,
    )
    _write_if_absent(
        harness / "review-checklist.md",
        "# Review\n\n- correctness\n- types\n- tests\n- security\n- conventions\n- scope\n",
        wrote,
        kept,
    )
    ignore(repo)
    return {"wrote": wrote, "kept": kept}


def ignore(repo: Path) -> dict[str, bool]:
    path = repo / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if IGNORE_BLOCK.strip() in existing:
        return {"changed": False}
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(prefix + IGNORE_BLOCK, encoding="utf-8")
    return {"changed": True}


def companions(argv: list[str]) -> dict[str, Any]:
    return {
        "freshness": "cursor",
        "installs": [],
        "removed": [],
        "fix_ignored": "--fix" in argv,
        "note": "companion installs are not run",
    }


def preflight(repo: Path, phase: str) -> dict[str, str]:
    _stop_if_requested(repo)
    end_state = _harness(repo) / "end-state.md"
    if not end_state.is_file():
        raise SystemExit(MISSING_END_STATE)
    if _end_state_status(end_state.read_text(encoding="utf-8")) != "approved":
        raise SystemExit("end state status is not approved")
    if not _authorized(repo, "end-state", _sha256(end_state)):
        raise SystemExit("no end-state approval matches this file")
    if phase in {"build", "ship"}:
        plan = _subject(repo, "plan")
        if not plan.is_file() or not _authorized(repo, "plan", _sha256(plan)):
            raise SystemExit("plan is not approved for these bytes")
    if phase == "ship":
        summary = _subject(repo, "ship")
        if not summary.is_file() or not _authorized(repo, "ship", _sha256(summary)):
            raise SystemExit("ship summary is not approved for these bytes")
    return {"phase": phase, "ok": "true"}


def permit(repo: Path, action: str, phrase: str) -> dict[str, str]:
    expected = BLOCKED_ACTIONS.get(action)
    if expected is None or phrase != expected:
        raise SystemExit("permission phrase does not match the action")
    row = {"action": action, "phrase": phrase}
    path = _harness(repo) / "permissions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def blocked(repo: Path, action: str) -> None:
    expected = BLOCKED_ACTIONS.get(action)
    if expected is None:
        raise SystemExit(f"unknown blocked action {action}")
    recorded = any(
        row.get("action") == action and row.get("phrase") == expected
        for row in _read_jsonl(_harness(repo) / "permissions.jsonl")
    )
    if not recorded:
        raise SystemExit(f"BLOCKED {action}: permission phrase is not recorded")
    print(
        f"CURSOR_UNSUPPORTED: {action} stays unexecuted in this package. "
        "Permission does not run a merge, a broadcast, a hook install, the headless SDK, or a paid provider call."
    )
    raise SystemExit(3)


def bridge(script: str, forwarded: list[str]) -> int:
    if script in BRIDGE:
        command = BRIDGE[script]
        if command == "companions":
            json.dump(companions(forwarded), sys.stdout)
            sys.stdout.write("\n")
            return 0
        path = forwarded[0] if forwarded else "."
        if command == "scope":
            json.dump(scope(Path(path)), sys.stdout)
            sys.stdout.write("\n")
            return 0
        if command == "check-in":
            print(check_in(_repo(path)))
            return 0
        if command == "ignore":
            json.dump(ignore(_repo(path)), sys.stdout)
            sys.stdout.write("\n")
            return 0
    action = BLOCKED_SCRIPTS.get(script, "")
    if action:
        print(
            f"BLOCKED unsupported-runtime-script {script}: maps to {action}, which this package does not execute."
        )
        return 2
    print(f"BLOCKED unsupported-runtime-script {script}: not included in the Cursor package. Do not improvise it.")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scope_parser = sub.add_parser("scope")
    scope_parser.add_argument("path", nargs="?", default=".")
    check = sub.add_parser("check-in")
    check.add_argument("path", nargs="?", default=".")
    approved = sub.add_parser("approve")
    approved.add_argument("--repo", required=True)
    approved.add_argument("--kind", required=True)
    approved.add_argument("--decision", required=True)
    scaffold_parser = sub.add_parser("scaffold")
    scaffold_parser.add_argument("path")
    pre = sub.add_parser("preflight")
    pre.add_argument("path")
    pre.add_argument("--phase", default="ready", choices=("ready", "build", "ship"))
    ign = sub.add_parser("ignore")
    ign.add_argument("path")
    comp = sub.add_parser("companions")
    comp.add_argument("rest", nargs=argparse.REMAINDER)
    perm = sub.add_parser("permit")
    perm.add_argument("--repo", required=True)
    perm.add_argument("--action", required=True)
    perm.add_argument("--phrase", required=True)
    block = sub.add_parser("blocked")
    block.add_argument("--repo", required=True)
    block.add_argument("--action", required=True)
    bridged = sub.add_parser("bridge")
    bridged.add_argument("script")
    bridged.add_argument("forwarded", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str]) -> int:
    _reject_grants(argv)
    args = _parser().parse_args(argv)
    if args.command == "scope":
        json.dump(scope(Path(args.path)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "check-in":
        print(check_in(_repo(args.path)))
        return 0
    if args.command == "approve":
        json.dump(approve(_repo(args.repo), args.kind, args.decision), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "scaffold":
        json.dump(scaffold(_repo(args.path)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "preflight":
        json.dump(preflight(_repo(args.path), args.phase), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "ignore":
        json.dump(ignore(_repo(args.path)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "companions":
        json.dump(companions(args.rest), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "permit":
        json.dump(permit(_repo(args.repo), args.action, args.phrase), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "blocked":
        blocked(_repo(args.repo), args.action)
        return 3
    if args.command == "bridge":
        return bridge(args.script, args.forwarded)
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            sys.exit(2)
        raise
