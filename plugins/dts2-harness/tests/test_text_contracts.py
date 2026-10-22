"""Text contracts for prompt and skill files: required phrases present, retired phrases absent.

Add one TestCase class per file under test. Each class mixes in TextContractMixin and calls
self.assert_contains(path, phrases) / self.assert_absent(path, phrases).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Final, Sequence

from helpers import PLUGIN_ROOT

AGENTS: Final[Path] = PLUGIN_ROOT / "agents"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TextContractMixin(unittest.TestCase):
    """Base with phrase assertions; not collected on its own because it defines no tests."""

    def assert_contains(self, path: Path, phrases: Sequence[str]) -> None:
        text: str = _read(path)
        missing: list[str] = [p for p in phrases if p not in text]
        self.assertEqual(missing, [], f"{path.name} is missing required phrases")

    def assert_absent(self, path: Path, phrases: Sequence[str]) -> None:
        text: str = _read(path)
        present: list[str] = [p for p in phrases if p in text]
        self.assertEqual(present, [], f"{path.name} contains retired phrases")


SUPABASE_ROUTE: Final[tuple[str, ...]] = (
    "dts2-harness:builder has no MCP tools", "supabase branches create", "supabase db query --linked",
    "supabase branches delete", "never `supabase branches get`", "prints keys",
    "resolves `-f` paths from the project root", "Initialising login role",
)


class LeadAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "lead.md"

    def test_model_and_complexity_line(self) -> None:
        self.assert_contains(self.PATH, ["\nmodel: opus\n", "complexity: <mechanical|normal|design>"])

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "## Done", "Axes", "Skills table", "separate file sets", "### Builder 1",
            ".harness/end-state.md", ".harness/discipline.md", "roster.py", "coexist",
            "Team: <n> builders on separate file sets",
        ])

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["Lane A", "Lane", "lane", "worktree", "Tier/Lanes"])


class ReviewerAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "reviewer.md"

    def test_model_is_sonnet(self) -> None:
        self.assert_contains(self.PATH, ["\nmodel: sonnet\n"])

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "#### Preserve", "#### Fix", "#### Open questions", "0–4", "Never write fixes",
            "critique", "walkthrough-findings", "### Priorities", ".harness/review/screens/",
            "Impeccable critique report path", ".harness/review/critique-<stamp>.md",
            "The caller supplies the run stamp", "date +%Y%m%d-%H%M%S",
            "npm audit --json", "pip-audit --format json", "Issue / Impact / Evidence / Fix / Priority",
        ])


class VerifierAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "verifier.md"

    def test_model_is_opus(self) -> None:
        self.assert_contains(self.PATH, ["\nmodel: opus\n"])

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Walkthrough", ".harness/review/screens/", "no browser available", "dev_server",
            "ready_pattern", "python3 -m playwright", "npx playwright",
            "Walkthrough | SKIP | no browser available",
            "The caller supplies the run stamp", "date +%Y%m%d-%H%M%S",
        ])

    def test_inherits_all_tools(self) -> None:
        self.assert_absent(self.PATH, ["tools:"])

    def test_head_guard(self) -> None:
        self.assert_contains(self.PATH, [
            "## HEAD guard", "git rev-parse HEAD", "at the start and again at the end",
            "| HEAD | PASS/MOVED | start <sha> / end <sha> |", "which commit each check ran against",
            "HEAD moved", "only for checks that cannot be attributed", "never a blanket BLOCKED",
        ])
        text: str = _read(self.PATH)
        self.assertLess(text.find("## HEAD guard"), text.find("## Checklist"))


class ScoutAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "scout.md"

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["Worktrees:"])

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Harnesses:", "Marketing surface:", ".omc", ".flow", ".beads", ".conductor",
            ".agent", ".impeccable", ".agents", "AGENTS.md", "CLAUDE.md",
        ])


class SetupSkillContracts(TextContractMixin):
    PATH: Final[Path] = PLUGIN_ROOT / "skills" / "setup" / "SKILL.md"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Paste any other repos", "what it serves", "context", "linked", "roster.py detect",
            "only Claude", "Continue anyway", "Clarity:", "end_state_threshold", "import",
            "coexist", "retire", "find-skills", "skill plan", "impeccable init",
            "serves component", "--scaffold-only", "pending approval",
        ])

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["worktree"])

    def test_muse_login_wording(self) -> None:
        self.assert_contains(self.PATH, [
            "has no login check: gemini, grok, opencode, muse", "`muse login`",
        ])

    def test_round_order(self) -> None:
        text: str = _read(self.PATH)
        markers: list[str] = [
            "Round 1", "Round 2 ", "Round 2b", "Round 2c", "Round 3", "Round 4 ", "Round 4b",
            "Round 5", "## Part 2",
        ]
        positions: list[int] = [text.find(m) for m in markers]
        self.assertNotIn(-1, positions, "setup is missing a round heading")
        self.assertEqual(positions, sorted(positions), "setup rounds are out of order")


class BuilderAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "builder.md"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "file set", "SECRET NEEDED: NAME — <what it unlocks> — <where consumed>",
            "never ask for or print its value", "not-configured path",
        ])

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["lane", "Lane"])

    def test_supabase_cli_route(self) -> None:
        self.assert_contains(self.PATH, SUPABASE_ROUTE)


class RunSkillContracts(TextContractMixin):
    PATH: Final[Path] = PLUGIN_ROOT / "skills" / "run" / "SKILL.md"
    ISOLATION_HEADING: Final[str] = "## Isolation (Rule 10)"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Plan checkpoint", "Ship checkpoint", "auto_learn", "provide now", "add later",
            "action-items.md", "add secret", "never print a value", "Finish pass", "Budget check",
            "roster.py probe", "costTier", "complexity", "frontier", "impeccable polish",
            "No end state yet", "evolve", "separate file sets", "Both checkpoints need a human",
            "escalate with what failed", "receipt",
            "Here is the plan, the done-criteria, and who does what. Approve, edit, or stop.",
            "Here is the receipt. Ship, fix the blocking items and re-check, or stop and revert.",
            "No end state yet; /dts2-harness:setup interviews to one.",
            "That changes the harness itself; use `/dts2-harness:evolve`.",
            "Cap at 3 rounds. After 3, stop and escalate with what failed; record it in `.harness/state.md`.",
            "Finish pass skipped: Impeccable not installed (github.com/pbakaus/impeccable)",
            "Both checkpoints need a human. Headless runs stop at each and write what a human would have seen.",
            ".harness/review/critique-<stamp>.md", "ensure-ignored.py", "roster.py\" resolve",
            "test -n \"${NAME:-}\"", "gh secret set NAME", ".env.example", "deferred wiring",
            ".harness/handoff/<agent>/<n>.md", "templates/receipt.md", "## Decisions",
        ])

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["Gate 1", "Gate 2"])

    def test_supabase_cli_route(self) -> None:
        self.assert_contains(self.PATH, SUPABASE_ROUTE)

    def test_dispatch_outcome_wording(self) -> None:
        self.assert_contains(self.PATH, [
            "Dropped: <agent> — <reason>", "classify --agent <name> --role <role> --exit-code <status>",
            "`dropForRun: true`", "unavailable (billing/quota)", "with the reset time when given",
            "Fallback: reviewer:security copilot -> grok (context budget)", "--usable <probe usable list>",
            "grok builders: edits allowed, no shell", "tell every codex builder `do not commit`",
            "the lead commits its work after review", "codex: `< /dev/null`",
        ])

    def test_prompts_travel_as_files(self) -> None:
        self.assert_contains(self.PATH, [
            ".harness/runs/<stamp>/prompts/", "--prompt-file <file>", "run its `shell` value as is",
            "Never paste the brief or the diff into a command line",
        ])
        self.assert_absent(self.PATH, ["with `{prompt}` replaced by", "`{prompt}` replaced by the review prompt"])

    def test_verifier_dispatch_mentions_head_guard(self) -> None:
        text: str = _read(self.PATH)
        block: str = text[text.find("## Phase 3 "):text.find("## Phase 3b")]
        for phrase in ("HEAD guard", "HEAD moved", "per check"):
            self.assertIn(phrase, block, phrase)

    def test_after_ship_commits_critique_report(self) -> None:
        text: str = _read(self.PATH)
        after: str = text[text.find("## After ship"):text.find("## Add secret mode")]
        self.assertIn(".harness/review/critique-<stamp>.md", after)

    def test_gh_secret_presence_check(self) -> None:
        self.assert_contains(self.PATH, ["gh secret list | grep -qE '^NAME\\b'"])

    def test_ship_fills_receipt_approver(self) -> None:
        self.assert_contains(self.PATH, [
            "### Approved by", "git config user.name", "date +%Y-%m-%d", "replacing the template placeholder",
        ])

    def test_single_mode_text_has_no_worktree_or_lane(self) -> None:
        text: str = _read(self.PATH)
        cut: int = text.find(self.ISOLATION_HEADING)
        self.assertNotEqual(cut, -1, "run is missing the isolation heading")
        head: str = text[:cut].lower()
        self.assertNotIn("worktree", head)
        self.assertNotIn("lane", head)

    def test_review_order_walkthrough_before_reviewers(self) -> None:
        text: str = _read(self.PATH)
        phase3: int = text.find("## Phase 3")
        finish: int = text.find("## Phase 3b")
        self.assertTrue(-1 < phase3 < finish, "run needs Phase 3 then Phase 3b")
        block: str = text[phase3:finish]
        self.assertLess(block.find("walkthrough"), block.find("reviewers in parallel"))


class ReleaseContract(unittest.TestCase):
    VERSION: Final[str] = "3.4.0"
    SKILL_COUNT: Final[int] = 9
    AGENT_COUNT: Final[int] = 6
    REPO_ROOT: Final[Path] = PLUGIN_ROOT.parent.parent

    def test_manifests_report_release_version(self) -> None:
        plugin: dict = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market: dict = json.loads((self.REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], self.VERSION)
        self.assertEqual([p["version"] for p in market["plugins"]], [self.VERSION])

    def test_readme_credits_upstreams(self) -> None:
        text: str = _read(self.REPO_ROOT / "README.md")
        for needle in ("oh-my-claudecode", "Impeccable", "marketingskills", "## Acknowledgements", "What's new in 3.0.0", "Known limits"):
            self.assertIn(needle, text)

    def test_skill_and_agent_counts(self) -> None:
        skills: list[str] = [d.name for d in (PLUGIN_ROOT / "skills").iterdir() if d.is_dir()]
        self.assertEqual(len(skills), self.SKILL_COUNT)
        self.assertIn("action-items", skills)
        self.assertEqual(len(list(AGENTS.iterdir())), self.AGENT_COUNT)


if __name__ == "__main__":
    unittest.main()
