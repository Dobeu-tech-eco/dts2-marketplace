#!/usr/bin/env python3
"""Give every detected agent a project memory file, seeded from one shared source. Idempotent; never clobbers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import state_io  # noqa: E402
from state_io import atomic_write  # noqa: E402
from profiles import PROFILE_DIR, Profiles  # noqa: E402

START_MARKER: Final[str] = "<!-- dts2:start -->"
END_MARKER: Final[str] = "<!-- dts2:end -->"
LEGACY_START_MARKER: Final[str] = "<!-- dts2-harness:start -->"
LEGACY_END_MARKER: Final[str] = "<!-- dts2-harness:end -->"
DEFAULT_RULES_FILE: Final[str] = "AGENTS.md"
DEFAULT_AGENTS: Final[str] = "claude"
LIST_SEPARATOR: Final[str] = ","
HANDOFF_POINTER: Final[str] = (
    "Harness state for any agent: .harness/handoff/latest.md (resume with /dt:run resume)."
)


def rules_files(profiles: dict[str, dict[str, Any]], agents: list[str]) -> list[str]:
    """Distinct rulesFile values for the given agents, sorted. A missing rulesFile means AGENTS.md."""
    found: set[str] = {
        profiles[name].get("rulesFile") or DEFAULT_RULES_FILE for name in agents if name in profiles
    }
    return sorted(found)


def memory_seed(project_name: str) -> str:
    return "\n".join([
        f"# Project memory: {project_name}",
        "",
        f"- Project: {project_name}",
        "- Approved end state: .harness/end-state.md",
        f"- {HANDOFF_POINTER}",
        "- Conventions and constraints: .harness/discipline.md and .harness/review-checklist.md.",
        "- Every agent in this repo shares this context, whichever rules file it reads.",
    ])


def managed_block(project_name: str) -> str:
    return f"{START_MARKER}\n{memory_seed(project_name)}\n{END_MARKER}\n"


def migrate_legacy(text: str, block: str) -> str | None:
    """Replace a pre-4.0 managed block (start through end marker) with `block`; None when there is no closed one."""
    start: int = text.find(LEGACY_START_MARKER)
    if start < 0:
        return None
    end: int = text.find(LEGACY_END_MARKER, start + len(LEGACY_START_MARKER))
    if end < 0:
        return None
    return text[:start] + block.rstrip("\n") + text[end + len(LEGACY_END_MARKER):]


def sync_file(path: Path, project_name: str) -> str:
    """Create the file, append the managed block once, migrate a pre-4.0 block, or leave it alone. Returns the action taken."""
    block: str = managed_block(project_name)
    if not path.exists():
        atomic_write(path, block)
        return "wrote"
    text: str = path.read_text(encoding="utf-8")
    if START_MARKER in text:
        return "unchanged"
    if LEGACY_START_MARKER in text:
        migrated: str | None = migrate_legacy(text, block)
        if migrated is None:
            return "unchanged"
        atomic_write(path, migrated)
        return "migrated"
    separator: str = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    atomic_write(path, text + separator + block)
    return "updated"


def project_name_for(directory: Path) -> str:
    config: Path = state_io.harness_path(directory, "config.yaml")
    if config.is_file():
        name: str = miniyaml.get_str(miniyaml.parse(config.read_text(encoding="utf-8")), "project")
        if name:
            return name
    return directory.resolve().name


def write_all(directory: Path, agents: list[str], project_name: str) -> list[str]:
    profiles: dict[str, dict[str, Any]] = Profiles.load(PROFILE_DIR).as_dict()
    lines: list[str] = []
    for name in rules_files(profiles, agents):
        lines.append(f"{sync_file(directory / name, project_name)} {name}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", required=True, metavar="DIR")
    parser.add_argument("--agents", default=DEFAULT_AGENTS)
    parser.add_argument("--project", default=None)
    args = parser.parse_args()
    directory: Path = Path(args.write)
    if not directory.is_dir():
        print(f"agent-memory error: '{directory}' is not a directory", file=sys.stderr)
        return 1
    agents: list[str] = [a.strip() for a in args.agents.split(LIST_SEPARATOR) if a.strip()]
    name: str = args.project or project_name_for(directory)
    for line in write_all(directory, agents, name):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
