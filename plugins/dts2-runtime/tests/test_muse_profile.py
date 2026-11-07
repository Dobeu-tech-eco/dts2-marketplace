"""The Muse Code (Meta) agent profile."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

MUSE: Final[Path] = PLUGIN_ROOT / "profiles" / "agents" / "muse.json"
MODEL_TIERS: Final[tuple[str, ...]] = ("frontier", "standard", "economy")


class MuseProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data: dict[str, Any] = json.loads(MUSE.read_text(encoding="utf-8"))

    def test_identity(self) -> None:
        self.assertEqual(self.data["name"], "muse")
        self.assertEqual(self.data["displayName"], "Muse")
        self.assertEqual(self.data["command"], ["muse", "exec"])
        self.assertEqual(self.data["rulesFile"], "AGENTS.md")
        self.assertEqual(self.data["invocation"], "live")

    def test_model_tiers_present_and_unverified(self) -> None:
        self.assertEqual(set(self.data["models"]), set(MODEL_TIERS))
        self.assertFalse(self.data["modelsVerified"])

    def test_roles_and_verification(self) -> None:
        self.assertIn("builder", self.data["roles"])
        self.assertIn("second-opinion", self.data["roles"])
        self.assertIs(self.data["verified"], False)

    def test_effort_and_burn(self) -> None:
        self.assertEqual(self.data["effortLevels"], ["medium"])
        self.assertEqual(set(self.data["tokenBurn"]), {"frontier", "standard", "economy"})

    def test_readme_marks_muse_unverified(self) -> None:
        text: str = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Muse", text)
        self.assertIn("unverified", text)


if __name__ == "__main__":
    unittest.main()
