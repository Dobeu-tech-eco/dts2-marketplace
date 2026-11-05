"""AC-2: delegate.py owns the complexity policy; handoff-write.recommended_agent() asks it, so the two cannot drift."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _load  # noqa: E402
from profiles import Profiles  # noqa: E402

delegate = _load.load("delegate")
handoff = _load.load("handoff-write")


class PolicyParityTests(unittest.TestCase):
    def test_handoff_recommendation_equals_delegate_for_every_complexity(self) -> None:
        claude = Profiles.load().get("claude")
        for complexity in delegate.COMPLEXITY_ORDER:
            plan = delegate.delegate(claude, "execution", complexity)
            self.assertEqual(delegate.builder_recommendation(complexity, claude), (plan["tier"], plan["effort"]))
            text = handoff.recommended_agent_for(complexity)
            self.assertIn(f"builder: claude ({plan['tier']}), effort {plan['effort']}", text)

    def test_handoff_keeps_no_policy_tables_of_its_own(self) -> None:
        source = (SCRIPTS / "handoff-write.py").read_text(encoding="utf-8")
        for name in ("COMPLEXITY_TIER", "COMPLEXITY_EFFORT", "COMPLEXITY_ORDER"):
            self.assertNotIn(name + ":", source)

    def test_highest_complexity(self) -> None:
        self.assertEqual(delegate.highest_complexity([]), "normal")
        self.assertEqual(delegate.highest_complexity(["mechanical", "design", "normal"]), "design")
        self.assertEqual(delegate.highest_complexity(["bogus"]), "normal")

    def test_builder_never_gets_frontier(self) -> None:
        claude = Profiles.load().get("claude")
        for complexity in delegate.COMPLEXITY_ORDER:
            self.assertNotEqual(delegate.builder_recommendation(complexity, claude)[0], "frontier")


if __name__ == "__main__":
    unittest.main()
