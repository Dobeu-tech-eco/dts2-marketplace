"""Whole-skill text for a skill split into a router SKILL.md plus phase files (Q-10): the router first, then the other
files in name order, joined with a newline. Same shape as helpers.read_run_skill()."""
from __future__ import annotations

from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SKILLS: Final[Path] = PLUGIN_ROOT / "skills"


def skill_dir(name: str) -> Path:
    return SKILLS / name


def read_skill(name: str) -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(skill_dir(name).glob("*.md")))


SPLIT_ROUTERS: Final[frozenset[str]] = frozenset({"skills/autopilot/SKILL.md", "skills/setup/SKILL.md"})


def read_rel(relative: str) -> str:
    """A file under the plugin root; a split skill's SKILL.md reads as the whole skill (router plus phase files)."""
    if relative in SPLIT_ROUTERS:
        return read_skill(relative.split("/")[1])
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")
