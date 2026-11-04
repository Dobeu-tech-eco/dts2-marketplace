"""Supply-chain helpers for companion skills: commit pins, update proposals, lock freshness.

Pure functions. The caller (skills-check.py) supplies the network and process access, so nothing
here runs a command. A pin is a full 40-character commit SHA kept in `.harness/keep.yaml`; an update
is only ever proposed here and applied by an explicit, separate step.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Final

PIN_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
REPO_URL: Final[re.Pattern[str]] = re.compile(
    r"https://github\.com/([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)(?:/tree/[0-9a-f]{40})? --skill ([A-Za-z0-9][\w.-]*)", re.ASCII)
SHORT_REF: Final[re.Pattern[str]] = re.compile(r"([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)@([A-Za-z0-9][\w.-]*)", re.ASCII)
LOCK_MAX_AGE_S: Final[int] = 24 * 3600
MAX_FILES_SHOWN: Final[int] = 20
INSTRUCTION_SUFFIXES: Final[tuple[str, ...]] = (".md", ".mdx", ".txt", ".yaml", ".yml", ".json")
PROPOSALS_FILE: Final[str] = "skill-updates.json"

HeadFn = Callable[[str], "str | None"]
FilesFn = Callable[[str, str, str], "list[str] | None"]


def valid_pin(value: str) -> bool:
    return bool(PIN_RE.fullmatch(value))


def repo_and_skill(ref: str) -> tuple[str, str] | None:
    for pattern in (REPO_URL, SHORT_REF):
        m = pattern.fullmatch(ref.strip())
        if m:
            return m.group(1), m.group(2)
    return None


def pinned_ref(ref: str, pin: str) -> str | None:
    """The install ref that fetches the skill at exactly `pin`; None when the ref or pin is not allowlisted."""
    parsed = repo_and_skill(ref)
    if parsed is None or not valid_pin(pin):
        return None
    return f"https://github.com/{parsed[0]}/tree/{pin} --skill {parsed[1]}"


def set_pin_text(text: str, name: str, sha: str) -> str:
    """Return keep.yaml text with `pin: <sha>` on the `name` skill entry (replacing an existing pin).

    An entry that is not there yet is appended under `skills:` with the default companion source left
    to the caller; here the text is unchanged when the entry is missing."""
    newline: str = "\r\n" if "\r\n" in text else "\n"
    lines: list[str] = text.splitlines()
    head = re.compile(rf"^(\s*)-\s*name:\s*{re.escape(name)}\s*(#.*)?$")
    out: list[str] = []
    state: str = "scan"
    indent: str = ""
    for line in lines:
        if state == "inside":
            if line.strip().startswith("pin:"):
                continue  # dropped; the fresh pin was written right after the name line
            if not line.strip() or line.strip().startswith("#") or not line.startswith(indent + " "):
                state = "done"
        if state == "scan":
            m = head.match(line)
            if m:
                indent = m.group(1)
                out.extend([line, f"{indent}  pin: {sha}"])
                state = "inside"
                continue
        out.append(line)
    return newline.join(out) + newline if state != "scan" else text


def lock_age_s(repo: Path, now: float | None = None) -> float | None:
    try:
        return (now if now is not None else time.time()) - (repo / "skills-lock.json").stat().st_mtime
    except OSError:
        return None


def lock_lists(repo: Path, name: str) -> bool:
    try:
        data = json.loads((repo / "skills-lock.json").read_text(encoding="utf-8"))
        return name in data["skills"]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def skip_install(repo: Path, name: str, now: float | None = None) -> bool:
    """True when the lock file is under 24 hours old and already lists the skill: a recent install ran."""
    age = lock_age_s(repo, now)
    return age is not None and 0 <= age < LOCK_MAX_AGE_S and lock_lists(repo, name)


def build_proposals(entries: list[dict[str, str]], head_of: HeadFn, files_between: FilesFn) -> list[dict[str, object]]:
    """One proposal per skill whose upstream head differs from its pin (or that has no pin yet).

    Each carries the changed file names and whether any instruction-bearing file changed, so a person
    can read the diff before approving. Nothing is installed or written to keep.yaml here."""
    heads: dict[str, str | None] = {}
    proposals: list[dict[str, object]] = []
    for entry in entries:
        parsed = repo_and_skill(entry["ref"])
        if parsed is None:
            continue
        repo_id, skill = parsed
        if repo_id not in heads:
            heads[repo_id] = head_of(repo_id)
        head = heads[repo_id]
        pin = entry.get("pin", "")
        if head is None or not valid_pin(head) or head == pin:
            continue
        files = files_between(repo_id, pin, head) if pin else None
        shown = [f for f in (files or []) if skill in f.split("/") or "/" not in f][:MAX_FILES_SHOWN]
        proposals.append({
            "name": entry["name"], "repo": repo_id, "pinned": pin or None, "upstream": head,
            "kind": "update" if pin else "pin",
            "compare_url": f"https://github.com/{repo_id}/compare/{pin}...{head}" if pin else None,
            "changed_files": shown, "changed_total": None if files is None else len(files),
            "instruction_files_changed": any(f.endswith(INSTRUCTION_SUFFIXES) for f in shown),
            "apply": f"skills-check.py <repo> --fix --apply-update {entry['name']}={head}",
        })
    return proposals


def add_entry_text(text: str, name: str, ref: str, sha: str) -> str:
    """Append a `skills:` entry (name, source, pin) for a default companion keep.yaml does not list yet."""
    newline: str = "\r\n" if "\r\n" in text else "\n"
    lines: list[str] = text.splitlines()
    entry: list[str] = [f"  - name: {name}", f"    source: npx skills add {ref}", f"    pin: {sha}", "    serves: harness"]
    at: int = next((i + 1 for i, line in enumerate(lines) if re.match(r"^skills:\s*(#.*)?$", line)), -1)
    if at < 0:
        lines.append("skills:")
        at = len(lines)
    lines[at:at] = entry
    return newline.join(lines) + newline
