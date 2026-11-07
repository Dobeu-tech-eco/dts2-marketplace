"""User-selectable lead provider: lead_eligible, signoff_agent, the model skill, the default setting."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "delegate.py"
PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "model" / "SKILL.md"
LOCAL_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "dts2-harness.local.md"
ADVISORY_ROLES: Final[tuple[str, ...]] = ("reviewer", "second-opinion")


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("delegate_lead_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["delegate_lead_under_test"] = module
    spec.loader.exec_module(module)
    return module


def all_profiles() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        loaded[data["name"]] = data
    return loaded


def frontmatter_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}:"):
            return line[len(key) + 1:].split("#")[0].strip()
    return ""


class LeadEligibleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.profiles: dict[str, dict[str, Any]] = all_profiles()

    def test_includes_claude_and_codex(self) -> None:
        eligible: list[str] = self.mod.lead_eligible(self.profiles)
        self.assertIn("claude", eligible)
        self.assertIn("codex", eligible)

    def test_excludes_profiles_without_advisory_roles(self) -> None:
        eligible: list[str] = self.mod.lead_eligible(self.profiles)
        for name in ("cursor", "antigravity", "opencode", "copilot"):
            self.assertNotIn(name, eligible, name)
        for name, profile in self.profiles.items():
            if not any(role in profile["roles"] for role in ADVISORY_ROLES):
                self.assertNotIn(name, eligible, name)

    def test_every_eligible_profile_has_an_advisory_role(self) -> None:
        for name in self.mod.lead_eligible(self.profiles):
            self.assertTrue(any(role in self.profiles[name]["roles"] for role in ADVISORY_ROLES), name)


class SignoffAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.profiles: dict[str, dict[str, Any]] = all_profiles()

    def test_eligible_provider_is_used(self) -> None:
        self.assertEqual(self.mod.signoff_agent(self.profiles, "codex"), "codex")

    def test_unknown_provider_falls_back_to_claude(self) -> None:
        self.assertEqual(self.mod.signoff_agent(self.profiles, "nope"), "claude")

    def test_ineligible_provider_falls_back_to_claude(self) -> None:
        self.assertEqual(self.mod.signoff_agent(self.profiles, "cursor"), "claude")


class SettingAndSkillTests(unittest.TestCase):
    def test_default_lead_provider_is_claude(self) -> None:
        self.assertEqual(frontmatter_value(LOCAL_TEMPLATE, "lead_provider"), "claude")

    def test_delegation_settings_present(self) -> None:
        self.assertEqual(frontmatter_value(LOCAL_TEMPLATE, "max_execution_effort"), "high")
        self.assertEqual(frontmatter_value(LOCAL_TEMPLATE, "delegation_strict"), "true")

    def test_model_skill_exists_without_angle_brackets(self) -> None:
        self.assertTrue(SKILL.is_file())
        description: str = frontmatter_value(SKILL, "description")
        self.assertTrue(description)
        self.assertNotIn("<", description)
        self.assertNotIn(">", description)

    def test_model_skill_says_execution_is_unaffected(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        self.assertIn("lead_provider", text)
        self.assertIn("cheapest capable", text)


if __name__ == "__main__":
    unittest.main()
