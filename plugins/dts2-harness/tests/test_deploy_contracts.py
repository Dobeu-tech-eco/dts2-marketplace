"""Text contracts for deployment verification across skills, agents and templates."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

RUN: Final[Path] = PLUGIN_ROOT / "skills" / "run" / "SKILL.md"
SETUP: Final[Path] = PLUGIN_ROOT / "skills" / "setup" / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    start: int = text.index(heading)
    nxt: int = text.find("\n## ", start + len(heading))
    return text[start:] if nxt == -1 else text[start:nxt]


class DeployContractTests(unittest.TestCase):
    def test_run_section_and_order(self) -> None:
        text: str = read(RUN)
        self.assertIn("## Deployment verification", text)
        self.assertGreater(text.index("## Deployment verification"), text.index("## Phase 4"))
        self.assertLess(text.index("## Deployment verification"), text.index("## Add secret mode"))

    def test_run_section_phrases(self) -> None:
        body: str = section(read(RUN), "## Deployment verification")
        for phrase in (
            "Mode: production", "Investigate and troubleshoot?", "gh run rerun", "explicit yes",
            "deploy.status", "planned", "live", "Deploy watch:", "DEPLOY_COMMANDS",
            "gh run view", "rollback point", "3-round", "prod-", "deploy.provider != none",
            "follow-up PR",
        ):
            self.assertIn(phrase, body, phrase)

    def test_run_never_deploys_without_yes(self) -> None:
        self.assertIn("never deploys, pushes, or re-runs CI", section(read(RUN), "## Deployment verification"))

    def test_vercel_verified_commits_cancel_is_a_note(self) -> None:
        body: str = section(read(RUN), "## Deployment verification")
        for phrase in (
            "**Vercel verified commits.**", "Canceled", "verified or signed commits",
            "unsigned agent commits", "non-blocking", "record it as a note, not a failure",
        ):
            self.assertIn(phrase, body, phrase)
        self.assertLess(body.index("**Vercel verified commits.**"), body.index("**Failure.**"))

    def test_setup_phrases(self) -> None:
        text: str = read(SETUP)
        for phrase in ("deploy-detect.py", "Production URL", "build one", "type your own",
                       "PRODUCTION_PLANS", "deploy.plan", "planned"):
            self.assertIn(phrase, text, phrase)
        self.assertGreater(text.index("deploy-detect.py"), text.index("### Round 2 "))
        self.assertLess(text.index("deploy-detect.py"), text.index("### Round 2b"))

    def test_setup_never_creates_accounts(self) -> None:
        self.assertIn("never creates provider accounts", read(SETUP))

    def test_templates(self) -> None:
        self.assertIn("Production:", read(PLUGIN_ROOT / "templates" / "receipt.md"))
        self.assertIn("not deployed yet", read(PLUGIN_ROOT / "templates" / "receipt.md"))
        end: str = read(PLUGIN_ROOT / "templates" / "end-state.md")
        for phrase in ("deploy:", "productionUrl", "checkCommand", "provider:"):
            self.assertIn(phrase, end, phrase)

    def test_receipt_production_after_rollback(self) -> None:
        text: str = read(PLUGIN_ROOT / "templates" / "receipt.md")
        self.assertGreater(text.index("Production:"), text.index("Rollback point"))

    def test_scout_and_verifier(self) -> None:
        self.assertIn("Deployment:", read(PLUGIN_ROOT / "agents" / "scout.md"))
        verifier: str = read(PLUGIN_ROOT / "agents" / "verifier.md")
        for phrase in ("Mode: production", "prod-<screen>.png", "no local server"):
            self.assertIn(phrase, verifier, phrase)


if __name__ == "__main__":
    unittest.main()
