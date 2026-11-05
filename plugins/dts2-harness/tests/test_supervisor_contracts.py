"""Text and template contracts for the supervisor: the config template parses, the skills call the script instead of
restating it, and only lanes.py writes the supervisor's state files."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT
from skill_text import read_skill

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import model_call  # noqa: E402

TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "config-supervisor.yaml"
SKILLS: Final[Path] = PLUGIN_ROOT / "skills"
STATE_FILES: Final[tuple[str, ...]] = ("budget.json", "model-ledger.jsonl", "merge-order.json", "run.json")


def skill(name: str) -> str:
    return read_skill(name)


class TemplateTests(unittest.TestCase):
    def test_template_parses_to_the_documented_defaults(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="dts2-cfgtpl-"))
        (root / ".harness").mkdir()
        (root / ".harness" / "config.yaml").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        budget = model_call.read_budget(root)
        self.assertEqual((budget["max_turns"], budget["max_wall_minutes"], budget["max_rounds"],
                          budget["max_fullauto_loops"], budget["max_usd"]), (80, 90.0, 4, 3, None))
        sup = model_call.read_supervisor(root)
        self.assertEqual((sup["max_model_calls"], sup["stall_minutes"], sup["retry_max"], sup["fallback_models"]),
                         (4, 10, 4, ["sonnet"]))

    def test_template_has_no_token_cap(self) -> None:
        self.assertNotIn("max_tokens:", TEMPLATE.read_text(encoding="utf-8"))

    def test_max_usd_template_line_is_optional_and_commented(self) -> None:
        self.assertRegex(TEMPLATE.read_text(encoding="utf-8"), r"(?m)^\s*# max_usd:")


class SkillTests(unittest.TestCase):
    def test_dpp_calls_the_supervisor_commands(self) -> None:
        text = skill("dpp")
        for command in ("lanes.py preflight", "lanes.py spawn", "lanes.py merge-go", "lanes.py merge-done",
                        "lanes.py merge-order", "lanes.py budget", "spawn --resume"):
            self.assertIn(command, text)

    def test_dpp_no_longer_hand_marks_stalled_lanes(self) -> None:
        self.assertNotIn("mark the lane `incomplete`, reason `stalled`", skill("dpp"))
        self.assertNotIn("then write `merge-go.md` into the lane's run dir", skill("dpp"))

    def test_fullauto_counts_loops_through_the_script(self) -> None:
        self.assertIn("lanes.py loop", skill("fullauto"))

    def test_autopilot_son_stamps_heartbeat_and_council_seats_share_the_limit(self) -> None:
        text = skill("autopilot")
        self.assertIn("lanes.py\" heartbeat", text)
        self.assertIn("lanes.py call", text)


class CallLimitTests(unittest.TestCase):
    """A6: no dispatch line in autopilot or dpp starts a CLI model outside `lanes.py call` or `spawn`."""

    def test_cli_model_lines_go_through_the_supervisor(self) -> None:
        for name in ("autopilot", "dpp"):
            for number, line in enumerate(skill(name).splitlines(), 1):
                starts_model = "roster.py command" in line or re.search(r"claude -p\s+\S", line)
                if starts_model:
                    self.assertTrue("lanes.py call" in line or "lanes.py spawn" in line,
                                    f"{name} line {number} starts a model outside the call limit")

    def test_roster_shell_is_never_run_directly(self) -> None:
        for name in ("autopilot", "dpp"):
            self.assertNotIn("the `shell` of", skill(name))

    def test_seats_receive_their_ballot_and_agent_tool_seats_are_called_out(self) -> None:
        text = skill("autopilot")
        self.assertIn("--prompt-file <ballot> -- claude -p", text)
        self.assertIn("cannot be gated", text)

    def test_readme_does_not_claim_every_call_is_gated(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("every model call goes through", readme)
        self.assertIn("Agent-tool seats", readme)


class SingleWriterTests(unittest.TestCase):
    def test_only_lanes_py_names_the_supervisor_state_files(self) -> None:
        for path in sorted((PLUGIN_ROOT / "scripts").glob("*.py")):
            if path.name == "lanes.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in STATE_FILES:
                self.assertNotIn(name, text, f"{path.name} must not touch {name}")

    def test_model_call_never_writes_state(self) -> None:
        text = (PLUGIN_ROOT / "scripts" / "model_call.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"atomic_write|write_text|open\([^)]*[\"']w", text))


class HeartbeatPhaseTests(unittest.TestCase):
    """A4: a son sets its phase through `lanes.py heartbeat --status`, never by writing status.json."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-phase-"))
        (self.repo / ".harness" / "runs" / "s1" / "a").mkdir(parents=True)

    def beat(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "scripts" / "lanes.py"), "--cwd", str(self.repo),
                               "heartbeat", "s1", "--lane", "a", *args], capture_output=True, text=True, check=False)

    def saved(self) -> dict[str, object]:
        data: dict[str, object] = json.loads((self.repo / ".harness" / "runs" / "s1" / "a" / "status.json").read_text())
        return data

    def test_status_reason_and_blockers_are_merged_under_the_lock(self) -> None:
        self.assertEqual(self.beat("--turn", "2").returncode, 0)
        done = self.beat("--status", "blocked", "--reason", "awaiting-items", "--blocked-by", "S1, D2")
        self.assertEqual(done.returncode, 0, done.stdout)
        saved = self.saved()
        self.assertEqual((saved["status"], saved["reason"], saved["blocked_by"], saved["turn"]),
                         ("blocked", "awaiting-items", ["S1", "D2"], 2))

    def test_unknown_phase_is_refused_and_writes_nothing(self) -> None:
        self.assertNotEqual(self.beat("--status", "building").returncode, 0)
        self.assertFalse((self.repo / ".harness" / "runs" / "s1" / "a" / "status.json").exists())

    def test_son_section_uses_the_script_for_every_phase(self) -> None:
        text = skill("autopilot")
        for phase in ("pr-open", "done", "blocked", "incomplete"):
            self.assertIn(f"--status {phase}", text)
        self.assertNotIn('"status": "blocked"', text)


class CostSourceDocTests(unittest.TestCase):
    def test_non_claude_seats_are_dispatched_with_cost_source_none(self) -> None:
        text = skill("autopilot")
        self.assertGreaterEqual(text.count("--cost-source none"), 2)
        for line in text.splitlines():
            if "roster.py command" in line and "lanes.py call" in line:
                self.assertIn("--cost-source none", line)

    def test_readme_says_max_usd_covers_claude_spend_only(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("covers Claude spend only", readme)
        self.assertIn("unreported_calls", readme)

    def test_fallback_template_names_a_chain_of_three(self) -> None:
        self.assertIn("chain of up to 3 models", TEMPLATE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
