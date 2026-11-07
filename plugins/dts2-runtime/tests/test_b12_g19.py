"""G-19: proc.py is the one place child processes start: timeout kill, 429 backoff, version pin, fallback flags."""
from __future__ import annotations

import os
import random
import re
import sys
import unittest
from pathlib import Path
from typing import Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import model_call  # noqa: E402
import proc  # noqa: E402


class BinaryTests(unittest.TestCase):
    def test_env_override_py_runs_under_this_python(self) -> None:
        with mock.patch.dict(os.environ, {"X_BIN": "/tmp/tool.py"}):
            self.assertEqual(proc.binary("X_BIN", "gh"), [sys.executable, "/tmp/tool.py"])

    def test_default_is_resolved_or_kept(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X_BIN", None)
            self.assertTrue(proc.binary("X_BIN", "definitely-not-installed-xyz")[0].endswith("definitely-not-installed-xyz"))


class RealRunnerTests(unittest.TestCase):
    def test_timeout_is_143_and_flagged(self) -> None:
        result = proc.SubprocessRunner().run([sys.executable, "-c", "import time; time.sleep(30)"], ".", 1)
        self.assertEqual(result["code"], 143)
        self.assertTrue(result["timed_out"])

    def test_missing_binary_is_127(self) -> None:
        result = proc.SubprocessRunner().run(["/nonexistent/binary-xyz"], ".", 5)
        self.assertEqual(result["code"], 127)

    def test_clean_run_returns_output(self) -> None:
        result = proc.SubprocessRunner().run([sys.executable, "-c", "print('hi')"], ".", 10)
        self.assertEqual((result["code"], result["stdout"].strip()), (0, "hi"))


class FakeRunnerTests(unittest.TestCase):
    def test_scripted_answers_and_recorded_calls(self) -> None:
        fake = proc.FakeRunner([{"stdout": "a"}, {"code": 2, "stderr": "bad"}])
        self.assertEqual(proc.run(["x", "1"], ".", runner=fake), (0, "a"))
        self.assertEqual(proc.run(["x", "2"], ".", runner=fake, merge_stderr=True), (2, "bad"))
        self.assertEqual([c["argv"] for c in fake.calls], [["x", "1"], ["x", "2"]])

    def test_running_out_of_answers_is_an_error(self) -> None:
        with self.assertRaises(AssertionError):
            proc.FakeRunner([]).run(["x"], ".", 1)

    def test_callable_answer_sees_argv(self) -> None:
        fake = proc.FakeRunner([lambda argv: {"stdout": argv[-1]}])
        self.assertEqual(proc.run(["x", "tail"], ".", runner=fake), (0, "tail"))

    def test_dry_run_runs_nothing(self) -> None:
        dry = proc.DryRunRunner()
        result = dry.run(["rm", "-rf", "/"], ".", 1)
        self.assertTrue(result["dry_run"])
        self.assertEqual(dry.calls, [["rm", "-rf", "/"]])

    def test_run_strips_ansi_and_maps_timeout_code(self) -> None:
        fake = proc.FakeRunner([{"stdout": "\x1b[31mred\x1b[0m"}, {"timed_out": True, "code": 143}])
        self.assertEqual(proc.run(["x"], ".", runner=fake, strip_ansi=True), (0, "red"))
        self.assertEqual(proc.run(["x"], ".", runner=fake, timeout_code=124), (124, "timed out"))


class RetryTests(unittest.TestCase):
    def run_retry(self, answers: list[dict], retry_max: int = 3, halt=None):
        sleeps: list[float] = []
        events: list[dict] = []
        fake = proc.FakeRunner(answers)
        result = proc.run_retrying(
            lambda left: fake.run(["c"], ".", left), 100, retry_max=retry_max, base_s=1, cap_s=8,
            retriable=lambda r: r["code"] != 0 and proc.looks_overloaded(r["stderr"]), halt=halt,
            sleep=sleeps.append, rng=random.Random(1), clock=lambda: 0.0, emit=events.append, label="t")
        return result, sleeps, events, fake

    def test_429_is_retried_with_growing_backoff_then_succeeds(self) -> None:
        result, sleeps, events, fake = self.run_retry(
            [{"code": 1, "stderr": "429 rate limit"}, {"code": 1, "stderr": "overloaded"}, {"code": 0}])
        self.assertEqual((result["code"], result["attempts"], result["retries"]), (0, 3, 2))
        self.assertEqual(len(sleeps), 2)
        self.assertLess(sleeps[0], sleeps[1] + 1)
        self.assertEqual([e["event"] for e in events], ["retry", "retry"])
        self.assertEqual(len(fake.calls), 3)

    def test_exhausted_retries_return_the_last_failure(self) -> None:
        result, _, _, fake = self.run_retry([{"code": 1, "stderr": "429"}] * 3, retry_max=2)
        self.assertEqual((result["code"], result["attempts"]), (1, 3))
        self.assertEqual(len(fake.calls), 3)

    def test_other_failures_are_not_retried(self) -> None:
        result, sleeps, _, fake = self.run_retry([{"code": 1, "stderr": "syntax error"}])
        self.assertEqual((result["attempts"], sleeps, len(fake.calls)), (1, [], 1))

    def test_halt_stops_retries_and_flags_it(self) -> None:
        result, sleeps, events, _ = self.run_retry([{"code": 1, "stderr": "429"}], halt=lambda r: True)
        self.assertTrue(result["halted_overload"])
        self.assertEqual((sleeps, events[0]["event"]), ([], "retry-halted"))

    def test_backoff_is_capped(self) -> None:
        self.assertLessEqual(proc.backoff_delay(20, 2.0, 60.0, random.Random(0)), 62.0)


class PinAndFallbackTests(unittest.TestCase):
    def test_cli_version_parses(self) -> None:
        self.assertEqual(proc.cli_version("2.1.7 (Claude Code)"), "2.1.7")
        self.assertIsNone(proc.cli_version("no digits"))

    def test_version_problem(self) -> None:
        self.assertIsNone(proc.version_problem(None, "2.1.7"))
        self.assertIsNone(proc.version_problem("2.1.7", "2.1.7"))
        self.assertIn("pinned", proc.version_problem("2.1.7", "2.2.0") or "")
        self.assertIn("cannot read", proc.version_problem(None, None) or "")

    def test_fallback_flags_cap_at_three(self) -> None:
        self.assertEqual(proc.fallback_flags(["a", "", "b", "c", "d"]), ["--fallback-model", "a,b,c"])
        self.assertEqual(proc.fallback_flags([]), [])

    def test_terminated_codes(self) -> None:
        self.assertTrue(proc.is_terminated(143))
        self.assertFalse(proc.is_terminated(1))


class MovedNotDuplicatedTests(unittest.TestCase):
    def test_model_call_reexports_the_proc_objects(self) -> None:
        for name in ("run_once", "terminate", "backoff_delay", "cli_version", "is_terminated"):
            self.assertIs(getattr(model_call, name), getattr(proc, name), name)

    def test_no_second_copy_of_the_process_code(self) -> None:
        for name in ("model_call.py", "skills-check.py", "task-ledger.py"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"subprocess\.(run|Popen)\(", text), name)
        self.assertNotIn("def terminate", (SCRIPTS / "model_call.py").read_text(encoding="utf-8"))

    def test_retry_loop_still_retries_through_the_patched_run_once(self) -> None:
        calls: list[int] = []

        def fake(argv, cwd, timeout_s, env, stdin_text=None, on_start=None):
            calls.append(1)
            return {"code": 1 if len(calls) == 1 else 0, "stdout": "", "stderr": "429", "timed_out": False}

        settings = {"retry_max": 2, "backoff_base_s": 0.0, "backoff_cap_s": 0.0}
        with mock.patch.object(model_call, "run_once", fake):
            out = model_call.retry_loop(["c"], Path("."), 10, "t", settings, lambda e: None, None, lambda s: None, None)
        self.assertEqual((out["code"], out["retries"]), (0, 1))


class CallersTests(unittest.TestCase):
    def test_task_ledger_open_prs_through_a_fake_runner(self) -> None:
        import _load
        ledger = _load.load("task-ledger")
        fake = proc.FakeRunner([{"stdout": '[{"number": 4}, {"number": 9}]'}])
        self.assertEqual(ledger.open_pr_numbers(Path("."), fake), {4, 9})
        self.assertEqual(ledger.open_pr_numbers(Path("."), proc.FakeRunner([{"code": 1}])), None)
        self.assertEqual(ledger.open_pr_numbers(Path("."), proc.FakeRunner([{"stdout": "not json"}])), None)

    def test_skills_check_run_through_a_fake_runner(self) -> None:
        import _load
        sc = _load.load("skills-check")
        with mock.patch.object(sc, "RUNNER", proc.FakeRunner([{"stdout": "\x1b[1mok\x1b[0m", "stderr": "!"}])):
            self.assertEqual(sc.run(["x"], Path(".")), (0, "ok!"))
        with mock.patch.object(sc, "RUNNER", proc.FakeRunner([{"timed_out": True, "code": 143}])):
            self.assertEqual(sc.run(["x"], Path("."))[0], sc.TIMED_OUT)


if __name__ == "__main__":
    unittest.main()
