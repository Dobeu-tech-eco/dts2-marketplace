"""Batch 21: verified review findings on the policy gate, G-54 dedupe, council instances, probe hooks and the publish deny."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import guard  # noqa: E402
import policy_gate  # noqa: E402


def denied(command: str) -> str | None:
    return policy_gate.deny_reason(policy_gate.load_policy(), command)


class PolicyGateFindings(unittest.TestCase):
    def test_F1_bundled_env_flags_still_reach_force_push(self) -> None:
        for command in ("env -iu PATH git push --force", "env -i -u PATH git push -f", "env -uPATH git push -f",
                        "env -iC /tmp git push -f", "env -S 'git push -f'"):
            self.assertIsNotNone(denied(command), command)
        self.assertEqual(guard.strip_wrappers(["env", "-iu", "PATH", "git", "push"]), ["git", "push"])
        self.assertEqual(guard.strip_wrappers(["env", "-i", "-u", "PATH", "FOO=1", "git", "push"]), ["git", "push"])

    def test_F2_expansion_hides_flag_only_rules(self) -> None:
        self.assertIn("admin-flag", denied("gh pr merge 3 $X") or "")
        self.assertIn("deploy-vercel-prod", denied("vercel $X") or "")
        self.assertIsNone(denied("gh pr view 3"))

    def test_F3_single_quoted_substitution_is_text(self) -> None:
        self.assertIsNone(denied("git commit -m '$(env)'"))
        self.assertIsNotNone(denied('echo "$(env)"'))
        self.assertIsNotNone(denied("echo $(env)"))
        self.assertIsNotNone(denied("echo `env`"))

    def test_F4_secret_in_an_option_value_is_not_gh_secret(self) -> None:
        self.assertIsNone(denied("gh pr create --title secret"))
        self.assertIsNone(denied("gh pr create secret"))
        self.assertIsNotNone(denied("gh secret set A"))
        self.assertIsNotNone(denied("gh -R o/r secret list"))
        self.assertIsNotNone(denied("gh repo delete o/r --yes"))
        self.assertIsNotNone(denied("git push -u origin --force"))


if __name__ == "__main__":
    unittest.main()
