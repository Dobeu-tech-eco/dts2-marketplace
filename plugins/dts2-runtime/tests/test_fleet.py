"""Fleet: session registry per hook event, broadcast delivery and targeting, Stop block-once, list/show/logs,
ref resolution, prune, check-ins and the shell hook. Every test runs against a temp fleet home."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, isolate_agent_status, make_tmp_home

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import fleet  # noqa: E402
import intake  # noqa: E402
import state_io  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "fleet.py"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "fleet-session.sh"
NOW: Final[datetime] = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
SID_A: Final[str] = "aaaa1111-0000-4000-8000-000000000001"
SID_B: Final[str] = "bbbb2222-0000-4000-8000-000000000002"
SID_A2: Final[str] = "aaaa9999-0000-4000-8000-000000000003"


def cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code: int = fleet.main(list(args))
    return code, out.getvalue(), err.getvalue()


class FleetCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home: Path = make_tmp_home()
        patcher = unittest.mock.patch.dict(os.environ, {"DTS2_FLEET_HOME": str(self.home / "fleet")})
        patcher.start()
        self.addCleanup(patcher.stop)
        isolate_agent_status(self)
        self.repo: Path = make_tmp_home()

    def payload(self, sid: str = SID_A, cwd: Path | None = None, **extra: Any) -> dict[str, Any]:
        return {"session_id": sid, "cwd": str(cwd or self.repo), "transcript_path": str(self.repo / "t.jsonl"), **extra}

    def event(self, name: str, sid: str = SID_A, now: datetime = NOW, cwd: Path | None = None) -> str | None:
        return fleet.run_hook(name, self.payload(sid, cwd), None, now)

    def entry(self, sid: str = SID_A) -> dict[str, Any]:
        return json.loads(fleet.session_path(sid).read_text(encoding="utf-8"))

    def send(self, kind: str, text: str = "hello", targets: list[str] | None = None, expires: str | None = "24h",
             now: datetime = NOW) -> dict[str, Any]:
        record: dict[str, Any] = fleet.make_broadcast(kind, text, targets or ["all"], expires, now)
        fleet.append_line(fleet.broadcasts_path(), record)
        return record

    def seed(self, sid: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {"session_id": sid, "cwd": str(self.repo), "repo": "demo", "branch": "main",
                                 "harness": False, "state": "idle", "turns": 0, "label": None,
                                 "started_at": fleet.to_iso(NOW), "last_seen": fleet.to_iso(NOW), **fields}
        fleet.write_json(fleet.session_path(sid), entry)
        return entry


class RegistryLifecycleTests(FleetCase):
    def test_session_start_creates_entry(self) -> None:
        self.assertIsNone(self.event("SessionStart"))
        entry = self.entry()
        self.assertEqual((entry["state"], entry["turns"], entry["session_id"]), ("idle", 0, SID_A))
        self.assertEqual(entry["cwd"], str(self.repo))
        self.assertFalse(entry["harness"])
        self.assertEqual(entry["started_at"], fleet.to_iso(NOW))
        self.assertIsNone(entry["label"])

    def test_user_prompt_submit_counts_turns_and_works(self) -> None:
        self.event("SessionStart")
        self.event("UserPromptSubmit", now=NOW + timedelta(seconds=5))
        self.event("UserPromptSubmit", now=NOW + timedelta(seconds=9))
        entry = self.entry()
        self.assertEqual((entry["state"], entry["turns"]), ("working", 2))
        self.assertEqual(entry["last_prompt_at"], fleet.to_iso(NOW + timedelta(seconds=9)))

    def test_stop_idles_and_session_end_ends(self) -> None:
        self.event("UserPromptSubmit")
        self.event("Stop", now=NOW + timedelta(seconds=3))
        self.assertEqual(self.entry()["state"], "idle")
        self.event("SessionEnd", now=NOW + timedelta(seconds=4))
        self.assertEqual(self.entry()["state"], "ended")

    def test_harness_flag_follows_cwd(self) -> None:
        (self.repo / state_io.HARNESS).mkdir()
        self.event("SessionStart")
        self.assertTrue(self.entry()["harness"])

    def test_repo_falls_back_to_cwd_name_outside_git(self) -> None:
        self.event("SessionStart")
        entry = self.entry()
        self.assertEqual(entry["repo"], self.repo.name)
        self.assertIsNone(entry["branch"])

    def test_git_repo_name_and_branch(self) -> None:
        subprocess.run(["git", "init", "-q", "-b", "trunk", str(self.repo)], check=True)
        self.event("SessionStart")
        entry = self.entry()
        self.assertEqual(entry["repo"], self.repo.resolve().name)
        self.assertEqual(entry["branch"], "trunk")

    def test_label_and_started_at_survive_refresh(self) -> None:
        self.event("SessionStart")
        fleet.write_json(fleet.session_path(SID_A), {**self.entry(), "label": "tab-3"})
        self.event("UserPromptSubmit", now=NOW + timedelta(minutes=5))
        entry = self.entry()
        self.assertEqual((entry["label"], entry["started_at"]), ("tab-3", fleet.to_iso(NOW)))

    def test_pid_recorded_when_given(self) -> None:
        fleet.run_hook("SessionStart", self.payload(), 4242, NOW)
        self.assertEqual(self.entry()["pid"], 4242)

    def test_post_tool_use_heartbeat_is_throttled(self) -> None:
        self.event("UserPromptSubmit")
        self.event("PostToolUse", now=NOW + timedelta(seconds=30))
        self.assertEqual(self.entry()["last_seen"], fleet.to_iso(NOW))
        self.event("PostToolUse", now=NOW + timedelta(seconds=61))
        self.assertEqual(self.entry()["last_seen"], fleet.to_iso(NOW + timedelta(seconds=61)))

    def test_post_tool_use_after_idle_marks_working(self) -> None:
        self.event("Stop")
        self.event("PostToolUse", now=NOW + timedelta(seconds=5))
        self.assertEqual(self.entry()["state"], "working")

    def test_prune_runs_on_session_start_and_keeps_recent_ended(self) -> None:
        old = fleet.to_iso(NOW - timedelta(days=20))
        self.seed(SID_B, state="ended", last_seen=old)
        self.seed(SID_A2, state="ended", last_seen=fleet.to_iso(NOW - timedelta(days=1)))
        self.event("SessionStart")
        self.assertFalse(fleet.session_path(SID_B).exists())
        self.assertTrue(fleet.session_path(SID_A2).exists())

    def test_hook_never_fails_on_garbage(self) -> None:
        for garbage in ("", "not json", "[]", "null", '{"session_id": 5}', '{"session_id": "../../x"}', "\x00\xff"):
            with unittest.mock.patch("sys.stdin", io.StringIO(garbage)), redirect_stdout(io.StringIO()) as out:
                code = fleet.main(["hook", "--event", "UserPromptSubmit"])
            self.assertEqual((code, out.getvalue()), (0, ""), garbage)
        self.assertFalse((self.home / "fleet" / "sessions").exists())

    def test_hook_swallows_internal_errors(self) -> None:
        with unittest.mock.patch("fleet.run_hook", side_effect=RuntimeError("boom")), \
                unittest.mock.patch("sys.stdin", io.StringIO(json.dumps(self.payload()))):
            self.assertEqual(fleet.main(["hook", "--event", "Stop"]), 0)


class DeliveryTests(FleetCase):
    def test_note_delivered_once_on_prompt(self) -> None:
        record = self.send("note", "release at noon")
        output = self.event("UserPromptSubmit")
        assert output is not None
        document = json.loads(output)["hookSpecificOutput"]
        self.assertEqual(document["hookEventName"], "UserPromptSubmit")
        self.assertIn(f"[dts2 fleet broadcast {record['id']} · note · from operator]", document["additionalContext"])
        self.assertIn("release at noon", document["additionalContext"])
        self.assertTrue(document["additionalContext"].rstrip().endswith("[end broadcast]"))
        self.assertIsNone(self.event("UserPromptSubmit", now=NOW + timedelta(seconds=1)))
        self.assertIsNone(self.event("PostToolUse", now=NOW + timedelta(seconds=90)))
        self.assertEqual(fleet.load_receipt(SID_A), [record["id"]])

    def test_post_tool_use_delivers_to_busy_session(self) -> None:
        self.event("UserPromptSubmit")
        self.send("note", "look up")
        output = self.event("PostToolUse", now=NOW + timedelta(seconds=2))
        assert output is not None
        self.assertEqual(json.loads(output)["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_session_start_delivers_unexpired_to_later_session(self) -> None:
        self.send("note", "still valid")
        output = self.event("SessionStart", now=NOW + timedelta(hours=1))
        assert output is not None
        self.assertIn("still valid", output)

    def test_expired_broadcast_is_never_delivered(self) -> None:
        self.send("note", "old news", expires="1h")
        self.assertIsNone(self.event("SessionStart", now=NOW + timedelta(hours=2)))
        self.assertEqual(fleet.load_receipt(SID_A), [])

    def test_each_session_gets_its_own_copy(self) -> None:
        self.send("note", "to everyone")
        self.assertIsNotNone(self.event("UserPromptSubmit", SID_A))
        self.assertIsNotNone(self.event("UserPromptSubmit", SID_B))

    def test_notes_survive_a_stop_before_the_next_prompt(self) -> None:
        self.event("SessionStart")
        self.send("note", "do not lose me")
        self.assertIsNone(self.event("Stop", now=NOW + timedelta(seconds=1)))
        self.assertIsNotNone(self.event("UserPromptSubmit", now=NOW + timedelta(seconds=2)))

    def test_later_broadcast_is_seen_after_an_earlier_one_was_handled(self) -> None:
        self.send("note", "first")
        self.assertIsNotNone(self.event("UserPromptSubmit"))
        second = self.send("note", "second", now=NOW + timedelta(seconds=1))
        output = self.event("PostToolUse", now=NOW + timedelta(seconds=120))
        assert output is not None
        self.assertIn(second["id"], output)
        self.assertNotIn("first", output)

    def test_non_matching_broadcast_not_redelivered_or_marked(self) -> None:
        self.send("note", "only others", targets=["repo:elsewhere"])
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertEqual(fleet.load_receipt(SID_A), [])

    def test_fast_path_skips_when_nothing_changed(self) -> None:
        self.send("note", "x")
        self.event("UserPromptSubmit")
        with unittest.mock.patch("fleet.load_broadcasts", side_effect=AssertionError("should not read")):
            self.assertIsNone(self.event("PostToolUse", now=NOW + timedelta(seconds=120)))

    def test_second_deliver_is_a_fast_path_without_reading(self) -> None:
        self.send("note", "x")
        self.assertIsNotNone(self.event("UserPromptSubmit"))
        with unittest.mock.patch("fleet.load_broadcasts") as reader:
            self.assertIsNone(self.event("UserPromptSubmit", now=NOW + timedelta(seconds=5)))
        reader.assert_not_called()
        self.assertEqual(fleet.read_json(fleet.seen_path(SID_A)), fleet.broadcasts_version())

    def test_broadcast_appended_during_the_read_is_not_skipped(self) -> None:
        self.send("note", "first")
        late: dict[str, Any] = {}
        real = fleet.load_broadcasts

        def racing() -> list[dict[str, Any]]:
            rows = real()
            if not late:  # another session appends after our snapshot, before our receipt is written
                late.update(self.send("handoff", "late arrival", now=NOW + timedelta(seconds=1)))
            return rows

        with unittest.mock.patch("fleet.load_broadcasts", racing):
            first = self.event("UserPromptSubmit", now=NOW + timedelta(seconds=2))
        assert first is not None
        self.assertNotIn(late["id"], first)
        future = fleet.broadcasts_path().stat().st_mtime_ns + 10_000_000_000
        os.utime(fleet.receipt_path(SID_A), ns=(future, future))  # receipt newer than the file, old mtime check would skip
        second = self.event("PostToolUse", now=NOW + timedelta(seconds=3))
        assert second is not None
        self.assertIn(late["id"], second)

    def test_stop_does_not_write_the_seen_marker(self) -> None:
        self.event("SessionStart")
        self.send("note", "pending at stop")
        self.assertIsNone(self.event("Stop", now=NOW + timedelta(seconds=1)))
        self.assertIsNone(fleet.read_json(fleet.seen_path(SID_A)))
        output = self.event("UserPromptSubmit", now=NOW + timedelta(seconds=2))
        assert output is not None
        self.assertIn("pending at stop", output)

    def test_no_broadcast_file_is_quiet(self) -> None:
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertFalse(fleet.receipt_path(SID_A).exists())

    def test_delivered_handoff_is_logged_as_steer_in_intake_ledger(self) -> None:
        (self.repo / state_io.HARNESS).mkdir()
        self.event("SessionStart")
        record = self.send("handoff", "update coming")
        self.event("UserPromptSubmit", now=NOW + timedelta(seconds=1))
        items = intake.load_items(self.repo)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "steer")
        self.assertIn(record["id"], items[0]["text"])

    def test_note_is_not_logged_to_intake(self) -> None:
        (self.repo / state_io.HARNESS).mkdir()
        self.send("note", "fyi")
        self.event("UserPromptSubmit")
        self.assertEqual(intake.load_items(self.repo), [])


class TargetTests(FleetCase):
    def test_all_harness_repo_id_label(self) -> None:
        entry = {"session_id": SID_A, "repo": "demo", "label": "tab-1", "harness": True}
        plain = {"session_id": SID_B, "repo": "other", "label": None, "harness": False}
        cases = [("all", True, True), ("harness", True, False), ("repo:demo", True, False), ("id:aaaa", True, False),
                 ("id:bbbb2", False, True), ("label:tab-1", True, False), ("label:nope", False, False),
                 ("repo:", False, False), ("nonsense", False, False)]
        for target, want_a, want_b in cases:
            self.assertEqual(fleet.target_matches(target, entry), want_a, target)
            self.assertEqual(fleet.target_matches(target, plain), want_b, target)

    def test_any_target_in_list_delivers(self) -> None:
        record = {"id": "x", "kind": "note", "targets": ["repo:nope", "label:tab-9"]}
        self.assertTrue(fleet.broadcast_matches(record, {"session_id": SID_A, "label": "tab-9"}))
        self.assertFalse(fleet.broadcast_matches(record, {"session_id": SID_A, "label": "tab-1"}))

    def test_harness_target_end_to_end(self) -> None:
        plain_repo = make_tmp_home()
        (self.repo / state_io.HARNESS).mkdir()
        self.send("note", "harness only", targets=["harness"])
        self.assertIsNotNone(self.event("UserPromptSubmit", SID_A, cwd=self.repo))
        self.assertIsNone(self.event("UserPromptSubmit", SID_B, cwd=plain_repo))

    def test_bad_target_rejected_on_send(self) -> None:
        code, _, err = cli("broadcast", "--kind", "note", "--text", "x", "--to", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("bad target", err)


class StopBlockTests(FleetCase):
    def test_handoff_blocks_stop_once(self) -> None:
        self.event("SessionStart")
        record = self.send("handoff", "plugin update coming")
        output = self.event("Stop", now=NOW + timedelta(seconds=1))
        assert output is not None
        document = json.loads(output)
        self.assertEqual(document["decision"], "block")
        self.assertIn(record["id"], document["reason"])
        self.assertIn("/dt:check-in", document["reason"])
        self.assertIsNone(self.event("Stop", now=NOW + timedelta(seconds=2)))
        self.assertIsNone(self.event("UserPromptSubmit", now=NOW + timedelta(seconds=3)))

    def test_pause_blocks_stop_with_pause_instruction(self) -> None:
        self.send("pause", "hold on")
        output = self.event("Stop")
        assert output is not None
        self.assertIn("then stop and wait", json.loads(output)["reason"])

    def test_note_and_knowledge_never_block_stop(self) -> None:
        self.send("note", "fyi")
        self.send("knowledge", "a finding")
        self.send("checkin", "report in")
        self.assertIsNone(self.event("Stop"))

    def test_handoff_seen_at_prompt_does_not_block_later_stop(self) -> None:
        self.send("handoff", "now")
        self.assertIsNotNone(self.event("UserPromptSubmit"))
        self.assertIsNone(self.event("Stop", now=NOW + timedelta(seconds=1)))

    def test_session_end_delivers_nothing(self) -> None:
        self.send("handoff", "now")
        self.assertIsNone(self.event("SessionEnd"))


class ListTests(FleetCase):
    def test_stale_after_thirty_minutes_and_ended_hidden(self) -> None:
        self.seed(SID_A, last_seen=fleet.to_iso(NOW - timedelta(minutes=45)))
        self.seed(SID_B, state="ended")
        rows = fleet.list_rows(False, NOW)
        self.assertEqual([(r["session_id"], r["effective_state"]) for r in rows], [(SID_A, "stale")])
        self.assertEqual({r["effective_state"] for r in fleet.list_rows(True, NOW)}, {"stale", "ended"})

    def test_recent_session_keeps_stored_state(self) -> None:
        self.seed(SID_A, state="working", last_seen=fleet.to_iso(NOW - timedelta(minutes=5)))
        self.assertEqual(fleet.list_rows(False, NOW)[0]["effective_state"], "working")

    @unittest.skipUnless(os.name == "posix", "pid check is posix only")
    def test_dead_pid_is_dead_and_live_pid_is_not(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.seed(SID_A, pid=child.pid)
        self.seed(SID_B, pid=os.getpid())
        states = {r["session_id"]: r["effective_state"] for r in fleet.list_rows(False, NOW)}
        self.assertEqual(states[SID_A], "dead")
        self.assertEqual(states[SID_B], "idle")

    def test_cli_table_and_json(self) -> None:
        self.seed(SID_A, label="tab-1", turns=3)
        code, out, _ = cli("list")
        self.assertEqual(code, 0)
        self.assertIn(SID_A[:8], out)
        self.assertIn("tab-1", out)
        self.assertIn("repo", out.splitlines()[0])
        _, as_json, _ = cli("list", "--json")
        self.assertEqual(json.loads(as_json)[0]["session_id"], SID_A)

    def test_empty_list_message(self) -> None:
        code, out, _ = cli("list")
        self.assertEqual(code, 0)
        self.assertIn("no live sessions", out)

    def test_age_text(self) -> None:
        self.assertEqual(fleet.age_text(NOW - timedelta(seconds=30), NOW), "30s")
        self.assertEqual(fleet.age_text(NOW - timedelta(minutes=10), NOW), "10m")
        self.assertEqual(fleet.age_text(NOW - timedelta(hours=5), NOW), "5h")
        self.assertEqual(fleet.age_text(NOW - timedelta(days=3), NOW), "3d")


class RefTests(FleetCase):
    def test_exact_prefix_and_label(self) -> None:
        self.seed(SID_A, label="alpha")
        self.seed(SID_B)
        sessions = fleet.load_sessions()
        self.assertEqual(fleet.resolve_ref(SID_A, sessions)["session_id"], SID_A)
        self.assertEqual(fleet.resolve_ref("bbbb", sessions)["session_id"], SID_B)
        self.assertEqual(fleet.resolve_ref("alpha", sessions)["session_id"], SID_A)

    def test_ambiguous_prefix_lists_candidates(self) -> None:
        self.seed(SID_A, label="alpha")
        self.seed(SID_A2)
        with self.assertRaises(fleet.FleetError) as caught:
            fleet.resolve_ref("aaaa", fleet.load_sessions())
        message = str(caught.exception)
        self.assertIn("ambiguous", message)
        self.assertIn(SID_A[:8], message)
        self.assertIn(SID_A2[:8], message)
        self.assertIn("alpha", message)

    def test_unknown_ref_is_an_error_exit(self) -> None:
        code, _, err = cli("show", "zzzz")
        self.assertEqual(code, 2)
        self.assertIn("no session matches", err)

    def test_label_command_sets_and_is_resolvable(self) -> None:
        self.seed(SID_A)
        self.assertEqual(cli("label", SID_A[:6], "t3-main")[0], 0)
        self.assertEqual(self.entry()["label"], "t3-main")
        self.assertEqual(fleet.resolve_ref("t3-main", fleet.load_sessions())["session_id"], SID_A)


class ShowAndLogsTests(FleetCase):
    def test_show_gathers_cwd_ledgers_read_only(self) -> None:
        handoff = self.repo / state_io.HANDOFF_LATEST_REL
        handoff.parent.mkdir(parents=True)
        handoff.write_text("# Handoff\nnext: ship it\n", encoding="utf-8")
        run = self.repo / state_io.RUNS_REL / "20260101-000000"
        run.mkdir(parents=True)
        (run / "task-ledger.md").write_text("| PR | branch |\n| 12 | feat/x |\n", encoding="utf-8")
        (run / "lane-a").mkdir()
        (run / "lane-a" / state_io.STATUS_NAME).write_text(json.dumps({"state": "building"}), encoding="utf-8")
        intake.add_item(self.repo, "Add pagination support to the invoices endpoint with a default page size")
        self.seed(SID_A, harness=True)
        before = sorted(p.name for p in self.repo.rglob("*"))
        code, out, _ = cli("show", "aaaa1111")
        self.assertEqual(code, 0)
        for needle in ("next: ship it", "| 12 | feat/x |", "in-1", "lane-a", "building"):
            self.assertIn(needle, out)
        document = json.loads(cli("show", SID_A, "--json")[1])
        self.assertEqual(document["session"]["session_id"], SID_A)
        self.assertEqual(len(document["intake_open"]), 1)
        self.assertEqual(document["incidents"], [])
        self.assertEqual(before, sorted(p.name for p in self.repo.rglob("*")))

    def transcript(self) -> Path:
        rows: list[dict[str, Any]] = [
            {"type": "summary", "summary": "ignored"},
            {"type": "user", "message": {"role": "user", "content": "first question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la " + "x" * 200}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "big output"}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "second " + "y" * 400}]}},
        ]
        path = self.repo / "t.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json at all\n", encoding="utf-8")
        return path

    def test_logs_render_text_and_tool_calls(self) -> None:
        path = self.transcript()
        self.seed(SID_A, transcript_path=str(path))
        before = path.read_bytes()
        code, out, _ = cli("logs", "aaaa", "-n", "10")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "[user] first question")
        self.assertEqual(lines[1], "[assistant] Let me look.")
        self.assertTrue(lines[2].startswith("  tool: Bash("))
        self.assertLessEqual(len(lines[2]), len("  tool: Bash()") + fleet.LOG_ARGS_CHARS)
        self.assertNotIn("big output", out)
        self.assertLessEqual(len(lines[3]), len("[user] ") + fleet.LOG_TEXT_CHARS)
        self.assertTrue(lines[3].endswith("..."))
        self.assertEqual(path.read_bytes(), before)

    def test_logs_limits_to_last_n_messages(self) -> None:
        self.seed(SID_A, transcript_path=str(self.transcript()))
        out = cli("logs", SID_A, "-n", "1")[1]
        self.assertTrue(out.startswith("[user] second"))
        self.assertNotIn("first question", out)

    def test_logs_missing_transcript_is_an_error(self) -> None:
        self.seed(SID_A, transcript_path=str(self.repo / "nope.jsonl"))
        code, _, err = cli("logs", SID_A)
        self.assertEqual(code, 2)
        self.assertIn("no readable transcript", err)


class BroadcastCommandTests(FleetCase):
    def test_checkin_broadcast_without_text_gets_default_text(self) -> None:
        code, _, err = cli("broadcast", "--kind", "checkin", "--to", "all")
        self.assertEqual(code, 0, err)
        records = fleet.load_broadcasts()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "checkin")
        self.assertEqual(records[0]["text"], fleet.CHECKIN_DEFAULT_TEXT)

    def test_note_without_text_still_fails(self) -> None:
        code, _, err = cli("broadcast", "--kind", "note", "--to", "all")
        self.assertEqual(code, 2)
        self.assertIn("needs text", err)
        self.assertEqual(fleet.load_broadcasts(), [])

    def test_broadcast_prints_id_and_live_match_count(self) -> None:
        self.seed(SID_A, last_seen=fleet.to_iso(fleet.utc_now()))
        self.seed(SID_B, state="ended", last_seen=fleet.to_iso(fleet.utc_now()))
        code, out, _ = cli("broadcast", "--kind", "handoff", "--text", "update coming")
        self.assertEqual(code, 0)
        self.assertIn("matches 1 registered live session(s)", out)
        record = fleet.load_broadcasts()[0]
        self.assertTrue(record["id"].startswith("bc-"))
        self.assertEqual((record["kind"], record["targets"], record["from"]), ("handoff", ["all"], "operator"))
        self.assertTrue(out.startswith(record["id"]))
        self.assertIsNotNone(fleet.parse_iso(record["expires"]))

    def test_positional_text_and_multiple_targets_and_expiry(self) -> None:
        cli("broadcast", "--kind", "note", "--to", "harness", "--to", "repo:demo", "--expires", "2h", "be", "careful")
        record = fleet.load_broadcasts()[0]
        self.assertEqual(record["text"], "be careful")
        self.assertEqual(record["targets"], ["harness", "repo:demo"])
        delta = fleet.parse_iso(record["expires"]) - fleet.parse_iso(record["created"])  # type: ignore[operator]
        self.assertEqual(delta, timedelta(hours=2))

    def test_empty_text_and_bad_duration_rejected(self) -> None:
        self.assertEqual(cli("broadcast", "--kind", "note")[0], 2)
        code, _, err = cli("broadcast", "--kind", "note", "--text", "x", "--expires", "soon")
        self.assertEqual(code, 2)
        self.assertIn("bad duration", err)

    def test_from_knowledge_without_script_errors_clearly(self) -> None:
        with unittest.mock.patch("fleet.knowledge_script", return_value=None):
            code, _, err = cli("broadcast", "--kind", "knowledge", "--from-knowledge", "prefs/x")
        self.assertEqual(code, 2)
        self.assertIn("knowledge store script", err)

    def test_from_knowledge_uses_script_output(self) -> None:
        script = self.repo / "knowledge.py"
        script.write_text("import sys\nprint('finding for ' + sys.argv[2])\n", encoding="utf-8")
        with unittest.mock.patch("fleet.knowledge_script", return_value=script):
            code, _, _ = cli("broadcast", "--kind", "knowledge", "--from-knowledge", "prefs/x")
        self.assertEqual(code, 0)
        self.assertEqual(fleet.load_broadcasts()[0]["text"], "finding for prefs/x")

    def test_status_counts_and_per_session_list(self) -> None:
        now = fleet.utc_now()
        self.seed(SID_A, last_seen=fleet.to_iso(now))
        self.seed(SID_B, last_seen=fleet.to_iso(now))
        record = self.send("handoff", "go", now=now)
        fleet.run_hook("UserPromptSubmit", self.payload(SID_A), None, now)
        results = json.loads(cli("status", "--json")[1])
        self.assertEqual((results[0]["delivered"], results[0]["pending"]), ([SID_A], [SID_B]))
        _, out, _ = cli("status", record["id"][:12])
        self.assertIn("delivered 1  pending 1", out)
        self.assertIn(f"pending    {SID_B[:8]}", out)
        self.assertEqual(cli("status", "bc-nope")[0], 2)


class PruneTests(FleetCase):
    def test_prune_removes_old_ended_with_receipts_and_expired_broadcasts(self) -> None:
        now = fleet.utc_now()
        self.seed(SID_A, state="ended", last_seen=fleet.to_iso(now - timedelta(days=30)))
        self.seed(SID_B, state="ended", last_seen=fleet.to_iso(now - timedelta(days=2)))
        self.seed(SID_A2, state="idle", last_seen=fleet.to_iso(now - timedelta(days=40)))
        fleet.write_json(fleet.receipt_path(SID_A), ["bc-1"])
        fleet.write_json(fleet.seen_path(SID_A), {"mtime_ns": 1, "size": 1, "ino": 1})
        fleet.append_line(fleet.checkins_path(SID_A), {"ts": fleet.to_iso(now), "status": "x"})
        stale = fleet.make_broadcast("note", "old", ["all"], "1h", now - timedelta(days=3))
        fresh = fleet.make_broadcast("note", "new", ["all"], "24h", now)
        for record in (stale, fresh):
            fleet.append_line(fleet.broadcasts_path(), record)
        code, out, _ = cli("prune")
        self.assertEqual(code, 0)
        self.assertIn("pruned 1 ended session", out)
        self.assertFalse(fleet.session_path(SID_A).exists())
        self.assertFalse(fleet.receipt_path(SID_A).exists())
        self.assertFalse(fleet.seen_path(SID_A).exists())
        self.assertFalse(fleet.checkins_path(SID_A).exists())
        self.assertTrue(fleet.session_path(SID_B).exists())
        self.assertTrue(fleet.session_path(SID_A2).exists())
        self.assertEqual([b["id"] for b in fleet.load_broadcasts()], [fresh["id"]])

    def test_prune_days_option(self) -> None:
        now = fleet.utc_now()
        self.seed(SID_B, state="ended", last_seen=fleet.to_iso(now - timedelta(days=2)))
        cli("prune", "--days", "1")
        self.assertFalse(fleet.session_path(SID_B).exists())


class CheckinTests(FleetCase):
    def test_checkin_broadcast_text_carries_session_id_and_never_blocks(self) -> None:
        record = self.send("checkin", "Report in please.")
        output = self.event("UserPromptSubmit")
        assert output is not None
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"checkin --session {SID_A}", context)
        self.assertIn(f"--broadcast {record['id']}", context)
        self.assertIn("fleet.py", context)
        self.assertIn("--blocker", context)
        self.assertIsNone(self.event("Stop", SID_B))

    def test_checkin_record_is_appended(self) -> None:
        code, out, _ = cli("checkin", "--session", SID_A, "--status", "tests green", "--blocker", "need token",
                           "--blocker", "CI down", "--next", "open PR", "--question", "squash?", "--broadcast", "bc-1")
        self.assertEqual(code, 0)
        self.assertIn("recorded", out)
        cli("checkin", "--session", SID_A, "--status", "second")
        rows = fleet.read_lines(fleet.checkins_path(SID_A))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["blockers"], ["need token", "CI down"])
        self.assertEqual((rows[0]["next"], rows[0]["questions"], rows[0]["broadcast_id"]), ("open PR", ["squash?"], "bc-1"))
        self.assertEqual((rows[1]["blockers"], rows[1]["questions"], rows[1]["next"]), ([], [], None))
        self.assertEqual(rows[0]["session_id"], SID_A)

    def test_checkin_session_from_env_and_missing(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": SID_B}):
            self.assertEqual(cli("checkin", "--status", "ok")[0], 0)
        self.assertEqual(len(fleet.read_lines(fleet.checkins_path(SID_B))), 1)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SESSION_ID"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            code, _, err = cli("checkin", "--status", "ok")
        self.assertEqual(code, 2)
        self.assertIn("--session", err)

    def test_report_counts_and_needs_you(self) -> None:
        now = fleet.utc_now()
        stamp = fleet.to_iso(now)
        self.seed(SID_A, label="tab-1", last_seen=stamp)
        self.seed(SID_B, last_seen=stamp)
        self.seed(SID_A2, last_seen=fleet.to_iso(now - timedelta(hours=2)))
        self.seed("cccc3333-0000-4000-8000-000000000004", state="ended", last_seen=stamp)
        cli("checkin", "--session", SID_A, "--status", "halfway", "--blocker", "need review", "--question", "which db?",
            "--next", "finish")
        cli("checkin", "--session", SID_B, "--status", "done")
        report = json.loads(cli("checkins", "--json")[1])
        self.assertEqual(report["summary"], {"sessions": 3, "checked_in": 2, "with_blockers": 1,
                                              "with_open_questions": 1, "stale": 1})
        self.assertEqual([(n["session"], n["type"], n["text"]) for n in report["needs_you"]],
                         [("tab-1", "blocker", "need review"), ("tab-1", "question", "which db?")])
        by_id = {s["session_id"]: s for s in report["sessions"]}
        self.assertEqual(by_id[SID_A]["checkin"]["status"], "halfway")
        self.assertIsNone(by_id[SID_A2]["checkin"])
        self.assertEqual(by_id[SID_A2]["state"], "stale")
        self.assertEqual(len(json.loads(cli("checkins", "--json", "--all")[1])["sessions"]), 4)

    def test_report_text_has_summary_blocks_and_needs_you(self) -> None:
        now = fleet.utc_now()
        self.seed(SID_A, label="tab-1", last_seen=fleet.to_iso(now))
        self.seed(SID_B, last_seen=fleet.to_iso(now))
        cli("checkin", "--session", SID_A, "--status", "halfway", "--blocker", "need review")
        out = cli("checkins")[1]
        self.assertTrue(out.splitlines()[0].startswith("2 sessions, 1 checked in, 1 with blockers"))
        self.assertIn("check-in (", out)
        self.assertIn("halfway", out)
        self.assertIn("no check-in yet", out)
        self.assertIn("derived: 0 open intake; handoff no; 0 pending broadcast(s)", out)
        self.assertTrue(out.rstrip().splitlines()[-1].strip().startswith("tab-1  blocker: need review"))

    def test_report_since_window_and_broadcast_filter(self) -> None:
        now = fleet.utc_now()
        self.seed(SID_A, last_seen=fleet.to_iso(now))
        fleet.append_line(fleet.checkins_path(SID_A), {"ts": fleet.to_iso(now - timedelta(hours=30)), "session_id": SID_A,
                                                       "broadcast_id": "bc-1", "status": "old", "blockers": [],
                                                       "next": None, "questions": []})
        self.assertIsNone(json.loads(cli("checkins", "--json")[1])["sessions"][0]["checkin"])
        self.assertEqual(json.loads(cli("checkins", "--json", "--since", "48h")[1])["sessions"][0]["checkin"]["status"], "old")
        self.assertIsNone(json.loads(cli("checkins", "--json", "--since", "48h", "--broadcast", "bc-2")[1])["sessions"][0]["checkin"])

    def test_report_derived_items_from_cwd(self) -> None:
        now = fleet.utc_now()
        handoff = self.repo / state_io.HANDOFF_LATEST_REL
        handoff.parent.mkdir(parents=True)
        handoff.write_text("# h\n", encoding="utf-8")
        intake.add_item(self.repo, "Add pagination support to the invoices endpoint with a default page size")
        self.seed(SID_A, harness=True, last_seen=fleet.to_iso(now))
        self.send("note", "unseen", now=now)
        derived = json.loads(cli("checkins", "--json")[1])["sessions"][0]["derived"]
        self.assertEqual((derived["open_intake"], derived["handoff_present"], derived["pending_broadcasts"]), (1, True, 1))
        self.assertEqual(derived["incidents"], 0)

    def test_report_is_read_only(self) -> None:
        self.seed(SID_A, last_seen=fleet.to_iso(fleet.utc_now()))
        before = sorted(str(p) for p in (self.home / "fleet").rglob("*"))
        cli("checkins")
        self.assertEqual(before, sorted(str(p) for p in (self.home / "fleet").rglob("*")))


class ShellHookTests(FleetCase):
    def run_hook(self, event: str, payload: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), **(extra_env or {})}
        return subprocess.run(["bash", str(HOOK), event], input=payload, capture_output=True, text=True,
                              cwd=str(self.repo), env=env, check=False)

    def test_registered_for_all_five_events(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event in fleet.EVENTS:
            commands = [h["command"] for g in hooks[event] for h in g["hooks"]]
            self.assertIn(f'bash "${{CLAUDE_PLUGIN_ROOT}}/hooks/fleet-session.sh" {event}', commands, event)
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_end_to_end_registers_with_claude_pid_and_delivers(self) -> None:
        self.send("note", "from the shell")
        done = self.run_hook("UserPromptSubmit", json.dumps(self.payload()))
        self.assertEqual(done.returncode, 0)
        self.assertIn("from the shell", json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"])
        entry = self.entry()
        self.assertEqual((entry["state"], entry["turns"]), ("working", 1))
        self.assertIsInstance(entry["pid"], int)
        self.assertEqual(entry["pid"], os.getpid())  # the hook shell's $PPID is its caller (Claude), not the `timeout` wrapper

    def test_garbage_and_empty_input_exit_zero_and_silent(self) -> None:
        for garbage in ("", "garbage", "{"):
            done = self.run_hook("Stop", garbage)
            self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_settings_switch_it_off(self) -> None:
        settings = self.repo / ".claude"
        settings.mkdir()
        (settings / "dts2-harness.local.md").write_text("---\nfleet: false\n---\n", encoding="utf-8")
        done = self.run_hook("SessionStart", json.dumps(self.payload()))
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertFalse(fleet.session_path(SID_A).exists())


class HomeResolutionTests(unittest.TestCase):
    def test_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with unittest.mock.patch.dict(os.environ, {"DTS2_FLEET_HOME": f"{folder}/f", "DTS2_HOME": f"{folder}/h"}):
                self.assertEqual(fleet.fleet_home(), Path(folder) / "f")
            env = {k: v for k, v in os.environ.items() if k != "DTS2_FLEET_HOME"}
            with unittest.mock.patch.dict(os.environ, {**env, "DTS2_HOME": f"{folder}/h"}, clear=True):
                self.assertEqual(fleet.fleet_home(), Path(folder) / "h" / "fleet")
            env.pop("DTS2_HOME", None)
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(fleet.fleet_home(), Path.home() / ".dts2" / "fleet")


if __name__ == "__main__":
    unittest.main()
