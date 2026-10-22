"""scripts/failover.py: pick the next lead provider when the current one stalls."""
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

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "failover.py"
PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("failover_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["failover_under_test"] = module
    spec.loader.exec_module(module)
    return module


def all_profiles() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        loaded[data["name"]] = data
    return loaded


class NextLeadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.profiles: dict[str, dict[str, Any]] = all_profiles()
        self.eligible: list[str] = self.mod.lead_eligible(self.profiles)
        self.verified: list[str] = [
            n for n in self.eligible if self.profiles[n].get("verified") is True
        ]
        self.unverified: list[str] = [n for n in self.eligible if n not in self.verified]
        self.ordered: list[str] = self.verified + self.unverified

    def test_returns_a_different_eligible_provider(self) -> None:
        chosen: str | None = self.mod.next_lead(self.profiles, "claude")
        self.assertIsNotNone(chosen)
        self.assertNotEqual(chosen, "claude")
        self.assertIn(chosen, self.eligible)

    def test_none_when_everything_else_is_excluded(self) -> None:
        others: list[str] = [n for n in self.eligible if n != "claude"]
        self.assertIsNone(self.mod.next_lead(self.profiles, "claude", exclude=others))

    def test_result_is_eligible_and_never_current(self) -> None:
        for current in list(self.profiles):
            chosen: str | None = self.mod.next_lead(self.profiles, current)
            self.assertIn(chosen, self.eligible, current)
            self.assertNotEqual(chosen, current)

    def test_excluded_providers_are_never_returned(self) -> None:
        excluded: list[str] = []
        current: str = "claude"
        while True:
            chosen = self.mod.next_lead(self.profiles, current, exclude=excluded)
            if chosen is None:
                break
            self.assertNotIn(chosen, excluded)
            excluded.append(chosen)
        self.assertEqual(set(excluded), set(self.eligible) - {"claude"})

    def test_order_is_verified_first_then_alphabetical_and_wraps(self) -> None:
        self.assertEqual(self.verified, sorted(self.verified))
        self.assertEqual(self.unverified, sorted(self.unverified))
        self.assertEqual(self.mod.verified_first(self.profiles), self.ordered)
        last: str = self.ordered[-1]
        self.assertEqual(self.mod.next_lead(self.profiles, last), self.ordered[0])

    def test_current_outside_eligible_starts_from_the_top(self) -> None:
        self.assertEqual(self.mod.next_lead(self.profiles, "cursor"), self.ordered[0])

    def test_verified_provider_is_returned_before_any_unverified(self) -> None:
        self.assertIn("codex", self.verified)
        self.assertEqual(self.mod.next_lead(self.profiles, "claude"), "codex")
        self.assertEqual(self.mod.next_lead(self.profiles, "muse"), self.verified[0])

    def test_unverified_only_when_all_verified_are_excluded(self) -> None:
        unverified_names: set[str] = {"muse", "gemini", "grok"}
        self.assertTrue(unverified_names <= set(self.unverified))
        excluded: list[str] = [n for n in self.verified if n != "claude"]
        returned: list[str] = []
        while True:
            chosen: str | None = self.mod.next_lead(
                self.profiles, "claude", exclude=excluded + returned,
            )
            if chosen is None:
                break
            self.assertIn(chosen, self.unverified)
            returned.append(chosen)
        self.assertEqual(set(returned), self.unverified_set())

    def unverified_set(self) -> set[str]:
        return set(self.unverified)

    def test_single_eligible_profile_has_no_failover(self) -> None:
        only: dict[str, dict[str, Any]] = {"claude": self.profiles["claude"]}
        self.assertIsNone(self.mod.next_lead(only, "claude"))


class CliTests(unittest.TestCase):
    def test_cli_prints_next(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--current", "claude", "--exclude", "codex"],
            capture_output=True, text=True, check=True,
        )
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["current"], "claude")
        self.assertNotIn(data["next"], (None, "claude", "codex"))

    def test_cli_prints_null_when_none_remain(self) -> None:
        mod: ModuleType = load_module()
        others: str = ",".join(n for n in mod.lead_eligible(all_profiles()) if n != "claude")
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--current", "claude", "--exclude", others],
            capture_output=True, text=True, check=True,
        )
        self.assertIsNone(json.loads(result.stdout)["next"])


if __name__ == "__main__":
    unittest.main()
