"""Native Windows gate: no sandbox block, every son needs --unsafe-no-sandbox or the unsafe_no_sandbox approval."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import son_launch  # noqa: E402
from lanes import supervisor  # noqa: E402
from lanes.common import MODEL_LEDGER_NAME, REASON_SANDBOX  # noqa: E402

STAMP: Final[str] = "20261120-1"
LANE: Final[str] = "lane-a"
MANIFEST: Final[dict[str, Any]] = {"stamp": STAMP, "lanes": [{"id": LANE}]}


class WindowsGate(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-wingate-"))
        self.runs = self.repo / ".harness" / "runs"
        (self.runs / STAMP).mkdir(parents=True)

    def approve(self, key: str) -> None:
        marker = self.repo / ".claude" / "settings.local.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"dts2_approvals": {"unsafe_no_sandbox": [key]}}), encoding="utf-8")

    def refusal(self, windows: bool, unsafe: bool = False) -> tuple[tuple[str, str] | None, str]:
        err = io.StringIO()
        with mock.patch.object(supervisor.portable, "IS_WINDOWS", windows), contextlib.redirect_stderr(err):
            return supervisor.sandbox_refusal(self.runs, STAMP, self.repo, LANE, unsafe), err.getvalue()

    def ledger(self) -> list[dict[str, Any]]:
        path = self.runs / STAMP / MODEL_LEDGER_NAME
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def settings(self, windows: bool) -> dict[str, Any]:
        with mock.patch.object(son_launch.portable, "IS_WINDOWS", windows):
            return son_launch.son_settings(self.repo, MANIFEST, LANE, self.repo)

    def test_no_sandbox_block_on_windows(self) -> None:
        settings = self.settings(True)
        self.assertNotIn("sandbox", settings)
        self.assertIn("hooks", settings)
        self.assertTrue(settings["permissions"]["deny"])

    def test_sandbox_block_on_linux(self) -> None:
        box = self.settings(False)["sandbox"]
        self.assertTrue(box["enabled"])
        self.assertTrue(box["failIfUnavailable"])

    def test_first_son_refused_without_flag_or_approval(self) -> None:
        result, _err = self.refusal(True)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[0], REASON_SANDBOX)
        self.assertEqual(result[1], supervisor.WINDOWS_REFUSAL)
        self.assertIn("WSL2", result[1])
        self.assertEqual(self.ledger(), [])

    def test_allowed_with_flag(self) -> None:
        result, err = self.refusal(True, unsafe=True)
        self.assertIsNone(result)
        self.assertIn("warning", err)

    def test_allowed_with_approval_by_lane_or_stamp(self) -> None:
        for key in (LANE, STAMP):
            self.approve(key)
            result, _err = self.refusal(True)
            self.assertIsNone(result, key)

    def test_unrelated_approval_does_not_allow(self) -> None:
        self.approve("other-lane")
        result, _err = self.refusal(True)
        self.assertIsNotNone(result)

    def test_ledger_event_written_when_allowed(self) -> None:
        self.refusal(True, unsafe=True)
        events = [e for e in self.ledger() if e.get("event") == "unsafe-no-sandbox"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["lane"], LANE)
        self.assertEqual(events[0]["platform"], "windows")
        self.assertTrue(events[0]["warning"])

    def test_linux_first_son_unchanged(self) -> None:
        result, err = self.refusal(False)
        self.assertIsNone(result)
        self.assertEqual(err, "")
        self.assertEqual(self.ledger(), [])

    def test_linux_second_son_without_sandbox_still_refused(self) -> None:
        with mock.patch.object(supervisor, "sandbox_config", return_value={"enabled": False, "domains": []}), \
                mock.patch.object(supervisor, "read_status_files", return_value=[(Path("x"), {"lane": "other"})]), \
                mock.patch.object(supervisor, "lane_alive", return_value=True):
            result, _err = self.refusal(False)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0], REASON_SANDBOX)
            self.assertIn("second unattended son", result[1])
            self.assertIsNone(self.refusal(False, unsafe=True)[0])

    def test_preflight_text_per_platform(self) -> None:
        for windows, platform, wanted, absent in ((True, "win32", "no OS sandbox", "bwrap)"),
                                                  (False, "darwin", "sandbox-exec", "bwrap"),
                                                  (False, "linux", "bwrap", "sandbox-exec")):
            with mock.patch.object(supervisor.portable, "IS_WINDOWS", windows), mock.patch.object(sys, "platform", platform):
                text = supervisor.sandbox_tool_text()
            self.assertIn(wanted, text, platform)
            self.assertNotIn(absent, text, platform)

    def test_preflight_failure_names_platform_sandbox(self) -> None:
        failed = {"code": 1, "stdout": "", "stderr": ""}
        with mock.patch.object(supervisor.portable, "IS_WINDOWS", True), \
                mock.patch.object(supervisor, "invoke", return_value=failed), \
                mock.patch.object(supervisor, "claude_version", return_value=None), \
                mock.patch.object(supervisor, "auth_problem", return_value=None), \
                mock.patch.object(supervisor, "push_access_problem", return_value=None), \
                mock.patch.object(supervisor, "head_push_problem", return_value=None):
            report = supervisor.preflight(self.runs, STAMP, self.repo)
        joined = " ".join(report["problems"])
        self.assertIn("no OS sandbox", joined)
        self.assertNotIn("(bwrap)", joined)


if __name__ == "__main__":
    unittest.main()
