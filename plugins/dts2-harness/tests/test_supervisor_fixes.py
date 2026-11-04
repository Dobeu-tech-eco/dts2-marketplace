"""Review fixes for the supervisor: merge order behind a parked dependency, spend of every retry attempt, a son that
keeps its session when overloaded, heartbeat versus status.json age, the dollar cap with unknown costs, one wall-clock
deadline across the slot wait, per-son budget shares, and the prompt piped to a `call` seat. Every model is a fake
DTS2_CLAUDE_BIN script; nothing real runs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any, Final

import test_supervisor as base
from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import model_call  # noqa: E402

STAMP: Final[str] = base.STAMP
SCRIPTED_CLAUDE: Final[str] = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
argv = sys.argv[1:]
if "--version" in argv:
    print("2.1.230 (Claude Code)")
    sys.exit(0)
state = Path(os.environ["FAKE_DIR"])
with open(state / "calls.log", "a") as log:
    log.write(json.dumps(argv) + "\n")
if "-p" in argv and argv[argv.index("-p") + 1] == "ok":
    print(json.dumps({"type": "result", "is_error": False, "session_id": "probe", "total_cost_usd": 0.01}))
    sys.exit(0)
count_file = state / "count"
count = (int(count_file.read_text()) if count_file.exists() else 0) + 1
count_file.write_text(str(count))
(state / f"stdin-{count}.txt").write_text(sys.stdin.read())
script = json.loads(os.environ.get("FAKE_SCRIPT", "[]"))
step = script[min(count, len(script)) - 1] if script else {}
time.sleep(float(step.get("sleep", 0)))
if step.get("stderr"):
    sys.stderr.write(step["stderr"])
if "stdout" in step:
    print(json.dumps(step["stdout"]))
sys.exit(int(step.get("code", 0)))
'''


def result(cost: float | None, session: str, error: bool = False, text: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"type": "result", "subtype": "success", "is_error": error, "session_id": session,
                           "num_turns": 2, "result": text}
    if cost is not None:
        out["total_cost_usd"] = cost
    return out


class FixBase(base.SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "claude.py").write_text(SCRIPTED_CLAUDE, encoding="utf-8")
        self.script: list[dict[str, Any]] = []

    def say(self, *steps: dict[str, Any]) -> dict[str, str]:
        return {"FAKE_SCRIPT": json.dumps(list(steps))}

    def call(self, label: str, *extra: str, **env: str) -> dict[str, Any]:
        return self.lanes("call", STAMP, "--label", label, *extra, "--", sys.executable, str(self.root / "claude.py"), "-p", "vote",
                          "--output-format", "json", **env)

    def budget(self) -> dict[str, Any]:
        return self.json_file("budget.json")


class MergeDependencyTests(base.SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        lanes = [{"id": i, "item": f"S{n}", "files": [f"{i}.py"], "ids": {}, "depends_on": d, "tier": "standard"}
                 for n, (i, d) in enumerate([("a", []), ("b", ["a"]), ("c", ["b"])])]
        self.manifest.write_text(json.dumps({"stamp": STAMP, "base": "abc", "scope": "single", "lanes": lanes}),
                                 encoding="utf-8")
        for lane_id in "abc":
            (self.runs / lane_id).mkdir(exist_ok=True)

    def phase(self, lane_id: str, phase: str) -> None:
        (self.runs / lane_id / "status.json").write_text(json.dumps({"lane": lane_id, "status": phase}))

    def go(self, lane_id: str) -> dict[str, Any]:
        return self.lanes("merge-go", str(self.manifest), "--lane", lane_id, "--head", "deadbeef")

    def test_dependent_of_a_parked_lane_is_never_next(self) -> None:
        self.phase("a", "incomplete")
        self.phase("b", "pr-open")
        self.assertIsNone(self.lanes("merge-order", str(self.manifest))["next"])
        refused = self.go("b")
        self.assertFalse(refused["ok"])
        self.assertIn("depends on unmerged lane a", refused["detail"])
        self.assertFalse((self.runs / "b" / "merge-go.md").exists())

    def test_blocked_dependency_holds_back_transitive_dependents(self) -> None:
        self.phase("a", "blocked")
        self.phase("b", "building")
        self.phase("c", "pr-open")
        refused = self.go("c")
        self.assertFalse(refused["ok"])
        self.assertIn("a", refused["waiting_on"])
        self.assertIn("b", refused["waiting_on"])

    def test_merged_dependency_releases_the_dependent(self) -> None:
        self.phase("a", "pr-open")
        self.phase("b", "pr-open")
        self.assertTrue(self.go("a")["ok"])
        self.assertTrue(self.lanes("merge-done", str(self.manifest), "--lane", "a")["ok"])
        self.assertTrue(self.go("b")["ok"])


class RetrySpendTests(FixBase):
    def setUp(self) -> None:
        super().setUp()
        self.config("supervisor:\n  backoff_base_s: 0\n  retry_max: 3\n")

    def test_every_attempt_is_charged(self) -> None:
        env = self.say({"code": 1, "stdout": result(7.5, "S1", True, "429 rate_limit"), "stderr": "429"},
                       {"stdout": result(0.5, "S2")})
        out = self.call("voter", **env)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["retries"], 1)
        self.assertEqual(out["charged_usd"], 8.0)
        budget = self.budget()
        self.assertEqual(budget["spent_usd"], 8.0)
        self.assertEqual(budget["lanes"]["call:voter"]["rounds"], 1)

    def test_attempt_without_cost_counts_as_unknown(self) -> None:
        env = self.say({"code": 1, "stdout": result(None, "S1", True, "429"), "stderr": "429"},
                       {"stdout": result(0.5, "S2")})
        out = self.call("voter", **env)
        self.assertEqual((out["charged_usd"], out["cost_known"]), (0.5, False))
        self.assertEqual(self.budget()["unknown_calls"], 1)

    def test_son_with_a_session_is_parked_overload_and_resumes(self) -> None:
        self.preflight()
        env = self.say({"code": 1, "stdout": result(7.5, "S1", True, "429 overloaded")},
                       {"stdout": result(0.5, "S1")})
        parked = self.spawn(**env)
        self.assertEqual(parked["reason"], "overload")
        self.assertEqual(len(self.son_calls()), 1, "the whole command is not rerun from scratch")
        self.assertEqual(self.status_json()["session_id"], "S1")
        self.assertEqual(self.budget()["spent_usd"], 7.5)
        self.lane_dir.joinpath("status.json").write_text(json.dumps({**self.status_json(), "status": "done"}))
        resumed = self.spawn("--resume", **env)
        self.assertTrue(resumed["ok"], resumed)
        argv = self.son_calls()[1]
        self.assertEqual(argv[argv.index("--resume") + 1], "S1")
        self.assertEqual(self.budget()["spent_usd"], 8.0)

    def test_son_without_a_session_is_still_retried(self) -> None:
        self.preflight()
        env = self.say({"code": 1, "stderr": "API Error: 429 rate_limit_error"}, {"stdout": result(0.5, "S1")})
        self.lane_dir.joinpath("status.json").write_text(json.dumps({"lane": "a", "status": "done"}))
        done = self.spawn(**env)
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["retries"], 1)


class HeartbeatFreshnessTests(base.SupervisorBase):
    def test_fresh_status_file_outranks_an_old_heartbeat(self) -> None:
        path = self.lane_dir / "status.json"
        path.write_text(json.dumps({"lane": "a", "status": "building", "heartbeat": int(time.time()) - 3600}))
        row = self.lanes("status", STAMP)["lanes"][0]
        self.assertFalse(row["stale"])
        self.assertAlmostEqual(row["last_seen"], time.time(), delta=30)

    def test_old_heartbeat_and_old_file_still_stall(self) -> None:
        path = self.lane_dir / "status.json"
        beat = int(time.time()) - 3600
        path.write_text(json.dumps({"lane": "a", "status": "building", "heartbeat": beat, "worktree": str(self.worktree)}))
        os.utime(path, (beat, beat))
        self.assertTrue(self.lanes("status", STAMP)["lanes"][0]["stale"])


class UnknownCostCapTests(FixBase):
    def test_unknown_cost_blocks_further_calls_under_max_usd(self) -> None:
        self.config("budget:\n  max_usd: 5\n")
        first = self.call("one", **self.say({"stdout": result(None, "S1")}))
        self.assertTrue(first["ok"])
        second = self.call("two", **self.say({"stdout": result(1.0, "S2")}))
        self.assertFalse(second["ok"])
        self.assertIn("spend unknown for 1 calls; max_usd cannot be enforced", second["detail"])
        refused = [e for e in self.ledger() if e["event"] == "refused"]
        self.assertIn("max_usd cannot be enforced", refused[0]["reason"])
        self.assertEqual(len(self.calls()), 1, "the second call never started")

    def test_unknown_cost_without_max_usd_is_allowed(self) -> None:
        self.call("one", **self.say({"stdout": result(None, "S1")}))
        self.assertTrue(self.call("two", **self.say({"stdout": result(1.0, "S2")}))["ok"])

    def test_spawn_is_refused_and_parked(self) -> None:
        self.config("budget:\n  max_usd: 5\n")
        self.preflight()
        self.call("one", **self.say({"stdout": result(None, "S1")}))
        refused = self.spawn()
        self.assertEqual(refused["reason"], "budget")
        self.assertEqual(self.status_json()["status"], "incomplete")


class DeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-deadline-"))
        (self.repo / ".harness").mkdir()
        (self.repo / ".harness" / "config.yaml").write_text("supervisor:\n  max_model_calls: 1\n", encoding="utf-8")

    def test_time_spent_waiting_for_a_slot_comes_off_the_run_limit(self) -> None:
        now = [100.0]
        held = model_call.slot_lock(self.repo / model_call.SLOTS_DIR / "slot-0.lock")

        def nap(seconds: float) -> None:
            now[0] += seconds + 1.0
            if now[0] >= 103.0 and held is not None and not held.closed:
                held.close()

        seen: list[float] = []

        def fake_run(argv: list[str], cwd: Path, timeout_s: float, env: Any, stdin_text: Any = None) -> dict[str, Any]:
            seen.append(timeout_s)
            return {"code": 0, "stdout": "", "stderr": "", "timed_out": False}

        try:
            with mock.patch.object(model_call, "run_once", fake_run):
                out = model_call.invoke(["x"], self.repo, 10.0, "t", sleep=nap, clock=lambda: now[0])
        finally:
            if held is not None and not held.closed:
                held.close()
        self.assertEqual(out["code"], 0)
        self.assertLess(seen[0], 10.0 - 2.0, "the wait for the slot was spent from the same deadline")

    def test_nothing_left_after_the_wait_is_a_timeout(self) -> None:
        ticks = iter([0.0, 0.0, 50.0, 50.0, 50.0])
        with mock.patch.object(model_call, "run_once", side_effect=AssertionError("must not start")):
            out = model_call.invoke(["x"], self.repo, 10.0, "t", clock=lambda: next(ticks))
        self.assertTrue(out["timed_out"])
        self.assertEqual(out["attempts"], 0)
        self.assertTrue(model_call.is_terminated(out["code"]))


class SharedBudgetTests(FixBase):
    def test_parallel_sons_split_max_usd(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.preflight()
        lanes = [{"id": i, "item": "S1", "files": [f"{i}.py"], "ids": {}, "depends_on": [], "tier": "standard"}
                 for i in "ab"]
        self.manifest.write_text(json.dumps({"stamp": STAMP, "base": "abc", "scope": "single", "lanes": lanes}),
                                 encoding="utf-8")
        (self.runs / "b").mkdir(exist_ok=True)
        env = {**os.environ, **self.env, **self.say({"sleep": 2, "stdout": result(0.5, "S1")})}
        procs = [subprocess.Popen([sys.executable, "-I", str(base.LANES), "--cwd", str(self.repo), "--no-prs", "spawn",
                                   str(self.manifest), "--lane", lane, "--worktree", str(self.worktree)],
                                  env=env, stdout=subprocess.PIPE, text=True) for lane in "ab"]
        for proc in procs:
            proc.communicate(timeout=60)
        caps = [float(c[c.index("--max-budget-usd") + 1]) for c in self.son_calls()]
        self.assertEqual(len(caps), 2)
        self.assertLessEqual(sum(caps), 10.0)
        self.assertEqual(self.budget().get("reserved_usd"), {}, "shares are released when the sons finish")

    def test_a_lone_son_gets_what_is_left(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.preflight()
        self.spawn(**self.say({"stdout": result(1.0, "S1")}))
        argv = self.son_calls()[0]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "10.00")


class PromptFileTests(FixBase):
    def test_ballot_reaches_the_seat_on_stdin_on_every_attempt(self) -> None:
        self.config("supervisor:\n  backoff_base_s: 0\n")
        ballot = self.root / "ballot.md"
        ballot.write_text("Vote on the plan.\nVOTE line first.\n", encoding="utf-8")
        env = self.say({"code": 1, "stderr": "429 rate limit"}, {"stdout": result(0.2, "S1")})
        out = self.call("seat", "--prompt-file", str(ballot), **env)
        self.assertTrue(out["ok"], out)
        for n in (1, 2):
            self.assertEqual((self.state / f"stdin-{n}.txt").read_text(encoding="utf-8"), ballot.read_text("utf-8"))

    def test_missing_prompt_file_fails_closed(self) -> None:
        out = self.call("seat", "--prompt-file", str(self.root / "nope.md"))
        self.assertFalse(out["ok"])
        self.assertIn("prompt file", out["error"])
        self.assertFalse((self.state / "calls.log").exists())


class CostSourceTests(FixBase):
    """A non-Claude CLI never prints a cost: it is counted as unreported and never locks a max_usd run."""

    def vote(self, *extra: str) -> dict[str, Any]:
        return self.lanes("call", STAMP, "--label", "seat", *extra, "--", "sh", "-c", "echo 'VOTE: APPROVE'")

    def test_non_claude_seat_does_not_lock_out_max_usd(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.preflight()
        out = self.vote()
        self.assertTrue(out["ok"], out)
        self.assertIn("VOTE: APPROVE", out["stdout"])
        budget = self.budget()
        self.assertEqual((budget["unreported_calls"], budget["unknown_calls"]), (1, 0))
        self.lane_dir.joinpath("status.json").write_text(json.dumps({"lane": "a", "status": "done"}))
        spawned = self.spawn(**self.say({"stdout": result(1.0, "S1")}))
        self.assertNotEqual(spawned.get("reason"), "budget", spawned)
        self.assertTrue(spawned["ok"], spawned)
        report = self.lanes("budget", STAMP)
        self.assertEqual(report["unreported_calls"], 1)
        self.assertFalse(report["spend_complete"])

    def test_explicit_none_on_a_claude_command_is_unreported_too(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        out = self.call("seat", "--cost-source", "none", **self.say({"stdout": result(None, "S1")}))
        self.assertTrue(out["ok"], out)
        self.assertEqual((self.budget()["unreported_calls"], self.budget()["unknown_calls"]), (1, 0))
        self.assertTrue(self.call("next", **self.say({"stdout": result(1.0, "S2")}))["ok"])

    def test_explicit_claude_on_another_command_stays_unknown(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.vote("--cost-source", "claude")
        self.assertEqual((self.budget()["unreported_calls"], self.budget()["unknown_calls"]), (0, 1))

    def test_unreported_calls_alone_keep_spend_incomplete_without_a_cap(self) -> None:
        self.vote()
        self.assertFalse(self.lanes("budget", STAMP)["spend_complete"])


if __name__ == "__main__":
    unittest.main()
