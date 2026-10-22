"""scripts/skill-suggest.py and the find-skills skill."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "skill-suggest.py"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "find-skills" / "SKILL.md"
DESIGN_SKILLS: Final[frozenset[str]] = frozenset({"impeccable", "frontend-design", "critique"})


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("skill_suggest_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["skill_suggest_under_test"] = module
    spec.loader.exec_module(module)
    return module


def description_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


class SuggestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_pr_fact_adds_pr_skills(self) -> None:
        result: list[str] = self.mod.suggest({"has_pr": True})
        self.assertIn("pr", result)
        self.assertIn("resolving-merge-conflicts", result)

    def test_frontend_fact_adds_a_design_skill(self) -> None:
        self.assertTrue(DESIGN_SKILLS & set(self.mod.suggest({"has_frontend": True})))

    def test_missing_tests_adds_a_test_skill(self) -> None:
        self.assertIn("test-driven-development", self.mod.suggest({"has_tests": False}))
        self.assertNotIn("test-driven-development", self.mod.suggest({"has_tests": True}))

    def test_empty_facts_still_return_the_general_set(self) -> None:
        result: list[str] = self.mod.suggest({})
        self.assertIn("grill-me", result)
        self.assertIn("research", result)

    def test_absent_facts_never_match(self) -> None:
        self.assertNotIn("test-driven-development", self.mod.suggest({}))

    def test_no_duplicates_and_stable_order(self) -> None:
        facts: dict[str, bool] = {
            "has_tests": True, "has_ci": True, "is_brownfield": True, "is_large": True, "has_pr": True,
            "has_frontend": True, "has_marketing": True, "has_agent_docs": True,
        }
        first: list[str] = self.mod.suggest(facts)
        self.assertEqual(len(first), len(set(first)))
        self.assertEqual(first, self.mod.suggest(dict(reversed(list(facts.items())))))
        self.assertEqual(first[:2], ["grill-me", "research"])

    def test_cli_prints_json_list(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--facts", json.dumps({"has_pr": True})],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("pr", json.loads(result.stdout))

    def test_cli_rejects_bad_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--facts", "{nope"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)


class SkillTests(unittest.TestCase):
    def test_skill_exists_without_angle_brackets(self) -> None:
        self.assertTrue(SKILL.is_file())
        description: str = description_of(SKILL)
        self.assertTrue(description)
        self.assertNotIn("<", description)
        self.assertNotIn(">", description)

    def test_skill_is_runnable_any_time_and_wires_in(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        for needle in (
            "any point", "scope-check.py", "repo-size.py", "env-detect.py", "AskUserQuestion",
            "skill-suggest.py", ".harness/keep.yaml",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
