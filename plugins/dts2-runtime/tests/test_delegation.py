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
            self.assertEqual(result["tier"], "economy", name)
            expected: str = self.mod.clamp_effort("low", data["effortLevels"])
            self.assertEqual(result["effort"], expected, name)

    def test_exhausted_effort_is_clamped_to_profile_levels(self) -> None:
        muse: dict[str, Any] = profile("muse")
        result: dict[str, Any] = self.mod.delegate(muse, "execution", "mechanical", budget="exhausted")
        self.assertEqual(result["tier"], "economy")
        self.assertIn(result["effort"], muse["effortLevels"])
        self.assertNotEqual(result["effort"], "low")
        claude_result: dict[str, Any] = self.mod.delegate(self.claude, "execution", "mechanical", budget="exhausted")
        self.assertEqual(claude_result["effort"], "low")

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


class CodexTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.codex: dict[str, Any] = profile("codex")

    def test_builders_get_standard_or_economy_never_frontier(self) -> None:
        mechanical: dict[str, Any] = self.mod.delegate(self.codex, "execution", "mechanical")
        normal: dict[str, Any] = self.mod.delegate(self.codex, "execution", "normal")
        design: dict[str, Any] = self.mod.delegate(self.codex, "execution", "design")
        self.assertEqual((mechanical["tier"], mechanical["model"], mechanical["effort"]),
                         ("economy", "gpt-6-luna", "low"))
        self.assertEqual((normal["tier"], normal["model"], normal["effort"]),
                         ("standard", "gpt-6.1-sol", "medium"))
        self.assertEqual((design["tier"], design["model"], design["effort"]),
                         ("standard", "gpt-6.1-sol", "high"))
        for result in (mechanical, normal, design):
            self.assertNotEqual(result["tier"], "frontier")
            self.assertNotIn(result["effort"], ("xhigh", "max", "ultra"))

    def test_signoff_may_use_frontier_and_xhigh_not_max(self) -> None:
        normal: dict[str, Any] = self.mod.delegate(self.codex, "signoff", "normal")
        design: dict[str, Any] = self.mod.delegate(self.codex, "signoff", "design")
        self.assertEqual((normal["model"], normal["tier"], normal["effort"]), ("gpt-6-astra", "frontier", "high"))
        self.assertEqual((design["model"], design["tier"], design["effort"]), ("gpt-6-astra", "frontier", "xhigh"))
        self.assertNotIn(design["effort"], ("max", "ultra"))

    def test_advisory_design_is_frontier_high(self) -> None:
        result: dict[str, Any] = self.mod.delegate(self.codex, "advisory", "design")
        self.assertEqual((result["tier"], result["model"], result["effort"]), ("frontier", "gpt-6-astra", "high"))

    def test_explicit_max_is_kept_and_ultra_clamps_on_luna(self) -> None:
        requested: dict[str, Any] = self.mod.delegate(self.codex, "signoff", "normal", effort="max")
        self.assertEqual(requested["effort"], "max")
        clamped: dict[str, Any] = self.mod.delegate(self.codex, "execution", "mechanical", effort="ultra")
        self.assertEqual(clamped["model"], "gpt-6-luna")
        self.assertEqual(clamped["effort"], "max")

    def test_unpinned_default_reports_as_standard(self) -> None:
        self.assertEqual(self.mod.tier_of_model(self.codex, None), "standard")
        self.assertEqual(self.mod.tier_of_model(self.codex, "gpt-6.1-sol"), "standard")
        self.assertEqual(self.mod.tier_of_model(self.codex, "gpt-6-astra"), "frontier")
        self.assertEqual(self.mod.tier_of_model(self.codex, "gpt-6-luna"), "economy")
        line: str = self.mod.receipt_line(self.codex, "execution", "medium", None)
        self.assertEqual(line, "- codex gpt-6.1-sol tier=standard effort=medium (execution)")
        pinned: str = self.mod.receipt_line(self.codex, "signoff", "xhigh", "gpt-6-astra")
        self.assertEqual(pinned, "- codex gpt-6-astra tier=frontier effort=xhigh (signoff)")

    def test_claude_signoff_still_reaches_max(self) -> None:
        result: dict[str, Any] = self.mod.delegate(profile("claude"), "signoff", "design")
        self.assertEqual(result["effort"], "max")


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
        self.assertEqual(data["model"], "muse-spark-1.3")

    def test_unknown_agent_exits_one(self) -> None:
        result = self.run_cli("--agent", "nope", "--seat", "execution", "--complexity", "normal")
        self.assertEqual(result.returncode, 1)
        self.assertIn("nope", result.stderr)

    def test_explicit_effort_flag(self) -> None:
        result = self.run_cli(
            "--agent", "codex", "--seat", "signoff", "--complexity", "normal", "--effort", "ultra",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual((data["model"], data["effort"]), ("gpt-6-astra", "ultra"))

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
            self.assertTrue(set(data["effortLevels"]) <= {"low", "medium", "high", "xhigh", "max", "ultra"}, name)
            self.assertTrue(all(isinstance(v, int) and v >= 0 for v in data["tokenBurn"].values()), name)

    def test_verified_effort_levels(self) -> None:
        self.assertEqual(profile("claude")["effortLevels"], ["low", "medium", "high", "max"])
        self.assertEqual(profile("codex")["effortLevels"], ["low", "medium", "high", "xhigh", "max", "ultra"])
        for name in ("gemini", "grok", "opencode", "copilot", "cursor", "antigravity", "muse"):
            self.assertEqual(profile(name)["effortLevels"], ["medium"], name)


if __name__ == "__main__":
    unittest.main()
