"""Strict delegation: frontier is for advice and sign-off only; builders raise effort, never tier."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "delegate.py"
PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
COMPLEXITIES: Final[tuple[str, ...]] = ("mechanical", "normal", "design")
BUDGETS: Final[tuple[str, ...]] = ("ok", "low", "exhausted")


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("delegate_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["delegate_under_test"] = module
    spec.loader.exec_module(module)
    return module


def profile(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return data


def all_profiles() -> dict[str, dict[str, Any]]:
    return {p.stem: profile(p.stem) for p in sorted(PROFILE_DIR.glob("*.json"))}


class ExecutionTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_tier_by_complexity(self) -> None:
        self.assertEqual(self.mod.execution_tier("mechanical"), "economy")
        self.assertEqual(self.mod.execution_tier("normal"), "standard")
        self.assertEqual(self.mod.execution_tier("design"), "standard")

    def test_assert_execution_not_frontier(self) -> None:
        with self.assertRaises(self.mod.DelegationError):
            self.mod.assert_execution_not_frontier("frontier")
        self.mod.assert_execution_not_frontier("standard")
        self.mod.assert_execution_not_frontier("economy")

    def test_violates_execution_policy(self) -> None:
        self.assertTrue(self.mod.violates_execution_policy("execution", "frontier"))
        self.assertFalse(self.mod.violates_execution_policy("advisory", "frontier"))
        self.assertFalse(self.mod.violates_execution_policy("signoff", "frontier"))
        self.assertFalse(self.mod.violates_execution_policy("execution", "standard"))


class ClampEffortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_clamp(self) -> None:
        self.assertEqual(self.mod.clamp_effort("max", ["low", "medium"]), "medium")
        self.assertEqual(self.mod.clamp_effort("high", ["low", "medium", "high", "max"]), "high")
        self.assertEqual(self.mod.clamp_effort("high", []), "medium")

    def test_below_all_available_uses_highest_available(self) -> None:
        self.assertEqual(self.mod.clamp_effort("low", ["medium"]), "medium")
        self.assertEqual(self.mod.clamp_effort("low", ["high", "max"]), "max")


class DelegateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.claude: dict[str, Any] = profile("claude")

    def test_execution_design_is_standard_high_never_frontier(self) -> None:
        result: dict[str, Any] = self.mod.delegate(self.claude, "execution", "design")
        self.assertEqual((result["tier"], result["effort"]), ("standard", "high"))
        self.assertEqual(result["model"], self.claude["models"]["standard"])
        self.assertNotEqual(result["model"], self.claude["models"]["frontier"])
        self.assertEqual(result["tokenBurn"], self.claude["tokenBurn"]["standard"])

    def test_signoff_design_is_frontier_max(self) -> None:
        result: dict[str, Any] = self.mod.delegate(self.claude, "signoff", "design")
        self.assertEqual((result["tier"], result["effort"]), ("frontier", "max"))
        self.assertEqual(result["model"], self.claude["models"]["frontier"])

    def test_advisory_tier_follows_complexity(self) -> None:
        self.assertEqual(self.mod.delegate(self.claude, "advisory", "normal")["tier"], "standard")
        self.assertEqual(self.mod.delegate(self.claude, "advisory", "design")["tier"], "frontier")

    def test_exhausted_budget_forces_economy_low(self) -> None:
        for name, data in all_profiles().items():
            result: dict[str, Any] = self.mod.delegate(data, "execution", "design", budget="exhausted")
            self.assertEqual((result["tier"], result["effort"]), ("economy", "low"), name)

    def test_low_budget_caps_effort_at_medium(self) -> None:
        result: dict[str, Any] = self.mod.delegate(self.claude, "execution", "design", budget="low")
        self.assertEqual(result["effort"], "medium")

    def test_effort_clamped_to_profile_levels(self) -> None:
        result: dict[str, Any] = self.mod.delegate(profile("muse"), "signoff", "design")
        self.assertEqual(result["effort"], "medium")

    def test_unknown_inputs_raise(self) -> None:
        for args in (("nope", "normal"), ("execution", "nope")):
            with self.assertRaises(self.mod.DelegationError):
                self.mod.delegate(self.claude, *args)
        with self.assertRaises(self.mod.DelegationError):
            self.mod.delegate(self.claude, "execution", "normal", budget="nope")

    def test_no_builder_path_yields_frontier(self) -> None:
        for name, data in all_profiles().items():
            for complexity in COMPLEXITIES:
                for budget in BUDGETS:
                    result: dict[str, Any] = self.mod.delegate(data, "execution", complexity, budget)
                    self.assertNotEqual(result["tier"], "frontier", (name, complexity, budget))
                    self.assertFalse(self.mod.violates_execution_policy("execution", result["tier"]))

    def test_lead_provider_ignored_for_execution(self) -> None:
        result: dict[str, Any] = self.mod.delegate(
            self.claude, "execution", "normal", lead_provider="codex", profiles=all_profiles(),
        )
        self.assertEqual(result["agent"], "claude")

    def test_lead_provider_sets_signoff_agent(self) -> None:
        result: dict[str, Any] = self.mod.delegate(
            self.claude, "signoff", "normal", lead_provider="codex", profiles=all_profiles(),
        )
        self.assertEqual(result["agent"], "codex")
        self.assertEqual(result["model"], profile("codex")["models"]["frontier"])


class DelegateCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, cwd=str(PLUGIN_ROOT),
        )

    def test_muse_execution_normal(self) -> None:
        result = self.run_cli("--agent", "muse", "--seat", "execution", "--complexity", "normal")
        self.assertEqual(result.returncode, 0, result.stderr)
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual((data["agent"], data["tier"], data["effort"]), ("muse", "standard", "medium"))
        self.assertEqual(data["model"], "muse-spark-1.2")

    def test_unknown_agent_exits_one(self) -> None:
        result = self.run_cli("--agent", "nope", "--seat", "execution", "--complexity", "normal")
        self.assertEqual(result.returncode, 1)
        self.assertIn("nope", result.stderr)

    def test_budget_flag(self) -> None:
        result = self.run_cli(
            "--agent", "claude", "--seat", "execution", "--complexity", "design", "--budget", "exhausted",
        )
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual((data["tier"], data["effort"]), ("economy", "low"))


class TokenBurnTests(unittest.TestCase):
    def test_every_profile_has_effort_and_burn(self) -> None:
        for name, data in all_profiles().items():
            self.assertEqual(set(data["tokenBurn"]), {"frontier", "standard", "economy"}, name)
            self.assertTrue(set(data["effortLevels"]) <= {"low", "medium", "high", "max"}, name)
            self.assertTrue(all(isinstance(v, int) and v >= 0 for v in data["tokenBurn"].values()), name)

    def test_verified_effort_levels(self) -> None:
        self.assertEqual(profile("claude")["effortLevels"], ["low", "medium", "high", "max"])
        self.assertEqual(profile("codex")["effortLevels"], ["low", "medium", "high"])
        for name in ("gemini", "grok", "opencode", "copilot", "cursor", "antigravity", "muse"):
            self.assertEqual(profile(name)["effortLevels"], ["medium"], name)


if __name__ == "__main__":
    unittest.main()
