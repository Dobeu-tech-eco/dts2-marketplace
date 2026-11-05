"""Every skill and agent frontmatter must be valid YAML: an unquoted ': ' inside a plain scalar breaks YAML-based loaders."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FILES: Final[list[Path]] = sorted([*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*.md")])
KEY_LINE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s+(.*))?$")

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # the minimal parser below covers the one failure mode that matters
    yaml = None


def frontmatter(path: Path) -> str:
    text: str = path.read_text(encoding="utf-8")
    match: re.Match[str] | None = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if match is None:
        raise ValueError(f"{path}: no frontmatter block")
    return match.group(1)


def minimal_check(block: str) -> None:
    """Reject a plain (unquoted) scalar value that contains ': ' or ' #', the two sequences YAML reads as syntax."""
    for line in block.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#", "-")):
            continue
        match: re.Match[str] | None = KEY_LINE.match(line)
        if match is None:
            raise ValueError(f"not a 'key: value' line: {line[:60]!r}")
        value: str = (match.group(2) or "").strip()
        if not value or value[0] in "\"'|>[{&*!":
            continue
        if ": " in value or " #" in value or value.endswith(":"):
            raise ValueError(f"unquoted ': ' in plain scalar: {line[:80]!r}")


class SkillFrontmatterYaml(unittest.TestCase):
    def test_files_were_found(self) -> None:
        self.assertGreaterEqual(len(FILES), 20)

    def test_every_frontmatter_parses(self) -> None:
        for path in FILES:
            with self.subTest(path=str(path.relative_to(ROOT))):
                block: str = frontmatter(path)
                minimal_check(block)
                if yaml is not None:
                    data: Any = yaml.safe_load(block)
                    self.assertIsInstance(data, dict)
                    self.assertIsInstance(data.get("name"), str)
                    self.assertIsInstance(data.get("description"), str)

    def test_minimal_check_rejects_the_known_bad_shape(self) -> None:
        with self.assertRaises(ValueError):
            minimal_check("name: x\ndescription: Run things: fast and slow")
        minimal_check('name: x\ndescription: "Run things: fast and slow"')


if __name__ == "__main__":
    unittest.main()
