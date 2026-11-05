"""The smoke eval runner: fixtures pass with fake binaries, deltas print, and only pass/fail regressions fail the run."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

RUNNER: Final[Path] = PLUGIN_ROOT / "evals" / "run.py"


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("eval_run", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(passed: bool, tokens: int, wall_ms: int) -> dict[str, Any]:
    return {"pass": passed, "tokens": tokens, "wall_ms": wall_ms, "fix_rounds": 0, "mismatch": {}}


class EvalRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_mod = load_runner()
        self.tmp = Path(tempfile.mkdtemp(prefix="dts2-evaltest-"))

    def main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["run.py", *argv]), contextlib.redirect_stdout(out):
            code: int = self.run_mod.main()
        return code, out.getvalue()

    def test_five_fixtures_exist_with_expected_files(self) -> None:
        folders = [p for p in (PLUGIN_ROOT / "evals" / "fixtures").iterdir() if p.is_dir()]
        self.assertEqual(len(folders), 5)
        for folder in folders:
            for name in ("task.md", "scenario.json", "expected.json"):
                self.assertTrue((folder / name).is_file(), f"{folder.name}/{name}")

    def test_fixtures_pass_and_results_are_written(self) -> None:
        results = self.tmp / "results"
        empty = self.tmp / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        code, text = self.main("--baseline", str(empty), "--results-dir", str(results))
        self.assertEqual(code, 0, text)
        files = list(results.glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["totals"]["passed"], 5)
        self.assertTrue(all(r["pass"] for r in data["fixtures"].values()))
        self.assertEqual(data["fixtures"]["one-fix-round"]["fix_rounds"], 1)
        self.assertEqual(data["fixtures"]["one-fix-round"]["tokens"], 3300)

    def test_committed_baseline_matches_a_fresh_run(self) -> None:
        baseline = json.loads((PLUGIN_ROOT / "evals" / "baseline.json").read_text(encoding="utf-8"))
        code, text = self.main("--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 0, text)
        self.assertIn("TOTAL: 5/5 pass", text)
        self.assertEqual(baseline["totals"]["tokens"], 8200)
        self.assertTrue(all(r["pass"] for r in baseline["fixtures"].values()))

    def test_unexpected_outcome_fails_the_fixture(self) -> None:
        source = PLUGIN_ROOT / "evals" / "fixtures" / "clean-fix"
        copy = self.tmp / "clean-fix"
        shutil.copytree(source, copy)
        wrong = json.loads((source / "expected.json").read_text(encoding="utf-8")) | {"route": "escalate"}
        (copy / "expected.json").write_text(json.dumps(wrong), encoding="utf-8")
        result = self.run_mod.run_fixture(copy, self.run_mod.fake_env())
        self.assertFalse(result["pass"])
        self.assertEqual(result["mismatch"]["route"]["got"], "pass")

    def two_row_baseline(self) -> Path:
        path = self.tmp / "two.json"
        rows = {"clean-fix": row(True, 1000, 1000), "one-fix-round": row(True, 2000, 3000)}
        path.write_text(json.dumps({"fixtures": rows, "totals": self.run_mod.totals(rows)}), encoding="utf-8")
        return path

    def test_update_baseline_with_fixture_keeps_other_rows(self) -> None:
        path = self.two_row_baseline()
        code, text = self.main("--fixture", "clean-fix", "--update-baseline", "--baseline", str(path), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 0, text)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["fixtures"]), ["clean-fix", "one-fix-round"])
        self.assertEqual(data["fixtures"]["one-fix-round"]["tokens"], 2000)
        self.assertEqual(data["totals"]["fixtures"], 2)

    def test_subset_total_delta_covers_only_that_fixture(self) -> None:
        path = self.two_row_baseline()
        with mock.patch.object(self.run_mod, "run_fixture", return_value=row(True, 1500, 1000)):
            code, text = self.main("--fixture", "clean-fix", "--baseline", str(path), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 0, text)
        self.assertIn("TOTAL: 1/1 pass tokens 1500 (+500) wall_ms 1000 (+0)", text)

    def test_corrupt_or_missing_explicit_baseline_exits_two(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text("{bad", encoding="utf-8")
        code, text = self.main("--fixture", "clean-fix", "--baseline", str(bad), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 2)
        self.assertIn("unreadable baseline", text)
        listy = self.tmp / "list.json"
        listy.write_text("[]", encoding="utf-8")
        self.assertEqual(self.main("--fixture", "clean-fix", "--baseline", str(listy), "--results-dir", str(self.tmp / "r"))[0], 2)
        code, text = self.main("--fixture", "clean-fix", "--baseline", str(self.tmp / "absent.json"), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 2)
        self.assertIn("unreadable baseline", text)

    def test_update_baseline_refuses_failing_fixtures(self) -> None:
        path = self.two_row_baseline()
        before = path.read_text(encoding="utf-8")
        with mock.patch.object(self.run_mod, "run_fixture", return_value=row(False, 1, 1)):
            code, text = self.main("--fixture", "clean-fix", "--update-baseline", "--baseline", str(path), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 2)
        self.assertIn("refusing to record a baseline with failing fixtures: clean-fix", text)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_stale_lease_fixture_checks_stored_epoch(self) -> None:
        expected = json.loads((PLUGIN_ROOT / "evals" / "fixtures" / "stale-lease" / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(expected["stored_epoch"], 2)
        result = self.run_mod.run_fixture(PLUGIN_ROOT / "evals" / "fixtures" / "stale-lease", self.run_mod.fake_env())
        self.assertTrue(result["pass"], result)

    def test_pass_fail_regression_exits_one(self) -> None:
        baseline = self.tmp / "b.json"
        baseline.write_text(json.dumps({"fixtures": {"clean-fix": row(True, 100, 100)}, "totals": {"tokens": 100, "wall_ms": 100}}))
        with mock.patch.object(self.run_mod, "run_fixture", return_value=row(False, 100, 100)):
            code, text = self.main("--fixture", "clean-fix", "--baseline", str(baseline), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 1)
        self.assertIn("REGRESSION: clean-fix", text)

    def test_cost_increase_alone_exits_zero_and_prints_delta(self) -> None:
        baseline = self.tmp / "b.json"
        baseline.write_text(json.dumps({"fixtures": {"clean-fix": row(True, 100, 100)}, "totals": {"tokens": 100, "wall_ms": 100}}))
        with mock.patch.object(self.run_mod, "run_fixture", return_value=row(True, 5000, 9000)):
            code, text = self.main("--fixture", "clean-fix", "--baseline", str(baseline), "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 0)
        self.assertIn("tokens 5000 (+4900)", text)
        self.assertIn("TOTAL: 1/1 pass tokens 5000 (+4900) wall_ms 9000 (+8900)", text)

    def test_unknown_fixture_exits_two(self) -> None:
        code, _ = self.main("--fixture", "nope", "--results-dir", str(self.tmp / "r"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
