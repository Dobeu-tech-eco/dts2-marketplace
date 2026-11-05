"""run_metrics wired into lanes: plan warning on stderr, a metrics row at run end, and `lanes.py report`."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.phases import transition  # noqa: E402
from lanes.runend import record_run_end, warn_thin_plan  # noqa: E402

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-8"


def lane(x: str, f: str) -> dict[str, object]:
    return {"id": x, "item": f"S{x}", "files": [f], "ids": {}, "depends_on": [], "tier": "standard"}


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-b13m-"))
        self.runs = self.repo / ".harness" / "runs"

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, check=False)

    def test_thin_plan_warns_only_when_accepted(self) -> None:
        self.assertIsNone(warn_thin_plan({"ok": False, "manifest": {"lanes": [lane("a", "x")]}}))
        self.assertIn("fewer than 2 disjoint lanes", warn_thin_plan({"ok": True, "manifest": {"lanes": [lane("a", "x")]}}) or "")
        self.assertIsNone(warn_thin_plan({"ok": True, "manifest": {"lanes": [lane("a", "x"), lane("b", "y")]}}))

    def test_plan_command_prints_the_warning_to_stderr(self) -> None:
        draft = self.repo / "d.json"
        draft.write_text(json.dumps({"stamp": STAMP, "base": "a", "scope": "single", "lanes": [lane("a", "src/a/x.py")]}), encoding="utf-8")
        checkin = self.repo / "c.json"
        checkin.write_text(json.dumps({"outstanding_items": ["Sa"]}), encoding="utf-8")
        done = self.cli("plan", "--from-checkin", str(checkin), "--draft", str(draft))
        self.assertIn("fewer than 2 disjoint lanes", done.stderr)
        self.assertTrue(json.loads(done.stdout)["ok"])

    def test_run_end_records_one_row_once(self) -> None:
        transition(self.runs, STAMP, "a", "done")
        transition(self.runs, STAMP, "b", "incomplete", reason="timeout")
        self.assertTrue(record_run_end(self.runs, STAMP, self.repo, "merged"))
        self.assertFalse(record_run_end(self.runs, STAMP, self.repo, "merged"))
        rows = [json.loads(r) for r in (self.repo / ".harness" / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["stamp"], rows[0]["lanes"], rows[0]["failures"], rows[0]["verdict"]),
                         (STAMP, 2, {"timeout": 1}, "merged"))

    def test_run_end_without_a_run_is_silent(self) -> None:
        self.assertFalse(record_run_end(self.runs, STAMP, self.repo))

    def test_report_command(self) -> None:
        transition(self.runs, STAMP, "a", "done")
        done = self.cli("report", STAMP, "--repo-url", "https://example.test/r")
        out = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0)
        self.assertIn("| a | done |", out["markdown"])


if __name__ == "__main__":
    unittest.main()
