"""scripts/marketing-select.py and the self-sufficient gtm skill."""
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

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "marketing-select.py"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "gtm" / "SKILL.md"
ALWAYS_ON: Final[list[str]] = ["product-marketing-context", "competitor-profiling", "launch-strategy"]
WEB_SKILLS: Final[list[str]] = ["seo-audit", "page-cro", "copywriting", "copy-editing"]
ANALYTICS: Final[str] = "analytics-tracking"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("marketing_select_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["marketing_select_under_test"] = module
    spec.loader.exec_module(module)
    return module


def is_subsequence(chosen: list[str], order: tuple[str, ...]) -> bool:
    positions: list[int] = [order.index(name) for name in chosen]
    return positions == sorted(positions)


class SelectMarketingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_empty_facts_give_always_on_in_order(self) -> None:
        self.assertEqual(self.mod.select_marketing({}), ALWAYS_ON)

    def test_web_adds_seo_cro_and_copy_in_order(self) -> None:
        chosen: list[str] = self.mod.select_marketing({"has_web": True})
        for name in WEB_SKILLS:
            self.assertIn(name, chosen)
        self.assertTrue(is_subsequence(chosen, self.mod.MARKETING_ORDER))

    def test_landing_adds_seo_and_cro_only(self) -> None:
        chosen: list[str] = self.mod.select_marketing({"has_landing": True})
        self.assertIn("seo-audit", chosen)
        self.assertIn("page-cro", chosen)
        self.assertNotIn("copywriting", chosen)

    def test_marketing_surface_adds_copy_only(self) -> None:
        chosen: list[str] = self.mod.select_marketing({"has_marketing_surface": True})
        self.assertIn("copywriting", chosen)
        self.assertIn("copy-editing", chosen)
        self.assertNotIn("seo-audit", chosen)

    def test_analytics_only_when_asked(self) -> None:
        self.assertNotIn(ANALYTICS, self.mod.select_marketing({"has_web": True}))
        self.assertNotIn(ANALYTICS, self.mod.select_marketing({"analytics": False}))
        self.assertIn(ANALYTICS, self.mod.select_marketing({"analytics": True}))

    def test_no_duplicates_and_known_names(self) -> None:
        everything: dict[str, bool] = {"has_web": True, "has_landing": True,
                                       "has_marketing_surface": True, "analytics": True}
        chosen: list[str] = self.mod.select_marketing(everything)
        self.assertEqual(len(chosen), len(set(chosen)))
        self.assertEqual(chosen, list(self.mod.MARKETING_ORDER))

    def test_cli_prints_json_list(self) -> None:
        result = subprocess.run(
            ["python3", "-I", str(SCRIPT), "--facts", json.dumps({"has_web": True})],
            capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), self.mod.select_marketing({"has_web": True}))

    def test_cli_rejects_non_object(self) -> None:
        result = subprocess.run(["python3", "-I", str(SCRIPT), "--facts", "[1]"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


class GtmSelfSufficientTests(unittest.TestCase):
    def test_never_hard_stops_and_self_installs(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        for needle in ("npx skills add https://github.com/coreyhaines31/marketingskills",
                       "marketing-select.py", ".harness/latest.md", "deep-interview", "one pass"):
            self.assertIn(needle, text)
        self.assertNotIn("and stop.", text)

    def test_description_has_no_angle_brackets(self) -> None:
        line: str = next(l for l in SKILL.read_text(encoding="utf-8").splitlines()
                         if l.startswith("description:"))
        self.assertNotIn("<", line)
        self.assertNotIn(">", line)

    def test_order_mirrors_skill_reference_block(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        order: tuple[str, ...] = load_module().MARKETING_ORDER
        positions: list[int] = [text.find(f"/marketing-skills:{n}") for n in order]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
