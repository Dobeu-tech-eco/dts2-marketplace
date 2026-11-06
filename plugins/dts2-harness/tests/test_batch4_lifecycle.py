"""Batch 4 round 2: the son's process lifecycle. G-52 (setsid, son.json, exit.json, pre-assigned session id, old process
group reaped), G-53 (reconcile applies the deterministic mappings), G-54 (effect dedupe keys), G-55 (lease TTL and gc),
G-56 (CLI semantics: INT then KILL, resume env, max-turns and budget text, api_retry, stream heartbeat), G-57 (the
stuck-loop detector), G-58 (`lanes.py wait`) and G-59 (the `son_model` setting). Every model is a fake DTS2_CLAUDE_BIN."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
import uuid
from pathlib import Path
from typing import Any, Final

import test_supervisor as base
from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import model_call  # noqa: E402
import proc  # noqa: E402
import settings_cache  # noqa: E402
import son_stream  # noqa: E402
import importlib  # noqa: E402

reconcile = importlib.import_module("lanes.reconcile")  # the package re-exports a function of the same name
from lanes import journal, leases, supervisor, waiter  # noqa: E402
from lanes.common import SON_MODEL, son_model  # noqa: E402
from lanes.phases import transition  # noqa: E402

STAMP: Final[str] = base.STAMP
STREAM_CLAUDE: Final[str] = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
argv = sys.argv[1:]
if "--version" in argv:
    print("2.1.250 (Claude Code)")
    sys.exit(0)
state = Path(os.environ["FAKE_DIR"])
if "-p" in argv and argv[argv.index("-p") + 1] == "ok":
    print(json.dumps({"type": "result", "is_error": False, "session_id": "probe", "total_cost_usd": 0.01}))
    sys.exit(0)
(state / "son-argv.json").write_text(json.dumps(argv))
(state / "son-env.json").write_text(json.dumps({k: v for k, v in os.environ.items() if k.startswith("CLAUDE_CODE")}))
(state / "son-pgid.txt").write_text(str(os.getpgid(0)) + " " + str(os.getpid()))
status_file = os.environ.get("FAKE_STATUS_FILE")
deadline = time.time() + 10
while status_file and time.time() < deadline:
    try:
        if json.loads(Path(status_file).read_text()).get("son_pid"):
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.01)
phase = os.environ.get("FAKE_PHASE", "done")
if phase != "none" and status_file:
    tmp = Path(status_file + ".fake")
    tmp.write_text(json.dumps({"lane": "a", "status": phase}))
    os.replace(tmp, status_file)
for step in json.loads(os.environ.get("FAKE_STREAM", "[]")):
    if "line" in step:
        print(json.dumps(step["line"]) if not isinstance(step["line"], str) else step["line"], flush=True)
    time.sleep(float(step.get("sleep", 0)))
sys.exit(int(os.environ.get("FAKE_CODE", "0")))
'''


def tool_pair(n: int, name: str = "Bash", command: str = "ls", out: str = "same", error: bool = False) -> list[dict[str, Any]]:
    return [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": name, "input": {"command": command}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": out, "is_error": error}]}},
    ]


def pairs(commands: list[str], out: str = "same", error: bool = False) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for n, command in enumerate(commands):
        events += tool_pair(n, command=command, out=out, error=error)
    return events


def final(**fields: Any) -> dict[str, Any]:
    return {"type": "result", "subtype": "success", "is_error": False, "session_id": "S1", "num_turns": 2,
            "total_cost_usd": 0.5, **fields}


class StuckDetectorTests(unittest.TestCase):
    def test_same_action_and_observation_four_times(self) -> None:
        self.assertIn("4 times", son_stream.detect_stuck(pairs(["ls"] * 4)) or "")

    def test_three_identical_calls_are_not_yet_stuck(self) -> None:
        self.assertIsNone(son_stream.detect_stuck(pairs(["ls"] * 3)))

    def test_same_action_failing_three_times(self) -> None:
        reason = son_stream.detect_stuck(pairs(["make"] * 3, out="boom", error=True))
        self.assertIn("failed 3 times", reason or "")

    def test_same_action_failing_twice_is_not_stuck(self) -> None:
        self.assertIsNone(son_stream.detect_stuck(pairs(["make"] * 2, out="boom", error=True)))

    def test_ping_pong_six_times(self) -> None:
        events = []
        for n, command in enumerate(["a", "b"] * 3):
            events += tool_pair(n, command=command, out=f"out-{n}")
        self.assertIn("took turns", son_stream.detect_stuck(events) or "")

    def test_ping_pong_five_times_is_not_stuck(self) -> None:
        events = []
        for n, command in enumerate(["a", "b", "a", "b", "a"]):
            events += tool_pair(n, command=command, out=f"out-{n}")
        self.assertIsNone(son_stream.detect_stuck(events))

    def test_progress_is_not_stuck(self) -> None:
        events = []
        for n in range(10):
            events += tool_pair(n, command=f"step {n}", out=f"result {n}")
        self.assertIsNone(son_stream.detect_stuck(events))

    def test_a_call_without_its_result_is_not_a_step(self) -> None:
        self.assertIsNone(son_stream.detect_stuck(pairs(["ls"] * 3) + tool_pair(9)[:1]))

    def test_api_retry_exhaustion(self) -> None:
        retry = {"type": "system", "subtype": "api_retry", "attempt": 2, "max_retries": 10}
        self.assertIsNone(son_stream.api_retries_exhausted("not a stream"))
        self.assertFalse(son_stream.api_retries_exhausted(json.dumps(retry)))
        self.assertTrue(son_stream.api_retries_exhausted(json.dumps({**retry, "attempt": 10})))

    def test_watcher_beats_from_events_and_flags_a_loop(self) -> None:
        beats: list[int] = []
        now = [0.0]
        watcher = son_stream.SonWatcher(lambda: beats.append(1), clock=lambda: now[0])
        stop = [watcher.feed(json.dumps(event)) for event in pairs(["ls"] * 4)]
        self.assertEqual(beats, [1], "one beat inside the throttle window")
        now[0] = 100.0
        watcher.feed(json.dumps({"type": "system"}))
        self.assertEqual(len(beats), 2)
        self.assertTrue(stop[-1])
        self.assertFalse(any(stop[:-1]))
        self.assertIsNotNone(watcher.stuck)
        self.assertFalse(watcher.feed("not json"))


class WrapSonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lane = Path(tempfile.mkdtemp(prefix="dts2-wrap-"))

    def test_fresh_command_gets_a_session_id_and_stream_json(self) -> None:
        cmd = proc.wrap_son(["claude", "-p", "x", "--output-format", "json"], self.lane, "11111111-2222-4333-8444-555555555555")
        self.assertEqual(cmd[cmd.index("--session-id") + 1], "11111111-2222-4333-8444-555555555555")
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", cmd)
        record = json.loads((self.lane / "son.json").read_text())
        self.assertEqual((record["argv"], record["session_id"]), (cmd, "11111111-2222-4333-8444-555555555555"))

    def test_session_id_defaults_to_a_uuid4(self) -> None:
        cmd = proc.wrap_son(["claude", "-p", "x"], self.lane)
        self.assertEqual(uuid.UUID(cmd[cmd.index("--session-id") + 1]).version, 4)

    def test_resume_keeps_its_session(self) -> None:
        cmd = proc.wrap_son(["claude", "-p", "x", "--resume", "OLD"], self.lane, "ignored")
        self.assertNotIn("--session-id", cmd)
        self.assertEqual(proc.son_session(self.lane), "OLD")

    def test_set_option_replaces_or_appends(self) -> None:
        self.assertEqual(proc.set_option(["a", "--m", "x", "b"], "--m", "y"), ["a", "--m", "y", "b"])
        self.assertEqual(proc.set_option(["a"], "--m", "y"), ["a", "--m", "y"])


class ProcessGroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lane = Path(tempfile.mkdtemp(prefix="dts2-pg-"))
        self.kids: list[subprocess.Popen[str]] = []

    def tearDown(self) -> None:
        for kid in self.kids:
            if kid.poll() is None:
                kid.kill()
                kid.wait()

    def start(self, code: str) -> subprocess.Popen[str]:
        kid = subprocess.Popen([sys.executable, "-c", code], start_new_session=True, stdout=subprocess.PIPE, text=True)
        self.kids.append(kid)
        self.assertEqual(kid.stdout.readline().strip(), "ready")  # type: ignore[union-attr]
        threading.Thread(target=kid.wait, daemon=True).start()  # reap it, so a dead group is really gone
        return kid

    def test_old_group_is_interrupted_before_redispatch(self) -> None:
        kid = self.start("import time; print('ready', flush=True); time.sleep(60)")
        proc.record_son_start(self.lane, kid.pid)
        self.assertEqual(json.loads((self.lane / "son.json").read_text())["pgid"], kid.pid)
        self.assertTrue(proc.reap_old_group(self.lane, grace_s=5))
        self.assertFalse(proc.group_alive(kid.pid))
        self.assertIsNone(json.loads((self.lane / "son.json").read_text())["pgid"])

    def test_a_group_that_ignores_sigint_is_killed_after_the_grace(self) -> None:
        kid = self.start("import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)")
        proc.record_son_start(self.lane, kid.pid)
        started = time.monotonic()
        self.assertTrue(proc.reap_old_group(self.lane, grace_s=0.5))
        self.assertFalse(proc.group_alive(kid.pid))
        self.assertGreaterEqual(time.monotonic() - started, 0.5)

    def test_no_group_means_nothing_to_reap(self) -> None:
        self.assertFalse(proc.reap_old_group(self.lane))
        proc.write_record(self.lane / "son.json", {"pgid": os.getpgid(0)})
        self.assertFalse(proc.reap_old_group(self.lane), "never signals its own group")

    def test_timeout_sends_sigint_then_sigkill_and_reports_143(self) -> None:
        code = "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"
        with mock.patch.object(proc, "INT_GRACE_S", 0.5):
            started = time.monotonic()
            out = proc.run_once([sys.executable, "-c", code], ".", 1.0, on_line=lambda _line: False)
        self.assertTrue(out["timed_out"])
        self.assertEqual(out["code"], proc.EXIT_TERMINATED)
        self.assertIn("ready", out["stdout"])
        self.assertLess(time.monotonic() - started, 15)

    def test_sigint_alone_ends_a_child_that_listens(self) -> None:
        code = "import time; print('ready', flush=True); time.sleep(60)"
        started = time.monotonic()
        out = proc.run_once([sys.executable, "-c", code], ".", 1.0, on_line=lambda _line: False)
        self.assertTrue(out["timed_out"])
        self.assertLess(time.monotonic() - started, 10, "no 30 s wait for a child that stops on SIGINT")

    def test_on_line_true_stops_the_child(self) -> None:
        code = "import time\nfor i in range(100):\n    print(i, flush=True); time.sleep(0.05)\ntime.sleep(60)"
        out = proc.run_once([sys.executable, "-c", code], ".", 30.0, on_line=lambda line: line.strip() == "3")
        self.assertTrue(out["stopped"])
        self.assertFalse(out["timed_out"])
        self.assertIn("3\n", out["stdout"])

    def test_the_child_leads_its_own_session(self) -> None:
        seen: list[int] = []
        out = proc.run_once([sys.executable, "-c", "import os; print(os.getpgid(0) == os.getpid())"], ".", 10.0,
                            on_start=seen.append)
        self.assertEqual(out["stdout"].strip(), "True")
        self.assertEqual(len(seen), 1)


class ExitReasonTests(unittest.TestCase):
    def call(self, **fields: Any) -> dict[str, Any]:
        return {"code": 0, "timed_out": False, "halted_overload": False, "retries": 0, **fields}

    def test_budget_limit_text_is_incomplete_budget(self) -> None:
        parsed = model_call.parse_result(json.dumps(final(is_error=True, subtype="success", result="Budget limit reached")))
        self.assertEqual(supervisor.exit_reason(self.call(code=0), parsed), "budget")

    def test_max_turns_text_is_incomplete_max_turns(self) -> None:
        parsed = model_call.parse_result(json.dumps(final(is_error=True, result="Reached max turns (80)")))
        self.assertEqual(supervisor.exit_reason(self.call(code=1), parsed), "max-turns")

    def test_error_max_turns_subtype_still_counts(self) -> None:
        parsed = model_call.parse_result(json.dumps(final(is_error=True, subtype="error_max_turns")))
        self.assertEqual(supervisor.exit_reason(self.call(code=1), parsed), "max-turns")

    def test_a_clean_result_that_mentions_the_budget_is_not_a_failure(self) -> None:
        parsed = model_call.parse_result(json.dumps(final(result="I kept inside the budget limit reached earlier")))
        self.assertIsNone(supervisor.exit_reason(self.call(), parsed))

    def test_a_stuck_son_is_stalled(self) -> None:
        self.assertEqual(supervisor.exit_reason(self.call(stuck="loop", code=-2), None), "stalled")

    def test_api_retry_in_progress_is_not_retried_by_the_harness(self) -> None:
        retrying = json.dumps({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10})
        self.assertFalse(model_call.is_overload(1, retrying, "429 overloaded"))
        gave_up = json.dumps({"type": "system", "subtype": "api_retry", "attempt": 10, "max_retries": 10})
        self.assertTrue(model_call.is_overload(1, gave_up, "529 overloaded"))
        self.assertTrue(model_call.is_overload(1, "", "529 overloaded"), "no stream: the old rule applies")


class ReconcileMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-rec-"))
        self.runs = self.root / "runs"
        self.lane = self.runs / STAMP / "a"
        self.lane.mkdir(parents=True)

    def status(self, phase: str, age: int = 0, **extra: Any) -> None:
        path = self.lane / "status.json"
        old = int(time.time()) - age
        path.write_text(json.dumps({"lane": "a", "status": phase, "heartbeat": old, **extra}))
        os.utime(path, (old, old))

    def run_reconcile(self, prs: list[dict[str, Any]] | None = None, dirty: bool = False) -> dict[str, Any]:
        out = reconcile.reconcile(self.runs, STAMP, self.root, ask=lambda _cwd, _ref: (prs or [], None), dirty=lambda _w: dirty)
        self.assertTrue(out["ok"], out)
        return out

    def phase(self) -> dict[str, Any]:
        return json.loads((self.lane / "status.json").read_text())

    def exit_file(self, **fields: Any) -> None:
        (self.lane / "exit.json").write_text(json.dumps({"code": 1, "signal": None, "reason": None, "timed_out": False, **fields}))

    def test_exit_json_without_a_final_phase_becomes_incomplete(self) -> None:
        for fields, reason in (({"reason": "max-turns"}, "max-turns"), ({"code": -9, "signal": "SIGKILL"}, "timeout"),
                               ({"timed_out": True, "code": 143}, "timeout"), ({"code": 0}, "no-final-status"),
                               ({"code": 2}, "error")):
            self.status("starting")
            self.exit_file(**fields)
            out = self.run_reconcile()
            self.assertEqual(out["actions"]["a"], "incomplete", fields)
            self.assertEqual((self.phase()["status"], self.phase()["reason"]), ("incomplete", reason), fields)

    def test_exit_json_never_overrides_a_finished_lane(self) -> None:
        self.status("done")
        self.exit_file()
        self.assertEqual(self.run_reconcile()["actions"]["a"], "none")
        self.assertEqual(self.phase()["status"], "done")

    def test_merged_on_github_becomes_done(self) -> None:
        self.status("pr-open")
        out = self.run_reconcile([{"number": 7, "state": "MERGED", "url": "u"}])
        self.assertEqual(out["actions"]["a"], "merged")
        self.assertEqual(self.phase()["status"], "done")

    def test_open_pr_is_adopted_not_recreated(self) -> None:
        self.status("pr-open")
        out = self.run_reconcile([{"number": 9, "state": "OPEN", "url": "u"}])
        self.assertEqual(out["actions"]["a"], "adopt-pr")
        self.assertEqual(self.phase()["pr"], 9)

    def test_a_quiet_clean_lane_becomes_incomplete_stalled(self) -> None:
        self.status("starting", age=7200)
        out = self.run_reconcile()
        self.assertEqual(out["actions"]["a"], "stalled")
        self.assertEqual((self.phase()["status"], self.phase()["reason"]), ("incomplete", "stalled"))

    def test_judgement_calls_still_go_back_to_the_head(self) -> None:
        self.status("starting", age=7200, worktree=str(self.root))
        out = self.run_reconcile(dirty=True)
        self.assertEqual(out["actions"]["a"], "resume")
        self.assertEqual(self.phase()["status"], "orphaned")

    def test_a_live_lane_is_left_alone(self) -> None:
        self.status("starting", age=7200, son_pid=os.getpid())
        self.exit_file()
        self.assertEqual(self.run_reconcile()["actions"]["a"], "none")


class EffectDedupeTests(unittest.TestCase):
    def test_journal_note_is_once_per_stamp_kind_lane_and_attempt(self) -> None:
        runs = Path(tempfile.mkdtemp(prefix="dts2-jr-"))
        (runs / STAMP).mkdir()
        self.assertTrue(journal.note(runs, STAMP, "merge-go", lane="a", key=1))
        self.assertFalse(journal.note(runs, STAMP, "merge-go", lane="a", key=1), "same attempt: refused")
        self.assertTrue(journal.note(runs, STAMP, "merge-go", lane="a", key=2), "a new attempt is a new effect")
        self.assertTrue(journal.note(runs, STAMP, "merge-go", lane="b", key=1))
        self.assertEqual(len(journal.journal_events(runs, STAMP, "merge-go")), 3)

    def test_pr_creation_is_check_then_act(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="dts2-cta-"))
        out = reconcile.reconcile_step(STAMP, "s1", root, ask=lambda _c, _b: ([{"number": 3, "state": "OPEN", "url": "u"}], None))
        self.assertEqual(out["action"], "adopt-pr")
        out = reconcile.reconcile_step(STAMP, "s1", root, ask=lambda _c, _b: ([{"number": 3, "state": "MERGED", "url": "u"}], None))
        self.assertEqual(out["action"], "merged")
        out = reconcile.reconcile_step(STAMP, "s1", root, ask=lambda _c, _b: (None, "down"))
        self.assertFalse(out["ok"], "gh down: nothing is decided")


class LeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-lease-"))
        self.runs = self.root / "runs"
        self.lane = self.runs / STAMP / "a"
        self.lane.mkdir(parents=True)
        self.path = self.lane / "lease.json"
        self.manifest = {"stamp": STAMP, "base": "abc", "lanes": [{"id": "a", "files": ["a.py"]}]}

    def lease(self, now: int, ttl: int = 100) -> None:
        leases.write_lease(self.manifest, self.manifest["lanes"][0], self.path, None, ttl, now=now)

    def test_default_ttl_is_a_multiple_of_the_wall_clock_cap(self) -> None:
        self.assertEqual(leases.lease_ttl_s(self.root), 90 * 60 * 2)

    def test_heartbeat_renews_the_ttl(self) -> None:
        self.lease(now=int(time.time()), ttl=100)
        (self.lane / "status.json").write_text(json.dumps({"lane": "a", "status": "starting"}))
        before = json.loads(self.path.read_text())["expires_at"]
        transition(self.runs, STAMP, "a", "starting", now=int(time.time()) + 50, actor="head")
        self.assertEqual(json.loads(self.path.read_text())["expires_at"], before + 50)

    def test_expired_lease_is_not_live(self) -> None:
        self.lease(now=1000, ttl=100)
        record = json.loads(self.path.read_text())
        from lanes.common import lease_live
        self.assertTrue(lease_live(record, 1099))
        self.assertFalse(lease_live(record, 1100))

    def test_gc_closes_a_crashed_runs_expired_lease(self) -> None:
        self.lease(now=1000, ttl=100)
        (self.lane / "status.json").write_text(json.dumps({"lane": "a", "status": "starting", "son_pid": 2_000_000_000}))
        self.assertEqual(leases.gc_leases(self.runs, 5000), [f"{STAMP}/a"])
        record = json.loads(self.path.read_text())
        self.assertEqual((record["status"], record["gc"], record["released"]), ("closed", True, 5000))
        self.assertEqual(leases.gc_leases(self.runs, 5001), [], "twice is safe")

    def test_gc_leaves_a_live_lease_and_a_running_lane(self) -> None:
        self.lease(now=1000, ttl=100)
        self.assertEqual(leases.gc_leases(self.runs, 1050), [])
        (self.lane / "status.json").write_text(json.dumps({"lane": "a", "son_pid": os.getpid()}))
        self.assertEqual(leases.gc_leases(self.runs, 5000), [])
        self.assertEqual(json.loads(self.path.read_text())["status"], "active")

    def test_branch_and_worktree_names_carry_the_stamp(self) -> None:
        from lanes.gitrefs import lane_ref
        self.assertIn(STAMP, lane_ref(STAMP, "a"))

    def test_gc_command_line(self) -> None:
        self.lease(now=1000, ttl=100)
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "lanes.py"), "--cwd", str(self.root), "--runs-dir", str(self.runs), "gc"],
                              capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(done.stdout)["closed"], [f"{STAMP}/a"])


class WaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-wait-"))
        self.runs = self.root / "runs"
        self.lane = self.runs / STAMP / "a"
        self.lane.mkdir(parents=True)
        (self.lane / "status.json").write_text(json.dumps({"lane": "a", "status": "pr-open"}))

    def test_times_out_at_a_hard_deadline_on_the_poll_path(self) -> None:
        now = [0.0]
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        out = waiter.wait_for_change(self.runs, STAMP, 20.0, sleep=sleep, clock=lambda: now[0], inotify=False)
        self.assertTrue(out["timed_out"])
        self.assertEqual(out["method"], "poll")
        self.assertLessEqual(sum(slept), 20.0 + 1e-9)
        self.assertGreater(slept[1], slept[0], "the sleep backs off")
        self.assertLessEqual(max(slept), waiter.BACKOFF_CAP_S)

    def test_returns_when_a_phase_changes(self) -> None:
        now = [0.0]

        def sleep(seconds: float) -> None:
            now[0] += seconds
            (self.lane / "status.json").write_text(json.dumps({"lane": "a", "status": "done"}))

        out = waiter.wait_for_change(self.runs, STAMP, 60.0, sleep=sleep, clock=lambda: now[0], inotify=False)
        self.assertEqual((out["changed"], out["timed_out"]), (["a"], False))
        self.assertEqual(out["lanes"]["a"]["phase"], "done")

    def test_returns_at_once_for_an_unseen_exit(self) -> None:
        (self.lane / "status.json").write_text(json.dumps({"lane": "a", "status": "starting"}))
        (self.lane / "exit.json").write_text("{}")
        out = waiter.wait_for_change(self.runs, STAMP, 60.0, sleep=lambda _s: None, inotify=False)
        self.assertEqual(out["changed"], ["a"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "inotify is Linux only")
    def test_inotify_wakes_on_exit_json(self) -> None:
        if waiter.open_watch(self.runs, STAMP) is None:
            self.skipTest("no inotify here")
        threading.Timer(0.3, lambda: (self.lane / "exit.json").write_text("{}")).start()
        started = time.monotonic()
        out = waiter.wait_for_change(self.runs, STAMP, 30.0)
        self.assertEqual((out["method"], out["changed"]), ("inotify", ["a"]))
        self.assertLess(time.monotonic() - started, 10)

    def test_cli_wait_times_out(self) -> None:
        env = {**os.environ, "DTS2_NO_INOTIFY": "1"}
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "lanes.py"), "--cwd", str(self.root), "--runs-dir", str(self.runs),
                               "wait", STAMP, "--timeout", "1"], capture_output=True, text=True, env=env, check=False)
        out = json.loads(done.stdout)
        self.assertTrue(out["timed_out"], out)
        self.assertEqual(out["method"], "poll")


class SonModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-model-"))
        (self.repo / ".claude").mkdir()

    def settings(self, text: str) -> None:
        (self.repo / ".claude" / "dts2-harness.local.md").write_text(f"---\n{text}\n---\n", encoding="utf-8")

    def test_default_is_sonnet(self) -> None:
        self.assertEqual((son_model(self.repo), SON_MODEL), ("sonnet", "sonnet"))
        self.assertEqual(settings_cache.DEFAULTS["local"]["son_model"], "sonnet")

    def test_setting_overrides_it(self) -> None:
        self.settings("son_model: sonnet")
        self.assertEqual(son_model(self.repo), "sonnet")

    def test_a_bad_name_falls_back(self) -> None:
        self.settings("son_model: 'opus; rm -rf /'")
        self.assertEqual(son_model(self.repo), "sonnet")

    def test_council_head_and_alternate_ids_do_not_overlap(self) -> None:
        block = json.loads((PLUGIN_ROOT / "profiles" / "agents" / "claude.json").read_text())["councilModels"]
        self.assertFalse(set(block["head"]) & set(block["alternates"]))


class SpawnLifecycleTests(base.SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "claude.py").write_text(STREAM_CLAUDE, encoding="utf-8")

    def stream(self, *steps: dict[str, Any], **env: str) -> dict[str, str]:
        return {"FAKE_STREAM": json.dumps(list(steps)), **env}

    def lane_file(self, name: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.lane_dir / name).read_text(encoding="utf-8"))
        return data

    def son_argv(self) -> list[str]:
        argv: list[str] = json.loads((self.state / "son-argv.json").read_text())
        return argv

    def test_son_gets_a_session_id_stream_json_and_the_resume_env(self) -> None:
        self.preflight()
        out = self.spawn(**self.stream({"line": final()}))
        self.assertTrue(out["ok"], out)
        argv = self.son_argv()
        session = argv[argv.index("--session-id") + 1]
        self.assertEqual(uuid.UUID(session).version, 4)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertEqual(json.loads((self.state / "son-env.json").read_text())["CLAUDE_CODE_RESUME_INTERRUPTED_TURN"], "1")

    def test_son_json_records_pid_pgid_and_argv(self) -> None:
        self.preflight()
        self.spawn(**self.stream({"line": final()}))
        record = self.lane_file("son.json")
        pgid, pid = (int(n) for n in (self.state / "son-pgid.txt").read_text().split())
        self.assertEqual((record["pid"], record["pgid"]), (pid, pgid))
        self.assertEqual(record["pgid"], record["pid"], "the son is its own session leader")
        self.assertEqual(record["argv"][2:], self.son_argv(), "son.json holds the argv the son ran with (after the interpreter and script)")
        self.assertIn("--session-id", record["argv"])

    def test_exit_json_has_code_cost_session_and_reason(self) -> None:
        self.preflight()
        self.spawn(**self.stream({"line": final(session_id="S9", total_cost_usd=1.25)}))
        record = self.lane_file("exit.json")
        self.assertEqual((record["code"], record["cost_usd"], record["session_id"], record["reason"]), (0, 1.25, "S9", None))
        self.assertIsNone(record["signal"])

    def test_exit_json_of_a_failed_son_carries_the_reason(self) -> None:
        self.preflight()
        self.spawn(**self.stream({"line": final(is_error=True, subtype="error_max_turns")}, FAKE_CODE="1", FAKE_PHASE="none"))
        record = self.lane_file("exit.json")
        self.assertEqual((record["code"], record["reason"]), (1, "max-turns"))
        self.assertEqual(self.status_json()["reason"], "max-turns")

    def test_budget_limit_text_parks_the_lane_incomplete(self) -> None:
        self.preflight()
        out = self.spawn(**self.stream({"line": final(is_error=True, result="Budget limit reached")}, FAKE_CODE="1", FAKE_PHASE="none"))
        self.assertEqual(out["reason"], "budget")
        self.assertEqual(self.status_json()["status"], "incomplete")

    def test_pre_assigned_session_id_is_saved_before_the_son_reports(self) -> None:
        self.preflight()
        self.spawn(**self.stream(FAKE_PHASE="none", FAKE_CODE="1"))
        argv = self.son_argv()
        self.assertEqual(self.status_json()["session_id"], argv[argv.index("--session-id") + 1])

    def test_resume_uses_the_saved_session_and_no_new_id(self) -> None:
        self.preflight()
        self.spawn(**self.stream({"line": final(session_id="S1", is_error=True, subtype="error_max_turns")}, FAKE_CODE="1", FAKE_PHASE="none"))
        self.spawn("--resume", **self.stream({"line": final(session_id="S1")}))
        argv = self.son_argv()
        self.assertEqual(argv[argv.index("--resume") + 1], "S1")
        self.assertNotIn("--session-id", argv)
        self.assertFalse((self.lane_dir / "exit.json").exists() and self.lane_file("exit.json")["reason"], "a fresh exit.json")

    def test_a_looping_son_is_stopped_and_the_lane_is_stalled(self) -> None:
        self.preflight()
        loop = [{"line": event} for event in pairs(["ls"] * 4)]
        started = time.monotonic()
        out = self.spawn(**self.stream(*loop, {"sleep": 60}, FAKE_PHASE="none"))
        self.assertLess(time.monotonic() - started, 40)
        self.assertEqual(out["reason"], "stalled")
        self.assertEqual((self.status_json()["status"], self.status_json()["reason"]), ("incomplete", "stalled"))
        self.assertIn("same action", self.status_json()["detail"])
        self.assertEqual(self.lane_file("exit.json")["stuck"][:11], "same action")

    def test_old_process_group_is_stopped_before_redispatch(self) -> None:
        self.preflight()
        left = subprocess.Popen(["sleep", "60"], start_new_session=True)
        threading.Thread(target=left.wait, daemon=True).start()
        try:
            proc.write_record(self.lane_dir / "son.json", {"pid": left.pid, "pgid": left.pid})
            self.spawn(**self.stream({"line": final()}))
            deadline = time.time() + 10
            while proc.group_alive(left.pid) and time.time() < deadline:
                time.sleep(0.1)
            self.assertFalse(proc.group_alive(left.pid))
        finally:
            if left.poll() is None:
                left.kill()

    def test_son_model_setting_reaches_the_command(self) -> None:
        settings = self.repo / ".claude" / "dts2-harness.local.md"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("---\nson_model: sonnet\n---\n", encoding="utf-8")
        self.preflight()
        self.spawn(**self.stream({"line": final()}))
        argv = self.son_argv()
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_default_model_is_sonnet(self) -> None:
        self.preflight()
        self.spawn(**self.stream({"line": final()}))
        argv = self.son_argv()
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_resume_passes_the_remaining_budget(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.preflight()
        self.spawn(**self.stream({"line": final(total_cost_usd=4.0, is_error=True, subtype="error_max_turns")}, FAKE_CODE="1", FAKE_PHASE="none"))
        self.spawn("--resume", **self.stream({"line": final(total_cost_usd=1.0)}))
        argv = self.son_argv()
        self.assertEqual(float(argv[argv.index("--max-budget-usd") + 1]), 6.0)


if __name__ == "__main__":
    unittest.main()
