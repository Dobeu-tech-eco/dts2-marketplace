from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import Any

from helpers import PLUGIN_ROOT, make_fake_home, make_tmp_home, run_script

SYNCED: dict[str, list[str]] = {
    "holocron": ["a.md", "b.md"], "beads": ["a.md", "b.md"], "twin": ["a.md", "b.md"],
    "marketing-skills": ["m.md"], "pensyve": ["p.md"], "idle": [],
}
USAGE: dict[str, int] = {"holocron": 5, "beads": 2, "marketing-skills": 0, "twin": 2}
SETTINGS: dict[str, Any] = {"enabledPlugins": {
    "dts2-harness@dts2": True, "used@mkt": True, "unused@mkt": True,
    **{f"{n}@synced": True for n in SYNCED}}}
MARKET: dict[str, list[str]] = {"dts2-harness@dts2": ["lead.md"], "used@mkt": [], "unused@mkt": []}


NO_REQUIRED: list[str] = ["nothing@*"]


def make_profile(required: list[str] | None = None, **claude: Any) -> Path:
    base: dict[str, Any] = {"enabledPlugins": ["dts2-harness@dts2"], "keepSyncedPlugins": []}
    profile = {"budget": {}, "claude": {**base, **claude},
               "requiredByHarness": required or ["marketing-skills@synced", "impeccable@*"]}
    path: Path = make_tmp_home() / "profile.json"
    path.write_text(json.dumps(profile))
    return path


def fake_home() -> Path:
    usage = {**USAGE, "used": 3}
    return make_fake_home(SYNCED, MARKET, SETTINGS, usage=usage, skills={"holocron": ["pdf"], "beads": ["pdf"]})


def plan_text(home: Path, profile: Path, *extra: str) -> str:
    result = subprocess.run(
        ["python3", "-I", str(PLUGIN_ROOT / "scripts" / "machine-prep.py"), "plan",
         "--profile", str(profile), "--claude-home", str(home), "--home", str(home), *extra],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), check=True)
    return result.stdout


def planned_flags(text: str) -> dict[str, str]:
    pairs = [line.split(": ", 1) for line in text.splitlines() if ": " in line]
    return {k: v.split(" -> ")[-1].split(" ")[0] for k, v in pairs}


class TierTest(unittest.TestCase):
    def test_light_disables_only_unused(self) -> None:
        flags = planned_flags(plan_text(fake_home(), make_profile(), "--tier", "light"))
        self.assertEqual(flags["unused@mkt"], "False")
        self.assertEqual(flags["pensyve@synced"], "False")
        self.assertNotIn("holocron@synced", flags)
        self.assertNotIn("used@mkt", flags)
        self.assertNotIn("syncClaudeAiPlugins", flags)

    def test_standard_keeps_top_n_by_usage(self) -> None:
        profile = make_profile(keepSyncedTopN=2)
        flags = planned_flags(plan_text(fake_home(), profile, "--tier", "standard"))
        self.assertNotIn("holocron@synced", flags)
        self.assertEqual(flags["pensyve@synced"], "False")
        self.assertEqual(flags["used@mkt"], "False")
        self.assertEqual(len([k for k, v in flags.items() if k.endswith("@synced") and v == "False"]), 3)

    def test_strict_turns_both_syncs_off(self) -> None:
        flags = planned_flags(plan_text(fake_home(), make_profile(NO_REQUIRED), "--tier", "strict"))
        self.assertEqual(flags["syncClaudeAiPlugins"], "False")
        self.assertEqual(flags["syncClaudeAiSkills"], "False")
        self.assertEqual(flags["unused@mkt"], "False")

    def test_required_by_harness_survives_strict(self) -> None:
        text = plan_text(fake_home(), make_profile(), "--tier", "strict")
        flags = planned_flags(text)
        self.assertIn("marketing-skills@synced: True -> True (requiredByHarness)", text)
        self.assertNotIn("marketing-skills@synced: True -> False", text)
        self.assertNotIn("syncClaudeAiPlugins", flags)
        self.assertEqual(flags["syncClaudeAiSkills"], "False")
        self.assertEqual(flags["holocron@synced"], "False")
        self.assertEqual(flags["pensyve@synced"], "False")

    def test_strict_turns_plugin_sync_off_when_nothing_required(self) -> None:
        flags = planned_flags(plan_text(fake_home(), make_profile(NO_REQUIRED), "--tier", "strict"))
        self.assertEqual(flags["syncClaudeAiPlugins"], "False")

    def test_default_tier_from_profile(self) -> None:
        flags = planned_flags(plan_text(fake_home(), make_profile(NO_REQUIRED, defaultTier="strict")))
        self.assertEqual(flags["syncClaudeAiPlugins"], "False")
        flags = planned_flags(plan_text(fake_home(), make_profile(defaultTier="light")))
        self.assertNotIn("syncClaudeAiPlugins", flags)


FAILING_SCAN: str = "import sys; sys.stderr.write('boom'); sys.exit(1)"


class UsageFailureTest(unittest.TestCase):
    def run_with_bad_scan(self, command: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        home, profile = fake_home(), make_profile()
        scan: Path = make_tmp_home() / "bad-scan.py"
        scan.write_text(FAILING_SCAN)
        result = subprocess.run(
            ["python3", "-I", str(PLUGIN_ROOT / "scripts" / "machine-prep.py"), command,
             "--profile", str(profile), "--claude-home", str(home), "--home", str(home), "--tier", "light"],
            capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env={**os.environ, "DTS2_USAGE_SCAN": str(scan)})
        return result, home

    def test_plan_and_apply_fail_without_writing(self) -> None:
        for command in ("plan", "apply"):
            result, home = self.run_with_bad_scan(command)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("boom", result.stderr)
            self.assertEqual(json.loads((home / "settings.json").read_text()), SETTINGS)
            self.assertFalse((home / "backups").exists())

    def test_audit_reports_null_usage_and_issue(self) -> None:
        result, _ = self.run_with_bad_scan("audit")
        report = json.loads(result.stdout)
        self.assertIsNone(report["inventory"]["usage"])
        self.assertIn("usage scan failed: boom", report["issues"])


class InventoryTest(unittest.TestCase):
    def audit(self) -> dict[str, Any]:
        home = fake_home()
        return run_script("machine-prep.py", "audit", "--profile", str(make_profile()),
                          "--claude-home", str(home), "--home", str(home))["inventory"]

    def test_usage_in_inventory(self) -> None:
        self.assertEqual(self.audit()["usage"]["holocron"], 5)

    def test_redundant_packs_detected_and_keep_is_most_used(self) -> None:
        packs = self.audit()["redundantAgentPacks"]
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["plugins"], ["beads@synced", "holocron@synced", "twin@synced"])
        self.assertEqual(packs[0]["agentCount"], 2)
        self.assertEqual(packs[0]["keep"], "holocron@synced")
        self.assertEqual(len(packs[0]["agentsHash"]), 64)

    def test_duplicate_skill_names_listed(self) -> None:
        dupes = self.audit()["duplicateSkillNames"]
        self.assertEqual(dupes, {"pdf": ["beads@synced", "holocron@synced"]})


if __name__ == "__main__":
    unittest.main()
