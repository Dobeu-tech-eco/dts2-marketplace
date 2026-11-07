"""SE-1: lanes, tokens and wall-clock in metrics.jsonl; plan-time and post-run warnings."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "run_metrics.py"
METRICS_REL: Final[str] = ".harness/metrics.jsonl"


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def record(repo: Path, stamp: str, tokens: int, size: str = "standard") -> subprocess.CompletedProcess[str]:
    return cli("record", str(repo), "--stamp", stamp, "--rounds", "2", "--duration", "90", "--verdict", "VERIFIED",
               "--lanes", "2", "--tokens", str(tokens), "--wall-clock-s", "600", "--size-class", size)


def rows(repo: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (repo / METRICS_REL).read_text(encoding="utf-8").splitlines()]


def manifest(*file_sets: list[str]) -> dict[str, Any]:
    return {"stamp": "s", "lanes": [{"id": f"l{n}", "files": files} for n, files in enumerate(file_sets)]}


class PlanWarning(unittest.TestCase):
    def check(self, data: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        path: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-")) / "m.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return cli("plan-check", str(path))

    def test_warns_with_one_lane(self) -> None:
        done = self.check(manifest(["a.py"]))
        self.assertEqual(done.returncode, 0)
        self.assertIn("fewer than 2 disjoint lanes", done.stdout)

    def test_warns_when_lanes_overlap(self) -> None:
        self.assertIn("fewer than 2 disjoint lanes", self.check(manifest(["a.py", "b.py"], ["./b.py"])).stdout)

    def test_quiet_with_two_disjoint_lanes(self) -> None:
        self.assertEqual(self.check(manifest(["a.py"], ["b.py"])).stdout.strip(), "")


class Record(unittest.TestCase):
    def test_row_carries_new_fields_and_keeps_old_ones(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-"))
        record(repo, "a", 1000)
        row = rows(repo)[0]
        self.assertEqual((row["lanes"], row["tokens"], row["wall_clock_s"]), (2, 1000, 600))
        self.assertEqual((row["stamp"], row["rounds"], row["duration_s"], row["verdict"]), ("a", 2, 90, "VERIFIED"))

    def test_no_warning_without_history(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-"))
        self.assertNotIn("warning", record(repo, "a", 10**9).stdout.lower())

    def test_warns_above_three_times_median_of_same_size_class(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-"))
        for n, tokens in enumerate((100, 200, 300)):
            record(repo, f"h{n}", tokens)
        record(repo, "other", 10**6, size="large")
        done = record(repo, "big", 601)
        self.assertIn("warning", done.stdout.lower())
        self.assertIn("3x median", done.stdout)

    def test_no_warning_at_exactly_three_times_median(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-"))
        for n, tokens in enumerate((100, 200, 300)):
            record(repo, f"h{n}", tokens)
        self.assertNotIn("warning", record(repo, "edge", 600).stdout.lower())

    def test_rows_without_tokens_are_ignored_in_median(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-se1-"))
        path: Path = repo / METRICS_REL
        path.parent.mkdir(parents=True)
        path.write_text('{"stamp":"old","rounds":1}\nnot json\n', encoding="utf-8")
        self.assertNotIn("warning", record(repo, "a", 10**9).stdout.lower())


if __name__ == "__main__":
    unittest.main()
