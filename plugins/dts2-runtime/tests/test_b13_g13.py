"""G-13: `transition` is the only writer of a lane's phase; one LEGAL table; heartbeat; graceful shutdown."""
from __future__ import annotations

import itertools
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.common import LaneError, MODEL_LEDGER_NAME  # noqa: E402
from lanes.phases import ACTOR_HEAD, ACTOR_SON, ALL_PHASES, LEGAL, transition  # noqa: E402
from lanes.shutdown import shutdown  # noqa: E402
from lanes.supervisor import park  # noqa: E402

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-7"
SLEEP_IGNORING_TERM: Final[str] = ("import signal, sys, time, pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                                   "pathlib.Path(sys.argv[1]).write_text('up'); time.sleep(60)")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-g13-"))
        self.runs = self.repo / ".harness" / "runs"
        self.addCleanup(os.environ.pop, "DTS2_SON_BRANCH_PREFIX", None)

    def status_file(self, lane: str = "a") -> Path:
        return self.runs / STAMP / lane / "status.json"

    def seed(self, phase: str | None, lane: str = "a", **more: Any) -> None:
        path = self.status_file(lane)
        path.parent.mkdir(parents=True, exist_ok=True)
        if phase is not None:
            path.write_text(json.dumps({"lane": lane, "status": phase, **more}), encoding="utf-8")

    def saved(self, lane: str = "a") -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.status_file(lane).read_text(encoding="utf-8"))
        return data

    def ledger(self) -> list[dict[str, Any]]:
        path = self.runs / STAMP / MODEL_LEDGER_NAME
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def cli(self, *args: str) -> tuple[int, dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, check=False)
        return done.returncode, json.loads(done.stdout)


class LegalTableTests(Base):
    def test_every_move_follows_the_table(self) -> None:
        sources: list[str | None] = [None, *ALL_PHASES]
        for source, target in itertools.product(sources, ALL_PHASES):
            with self.subTest(source=source, target=target):
                self.status_file().unlink(missing_ok=True)
                self.seed(source)
                result = transition(self.runs, STAMP, "a", target, actor=ACTOR_HEAD)
                allowed = source == target or target in LEGAL[source]
                self.assertEqual(result["ok"], allowed, result)
                if not allowed:
                    self.assertIn("illegal move", result["detail"])
                    if source is None:
                        self.assertFalse(self.status_file().exists())
                    else:
                        self.assertEqual(self.saved()["status"], source)

    def test_done_is_final(self) -> None:
        self.assertEqual(LEGAL["done"], frozenset())
        self.seed("done")
        refused = transition(self.runs, STAMP, "a", "pr-open")
        self.assertFalse(refused["ok"])
        self.assertIn("final", refused["detail"])

    def test_a_phase_written_before_the_table_existed_can_move_on(self) -> None:
        self.seed("running")
        self.assertTrue(transition(self.runs, STAMP, "a", "pr-open")["ok"])

    def test_unknown_target_is_an_error(self) -> None:
        with self.assertRaises(LaneError):
            transition(self.runs, STAMP, "a", "building")

    def test_ids_must_be_single_path_segments(self) -> None:
        for stamp, lane in (("None", "a"), ("../x", "a"), (STAMP, "../a"), (STAMP, "null")):
            with self.subTest(stamp=stamp, lane=lane), self.assertRaises(LaneError):
                transition(self.runs, stamp, lane, "done")


class TransitionWriteTests(Base):
    def test_move_stamps_heartbeat_reason_and_a_ledger_line(self) -> None:
        self.seed("starting")
        result = transition(self.runs, STAMP, "a", "blocked", reason="awaiting-items", blocked_by=["S1"], turn=3, now=1000)
        self.assertEqual((result["ok"], result["from"], result["to"]), (True, "starting", "blocked"))
        saved = self.saved()
        self.assertEqual((saved["status"], saved["heartbeat"], saved["reason"], saved["blocked_by"], saved["turn"]),
                         ("blocked", 1000, "awaiting-items", ["S1"], 3))
        events = [e for e in self.ledger() if e["event"] == "transition"]
        self.assertEqual([(e["from"], e["to"], e["actor"]) for e in events], [("starting", "blocked", "head")])

    def test_first_report_creates_the_file(self) -> None:
        self.assertTrue(transition(self.runs, STAMP, "a", "pr-open")["ok"])
        self.assertEqual(self.saved()["status"], "pr-open")

    def test_moving_to_starting_clears_what_the_last_attempt_recorded(self) -> None:
        self.seed("incomplete", reason="timeout", detail="exit 143", parked_at=5, stalled_at=6, worktree="/w")
        transition(self.runs, STAMP, "a", "starting")
        saved = self.saved()
        self.assertEqual((saved["status"], saved["reason"], saved["detail"], saved["parked_at"], saved["stalled_at"]),
                         ("starting", None, None, None, None))
        self.assertEqual(saved["worktree"], "/w")

    def test_staying_in_a_phase_is_a_heartbeat_and_writes_no_ledger_line(self) -> None:
        self.seed("pr-open")
        transition(self.runs, STAMP, "a", "pr-open", now=50)
        self.assertEqual(self.saved()["heartbeat"], 50)
        self.assertEqual([e for e in self.ledger() if e["event"] == "transition"], [])

    def test_a_heartbeat_renews_the_lease(self) -> None:
        self.seed("starting")
        lease = self.runs / STAMP / "a" / "lease.json"
        lease.write_text(json.dumps({"status": "active", "epoch": 1, "expires_at": 10, "ttl_s": 600}), encoding="utf-8")
        transition(self.runs, STAMP, "a", "pr-open", now=1000)
        self.assertEqual(json.loads(lease.read_text(encoding="utf-8"))["expires_at"], 1600)


class SonTests(Base):
    def test_a_son_reports_its_phases_but_never_the_heads(self) -> None:
        os.environ["DTS2_SON_BRANCH_PREFIX"] = "dts2/x/lane-a"
        self.seed("incomplete")
        refused = transition(self.runs, STAMP, "a", "starting")
        self.assertFalse(refused["ok"])
        self.assertIn("head's move", refused["detail"])
        self.assertFalse(transition(self.runs, STAMP, "a", "orphaned")["ok"])
        self.assertTrue(transition(self.runs, STAMP, "a", "blocked", reason="x")["ok"])
        self.assertEqual(self.ledger()[-1]["actor"], ACTOR_SON)

    def test_heartbeat_status_goes_through_the_table(self) -> None:
        self.seed("done")
        code, out = self.cli("heartbeat", STAMP, "--lane", "a", "--status", "pr-open")
        self.assertEqual(code, 2)
        self.assertIn("illegal move", out["detail"])
        self.assertEqual(self.saved()["status"], "done")

    def test_transition_command(self) -> None:
        self.seed("starting")
        code, out = self.cli("transition", STAMP, "--lane", "a", "--to", "pr-open")
        self.assertEqual((code, out["to"]), (0, "pr-open"))
        code, out = self.cli("transition", STAMP, "--lane", "a", "--to", "starting")
        self.assertEqual((code, out["to"]), (0, "starting"))
        code, out = self.cli("transition", STAMP, "--lane", "a", "--to", "done")
        self.assertEqual(code, 0)
        code, out = self.cli("transition", STAMP, "--lane", "a", "--to", "blocked")
        self.assertEqual(code, 2)


class SoleWriterTests(Base):
    def test_only_phases_py_writes_a_lane_phase(self) -> None:
        offenders: list[str] = []
        for path in sorted((SCRIPTS / "lanes").glob("*.py")):
            if path.name == "phases.py":
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            if any(re.search(r'"status":\s*PHASE_', line) and not line.lstrip().startswith("return") for line in lines):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_park_goes_through_transition(self) -> None:
        self.seed("starting", worktree="/w")
        park(self.runs, STAMP, "a", "timeout", "exit 143")
        saved = self.saved()
        self.assertEqual((saved["status"], saved["reason"], saved["detail"]), ("incomplete", "timeout", "exit 143"))
        self.assertEqual([(e["from"], e["to"]) for e in self.ledger() if e["event"] == "transition"], [("starting", "incomplete")])

    def test_park_leaves_a_finished_lane_alone(self) -> None:
        self.seed("done")
        park(self.runs, STAMP, "a", "timeout", "late")
        self.assertEqual(self.saved()["status"], "done")


class ShutdownTests(Base):
    def start(self, code: str) -> subprocess.Popen[bytes]:
        ready = self.repo / "ready"
        proc = subprocess.Popen([sys.executable, "-c", code, str(ready)], start_new_session=True)
        for _ in range(100):  # wait until the child has installed its signal handler
            if ready.exists() or "ignoring" not in code and "SIG_IGN" not in code:
                break
            time.sleep(0.05)
        threading.Thread(target=proc.wait, daemon=True).start()  # reap it, so a stopped child does not linger as a zombie
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def test_running_lane_is_parked_stopped_and_released(self) -> None:
        proc = self.start("import time; time.sleep(60)")
        self.seed("starting", son_pid=proc.pid, spawn_pid=None)
        lease = self.runs / STAMP / "a" / "lease.json"
        lease.write_text(json.dumps({"status": "active", "epoch": 2}), encoding="utf-8")
        self.seed("done", lane="b")
        result = shutdown(self.runs, STAMP, self.repo, grace_s=5.0)
        self.assertTrue(result["ok"])
        rows = {row["lane"]: row for row in result["lanes"]}
        self.assertEqual((rows["a"]["parked"], rows["a"]["stopped"], rows["a"]["killed"], rows["a"]["lease_closed"]),
                         (True, [proc.pid], [], True))
        self.assertIsNotNone(proc.wait(timeout=5))
        saved = self.saved()
        self.assertEqual((saved["status"], saved["reason"], saved["son_pid"]), ("incomplete", "shutdown", None))
        self.assertEqual(json.loads(lease.read_text(encoding="utf-8"))["status"], "closed")
        self.assertEqual(self.saved("b")["status"], "done")
        self.assertFalse(rows["b"]["parked"])

    def test_a_son_that_ignores_sigterm_is_killed_after_the_grace_period(self) -> None:
        proc = self.start(SLEEP_IGNORING_TERM)
        self.seed("pr-open", son_pid=proc.pid)
        result = shutdown(self.runs, STAMP, self.repo, grace_s=0.6)
        self.assertEqual(result["lanes"][0]["killed"], [proc.pid])
        self.assertEqual(proc.wait(timeout=5), -signal.SIGKILL)

    def test_the_kill_is_not_recorded_as_a_timeout(self) -> None:
        self.seed("starting")
        shutdown(self.runs, STAMP, self.repo)
        park(self.runs, STAMP, "a", "timeout", "exit 143")  # what the spawn that lost its son would write
        self.assertEqual(self.saved()["reason"], "shutdown")

    def test_shutdown_twice_is_safe_and_a_son_is_refused(self) -> None:
        self.seed("starting")
        self.assertTrue(shutdown(self.runs, STAMP, self.repo)["ok"])
        self.assertTrue(shutdown(self.runs, STAMP, self.repo)["ok"])
        os.environ["DTS2_SON_BRANCH_PREFIX"] = "dts2/x/lane-a"
        self.assertFalse(shutdown(self.runs, STAMP, self.repo)["ok"])

    def test_shutdown_command_records_one_metrics_row(self) -> None:
        self.seed("starting")
        code, out = self.cli("shutdown", STAMP, "--grace-s", "0.5")
        self.assertEqual((code, out["ok"]), (0, True))
        rows = (self.repo / ".harness" / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(r)["verdict"] for r in rows], ["shutdown"])


if __name__ == "__main__":
    unittest.main()
