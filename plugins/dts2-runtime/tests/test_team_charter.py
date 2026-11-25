"""Optional TEAM.md: missing file and unreachable seats stay on the harness roster."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "team_charter.py"
TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "TEAM.md"
BRIEF: Final[Path] = PLUGIN_ROOT / "templates" / "brief.md"
APPROVAL: Final[str] = "Merges, deploys and spending need an explicit human approval."
HEADINGS: Final[tuple[str, ...]] = (
    "## Objective", "## Context", "## Scope", "## Authorized and prohibited",
    "## Inputs", "## Deliverable and evidence", "## Deadline and dependencies",
)


def charter(*rows: str) -> str:
    lines = ["# Team charter", "", "| Role | Seat | Providers |", "| --- | --- | --- |", *rows, ""]
    return "\n".join(lines)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-I", str(SCRIPT), *args],
        cwd=repo, capture_output=True, text=True, check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


class MissingCharterTests(unittest.TestCase):
    def test_cli_missing_file_is_todays_flow(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        result = run(repo, "resolve", "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["present"], False)
        self.assertEqual(data["mode"], "harness")
        self.assertEqual(data["roles"], {})
        self.assertEqual(data["warnings"], [])
        self.assertEqual(result.stderr, "")

    def test_review_cap_absent_does_not_escalate(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        result = run(repo, "review-cap", "--repo", str(repo), "--round", "9")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["mode"], "harness")
        self.assertIsNone(data["cap"])
        self.assertFalse(data["escalate"])
        self.assertEqual(result.stderr, "")


class CharterLocationTests(unittest.TestCase):
    def test_harness_copy_is_enough(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        folder = repo / ".harness"
        folder.mkdir()
        (folder / "TEAM.md").write_text(charter("| lead | lead | claude |"), encoding="utf-8")
        probe = repo / "probe.json"
        probe.write_text(json.dumps({"agents": {"claude": {"available": True}}}), encoding="utf-8")
        result = run(repo, "resolve", "--repo", str(repo), "--probe-json", str(probe))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertTrue(data["present"])
        self.assertEqual(data["roles"]["lead"]["agent"], "claude")
        self.assertEqual(data["roles"]["lead"]["source"], "charter")


class UnreachableSeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        (self.repo / "TEAM.md").write_text(charter(
            "| builder | execution | t3code, codex |",
            "| dispatcher | lead | t3code |",
            "| lead | lead | claude |",
        ), encoding="utf-8")
        self.probe = self.repo / "probe.json"
        self.probe.write_text(json.dumps({
            "usable": ["claude", "codex"],
            "agents": {
                "claude": {"available": True},
                "codex": {"available": True},
                "t3code": {"available": False, "reason": "connector down"},
            },
        }), encoding="utf-8")

    def test_next_seat_and_harness_fallback(self) -> None:
        result = run(self.repo, "resolve", "--repo", str(self.repo), "--probe-json", str(self.probe))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        builder = data["roles"]["builder"]
        self.assertEqual(builder["agent"], "codex")
        self.assertEqual(builder["source"], "charter")
        self.assertEqual(builder["skipped"], ["t3code"])
        dispatcher = data["roles"]["dispatcher"]
        self.assertIsNone(dispatcher["agent"])
        self.assertEqual(dispatcher["source"], "harness")
        self.assertEqual(dispatcher["seat"], "lead")
        lead = data["roles"]["lead"]
        self.assertEqual(lead["agent"], "claude")
        self.assertEqual(lead["source"], "charter")
        self.assertEqual(set(data["roles"]), {"builder", "dispatcher", "lead"})
        self.assertEqual(data["warnings"].count(
            "team charter: builder seat t3code unreachable; using codex"
        ), 1)
        self.assertIn(
            "team charter: dispatcher seat t3code unreachable; using the harness roster",
            data["warnings"],
        )
        self.assertEqual(len(result.stderr.strip().splitlines()), len(data["warnings"]))

    def test_live_probe_unreachable_connector_exits_zero(self) -> None:
        """No probe file: a connector the roster does not have cannot fail the command."""
        (self.repo / "TEAM.md").write_text(
            charter("| builder | execution | t3code |", "| dispatcher | lead | t3 |"),
            encoding="utf-8",
        )
        result = run(self.repo, "resolve", "--repo", str(self.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertTrue(data["present"])
        self.assertEqual(data["roles"]["builder"]["source"], "harness")
        self.assertIsNone(data["roles"]["builder"]["agent"])
        self.assertTrue(data["warnings"])
        self.assertTrue(result.stderr.strip())

    def test_unreadable_probe_falls_back(self) -> None:
        result = run(
            self.repo, "resolve", "--repo", str(self.repo),
            "--probe-json", str(self.repo / "missing.json"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["mode"], "charter")
        self.assertEqual(data["roles"]["lead"]["source"], "harness")
        self.assertIsNone(data["roles"]["lead"]["agent"])
        self.assertIn("team charter: probe unreadable; using the harness roster", data["warnings"])
        self.assertIn("probe unreadable", result.stderr)


class SeatEligibilityTests(unittest.TestCase):
    def test_ineligible_provider_falls_through(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        (repo / "TEAM.md").write_text(charter(
            "| playtester | signoff | codex-api, claude |",
            "| builder | execution | codex |",
        ), encoding="utf-8")
        probe = repo / "probe.json"
        probe.write_text(json.dumps({
            "agents": {
                "codex-api": {"available": True},
                "claude": {"available": True},
                "codex": {"available": True, "roles": ["builder"]},
            },
        }), encoding="utf-8")
        result = run(repo, "resolve", "--repo", str(repo), "--probe-json", str(probe))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        playtester = data["roles"]["playtester"]
        self.assertEqual(playtester["agent"], "claude")
        self.assertEqual(playtester["source"], "charter")
        self.assertEqual(playtester["skipped"], ["codex-api"])
        self.assertIn(
            "team charter: playtester seat codex-api cannot fill signoff; using claude",
            data["warnings"],
        )
        self.assertEqual(data["roles"]["builder"]["agent"], "codex")
        self.assertEqual(data["roles"]["builder"]["source"], "charter")

    def test_probe_roles_narrow_a_profile(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        (repo / "TEAM.md").write_text(
            charter("| playtester | signoff | claude |"), encoding="utf-8",
        )
        probe = repo / "probe.json"
        probe.write_text(json.dumps({
            "agents": {"claude": {"available": True, "roles": ["builder"]}},
        }), encoding="utf-8")
        result = run(repo, "resolve", "--repo", str(repo), "--probe-json", str(probe))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["roles"]["playtester"]["source"], "harness")
        self.assertIsNone(data["roles"]["playtester"]["agent"])
        self.assertIn(
            "team charter: playtester seat claude cannot fill signoff; using the harness roster",
            data["warnings"],
        )

    def test_build_phase_keeps_the_chosen_fallback(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        self.assertIn("a warning does not drop that agent", text)
        self.assertNotIn("or any `warnings` line", text)


class ReviewCapTests(unittest.TestCase):
    def test_third_round_continues_and_fourth_asks_the_person(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        (repo / "TEAM.md").write_text(charter("| reviewer | advisory | claude |"), encoding="utf-8")
        third = payload(run(repo, "review-cap", "--repo", str(repo), "--round", "3"))
        self.assertEqual(third["cap"], 3)
        self.assertFalse(third["escalate"])
        self.assertEqual(third["warning"], None)
        fourth = run(repo, "review-cap", "--repo", str(repo), "--round", "4")
        data = payload(fourth)
        self.assertTrue(data["escalate"])
        self.assertIn("escalating to the human", data["warning"])
        self.assertIn("escalating to the human", fourth.stderr)


class ReaderUnavailableTests(unittest.TestCase):
    def test_skills_keep_going_when_the_reader_cannot_run(self) -> None:
        phrase = "team charter: reader unavailable; using the harness roster"
        paths = [
            PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md",
            PLUGIN_ROOT / "skills" / "run" / "phase-3-review.md",
            PLUGIN_ROOT / "skills" / "autopilot" / "phase-2-step.md",
            PLUGIN_ROOT / "skills" / "model" / "SKILL.md",
            PLUGIN_ROOT / "skills" / "onboard" / "SKILL.md",
        ]
        for path in paths:
            self.assertIn(phrase, path.read_text(encoding="utf-8"), path.name)
            self.assertIn("Do not stop the run.", path.read_text(encoding="utf-8"), path.name)


class BriefTests(unittest.TestCase):
    def test_seven_fields_and_human_approval(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-charter-"))
        result = run(
            repo, "brief",
            "--role", "builder",
            "--objective", "Add the limit",
            "--context", "Section 2",
            "--scope", "execution seat",
            "--authorized", "Edit the owned files",
            "--prohibited", "Do not touch CI",
            "--inputs", "src/upload.ts",
            "--deliverable", "The limit",
            "--evidence", "The new test passes",
            "--deadline", "Before review",
            "--dependencies", "none",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for heading in HEADINGS:
            self.assertIn(heading, result.stdout)
        self.assertIn(APPROVAL, result.stdout)
        self.assertIn("Add the limit", result.stdout)
        self.assertIn("Do not touch CI", result.stdout)
        self.assertEqual(result.stdout.count(APPROVAL), 1)

    def test_template_names_the_seven_fields(self) -> None:
        text = BRIEF.read_text(encoding="utf-8")
        for heading in HEADINGS:
            self.assertIn(heading, text)
        self.assertIn(APPROVAL, text)
        charter_text = TEMPLATE.read_text(encoding="utf-8")
        for role in ("lead", "builder", "reviewer", "playtester", "copywriter", "dispatcher"):
            self.assertIn(role, charter_text)
        self.assertIn("3 rounds", charter_text)
        self.assertIn("explicit human approval", charter_text)


if __name__ == "__main__":
    unittest.main()
