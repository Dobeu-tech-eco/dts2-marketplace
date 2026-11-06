"""templates/settings.unattended.json, scripts/unattended.py and the unattended PermissionDenied path."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import approvals  # noqa: E402
import unattended  # noqa: E402

TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "settings.unattended.json"
POLICY: Final[Path] = PLUGIN_ROOT / "templates" / "policy.json"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "permission-denied.sh"
STAMP: Final[str] = "20261106-1"
LANE: Final[str] = "a"


def template() -> dict[str, Any]:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


class ProfileTemplateTests(unittest.TestCase):
    def test_valid_json_dontask_and_bypass_disabled(self) -> None:
        profile = template()
        self.assertEqual(profile["permissions"]["defaultMode"], "dontAsk")
        self.assertEqual(profile["permissions"]["disableBypassPermissionsMode"], "disable")
        self.assertTrue(profile["sandbox"]["enabled"])
        self.assertFalse(profile["sandbox"]["allowUnsandboxedCommands"])

    def test_every_policy_deny_rule_is_mirrored(self) -> None:
        ids = [rule["id"] for rule in json.loads(POLICY.read_text(encoding="utf-8"))["deny"]]
        self.assertEqual(sorted(unattended.POLICY_MIRRORS), sorted(ids), "policy.json deny rules and POLICY_MIRRORS differ")
        deny = set(template()["permissions"]["deny"])
        for rule_id in ids:
            for pattern in unattended.POLICY_MIRRORS[rule_id]:
                self.assertIn(pattern, deny, f"{rule_id}: {pattern} is not in the template deny list")

    def test_policy_rule_words_appear_in_their_patterns(self) -> None:
        by_id = {rule["id"]: rule for rule in json.loads(POLICY.read_text(encoding="utf-8"))["deny"]}
        for rule_id, patterns in unattended.POLICY_MIRRORS.items():
            rule = by_id[rule_id]
            words = [*rule.get("cmd", []), *rule.get("bare_cmd", [])]
            self.assertTrue(any(f"({word}" in pattern for word in words for pattern in patterns), rule_id)
            for sub in rule.get("sub", [])[-1:]:
                self.assertTrue(any(sub in pattern for pattern in patterns), f"{rule_id} lacks {sub}")
            for flag in rule.get("flags", []):
                if rule_id != "force-push":
                    self.assertTrue(any(flag in pattern for pattern in patterns), f"{rule_id} lacks {flag}")

    def test_force_push_flags_are_mirrored(self) -> None:
        text = " ".join(unattended.POLICY_MIRRORS["force-push"])
        for flag in ("--force", "--mirror", "-f", "+"):
            self.assertIn(flag, text)

    def test_approvals_file_deny_rules_are_present(self) -> None:
        deny = set(template()["permissions"]["deny"])
        for rule in approvals.deny_rules():
            self.assertIn(rule, deny)

    def test_no_deny_pattern_is_also_allowed(self) -> None:
        profile = template()["permissions"]
        self.assertEqual(set(profile["allow"]) & set(profile["deny"]), set())


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-unatt-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cwd = self.root / "proj"
        self.home = self.root / "home"
        (self.cwd / ".claude").mkdir(parents=True)
        self.home.mkdir()
        self.settings = self.cwd / ".claude" / "settings.json"

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(SCRIPTS / "unattended.py"), *args, "--cwd", str(self.cwd), "--home", str(self.home)],
                              capture_output=True, text=True, check=False)

    def test_diff_writes_nothing(self) -> None:
        done = self.run_cli("diff")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["changed"])
        self.assertFalse(self.settings.exists())

    def test_apply_is_append_only_and_backs_up(self) -> None:
        existing = {"permissions": {"defaultMode": "acceptEdits", "allow": ["Bash(make *)"], "deny": ["Bash(rm -rf *)"]},
                    "model": "opus", "hooks": {"Stop": [{"hooks": []}]}}
        self.settings.write_text(json.dumps(existing), encoding="utf-8")
        done = self.run_cli("apply")
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        merged = json.loads(self.settings.read_text(encoding="utf-8"))
        backup = Path(result["backup"])
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), existing)
        self.assertIn(".bak", backup.name)
        self.assertEqual(merged["model"], "opus")
        self.assertEqual(merged["hooks"], existing["hooks"])
        self.assertEqual(merged["permissions"]["defaultMode"], "acceptEdits", "an existing value is kept")
        self.assertIn("permissions.defaultMode", result["kept"])
        self.assertEqual(merged["permissions"]["allow"][0], "Bash(make *)")
        self.assertEqual(merged["permissions"]["deny"][0], "Bash(rm -rf *)")
        for key in ("allow", "deny"):
            self.assertTrue(set(template()["permissions"][key]) <= set(merged["permissions"][key]))
        self.assertEqual(merged["permissions"]["disableBypassPermissionsMode"], "disable")
        self.assertTrue(merged["sandbox"]["enabled"])

    def test_apply_twice_changes_nothing_and_makes_no_second_backup(self) -> None:
        self.settings.write_text("{}", encoding="utf-8")
        self.run_cli("apply")
        first = self.settings.read_text(encoding="utf-8")
        again = json.loads(self.run_cli("apply").stdout)
        self.assertFalse(again["changed"])
        self.assertIsNone(again["backup"])
        self.assertEqual(self.settings.read_text(encoding="utf-8"), first)
        self.assertEqual(len(list(self.settings.parent.glob("settings.json.bak*"))), 1)

    def test_apply_without_a_file_creates_it_without_backup(self) -> None:
        result = json.loads(self.run_cli("apply").stdout)
        self.assertIsNone(result["backup"])
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["defaultMode"], "dontAsk")

    def test_dry_run_and_invalid_json_write_nothing(self) -> None:
        self.run_cli("apply", "--dry-run")
        self.assertFalse(self.settings.exists())
        self.settings.write_text("{nope", encoding="utf-8")
        done = self.run_cli("apply")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{nope")


class PermissionDeniedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.lane_dir = self.repo / ".harness" / "runs" / STAMP / LANE
        self.lane_dir.mkdir(parents=True)
        (self.lane_dir / "status.json").write_text(json.dumps({"lane": LANE, "status": "starting"}), encoding="utf-8")
        self.payload = {"cwd": str(self.repo), "session_id": "s9", "tool_name": "Bash", "reason": "git push denied"}

    def mode(self, on: bool) -> None:
        path = self.repo / ".claude" / "dts2-harness.local.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nautonomy: unattended\n---\n" if on else "---\nenabled: true\n---\n", encoding="utf-8")

    def fire(self, lane: bool = True) -> subprocess.CompletedProcess[str]:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
        if lane:
            env["DTS2_SON_BRANCH_PREFIX"] = f"dts2/{STAMP}/lane-{LANE}"
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.repo), input=json.dumps(self.payload), capture_output=True,
                              text=True, check=False, env=env)

    def status(self) -> dict[str, Any]:
        return json.loads((self.lane_dir / "status.json").read_text(encoding="utf-8"))

    def test_unattended_lane_gets_need_human_item_and_parks(self) -> None:
        self.mode(True)
        self.assertEqual(self.fire().returncode, 0)
        asked = json.loads((self.lane_dir / "questions" / "h1.json").read_text(encoding="utf-8"))
        self.assertEqual((asked["kind"], asked["lane"]), ("need-human", LANE))
        self.assertIn("PermissionDenied for Bash", asked["text"])
        saved = self.status()
        self.assertEqual((saved["status"], saved["reason"], saved["waiting_on"]), ("incomplete", "permission-denied", "h1"))
        text = (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn("PermissionDenied for Bash", text)

    def test_env_flag_alone_turns_it_on(self) -> None:
        self.assertFalse(unattended.is_unattended(self.repo))
        os.environ["DTS2_UNATTENDED"] = "1"
        self.addCleanup(os.environ.pop, "DTS2_UNATTENDED", None)
        self.assertTrue(unattended.is_unattended(self.repo))

    def test_normal_mode_only_appends_the_action_item(self) -> None:
        self.mode(False)
        self.assertEqual(self.fire().returncode, 0)
        self.assertFalse((self.lane_dir / "questions").exists())
        self.assertEqual(self.status()["status"], "starting")
        self.assertIn("PermissionDenied for Bash", (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8"))

    def test_unattended_without_a_lane_is_only_the_action_item(self) -> None:
        self.mode(True)
        self.assertEqual(self.fire(lane=False).returncode, 0)
        self.assertFalse((self.lane_dir / "questions").exists())
        self.assertEqual(self.status()["status"], "starting")

    def test_unattended_with_an_unknown_lane_never_fails(self) -> None:
        self.mode(True)
        shutil.rmtree(self.lane_dir)
        done = self.fire()
        self.assertEqual(done.returncode, 0)
        self.assertIn("PermissionDenied for Bash", (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
