"""N6: run_report.py prints one run as a markdown table."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "run_report.py"
STAMP: Final[str] = "20261105-0001"
HEADER: Final[str] = "| Lane | Status | Rounds | Cost (USD) | Wall-clock | PR |"


def make_run() -> Path:
    runs: Path = Path(tempfile.mkdtemp(prefix="dts2-report-"))
    run_dir: Path = runs / STAMP
    (run_dir / "a").mkdir(parents=True)
    (run_dir / "b").mkdir()
    (run_dir / "budget.json").write_text(json.dumps({
        "started": 1000, "spent_usd": 3.5,
        "lanes": {"a": {"rounds": 2, "charged_usd": 3.25, "sessions": {}}, "b": {"rounds": 1, "sessions": {}}},
    }), encoding="utf-8")
    (run_dir / "a" / "status.json").write_text(json.dumps(
        {"lane": "a", "status": "done", "pr": 12, "heartbeat": 1000 + 754}), encoding="utf-8")
    (run_dir / "b" / "status.json").write_text(json.dumps({"lane": "b", "status": "blocked"}), encoding="utf-8")
    return runs


def run(runs: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), STAMP, "--runs-dir", str(runs), *args],
                          capture_output=True, text=True, check=False)


class RunReport(unittest.TestCase):
    def test_prints_table_with_one_row_per_lane(self) -> None:
        done = run(make_run())
        self.assertEqual(done.returncode, 0, done.stderr)
        lines: list[str] = done.stdout.strip().splitlines()
        self.assertIn(HEADER, lines)
        self.assertEqual(lines[lines.index(HEADER) + 1], "| --- | --- | --- | --- | --- | --- |")
        self.assertIn("| a | done | 2 | 3.25 | 12m34s | #12 |", lines)

    def test_missing_data_is_a_dash_not_zero(self) -> None:
        self.assertIn("| b | blocked | 1 | - | - | - |", run(make_run()).stdout.splitlines())

    def test_pr_link_uses_repo_url(self) -> None:
        out = run(make_run(), "--repo-url", "https://github.com/o/r").stdout
        self.assertIn("[#12](https://github.com/o/r/pull/12)", out)

    def test_total_row_sums_known_cost(self) -> None:
        self.assertIn("| Total |  | 3 | 3.25 |  |  |", run(make_run()).stdout.splitlines())

    def test_unknown_run_fails(self) -> None:
        done = run(Path(tempfile.mkdtemp(prefix="dts2-report-")))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no run", done.stderr)


if __name__ == "__main__":
    unittest.main()
