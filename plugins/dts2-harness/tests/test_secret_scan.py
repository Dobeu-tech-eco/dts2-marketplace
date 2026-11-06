"""No key-shaped string ships in the plugin's templates, profiles, skills, agents or docs."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import son_launch  # noqa: E402

SCAN_DIRS: Final[tuple[str, ...]] = ("templates", "profiles", "skills", "agents", "docs")
SUFFIXES: Final[frozenset[str]] = frozenset({".md", ".json", ".yaml", ".yml", ".txt", ".sh", ".py", ".toml", ".example", ".tmpl", ""})
FAKE_MARKER: Final[re.Pattern[str]] = re.compile(r"FAKE|EXAMPLE|PLACEHOLDER|NEVER-PRINT|x{8,}|\.\.\.", re.IGNORECASE)
SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"), re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"xai-[A-Za-z0-9]{20,}"), re.compile(r"ghp_[A-Za-z0-9]{30,}"),
)


def shipped_files() -> list[Path]:
    return [p for d in SCAN_DIRS for p in sorted((PLUGIN_ROOT / d).rglob("*"))
            if p.is_file() and p.suffix in SUFFIXES and "__pycache__" not in p.parts]


def key_shaped_lines(path: Path) -> list[str]:
    hits: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for shape in SHAPES:
            for match in shape.finditer(line):
                if not FAKE_MARKER.search(match.group(0)):
                    hits.append(f"{path.relative_to(PLUGIN_ROOT)}:{number}")
    return hits


class SecretScanTests(unittest.TestCase):
    def test_something_is_scanned(self) -> None:
        self.assertGreater(len(shipped_files()), 20)

    def test_no_key_shaped_string_ships(self) -> None:
        hits: list[str] = [h for path in shipped_files() for h in key_shaped_lines(path)]
        self.assertEqual(hits, [], "key-shaped strings (use an obvious FAKE fixture instead)")

    def test_the_scan_catches_a_real_looking_key(self) -> None:
        text: str = "key: sk-" + "Zq9" * 8
        self.assertTrue(son_launch.secret_shaped(text))
        self.assertTrue(any(s.search(text) for s in SHAPES))

    def test_fake_fixtures_are_allowed(self) -> None:
        self.assertFalse(son_launch.secret_shaped("sk-test-FAKE"))
        self.assertTrue(FAKE_MARKER.search("sk-test-FAKE"))


if __name__ == "__main__":
    unittest.main()
