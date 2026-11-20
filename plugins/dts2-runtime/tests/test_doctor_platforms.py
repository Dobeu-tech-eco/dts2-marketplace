"""doctor platform and host checks: Windows warns (never parks), sandbox tool by platform, T3 Code detection."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import doctor  # noqa: E402


def _env_without_override() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != doctor.SANDBOX_OVERRIDE}


class PlatformChecks(unittest.TestCase):
    def test_windows_warns_with_guidance_never_parks(self) -> None:
        with mock.patch.object(sys, "platform", "win32"):
            row = doctor.check_platform()
        self.assertEqual(row["status"], doctor.WARN)
        self.assertIn("unsafe_no_sandbox", row["detail"])
        self.assertIn("WSL2", row["detail"])
        self.assertNotIn("park", row["detail"].lower())

    def test_other_platforms_pass(self) -> None:
        for plat in ("linux", "darwin"):
            with mock.patch.object(sys, "platform", plat):
                self.assertEqual(doctor.check_platform()["status"], doctor.PASS)

    def test_sandbox_tool_by_platform(self) -> None:
        for plat, tool in (("darwin", "sandbox-exec"), ("linux", "bwrap")):
            with mock.patch.object(sys, "platform", plat), mock.patch.dict(os.environ, _env_without_override(), clear=True):
                with mock.patch.object(doctor.shutil, "which", return_value=f"/x/{tool}") as which:
                    row = doctor.check_sandbox()
            which.assert_called_with(tool)
            self.assertEqual(row["status"], doctor.PASS)

    def test_windows_has_no_sandbox_tool(self) -> None:
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(os.environ, _env_without_override(), clear=True):
            self.assertEqual(doctor.check_sandbox()["status"], doctor.WARN)

    def test_helper_rows(self) -> None:
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(doctor.shutil, "which", return_value=None):
            rows = {r["name"]: r for r in doctor.check_helper_tools()}
        self.assertEqual(rows["socat"]["status"], doctor.WARN)
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual({r["status"] for r in doctor.check_helper_tools()}, {doctor.PASS})


class HostDetection(unittest.TestCase):
    def test_default_is_claude_code(self) -> None:
        self.assertEqual(doctor.detect_host({"PATH": "/bin"}), "claude-code")

    def test_override(self) -> None:
        self.assertEqual(doctor.detect_host({"DTS2_HOST": "t3code"}), "t3code")

    def test_prefixed_variables(self) -> None:
        self.assertEqual(doctor.detect_host({"T3_CODE_THREAD": "1"}), "t3code")
        self.assertEqual(doctor.detect_host({"T3CODE_HOME": "x"}), "t3code")

    def test_host_row_reported(self) -> None:
        with mock.patch.dict(os.environ, {"DTS2_HOST": "t3code"}):
            row = doctor.check_host()
        self.assertIn("t3code", row["detail"])
        self.assertIn("lanes.py spawn", row["detail"])


if __name__ == "__main__":
    unittest.main()
