"""Tests for scripts/metrics.py and the learning-loop text contracts."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, _write

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "metrics.py"
METRICS_REL: Final[str] = ".harness/metrics.jsonl"
NO_RUNS: Final[str] = "Trend: no runs yet"


def run(repo: Path, *args: str) -> str:
    done: subprocess.CompletedProcess[str] = subprocess.run(
        ["python3", "-I", str(SCRIPT), str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


def append(repo: Path, stamp: str, rounds: int, verdict: str, failures: str) -> None:
    run(repo, "append", "--stamp", stamp, "--rounds", str(rounds), "--duration", "90",
        "--verdict", verdict, "--agents", "builder,reviewer", "--failures", failures)


def make_repo() -> Path:
    return Path(tempfile.mkdtemp(prefix="dts2-metrics-"))


class MetricsAppend(unittest.TestCase):
    def test_append_writes_one_json_line(self) -> None:
        repo: Path = make_repo()
        append(repo, "20261021-0001", 2, "VERIFIED", "lint=2,tests=1")
        lines: list[str] = (repo / METRICS_REL).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["stamp"], "20261021-0001")
        self.assertEqual(row["rounds"], 2)
        self.assertEqual(row["duration_s"], 90)
        self.assertEqual(row["agents"], ["builder", "reviewer"])
        self.assertEqual(row["failures"], {"lint": 2, "tests": 1})
        self.assertEqual(row["verdict"], "VERIFIED")

    def test_append_twice_appends(self) -> None:
        repo: Path = make_repo()
        append(repo, "a", 1, "VERIFIED", "")
        append(repo, "b", 3, "BLOCKED", "")
        self.assertEqual(len((repo / METRICS_REL).read_text(encoding="utf-8").splitlines()), 2)

    def test_empty_failures_is_empty_dict(self) -> None:
        repo: Path = make_repo()
        append(repo, "a", 1, "VERIFIED", "")
        row = json.loads((repo / METRICS_REL).read_text(encoding="utf-8"))
        self.assertEqual(row["failures"], {})


class MetricsTrend(unittest.TestCase):
    def test_no_file(self) -> None:
        self.assertEqual(run(make_repo(), "trend"), NO_RUNS)

    def test_trend_line(self) -> None:
        repo: Path = make_repo()
        append(repo, "a", 1, "VERIFIED", "lint=1")
        append(repo, "b", 2, "VERIFIED", "lint=2,tests=1")
        append(repo, "c", 3, "BLOCKED", "tests=1")
        self.assertEqual(
            run(repo, "trend"),
            "Trend (last 3): rounds avg 2.0, failures top lint, verdict VERIFIED 2/3",
        )

    def test_last_limits_window(self) -> None:
        repo: Path = make_repo()
        for index in range(7):
            append(repo, str(index), 2, "VERIFIED", "")
        self.assertTrue(run(repo, "trend").startswith("Trend (last 5): rounds avg 2.0, failures top none"))
        self.assertTrue(run(repo, "trend", "--last", "2").startswith("Trend (last 2):"))

    def test_malformed_lines_skipped(self) -> None:
        repo: Path = make_repo()
        append(repo, "a", 4, "VERIFIED", "")
        path: Path = repo / METRICS_REL
        path.write_text(path.read_text(encoding="utf-8") + "not json\n[1,2]\n{\"rounds\": \"x\"}\n\n", encoding="utf-8")
        self.assertEqual(run(repo, "trend"), "Trend (last 1): rounds avg 4.0, failures top none, verdict VERIFIED 1/1")

    def test_only_malformed_is_no_runs(self) -> None:
        repo: Path = make_repo()
        _write(repo / METRICS_REL, "garbage\n")
        self.assertEqual(run(repo, "trend"), NO_RUNS)


class LearningLoopText(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")

    def test_learn_text(self) -> None:
        text: str = self.read("skills/learn/SKILL.md")
        for phrase in ("metrics.jsonl", "harness-lessons", "harness:", "metrics.py"):
            self.assertIn(phrase, text)

    def test_learn_promote_and_group_seams(self) -> None:
        learn: str = self.read("skills/learn/SKILL.md")
        for phrase in ("learn promote", "add Promotions"):
            self.assertIn(phrase, learn)
        run: str = self.read("skills/run/SKILL.md")
        for phrase in ("Run metrics", "Add secret mode", "add Handoff", "## Deploy"):
            self.assertIn(phrase, run)
        self.assertLess(run.index("## Phase 3c"), run.index("applies the resulting fix list"))
        self.assertLess(run.index("applies the resulting fix list"), run.index("its table replaces the earlier test rows"))
        setup: str = self.read("skills/setup/SKILL.md")
        part2: str = setup[setup.index("## Part 2"):]
        self.assertIn("Harness state for any agent", part2)

    def test_evolve_text(self) -> None:
        text: str = self.read("skills/evolve/SKILL.md")
        for phrase in ("## Harness lessons", "harness-lessons", "explicit yes"):
            self.assertIn(phrase, text)

    def test_run_prints_trend(self) -> None:
        text: str = self.read("skills/run/SKILL.md")
        self.assertIn("metrics.py", text)
        self.assertIn("Trend", text)

    def test_template(self) -> None:
        text: str = self.read("templates/harness-lessons.md")
        self.assertIn("harness-lessons", text.lower())


if __name__ == "__main__":
    unittest.main()
