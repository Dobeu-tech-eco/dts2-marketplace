"""Batch 22: review findings R1 (quote scan with a nested substitution) and R2 (value-taking flags before a sub-command)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import policy_gate  # noqa: E402


def denied(command: str) -> str | None:
    return policy_gate.deny_reason(policy_gate.load_policy(), command)


class ReviewFindings(unittest.TestCase):
    def test_R1_single_quote_inside_nested_substitution_stays_literal(self) -> None:
        self.assertIsNotNone(denied("""echo "$(echo "'$(printenv)'")\""""))
        self.assertIsNotNone(denied("""echo "$(echo '$(x)' "$(env)")\""""))
        self.assertIsNone(denied("git commit -m '$(env)'"))  # F3 still holds

    def test_R2_value_taking_flags_before_the_subcommand(self) -> None:
        self.assertIsNotNone(denied("vercel --token x --scope y env ls"))
        self.assertIsNotNone(denied("vercel --token x env ls"))
        self.assertIsNone(denied("gh pr create --title secret"))  # F4 still holds


if __name__ == "__main__":
    unittest.main()
