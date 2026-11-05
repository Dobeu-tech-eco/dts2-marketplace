"""Batch 7/8 (round 2): eval statistics with a fake runner (G-75), the pinned skills CLI, lease-gated self-upgrade and son
version skew (G-76), and no hard-coded org string (G-77)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import eval_stats  # noqa: E402
import harness_skew  # noqa: E402

RUN_PY: Final[Path] = PLUGIN_ROOT / "evals" / "run.py"
SKILLS_CHECK: Final[Path] = SCRIPTS / "skills-check.py"
FAR_FUTURE: Final[int] = 4_000_000_000


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(*walls: int, ok: bool = True) -> list[dict[str, Any]]:
    return [{"pass": ok, "wall_ms": w} for w in walls]


class EvalStatsTests(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertGreaterEqual(eval_stats.MIN_RUNS, 5)
        self.assertEqual(eval_stats.DEFAULT_RUNS, eval_stats.MIN_RUNS)

    def test_summary_median_range_and_pass_k(self) -> None:
        got = eval_stats.summarize(rows(100, 140, 120, 110, 130))
        self.assertEqual((got["median"], got["min"], got["max"], got["k"]), (120.0, 100.0, 140.0, 5))
        self.assertEqual(got["pass_k"], 1.0)

    def test_pass_k_drops_with_a_failed_run(self) -> None:
        mixed = rows(100, 100, 100, 100) + [{"pass": False, "wall_ms": 1}]
        got = eval_stats.summarize(mixed)
        self.assertEqual(got["passed"], 4)
        self.assertAlmostEqual(got["pass_k"], 0.8 ** 5)
        self.assertEqual(got["min"], 100.0)  # the failed run's 1 ms never counts as fast

    def test_alternates_a_then_b(self) -> None:
        order: list[str] = []
        eval_stats.alternate(lambda: order.append("A") or {"pass": True, "wall_ms": 1},  # type: ignore[func-returns-value]
                             lambda: order.append("B") or {"pass": True, "wall_ms": 1}, 3)  # type: ignore[func-returns-value]
        self.assertEqual(order, ["A", "B"] * 3)

    def verdict_for(self, a: list[int], b: list[int]) -> str:
        return str(eval_stats.verdict(eval_stats.summarize(rows(*a)), eval_stats.summarize(rows(*b))))

    def test_faster(self) -> None:
        self.assertEqual(self.verdict_for([100, 102, 101, 99, 100], [50, 52, 51, 49, 50]), eval_stats.FASTER)

    def test_slower(self) -> None:
        self.assertEqual(self.verdict_for([100, 102, 101, 99, 100], [200, 205, 199, 201, 200]), eval_stats.SLOWER)

    def test_no_difference_inside_threshold(self) -> None:
        self.assertEqual(self.verdict_for([100, 102, 101, 99, 100], [104, 106, 105, 103, 104]), eval_stats.NO_DIFFERENCE)

    def test_inconclusive_when_ranges_overlap(self) -> None:
        self.assertEqual(self.verdict_for([60, 100, 140, 80, 120], [90, 130, 170, 110, 150]), eval_stats.INCONCLUSIVE)

    def test_inconclusive_with_too_few_runs_or_a_failure(self) -> None:
        self.assertEqual(self.verdict_for([100, 100, 100], [10, 10, 10]), eval_stats.INCONCLUSIVE)
        failed = eval_stats.summarize(rows(100, 100, 100, 100) + [{"pass": False, "wall_ms": 5}])
        self.assertEqual(eval_stats.verdict(eval_stats.summarize(rows(100, 100, 100, 100, 100)), failed), eval_stats.INCONCLUSIVE)

    def test_compare_with_a_fake_runner(self) -> None:
        times = iter([100, 50] * 5)
        result = eval_stats.compare(lambda: {"pass": True, "wall_ms": next(times)}, lambda: {"pass": True, "wall_ms": next(times)})
        self.assertEqual(result["verdict"], eval_stats.FASTER)
        self.assertEqual((result["a"]["k"], result["b"]["k"]), (5, 5))


class EvalRunnerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_mod = load("eval_run_b7", RUN_PY)

    def main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["run.py", *argv]), contextlib.redirect_stdout(out):
            code = self.run_mod.main()
        return code, out.getvalue()

    def test_fewer_than_five_runs_refused(self) -> None:
        code, out = self.main("--arm-b-env", "X=1", "--runs", "3")
        self.assertEqual(code, 2)
        self.assertIn("at least 5", out)

    def test_bad_override_refused(self) -> None:
        code, out = self.main("--arm-b-env", "NOEQUALS")
        self.assertEqual(code, 2)
        self.assertIn("KEY=VALUE", out)

    def test_ab_mode_reports_with_a_fake_fixture_runner(self) -> None:
        walls = iter([100, 50] * 5)
        fake = lambda _fixture, _env: {"pass": True, "wall_ms": next(walls), "tokens": 0, "fix_rounds": 0, "mismatch": {}}  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(self.run_mod, "run_fixture", fake):
            code, out = self.main("--fixture", "clean-fix", "--arm-b-env", "X=1", "--results-dir", tmp)
            self.assertEqual(code, 0)
            self.assertIn("clean-fix: faster", out)
            self.assertIn("median 100 ms", out)
            self.assertIn("pass^k 1.00", out)
            saved = next(Path(tmp).glob("*-ab.json"))
            self.assertEqual(json.loads(saved.read_text())["fixtures"]["clean-fix"]["verdict"], "faster")


def write_plugin(root: Path, version: str, repository: str | None = None) -> Path:
    manifest = root / ".claude-plugin"
    manifest.mkdir(parents=True)
    data: dict[str, Any] = {"name": "dts2-harness", "version": version}
    if repository:
        data["repository"] = repository
    (manifest / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
    return root


class SkillsCliPinTests(unittest.TestCase):
    def test_npx_argv_pins_the_version(self) -> None:
        sc = load("skills_check_b7", SKILLS_CHECK)
        self.assertRegex(sc.SKILLS_CLI_VERSION, r"^\d+\.\d+\.\d+$")
        argv = sc.npx("add", "x")
        self.assertEqual(argv[-4:], ["--yes", f"skills@{sc.SKILLS_CLI_VERSION}", "add", "x"])
        self.assertNotIn("skills", argv)  # a bare `skills` (a moving latest) is never passed


class LeaseGateTests(unittest.TestCase):
    def lease(self, repo: Path, stamp: str, lane: str, status: str, expires: int) -> None:
        folder = repo / ".harness" / "runs" / stamp / lane
        folder.mkdir(parents=True)
        (folder / "lease.json").write_text(json.dumps({"status": status, "expires_at": expires}), encoding="utf-8")

    def test_live_leases_listed_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.lease(repo, "s1", "a", "active", FAR_FUTURE)
            self.lease(repo, "s1", "b", "closed", FAR_FUTURE)
            self.lease(repo, "s1", "c", "active", 5)
            before = sorted(p.read_text() for p in repo.rglob("lease.json"))
            self.assertEqual(harness_skew.live_leases(repo, int(time.time())), ["s1/a"])
            self.assertEqual(sorted(p.read_text() for p in repo.rglob("lease.json")), before)

    def test_no_runs_folder_means_no_leases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(harness_skew.live_leases(Path(tmp), 0), [])

    def test_self_upgrade_deferred_while_a_lease_is_live(self) -> None:
        sc = load("skills_check_b7_lease", SKILLS_CHECK)
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(sc, "published_version", return_value="9.9.9"), \
                unittest.mock.patch.object(sc, "run", return_value=(0, "")) as ran:
            repo = Path(tmp) / "repo"
            self.lease(repo, "s1", "a", "active", FAR_FUTURE)
            root = write_plugin(Path(tmp) / "plugin", "1.0.0")
            result = sc.check_harness(repo, Path(tmp) / "home", root, True, True)
            self.assertTrue(result["upgrade_available"])
            self.assertFalse(result["upgrade_started"])
            self.assertIn("s1/a", result["upgrade_deferred"])
            calls = [" ".join(str(a) for a in c.args[0]) for c in ran.call_args_list]
            self.assertFalse([c for c in calls if "plugin update" in c or "handoff-write" in c], calls)


class VersionSkewTests(unittest.TestCase):
    def test_same_version_is_fine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            head = write_plugin(Path(tmp) / "head", "3.10.0")
            son = write_plugin(Path(tmp) / "son", "3.10.0")
            self.assertIsNone(harness_skew.skew_problem(head, son))

    def test_mismatch_and_unreadable_are_problems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            head = write_plugin(Path(tmp) / "head", "3.10.0")
            son = write_plugin(Path(tmp) / "son", "3.9.0")
            self.assertIn("3.9.0", str(harness_skew.skew_problem(head, son)))
            self.assertIn("unreadable", str(harness_skew.skew_problem(head, Path(tmp) / "missing")))

    def test_cli_parks_with_version_skew_reason(self) -> None:
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            head = write_plugin(Path(tmp) / "head", "3.10.0")
            son = write_plugin(Path(tmp) / "son", "3.9.0")
            repo = Path(tmp) / "repo"
            repo.mkdir()
            env = {**os.environ, "DTS2_NPX_BIN": "true", "DTS2_GH_BIN": "true", "DTS2_CLAUDE_BIN": "true"}
            done = subprocess.run([sys.executable, "-I", str(SKILLS_CHECK), str(repo), "--no-upstream", "--home", tmp,
                                   "--plugin-root", str(head), "--son-root", str(son)], capture_output=True, text=True, env=env, check=True)
            skew = json.loads(done.stdout)["skew"]
            self.assertEqual((skew["ok"], skew["reason"]), (False, "version-skew"))


class SupervisorSkewTests(unittest.TestCase):
    """spawn_refusal refuses a son whose plugin.json version differs from the head's (G-76); fake sons are tmp dirs."""

    def refusal(self, son_version: str | None) -> tuple[str, str] | None:
        from lanes import supervisor
        with tempfile.TemporaryDirectory() as tmp:
            head = write_plugin(Path(tmp) / "head", "3.10.0")
            son = write_plugin(Path(tmp) / "son", son_version) if son_version else Path(tmp) / "missing"
            pinned = unittest.mock.Mock(preflight_ok=True, claude_version="2.1.200")
            with unittest.mock.patch.object(supervisor, "PLUGIN_ROOT", head), \
                    unittest.mock.patch.object(supervisor, "read_run", return_value=pinned):
                return supervisor.spawn_refusal(Path(tmp), "s1", Path(tmp), "a", son)

    def test_mismatched_son_is_refused_with_the_skew_reason(self) -> None:
        got = self.refusal("3.9.0")
        self.assertIsNotNone(got)
        reason, detail = got or ("", "")
        self.assertEqual(reason, "version-skew")
        self.assertIn("3.9.0", detail)

    def test_unreadable_son_version_is_refused(self) -> None:
        got = self.refusal(None)
        self.assertEqual((got or ("", ""))[0], "version-skew")
        self.assertIn("unreadable", (got or ("", ""))[1])


class OrgStringTests(unittest.TestCase):
    def test_marketplace_repo_from_plugin_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(harness_skew.MARKETPLACE_ENV, None)
            root = write_plugin(Path(tmp), "1.0.0", "https://github.com/acme-co/market-place")
            self.assertEqual(harness_skew.marketplace_repo(root), "acme-co/market-place")

    def test_env_override_wins_and_bad_values_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_plugin(Path(tmp), "1.0.0", "https://github.com/acme-co/market-place.git")
            with unittest.mock.patch.dict(os.environ, {harness_skew.MARKETPLACE_ENV: "other/repo"}):
                self.assertEqual(harness_skew.marketplace_repo(root), "other/repo")
            with unittest.mock.patch.dict(os.environ, {harness_skew.MARKETPLACE_ENV: "bad value; rm"}):
                self.assertEqual(harness_skew.marketplace_repo(root), "acme-co/market-place")

    def test_git_remote_is_the_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(harness_skew.proc, "run",
                                                                             return_value=(0, "git@github.com:x-org/y-repo.git\n")):
            os.environ.pop(harness_skew.MARKETPLACE_ENV, None)
            root = write_plugin(Path(tmp), "1.0.0")
            self.assertEqual(harness_skew.marketplace_repo(root), "x-org/y-repo")

    def test_no_name_means_no_remote_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(harness_skew.proc, "run", return_value=(1, "")):
            os.environ.pop(harness_skew.MARKETPLACE_ENV, None)
            self.assertIsNone(harness_skew.marketplace_repo(write_plugin(Path(tmp), "1.0.0")))

    def test_scripts_and_evolve_skill_carry_no_org(self) -> None:
        self.assertNotIn("Dobeu-tech-eco", SKILLS_CHECK.read_text(encoding="utf-8"))
        self.assertNotIn("Dobeu-tech-eco", (PLUGIN_ROOT / "skills" / "evolve" / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
