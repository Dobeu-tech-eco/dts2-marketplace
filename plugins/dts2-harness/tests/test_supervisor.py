"""Contracts for the lanes.py supervisor: caps, spend accounting, concurrency, backoff, CLI pin, fallback, heartbeat,
stall snapshot, loop cap and merge order. Every model is a fake DTS2_CLAUDE_BIN script; nothing real runs."""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
LANES: Final[Path] = SCRIPTS / "lanes.py"
sys.path.insert(0, str(SCRIPTS))
import model_call  # noqa: E402

STAMP: Final[str] = "20261104-9"
VERSION: Final[str] = "2.1.230"
FAKE_CLAUDE: Final[str] = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
argv = sys.argv[1:]
if "--version" in argv:
    print(os.environ.get("FAKE_VERSION", "2.1.230") + " (Claude Code)")
    sys.exit(0)
state = Path(os.environ["FAKE_DIR"])
with open(state / "calls.log", "a") as log:
    log.write(json.dumps(argv) + "\n")
count_file = state / "count"
is_probe = "-p" in argv and argv[argv.index("-p") + 1] == "ok"
count = int(count_file.read_text()) if count_file.exists() else 0
if not is_probe:
    count += 1
    count_file.write_text(str(count))
mode = os.environ.get("FAKE_MODE", "ok")
session = os.environ.get("FAKE_SESSION", "sess-1")
cost = float(os.environ.get("FAKE_COST", "0.5"))
result = {"type": "result", "subtype": "success", "is_error": False, "session_id": session, "num_turns": 3,
          "total_cost_usd": cost}
status_file = os.environ.get("FAKE_STATUS_FILE")
if status_file and "-p" in argv and argv[argv.index("-p") + 1] != "ok":
    Path(status_file).write_text(json.dumps({"lane": "a", "status": os.environ.get("FAKE_PHASE", "done")}))
if mode == "429-then-ok" and count <= int(os.environ.get("FAKE_FAILS", "2")):
    sys.stderr.write("API Error: 429 rate_limit_error\n")
    sys.exit(1)
if mode == "always-429":
    print(json.dumps({**result, "is_error": True, "result": "overloaded_error"}))
    sys.exit(1)
if mode == "no-cost":
    del result["total_cost_usd"]
if mode == "zero-cost":
    result["total_cost_usd"] = 0
if mode == "exit143":
    sys.exit(143)
if mode == "sleep":
    time.sleep(30)
if mode == "fallback":
    result["modelUsage"] = {"claude-sonnet-fake": {"costUSD": cost}}
if mode == "max-turns":
    result.update({"subtype": "error_max_turns", "is_error": True})
    print(json.dumps(result))
    sys.exit(1)
if mode == "error":
    sys.stderr.write("boom\n")
    sys.exit(1)
if mode == "garbage":
    print("not json at all")
    sys.exit(0)
print(json.dumps(result))
'''
FAKE_GIT: Final[str] = """#!/usr/bin/env python3
import sys
if "--version" in sys.argv:
    print("git version 2.40.0")
else:
    print("diff --git a/x b/x\\n+changed")
"""


class SupervisorBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-sup-"))
        self.repo = self.root / "repo"
        self.runs = self.repo / ".harness" / "runs" / STAMP
        self.lane_dir = self.runs / "a"
        self.lane_dir.mkdir(parents=True)
        self.worktree = self.root / "wt-a"
        self.worktree.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        (self.root / "claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
        (self.root / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        self.manifest = self.root / "lanes.json"
        self.manifest.write_text(json.dumps({"stamp": STAMP, "base": "abc", "scope": "single", "lanes": [
            {"id": "a", "item": "S1", "files": ["a.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}),
            encoding="utf-8")
        self.env: dict[str, str] = {
            "DTS2_CLAUDE_BIN": str(self.root / "claude.py"), "DTS2_GIT_BIN": str(self.root / "git.py"),
            "FAKE_DIR": str(self.state), "FAKE_STATUS_FILE": str(self.lane_dir / "status.json"),
        }

    def config(self, text: str) -> None:
        path = self.repo / ".harness" / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def lanes(self, *args: str, **env: str) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, env={**os.environ, **self.env, **env}, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        parsed["_code"] = done.returncode
        return parsed

    def preflight(self, **env: str) -> dict[str, Any]:
        return self.lanes("preflight", STAMP, **env)

    def spawn(self, *extra: str, **env: str) -> dict[str, Any]:
        return self.lanes("spawn", str(self.manifest), "--lane", "a", "--worktree", str(self.worktree), *extra, **env)

    def json_file(self, name: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.runs / name).read_text(encoding="utf-8"))
        return data

    def ledger(self) -> list[dict[str, Any]]:
        path = self.runs / "model-ledger.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def calls(self) -> list[list[str]]:
        text = (self.state / "calls.log").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line]

    def son_calls(self) -> list[list[str]]:
        return [c for c in self.calls() if c[c.index("-p") + 1] != "ok"]

    def status_json(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.lane_dir / "status.json").read_text(encoding="utf-8"))
        return data


class PreflightTests(SupervisorBase):
    def test_preflight_pins_version_and_enables_spawn(self) -> None:
        result = self.preflight()
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.json_file("run.json")["claude_version"], VERSION)
        probe = self.calls()[0]
        self.assertEqual(probe[probe.index("-p") + 1], "ok")
        self.assertEqual(probe[probe.index("--output-format") + 1], "json")

    def test_spawn_refuses_without_preflight(self) -> None:
        result = self.spawn()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "preflight-missing")
        self.assertEqual(self.status_json()["status"], "incomplete")
        self.assertFalse((self.state / "calls.log").exists(), "no son may start")

    def test_failed_probe_leaves_spawn_closed(self) -> None:
        result = self.preflight(FAKE_MODE="error")
        self.assertFalse(result["ok"])
        self.assertFalse(self.json_file("run.json")["preflight_ok"])
        self.assertEqual(self.spawn()["reason"], "preflight-missing")

    def test_second_preflight_with_other_version_is_refused(self) -> None:
        self.preflight()
        result = self.preflight(FAKE_VERSION="2.2.0")
        self.assertFalse(result["ok"])
        self.assertIn("differs", result["problems"][0])
        self.assertEqual(self.json_file("run.json")["claude_version"], VERSION)

    def test_spawn_refuses_on_version_skew(self) -> None:
        self.preflight()
        result = self.spawn(FAKE_VERSION="2.2.0")
        self.assertEqual(result["reason"], "version-skew")
        self.assertEqual(self.status_json()["reason"], "version-skew")
        self.assertEqual(len(self.calls()), 1, "only the preflight probe ran")


class SpawnTests(SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        self.config("budget:\n  max_turns: 7\n")
        self.preflight()

    def test_son_gets_caps_fallback_and_json_output(self) -> None:
        result = self.spawn()
        self.assertTrue(result["ok"], result)
        argv = self.son_calls()[0]
        self.assertEqual(argv[argv.index("--max-turns") + 1], "7")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--fallback-model") + 1], "sonnet")
        self.assertNotIn("--max-budget-usd", argv)
        self.assertNotIn("--resume", argv)

    def test_status_gets_session_worktree_and_heartbeat(self) -> None:
        self.spawn()
        status = self.status_json()
        self.assertEqual(status["session_id"], "sess-1")
        self.assertEqual(status["worktree"], str(self.worktree))
        self.assertAlmostEqual(status["heartbeat"], time.time(), delta=30)
        self.assertEqual(status["status"], "done")

    def test_cost_is_recorded(self) -> None:
        result = self.spawn()
        self.assertEqual(result["charged_usd"], 0.5)
        budget = self.json_file("budget.json")
        self.assertEqual(budget["spent_usd"], 0.5)
        self.assertEqual(budget["unknown_calls"], 0)
        self.assertIn("son-exit", [e["event"] for e in self.ledger()])

    def test_missing_cost_is_unknown_not_zero(self) -> None:
        result = self.spawn(FAKE_MODE="no-cost")
        self.assertIsNone(result["charged_usd"])
        self.assertFalse(result["cost_known"])
        budget = self.json_file("budget.json")
        self.assertEqual(budget["unknown_calls"], 1)
        self.assertEqual(self.lanes("budget", STAMP)["spend_complete"], False)

    def test_zero_cost_is_unknown_not_zero(self) -> None:
        result = self.spawn(FAKE_MODE="zero-cost")
        self.assertIsNone(result["charged_usd"])
        self.assertEqual(self.json_file("budget.json")["unknown_calls"], 1)

    def test_unparseable_output_is_unknown_cost(self) -> None:
        result = self.spawn(FAKE_MODE="garbage")
        self.assertIsNone(result["charged_usd"])
        self.assertEqual(result["session_id"], None)

    def test_max_usd_is_passed_as_remaining_budget(self) -> None:
        self.config("budget:\n  max_usd: 2.0\n")
        self.spawn(FAKE_COST="0.5", FAKE_PHASE="building")
        self.spawn("--resume", FAKE_COST="0.75", FAKE_PHASE="done")
        first, second = self.son_calls()
        self.assertEqual(first[first.index("--max-budget-usd") + 1], "2.00")
        # the flag counts only new spend on a resume, so the resumed son gets the share left
        self.assertEqual(second[second.index("--max-budget-usd") + 1], "1.50")

    def test_resume_charges_only_the_difference(self) -> None:
        self.spawn(FAKE_COST="1.0", FAKE_PHASE="building")
        parked = self.status_json()
        self.assertEqual(parked["status"], "incomplete")
        self.assertEqual(parked["reason"], "no-final-status")
        self.assertEqual(parked["cost_at_park"], 1.0)
        result = self.spawn("--resume", FAKE_COST="1.6", FAKE_PHASE="done")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["charged_usd"], 0.6)
        self.assertEqual(self.json_file("budget.json")["spent_usd"], 1.6)
        self.assertEqual(self.son_calls()[1][self.son_calls()[1].index("--resume") + 1], "sess-1")

    def test_resume_without_session_parks(self) -> None:
        result = self.spawn("--resume")
        self.assertFalse(result["ok"])
        self.assertEqual(self.status_json()["status"], "incomplete")

    def test_exit_143_maps_to_incomplete_timeout(self) -> None:
        result = self.spawn(FAKE_MODE="exit143", FAKE_PHASE="building")
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(self.status_json()["status"], "incomplete")
        self.assertEqual(self.status_json()["reason"], "timeout")
        self.assertIn("park", [e["event"] for e in self.ledger()])

    def test_wall_clock_kills_a_slow_son(self) -> None:
        self.config("budget:\n  max_wall_minutes: 0.03\n")
        started = time.monotonic()
        result = self.spawn(FAKE_MODE="sleep", FAKE_PHASE="building")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["exit"], 143)

    def test_max_turns_result_parks_with_reason(self) -> None:
        result = self.spawn(FAKE_MODE="max-turns", FAKE_PHASE="building")
        self.assertEqual(result["reason"], "max-turns")

    def test_plain_error_parks(self) -> None:
        self.assertEqual(self.spawn(FAKE_MODE="error", FAKE_PHASE="building")["reason"], "error")

    def test_finished_lane_is_not_overwritten_by_a_late_error(self) -> None:
        self.spawn(FAKE_MODE="error", FAKE_PHASE="done")
        self.assertEqual(self.status_json()["status"], "done")

    def test_fallback_is_recorded_in_ledger_and_status(self) -> None:
        result = self.spawn(FAKE_MODE="fallback")
        self.assertEqual(result["fallback_model"], "claude-sonnet-fake")
        self.assertEqual(self.status_json()["fallback_model"], "claude-sonnet-fake")
        self.assertIn("fallback", [e["event"] for e in self.ledger()])

    def test_primary_model_in_usage_is_not_a_fallback(self) -> None:
        parsed = model_call.parse_result(json.dumps({"type": "result", "modelUsage": {"claude-opus-x": {}}}))
        self.assertIsNone(model_call.fallback_used(parsed, "opus"))


class CapTests(SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        self.preflight()

    def test_max_rounds_stops_further_starts(self) -> None:
        self.config("budget:\n  max_rounds: 1\n")
        self.assertTrue(self.spawn()["ok"])
        result = self.spawn()
        self.assertEqual(result["reason"], "budget")
        self.assertIn("max_rounds", result["detail"])
        self.assertEqual(len(self.son_calls()), 1)

    def test_max_usd_spent_stops_further_starts_and_parks(self) -> None:
        self.config("budget:\n  max_usd: 1.0\n")
        self.spawn(FAKE_COST="1.2", FAKE_PHASE="building")
        result = self.spawn("--resume")
        self.assertEqual(result["reason"], "budget")
        self.assertIn("max_usd", result["detail"])
        self.assertEqual(self.status_json()["status"], "incomplete")

    def test_max_wall_spent_stops_further_starts(self) -> None:
        self.config("budget:\n  max_wall_minutes: 1\n")
        self.spawn()
        budget = self.json_file("budget.json")
        (self.runs / "budget.json").write_text(json.dumps({**budget, "started": int(time.time()) - 3600}))
        self.assertIn("max_wall_minutes", self.spawn()["detail"])

    def test_budget_command_reports_caps_and_spend(self) -> None:
        self.config("budget:\n  max_usd: 5\n  max_turns: 9\n")
        self.spawn(FAKE_COST="1.5")
        report = self.lanes("budget", STAMP)
        self.assertEqual(report["caps"]["max_turns"], 9)
        self.assertEqual(report["spent_usd"], 1.5)
        self.assertEqual(report["remaining_usd"], 3.5)
        self.assertTrue(report["spend_complete"])

    def test_defaults_without_config(self) -> None:
        caps = self.lanes("budget", STAMP)["caps"]
        self.assertEqual((caps["max_turns"], caps["max_rounds"], caps["max_fullauto_loops"], caps["max_usd"]),
                         (80, 4, 3, None))

    def test_loop_cap_parks_the_run(self) -> None:
        self.config("budget:\n  max_fullauto_loops: 2\n")
        self.assertTrue(self.lanes("loop", STAMP)["ok"])
        self.assertTrue(self.lanes("loop", STAMP)["ok"])
        third = self.lanes("loop", STAMP)
        self.assertFalse(third["ok"])
        self.assertTrue(third["stop"])
        self.assertEqual(third["status"], "incomplete")
        self.assertIn("park", [e["event"] for e in self.ledger()])


class RetryTests(SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        self.config("supervisor:\n  backoff_base_s: 0\n  retry_max: 3\n")
        self.preflight()

    def test_429_is_retried_and_logged(self) -> None:
        result = self.spawn(FAKE_MODE="429-then-ok", FAKE_FAILS="2")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["retries"], 2)
        retries = [e for e in self.ledger() if e["event"] == "retry"]
        self.assertEqual([e["attempt"] for e in retries], [1, 2])
        self.assertEqual(retries[0]["reason"], "429-or-overload")

    def test_overload_in_json_result_parks_the_son_with_its_session(self) -> None:
        # changed with the retry fix: a son whose failed attempt reports a session is parked `overload` and resumed,
        # not rerun from scratch (the retry-until-cap path for non-son calls is in test_supervisor_fixes)
        result = self.spawn(FAKE_MODE="always-429", FAKE_PHASE="building")
        self.assertFalse(result["ok"])
        self.assertEqual(result["retries"], 0)
        self.assertEqual(result["reason"], "overload")
        self.assertEqual(self.status_json()["session_id"], "sess-1")

    def test_plain_failure_is_not_retried(self) -> None:
        self.assertEqual(self.spawn(FAKE_MODE="error", FAKE_PHASE="building")["retries"], 0)

    def test_call_runs_any_command_with_retry_and_charges_spend(self) -> None:
        out = self.root / "ballot.json"
        result = self.lanes("call", STAMP, "--label", "voter-2", "--out", str(out), "--",
                            sys.executable, str(self.root / "claude.py"), "-p", "vote", "--output-format", "json",
                            FAKE_MODE="429-then-ok", FAKE_FAILS="1")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["retries"], 1)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["session_id"], "sess-1")
        self.assertEqual(self.json_file("budget.json")["lanes"]["call:voter-2"]["charged_usd"], 0.5)

    def test_call_refused_when_budget_spent(self) -> None:
        self.config("budget:\n  max_usd: 1\nsupervisor:\n  backoff_base_s: 0\n")
        self.spawn(FAKE_COST="2")
        result = self.lanes("call", STAMP, "--label", "voter-1", "--", sys.executable, str(self.root / "claude.py"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "budget")


class ModelCallUnitTests(unittest.TestCase):
    def test_backoff_doubles_and_caps_with_jitter(self) -> None:
        rng = random.Random(1)
        delays = [model_call.backoff_delay(n, 2.0, 10.0, rng) for n in range(5)]
        self.assertTrue(all(min(10.0, 2.0 * 2 ** n) <= d <= min(10.0, 2.0 * 2 ** n) + 2.0 for n, d in enumerate(delays)), delays)
        self.assertLessEqual(max(delays), 12.0)

    def test_overload_classifier(self) -> None:
        self.assertTrue(model_call.is_overload(1, "", "HTTP 429 Too Many Requests"))
        self.assertTrue(model_call.is_overload(1, "overloaded_error", ""))
        self.assertTrue(model_call.is_overload(0, json.dumps({"type": "result", "is_error": True,
                                                              "result": "rate limit"}), ""))
        self.assertFalse(model_call.is_overload(0, "429 appears in prose", ""))
        self.assertFalse(model_call.is_overload(1, "", "syntax error"))

    def test_parse_result_is_strict(self) -> None:
        bad = json.dumps({"type": "result", "session_id": "has spaces; rm -rf", "total_cost_usd": "5", "num_turns": -1})
        parsed = model_call.parse_result(bad) or {}
        self.assertIsNone(parsed["session_id"])
        self.assertIsNone(parsed["cost_usd"])
        self.assertIsNone(parsed["num_turns"])
        for cost in (0, -1, True, float("inf"), 1e12):
            line = json.dumps({"type": "result", "total_cost_usd": cost})
            self.assertIsNone((model_call.parse_result(line) or {})["cost_usd"], cost)
        self.assertIsNone(model_call.parse_result("nope"))

    def test_parse_result_reads_a_list_and_cost_alias(self) -> None:
        text = json.dumps([{"type": "system"}, {"type": "result", "session_id": "s_1", "cost_usd": 2.5}])
        parsed = model_call.parse_result(text) or {}
        self.assertEqual((parsed["session_id"], parsed["cost_usd"]), ("s_1", 2.5))

    def test_slot_limit_is_shared_and_released(self) -> None:
        cwd = Path(tempfile.mkdtemp(prefix="dts2-slots-"))
        first = model_call.acquire_slot(cwd, 2, 0)
        second = model_call.acquire_slot(cwd, 2, 0)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(model_call.acquire_slot(cwd, 2, 0), "a third call has to wait")
        model_call.release_slot(first)
        third = model_call.acquire_slot(cwd, 2, 0)
        self.assertIsNotNone(third)
        model_call.release_slot(second)
        model_call.release_slot(third)

    def test_concurrency_default_and_config(self) -> None:
        cwd = Path(tempfile.mkdtemp(prefix="dts2-cfg-"))
        self.assertEqual(model_call.read_supervisor(cwd)["max_model_calls"], 4)
        self.assertEqual(model_call.read_supervisor(cwd)["stall_minutes"], 10)
        (cwd / ".harness").mkdir()
        (cwd / ".harness" / "config.yaml").write_text(
            "other:\n  max_model_calls: 9\nsupervisor:\n  max_model_calls: 2  # shared\n  stall_minutes: 3\n",
            encoding="utf-8")
        settings = model_call.read_supervisor(cwd)
        self.assertEqual((settings["max_model_calls"], settings["stall_minutes"]), (2, 3))


class ConcurrencyTests(SupervisorBase):
    def test_second_call_waits_for_the_only_slot(self) -> None:
        self.config("supervisor:\n  max_model_calls: 1\n")
        sleeper = [sys.executable, "-c", "import time; time.sleep(2)"]
        env = {**os.environ, **self.env}
        started = time.monotonic()
        procs = [subprocess.Popen([sys.executable, "-I", str(LANES), "--cwd", str(self.repo), "call", STAMP,
                                   "--label", f"v{n}", "--", *sleeper], stdout=subprocess.PIPE, text=True, env=env)
                 for n in range(2)]
        for proc in procs:
            proc.communicate(timeout=60)
        self.assertGreaterEqual(time.monotonic() - started, 3.8, "two 2 s calls through one slot run back to back")


class HeartbeatTests(SupervisorBase):
    def write_status(self, **fields: Any) -> Path:
        path = self.lane_dir / "status.json"
        path.write_text(json.dumps({"lane": "a", "status": "building", "worktree": str(self.worktree), **fields}),
                        encoding="utf-8")
        if "heartbeat" in fields:  # a lane that has gone quiet has an old file too (a fresh mtime counts as activity)
            os.utime(path, (fields["heartbeat"], fields["heartbeat"]))
        return path

    def test_heartbeat_command_merges_into_status(self) -> None:
        self.write_status(session_id="keep-me")
        result = self.lanes("heartbeat", STAMP, "--lane", "a", "--turn", "4")
        self.assertTrue(result["ok"])
        status = self.status_json()
        self.assertEqual((status["session_id"], status["turn"], status["status"]), ("keep-me", 4, "building"))
        self.assertAlmostEqual(status["heartbeat"], time.time(), delta=30)

    def test_heartbeat_creates_status_when_missing(self) -> None:
        self.assertTrue(self.lanes("heartbeat", STAMP, "--lane", "a")["ok"])
        self.assertIn("heartbeat", self.status_json())

    def test_fresh_heartbeat_is_not_stalled(self) -> None:
        self.write_status(heartbeat=int(time.time()) - 60)
        row = self.lanes("status", STAMP)["lanes"][0]
        self.assertFalse(row["stale"])
        self.assertEqual(self.status_json()["status"], "building")

    def test_quiet_heartbeat_is_stalled_snapshotted_and_marked(self) -> None:
        self.config("supervisor:\n  stall_minutes: 2\n")
        self.write_status(heartbeat=int(time.time()) - 400)
        row = self.lanes("status", STAMP)["lanes"][0]
        self.assertTrue(row["stale"])
        self.assertEqual(row["incomplete_reason"], "stalled")
        diff = Path(row["snapshot"])
        self.assertIn("+changed", diff.read_text(encoding="utf-8"))
        snapshots = sorted(p.name for p in self.lane_dir.glob("stall-*-status.json"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(json.loads((self.lane_dir / snapshots[0]).read_text(encoding="utf-8"))["status"], "building")
        self.assertEqual(self.status_json()["status"], "incomplete")
        self.assertEqual(self.status_json()["reason"], "stalled")
        self.assertIn("stalled", [e["event"] for e in self.ledger()])
        again = self.lanes("status", STAMP)["lanes"][0]
        self.assertFalse(again["stale"], "an incomplete lane is not snapshotted twice")
        self.assertEqual(len(list(self.lane_dir.glob("stall-*-status.json"))), 1)

    def test_stall_minutes_default_is_ten(self) -> None:
        self.write_status(heartbeat=int(time.time()) - 9 * 60)
        self.assertFalse(self.lanes("status", STAMP)["lanes"][0]["stale"])
        self.write_status(heartbeat=int(time.time()) - 11 * 60)
        self.assertTrue(self.lanes("status", STAMP)["lanes"][0]["stale"])

    def test_stall_without_worktree_still_snapshots_status(self) -> None:
        path = self.write_status(heartbeat=int(time.time()) - 4000)
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["worktree"]
        path.write_text(json.dumps(data), encoding="utf-8")
        os.utime(path, (data["heartbeat"], data["heartbeat"]))
        row = self.lanes("status", STAMP)["lanes"][0]
        self.assertEqual(Path(row["snapshot"]).read_text(encoding="utf-8"), "")


class MergeOrderTests(SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        lanes = [
            {"id": "a", "item": "S1", "files": ["a.py"], "ids": {}, "depends_on": ["b"], "tier": "standard"},
            {"id": "b", "item": "S2", "files": ["b.py"], "ids": {}, "depends_on": [], "tier": "standard"},
            {"id": "c", "item": "S3", "files": ["c.py"], "ids": {}, "depends_on": [], "tier": "standard"},
        ]
        self.manifest.write_text(json.dumps({"stamp": STAMP, "base": "abc", "scope": "single", "lanes": lanes}),
                                 encoding="utf-8")
        for lane_id in "abc":
            (self.runs / lane_id).mkdir(exist_ok=True)

    def phase(self, lane_id: str, phase: str) -> None:
        (self.runs / lane_id / "status.json").write_text(json.dumps({"lane": lane_id, "status": phase}))

    def go(self, lane_id: str) -> dict[str, Any]:
        return self.lanes("merge-go", str(self.manifest), "--lane", lane_id, "--head", "deadbeef")

    def test_order_puts_dependencies_first(self) -> None:
        result = self.lanes("merge-order", str(self.manifest))
        self.assertEqual(result["order"], ["b", "a", "c"])
        self.assertTrue((self.runs / "merge-order.json").is_file())

    def test_merge_go_follows_order_one_at_a_time(self) -> None:
        for lane_id in "abc":
            self.phase(lane_id, "pr-open")
        refused = self.go("a")
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["waiting_on"], ["b"])
        self.assertEqual(self.lanes("merge-order", str(self.manifest))["next"], "b")
        self.assertTrue(self.go("b")["ok"])
        self.assertIn("deadbeef", (self.runs / "b" / "merge-go.md").read_text(encoding="utf-8"))
        self.assertIn("holds the merge", self.go("a")["detail"])
        self.assertFalse(self.lanes("merge-done", str(self.manifest), "--lane", "a")["ok"])
        self.assertTrue(self.lanes("merge-done", str(self.manifest), "--lane", "b")["ok"])
        self.assertTrue(self.go("a")["ok"])

    def test_a_lane_still_building_keeps_its_turn(self) -> None:
        self.phase("b", "building")
        self.phase("a", "pr-open")
        self.phase("c", "pr-open")
        self.assertFalse(self.go("a")["ok"])
        self.assertFalse(self.go("c")["ok"])
        self.assertIsNone(self.lanes("merge-order", str(self.manifest))["next"])

    def test_parked_lane_loses_its_turn_for_lanes_that_do_not_depend_on_it(self) -> None:
        # a depends on b, so a parked b no longer lets a through (see test_supervisor_fixes); c is independent
        self.phase("b", "incomplete")
        self.phase("a", "pr-open")
        self.phase("c", "pr-open")
        self.assertTrue(self.go("c")["ok"])

    def test_dependency_cycle_is_an_error(self) -> None:
        lanes = [{"id": "a", "item": "S1", "files": [], "depends_on": ["b"]},
                 {"id": "b", "item": "S2", "files": [], "depends_on": ["a"]}]
        self.manifest.write_text(json.dumps({"stamp": STAMP, "lanes": lanes}), encoding="utf-8")
        result = self.lanes("merge-order", str(self.manifest))
        self.assertFalse(result["ok"])
        self.assertIn("cycle", result["error"])


if __name__ == "__main__":
    unittest.main()
