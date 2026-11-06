"""Incident detectors, lesson injection selection, counters (demote/expire), tier promotion and the library functions."""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import incidents  # noqa: E402
import incidents_detect as detect  # noqa: E402
import incidents_lessons as learn  # noqa: E402
import state_io  # noqa: E402
import subagent_report  # noqa: E402

DAY: Final[int] = 86400
NOW: Final[int] = 1_800_000_000
LONG_BRIEF: Final[str] = ("Goal: fix the retry bug in src/api/client.py. Scope: only touch src/api/client.py and tests/test_client.py. "
                          "Done when the tests pass; report the files changed. " * 2)
GOOD_REPORT: Final[str] = "## Files changed\n- a\n\n## Commands run\n- t\n\n## Concerns\nnone\n"


def make_repo() -> Path:
    repo: Path = make_tmp_home()
    (repo / ".harness").mkdir()
    return repo


def write_lessons(repo: Path, *lines: str) -> None:
    (repo / ".harness" / "lessons.md").write_text("# Lessons\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


class HomeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home: Path = make_tmp_home()
        patcher = mock.patch.dict(os.environ, {"DTS2_HOME": str(self.home), "DTS2_KNOWLEDGE_SCRIPT": str(self.home / "none.py"),
                                               "DTS2_FLEET_SCRIPT": str(self.home / "none-fleet.py")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo: Path = make_repo()


class DetectorTests(unittest.TestCase):
    def test_agent_class_strips_prefix(self) -> None:
        self.assertEqual(detect.agent_class("dts2:builder"), "builder")
        self.assertEqual(detect.agent_class("Explore"), "Explore")
        self.assertEqual(detect.agent_class(""), detect.UNKNOWN_CLASS)

    def test_good_brief_has_no_problems(self) -> None:
        self.assertEqual(detect.brief_problems(LONG_BRIEF, 200), [])

    def test_short_brief_is_flagged(self) -> None:
        problems = detect.brief_problems("fix it", 200)
        self.assertTrue(any("under 200" in p for p in problems))

    def test_brief_missing_scope_and_done(self) -> None:
        body = "Please implement the retry logic for the client. " * 6
        problems = detect.brief_problems(body, 50)
        self.assertIn("no file scope", problems)
        self.assertIn("no done-definition", problems)
        self.assertNotIn("no goal", problems)

    def test_brief_without_goal(self) -> None:
        self.assertIn("no goal", detect.brief_problems("zzz qqq www " * 30 + "src/a.py done when ok", 50))

    def test_brief_paths(self) -> None:
        self.assertEqual(detect.brief_paths("edit src/a/b.py and README.md, see https://x.test/a/b"), ["src/a/b.py", "README.md"])

    def test_report_findings(self) -> None:
        empty = detect.report_findings("ok", "builder", subagent_report.REQUIRED, subagent_report.missing_fields)
        self.assertTrue(empty["no_report"])
        partial = detect.report_findings("PARTIAL: hit turn cap at step 3, more text", "builder", subagent_report.REQUIRED,
                                         subagent_report.missing_fields)
        self.assertTrue(partial["partial"] and not partial["report_ok"] and partial["missing_sections"] == [])
        missing = detect.report_findings("## Files changed\n- a\n" + "x" * 30, "builder", subagent_report.REQUIRED,
                                         subagent_report.missing_fields)
        self.assertEqual(missing["missing_sections"], ["commands run", "concerns"])
        good = detect.report_findings(GOOD_REPORT, "builder", subagent_report.REQUIRED, subagent_report.missing_fields)
        self.assertTrue(good["report_ok"])
        other = detect.report_findings("a perfectly fine free text report", "scout", subagent_report.REQUIRED,
                                       subagent_report.missing_fields)
        self.assertTrue(other["report_ok"])

    def test_parse_lessons_line(self) -> None:
        text = "## Files changed\n- a\n\nLessons: L-012 helpful, L-019 not-helpful, H-020 unused\n"
        self.assertEqual(detect.parse_lessons_line(text), {"L-012": "helpful", "L-019": "not-helpful", "H-020": "unused"})
        self.assertEqual(detect.parse_lessons_line("no such line"), {})

    def test_signature_and_glob(self) -> None:
        self.assertEqual(detect.top_glob(["src/a/b.py"]), "src/**")
        self.assertEqual(detect.top_glob(["README.md"]), "*")
        self.assertEqual(detect.top_glob([]), "*")
        self.assertEqual(detect.signature("partial", "builder", ["src/x.py"]), "partial|builder|src/**")

    def test_lesson_category_and_agents(self) -> None:
        self.assertEqual(detect.lesson_category("- [L-1] x {cat: partial}"), "partial")
        self.assertEqual(detect.lesson_category("- [L-1] avoid rework-other-agent edits"), "rework-other-agent")
        self.assertIsNone(detect.lesson_category("- [L-1] plain"))
        self.assertEqual(detect.lesson_agents("- [L-1] x {agents: builder, fixer}"), ["builder", "fixer"])

    def test_rework_owner(self) -> None:
        self.assertEqual(detect.rework_owner({"a.py": "x"}, "a.py", "y"), "x")
        self.assertIsNone(detect.rework_owner({"a.py": "x"}, "a.py", "x"))
        self.assertIsNone(detect.rework_owner({}, "a.py", "x"))


class CounterTests(unittest.TestCase):
    def entry(self, **kw: Any) -> dict[str, Any]:
        return {**learn.EMPTY_STATS, **kw}

    def test_verdicts_update_counters(self) -> None:
        e = self.entry()
        learn.apply_verdict(e, "helpful", NOW)
        learn.apply_verdict(e, "unused", NOW)
        self.assertEqual((e["helpful"], e["unused"], e["unused_streak"]), (1, 1, 1))
        learn.apply_verdict(e, "not-helpful", NOW)
        self.assertEqual((e["harmful"], e["unused_streak"]), (1, 0))

    def test_demote_when_harmful_exceeds_helpful_by_two(self) -> None:
        self.assertEqual(learn.lesson_status(self.entry(helpful=1, harmful=2), NOW), "active")
        self.assertEqual(learn.lesson_status(self.entry(helpful=1, harmful=3), NOW), "demoted")
        self.assertEqual(learn.lesson_status(self.entry(helpful=0, harmful=2), NOW), "demoted")

    def test_expire_after_ten_unused_in_a_row(self) -> None:
        self.assertEqual(learn.lesson_status(self.entry(unused_streak=9), NOW), "active")
        self.assertEqual(learn.lesson_status(self.entry(unused_streak=10), NOW), "expired")

    def test_expire_after_thirty_idle_days(self) -> None:
        self.assertEqual(learn.lesson_status(self.entry(last_used=NOW - 29 * DAY), NOW), "active")
        self.assertEqual(learn.lesson_status(self.entry(last_used=NOW - 31 * DAY), NOW), "expired")
        self.assertEqual(learn.lesson_status(self.entry(first_injected=NOW - 31 * DAY), NOW), "expired")
        self.assertEqual(learn.lesson_status(None, NOW), "active")


class SelectionTests(HomeCase):
    def test_matches_paths_and_class(self) -> None:
        write_lessons(self.repo, "- [L-001] Validate input. {paths: src/api/**} (seen 1x, last 2026-10-01)",
                      "- [L-002] Only for reviewers. {agents: reviewer}", "- [L-003] Docs only. {paths: docs/**}",
                      "- [L-004] Always applies.")
        got = learn.select(self.repo, "builder", ["src/api/client.py"], 5, NOW)
        self.assertEqual([g["id"] for g in got], ["L-001", "L-004"])
        self.assertEqual(got[0]["text"], "Validate input.")
        self.assertEqual(got[0]["tier"], 2)

    def test_limit_and_newest_wins(self) -> None:
        write_lessons(self.repo, *[f"- [L-00{i}] Rule {i}." for i in range(1, 6)])
        got = learn.select(self.repo, "builder", [], 3, NOW)
        self.assertEqual(len(got), 3)
        self.assertEqual(learn.select(self.repo, "builder", [], 0, NOW), [])

    def test_demoted_and_expired_are_never_injected(self) -> None:
        write_lessons(self.repo, "- [L-001] Bad.", "- [L-002] Old.", "- [L-003] Fine.")
        learn.sidecar_for(2, self.repo).update(lambda t: t.update({"L-001": {"helpful": 0, "harmful": 2},
                                                                   "L-002": {"unused_streak": 10}}))
        self.assertEqual([g["id"] for g in learn.select(self.repo, "builder", [], 5, NOW)], ["L-003"])

    def test_promoted_enforced_lessons_are_skipped(self) -> None:
        write_lessons(self.repo, "- [L-001] Held by a check. (seen 2x, last 2026-10-17, promoted_at: 2026-10-20)")
        self.assertEqual(learn.select(self.repo, "builder", [], 5, NOW), [])

    def test_tier_three_and_closest_tier_wins(self) -> None:
        write_lessons(self.repo, "- [H-001] Project version.")
        (self.home / "lessons.md").write_text("# Lessons\n- [H-001] Harness version.\n- [H-002] Harness only.\n", encoding="utf-8")
        got = learn.select(self.repo, "builder", [], 5, NOW)
        self.assertEqual([(g["id"], g["tier"], g["text"]) for g in got],
                         [("H-001", 2, "Project version."), ("H-002", 3, "Harness only.")])

    def test_tier_four_only_with_script_and_store(self) -> None:
        fake = self.home / "knowledge.py"
        fake.write_text("import json,sys\nprint(json.dumps([{'key':'abc','text':'From the store.'}]))\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake)}):
            self.assertEqual(learn.select(self.repo, "builder", [], 3, NOW), [])  # no store configured
            with mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE": "cf"}):
                got = learn.select(self.repo, "builder", [], 3, NOW)
        self.assertEqual([(g["id"], g["tier"]) for g in got], [("K-abc", 4)])

    def test_tier_four_failure_is_skipped(self) -> None:
        fake = self.home / "knowledge.py"
        fake.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        write_lessons(self.repo, "- [L-001] Local.")
        with mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf"}):
            self.assertEqual([g["id"] for g in learn.select(self.repo, "builder", [], 3, NOW)], ["L-001"])

    def test_block_lists_lessons_and_feedback_line(self) -> None:
        block = learn.injection_block([{"id": "L-001", "text": "Rule one."}, {"id": "L-002", "text": "Rule two."}])
        self.assertIn("- [L-001] Rule one.", block)
        self.assertIn("Lessons: L-001 helpful|not-helpful|unused, L-002 helpful|not-helpful|unused", block)
        self.assertEqual(learn.injection_block([]), "")


class PromoteTests(HomeCase):
    def test_promote_to_harness_writes_lesson_and_ledger_once(self) -> None:
        write_lessons(self.repo, "- [L-001] Validate input. {paths: src/**} (seen 2x, last 2026-10-17, source: run a)")
        first = learn.promote_harness(self.repo, "L-001", None, date(2026, 11, 6))
        self.assertTrue(first["ok"])
        self.assertEqual(first["id"], "H-001")
        text = (self.home / "lessons.md").read_text(encoding="utf-8")
        self.assertIn("- [H-001] Validate input. {paths: src/**} (source: promoted from", text)
        ledger = (self.home / "ledgers" / "harness.jsonl").read_text(encoding="utf-8")
        self.assertIn('"kind": "promote"', ledger)
        again = learn.promote_harness(self.repo, "L-001", None, date(2026, 11, 6))
        self.assertTrue(again["duplicate"])
        self.assertEqual((self.home / "lessons.md").read_text(encoding="utf-8").count("[H-001]"), 1)

    def test_promote_signature_and_unknown(self) -> None:
        got = learn.promote_harness(self.repo, "partial|builder|src/**", None, date(2026, 11, 6))
        self.assertTrue(got["ok"])
        self.assertIn("{cat: partial}", (self.home / "lessons.md").read_text(encoding="utf-8"))
        self.assertFalse(learn.promote_harness(self.repo, "L-999", None, date(2026, 11, 6))["ok"])

    def test_promote_to_knowledge_skipped_without_store(self) -> None:
        write_lessons(self.repo, "- [L-001] Rule.")
        got = learn.promote_knowledge(self.repo, "L-001", None)
        self.assertTrue(got["skipped"])
        self.assertIn("tier 4 skipped", got["detail"])

    def test_promote_to_knowledge_calls_script(self) -> None:
        write_lessons(self.repo, "- [L-001] Rule one.")
        log = self.home / "calls.txt"
        fake = self.home / "knowledge.py"
        fake.write_text(f"import sys\nopen({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf"}):
            got = learn.promote_knowledge(self.repo, "L-001", None)
        self.assertTrue(got["ok"])
        self.assertEqual(log.read_text(encoding="utf-8").strip(), "set incident-l-001 Rule one. --kind learning --tag incident")

    def test_promote_broadcasts_to_fleet_when_present(self) -> None:
        write_lessons(self.repo, "- [L-001] Rule one.")
        log = self.home / "fleet.txt"
        fake = self.home / "fleet.py"
        fake.write_text(f"import sys\nopen({str(log)!r}, 'w').write(' '.join(sys.argv[1:]))\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_FLEET_SCRIPT": str(fake)}):
            got = learn.promote_harness(self.repo, "L-001", None, date(2026, 11, 6))
        self.assertTrue(got["fleet_broadcast"])
        self.assertEqual(log.read_text(encoding="utf-8"), "broadcast --kind knowledge --text [H-001] Rule one.")

    def test_fleet_failure_is_ignored(self) -> None:
        write_lessons(self.repo, "- [L-001] Rule one.")
        fake = self.home / "fleet.py"
        fake.write_text("raise SystemExit(9)\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_FLEET_SCRIPT": str(fake)}):
            got = learn.promote_harness(self.repo, "L-001", None, date(2026, 11, 6))
        self.assertTrue(got["ok"])
        self.assertFalse(got["fleet_broadcast"])


class LibraryTests(HomeCase):
    CFG: Final[dict[str, Any]] = {"incident_hung_minutes": 20, "incident_inject_max": 3, "incident_inject_mode": "context",
                                  "incident_brief_min_chars": 200, "incident_capture": True, "incidents_auto_review": False}

    def incident(self, category: str = "partial", session: str = "s1", agent: str = "a1", paths: list[str] | None = None,
                 now: int = NOW, key: str | None = None) -> dict[str, Any] | None:
        return incidents.record_incident(self.repo, category=category, session_id=session, agent_id=agent, klass="builder",
                                         what="x", detected_by="t", evidence={"paths": paths or ["src/a.py"]}, now=now, key=key)

    def test_record_incident_fields_and_dedupe(self) -> None:
        first = self.incident()
        assert first is not None
        for field in ("incident_id", "ts", "session_id", "run", "agent_id", "agent_class", "category", "mast", "severity",
                      "what_happened", "detected_by", "how_resolved", "root_cause", "evidence"):
            self.assertIn(field, first)
        self.assertEqual((first["mast"], first["severity"], first["how_resolved"]), ("1.5", "incident", "open"))
        self.assertIsNone(self.incident())
        self.assertIsNotNone(self.incident(agent="a2"))

    def test_resolve_applies_latest_resolution(self) -> None:
        first = self.incident()
        assert first is not None
        self.assertEqual(len(incidents.open_incidents(self.repo)), 1)
        args = incidents.build_parser().parse_args(["resolve", first["incident_id"], "--root-cause", "vague brief", "--how", "lesson L-3"])
        self.assertTrue(incidents.cmd_resolve(self.repo, args)["ok"])
        self.assertEqual(incidents.open_incidents(self.repo), [])
        self.assertEqual(incidents.incidents_merged(self.repo)[0]["root_cause"], "vague brief")
        bad = incidents.build_parser().parse_args(["resolve", "INC-nope", "--root-cause", "x", "--how", "y"])
        self.assertFalse(incidents.cmd_resolve(self.repo, bad)["ok"])

    def test_debrief_marks_isolated_then_trend(self) -> None:
        self.incident(session="s1", now=NOW - 2 * DAY)
        self.assertEqual([e["label"] for e in incidents.debrief(self.repo, "s1", NOW)], ["isolated"])
        self.incident(session="s2", now=NOW - DAY)
        self.incident(session="s3", now=NOW)
        labels = incidents.debrief(self.repo, "s3", NOW)
        self.assertEqual([e["label"] for e in labels], ["trend"])
        head = (self.repo / state_io.HEAD_LEDGER_REL).read_text(encoding="utf-8")
        self.assertIn('"label": "trend"', head)
        self.assertEqual({i["session_id"]: i["debrief"] for i in incidents.incidents_merged(self.repo)}["s3"], "trend")

    def test_old_incidents_do_not_make_a_trend(self) -> None:
        self.incident(session="s1", now=NOW - 40 * DAY)
        self.incident(session="s2", now=NOW - 30 * DAY)
        self.incident(session="s3", now=NOW)
        self.assertEqual(incidents.debrief(self.repo, "s3", NOW)[0]["label"], "isolated")

    def test_different_glob_is_a_different_signature(self) -> None:
        self.incident(session="s1", paths=["docs/a.md"])
        self.incident(session="s2", paths=["src/a.py"])
        self.incident(session="s3", paths=["src/a.py"])
        self.assertEqual(incidents.debrief(self.repo, "s3", NOW)[0]["label"], "isolated")

    def start(self, agent: str, ts: int, session: str = "s1") -> None:
        ev = state_io.make_event("agent-start", id=state_io.event_id("agent-start", agent), ts=ts, agent_id=agent,
                                 agent_class="builder", session_id=session, parent_agent_id=None)
        state_io.append_event_at(self.repo / state_io.AGENTS_REL, ev)

    def test_watchdog_flags_only_hung_agents_once(self) -> None:
        self.start("old", NOW - 25 * 60)
        self.start("fresh", NOW - 5 * 60)
        made = incidents.watchdog(self.repo, self.CFG, NOW)
        self.assertEqual([m["agent_id"] for m in made], ["old"])
        self.assertEqual(made[0]["category"], "hung-spawn")
        self.assertEqual(made[0]["severity"], "blocking")
        self.assertEqual(incidents.watchdog(self.repo, self.CFG, NOW), [])

    def test_watchdog_threshold_is_configurable(self) -> None:
        self.start("a", NOW - 6 * 60)
        self.assertEqual(len(incidents.watchdog(self.repo, {**self.CFG, "incident_hung_minutes": 5}, NOW)), 1)

    def test_hung_incident_auto_resolves_when_agent_stops(self) -> None:
        self.start("old", NOW - 25 * 60)
        incidents.watchdog(self.repo, self.CFG, NOW)
        self.assertEqual(len(incidents.open_incidents(self.repo)), 1)
        stop = state_io.make_event("agent-stop", id="stop-old", agent_id="old", session_id="s1")
        state_io.append_event_at(self.repo / state_io.AGENTS_REL, stop)
        self.assertEqual(incidents.open_incidents(self.repo), [])
        self.assertEqual(incidents.incidents_merged(self.repo)[0]["how_resolved"], "auto")

    def test_running_agents_report_age_and_class(self) -> None:
        self.start("a", NOW - 90)
        running = incidents.running_agents(self.repo, NOW)
        self.assertEqual((running[0]["agent_id"], running[0]["agent_class"], running[0]["age_s"]), ("a", "builder", 90))

    def test_son_park_reader_records_once_and_writes_tier_one_ledger(self) -> None:
        stamp = "20261106-100000"
        ledger = self.repo / state_io.run_rel(stamp, "model-ledger.jsonl")
        ledger.parent.mkdir(parents=True)
        rows = [{"t": 5, "lane": "L1", "event": "park", "reason": "stalled", "detail": "x"},
                {"t": 6, "lane": "L2", "event": "park", "reason": "budget", "detail": "x"},
                {"t": 7, "lane": "L3", "event": "stuck", "detail": "loop"}]
        ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        made = incidents.son_parks(self.repo)
        self.assertEqual(sorted(m["agent_id"] for m in made), ["L1", "L3"])
        self.assertEqual(incidents.son_parks(self.repo), [])
        tier_one = (self.repo / state_io.run_rel(stamp, "incidents.jsonl")).read_text(encoding="utf-8")
        self.assertEqual(tier_one.count('"son-park"'), 2)

    def test_throttle_once_per_ten_minutes(self) -> None:
        self.assertFalse(incidents.throttled(self.repo, "s1", NOW))
        self.assertTrue(incidents.throttled(self.repo, "s1", NOW + 599))
        self.assertFalse(incidents.throttled(self.repo, "s1", NOW + 601))
        self.assertFalse(incidents.throttled(self.repo, "other", NOW + 1))

    def test_rework_detected_for_second_agent_only(self) -> None:
        self.start("a1", NOW)
        self.start("b2", NOW)
        edit = {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(self.repo / "src" / "x.py")}}
        incidents.rework_check(self.repo, {**edit, "agent_id": "a1", "agent_type": "dts2:builder"}, NOW)
        incidents.rework_check(self.repo, {**edit, "agent_id": "a1", "agent_type": "dts2:builder"}, NOW)
        self.assertEqual(incidents.incidents_merged(self.repo), [])
        incidents.rework_check(self.repo, {**edit, "agent_id": "b2", "agent_type": "dts2:reviewer"}, NOW)
        found = incidents.incidents_merged(self.repo)
        self.assertEqual([(i["category"], i["agent_id"]) for i in found], [("rework-other-agent", "b2")])
        self.assertEqual(found[0]["evidence"]["paths"], ["src/x.py"])
        self.assertEqual(found[0]["evidence"]["other_agent_id"], "a1")
        self.assertEqual(len(incidents.drain_live(self.repo)), 1)
        self.assertEqual(incidents.drain_live(self.repo), [])

    def test_class_table_counts(self) -> None:
        self.start("a1", NOW)
        stop = state_io.make_event("agent-stop", id="s-a1", agent_id="a1", agent_class="builder", session_id="s1", duration_s=30,
                                   report_chars=3, partial=True)
        state_io.append_event_at(self.repo / state_io.AGENTS_REL, stop)
        self.incident(category="rework-other-agent", agent="a1")
        row = incidents.class_table(self.repo, "s1")[0]
        self.assertEqual((row["spawned"], row["finished"], row["partial"], row["no_report"], row["incidents"], row["rework"],
                          row["avg_duration_s"]), (1, 1, 1, 1, 1, 1, 30))

    def test_end_of_run_writes_brief_metrics_and_line(self) -> None:
        self.start("a1", NOW)
        self.incident()
        line = incidents.end_of_run(self.repo, "s1", self.CFG, NOW)
        assert line is not None
        self.assertIn("1 spawned", line)
        self.assertTrue((self.repo / ".harness" / "briefs" / "s1.md").is_file())
        metrics = (self.repo / state_io.METRICS_REL).read_text(encoding="utf-8")
        self.assertIn('"kind": "briefs"', metrics)
        self.assertIsNone(incidents.end_of_run(self.repo, "empty-session", self.CFG, NOW))

    def test_review_input_lists_open_trends_and_lesson_counters(self) -> None:
        for n in range(3):
            self.incident(session=f"s{n}", now=int(__import__("time").time()))
        learn.sidecar_for(2, self.repo).update(lambda t: t.update({"L-001": {"helpful": 0, "harmful": 2}}))
        data = incidents.cmd_review_input(self.repo)
        self.assertEqual(len(data["open_incidents"]), 3)
        self.assertEqual(list(data["trends"]), ["partial|builder|src/**"])
        self.assertEqual(data["demoted"], ["L-001"])

    def test_session_note(self) -> None:
        self.assertIsNone(incidents.session_note(self.repo, self.CFG, NOW))
        self.incident()
        self.start("old", NOW - 30 * 60)
        note = incidents.session_note(self.repo, self.CFG, NOW)
        assert note is not None
        self.assertIn("1 open (1 partial)", note)
        self.assertIn("1 agent(s) possibly hung", note)
        for n in range(3):
            self.incident(session=f"x{n}", agent=f"x{n}")
        nudged = incidents.session_note(self.repo, {**self.CFG, "incidents_auto_review": True}, NOW)
        assert nudged is not None
        self.assertIn("run /dts2:incidents review", nudged)

    def test_settings_registered_with_defaults(self) -> None:
        cfg = incidents.settings(self.repo)
        self.assertEqual((cfg["incident_capture"], cfg["incident_hung_minutes"], cfg["incident_brief_min_chars"],
                          cfg["incidents_auto_review"], cfg["incident_inject_max"], cfg["incident_inject_mode"]),
                         (True, 20, 200, False, 3, "context"))


if __name__ == "__main__":
    unittest.main()
