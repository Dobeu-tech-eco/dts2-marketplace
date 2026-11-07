"""Batch 23: review finding R3 (an escaped `\\$(` or `$$(` must not open a substitution context in the quote scan)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import guard  # noqa: E402
import policy_gate  # noqa: E402


def denied(command: str) -> str | None:
    return policy_gate.deny_reason(policy_gate.load_policy(), command)


class ReviewFindings(unittest.TestCase):
    def test_R3_escaped_dollar_does_not_open_substitution(self) -> None:
        self.assertIsNotNone(denied("""echo "\\$('$(printenv)')\""""))
        self.assertIsNotNone(denied("""echo "$$('$(printenv)')\""""))

    def test_R3_prior_behaviour_holds(self) -> None:
        self.assertIsNotNone(denied("""echo "$(echo "'$(printenv)'")\""""))
        self.assertIsNone(denied("git commit -m '$(env)'"))
        self.assertIsNotNone(denied("""echo "\\$(x)" && printenv"""))
        self.assertIsNone(denied("""printf '%s' "\\$HOME\""""))

    def test_R3_mask_literals_leaves_inner_substitution_unmasked(self) -> None:
        self.assertIn("$(printenv)", guard.mask_literals("""echo "\\$('$(printenv)')\""""))


if __name__ == "__main__":
    unittest.main()
