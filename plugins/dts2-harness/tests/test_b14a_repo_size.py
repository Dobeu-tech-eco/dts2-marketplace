"""AA-2: repo-size --json per-module lines, heavy-file list and section split."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "repo-size.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repo_size_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lines(n: int) -> str:
    return "x = 1\n" * n


class RepoSizeModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="b14a-size-"))
        for rel, n in (("api/a.py", 100), ("api/big.py", 600), ("web/b.py", 200), ("web/c.py", 50), ("root.py", 10)):
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(lines(n), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)

    def report(self) -> dict[str, object]:
        proc = subprocess.run(["python3", "-I", str(SCRIPT), str(self.repo), "--json"], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)

    def test_json_has_per_module_lines(self) -> None:
        self.assertEqual(self.report()["module_lines"], {".": 10, "api": 700, "web": 250})

    def test_json_lists_heavy_files_500_plus(self) -> None:
        self.assertEqual(self.report()["heavy"], [{"path": "api/big.py", "lines": 600}])

    def test_heavy_file_gets_its_own_section(self) -> None:
        sections = self.report()["sections"]
        heavy = [s for s in sections if s["heavy"]]
        self.assertEqual([s["files"] for s in heavy], [["api/big.py"]])
        api_rest = [s for s in sections if s["area"] == "api" and not s["heavy"]]
        self.assertEqual(api_rest[0]["lines"], 100)

    def test_section_cap_is_reported(self) -> None:
        self.assertEqual(self.report()["section_cap"], 1500)

    def test_module_over_cap_is_split_into_sections_under_cap(self) -> None:
        module = load()
        per_file = {f"m/f{i}.py": 400 for i in range(10)}
        sections = module.build_sections(per_file, heavy_lines=500, cap=1500)
        self.assertGreater(len(sections), 1)
        for section in sections:
            self.assertLessEqual(section["lines"], 1500)
            self.assertFalse(section["heavy"])
        self.assertEqual(sum(s["lines"] for s in sections), 4000)

    def test_plain_output_unchanged(self) -> None:
        proc = subprocess.run(["python3", "-I", str(SCRIPT), str(self.repo)], capture_output=True, text=True, check=True)
        self.assertIn("LOC, tier", proc.stdout)


class LeadUsesSectionsTests(unittest.TestCase):
    def test_lead_applies_heavy_and_cap_rules(self) -> None:
        text = (PLUGIN_ROOT / "agents" / "lead.md").read_text(encoding="utf-8")
        for needle in ("module_lines", "heavy", "1,500"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
