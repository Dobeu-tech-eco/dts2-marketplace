"""hooks/agent-telemetry.sh end to end (subprocess, JSON on stdin) plus the StopFailure / PermissionDenied wiring."""
from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"
SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "incidents.py"
SESSION: Final[str] = "sess-1"
BRIEF: Final[str] = ("Goal: fix the retry bug in src/api/client.py. Scope: only touch src/api/client.py and tests/test_client.py. "
                     "Done when the tests pass; report the files changed. " * 2)
HOOK_BUDGET_S: Final[float] = 0.2
HOOK_TIMING_RUNS: Final[int] = 3
GOOD_REPORT: Final[str] = "## Files changed\n- a\n\n## Commands run\n- t\n\n## Concerns\nnone\n"


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_tmp_home()
        (self.repo / ".harness").mkdir()
        self.home: Path = make_tmp_home()
        self.env: dict[str, str] = {**os.environ, "DTS2_HOME": str(self.home), "DTS2_AGENT_STATUS": str(self.home / "agent-status.json"),
                                    "DTS2_KNOWLEDGE_SCRIPT": str(self.home / "none.py"), "DTS2_FLEET_SCRIPT": str(self.home / "none.py")}

    def run_hook(self, event: str, payload: dict[str, Any] | str, repo: Path | None = None) -> subprocess.CompletedProcess[str]:
        body = payload if isinstance(payload, str) else json.dumps({"session_id": SESSION, "cwd": str(repo or self.repo), **payload})
        return subprocess.run(["bash", str(HOOKS / "agent-telemetry.sh"), event], input=body, capture_output=True, text=True,
                              cwd=str(repo or self.repo), env=self.env, check=False)

    def out(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        done = self.run_hook(event, payload)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def rows(self, rel: str) -> list[dict[str, Any]]:
        path = self.repo / rel
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def incidents(self) -> list[dict[str, Any]]:
        return [r for r in self.rows(".harness/agents.jsonl") if r["kind"] == "incident"]

    def lessons(self, *lines: str) -> None:
        (self.repo / ".harness" / "lessons.md").write_text("# Lessons\n\n" + "\n".join(lines) + "\n", encoding="utf-8")

    def spawn(self, agent_id: str, brief: str = BRIEF, agent_type: str = "dt:builder") -> dict[str, Any]:
        self.out("pre-agent", {"tool_name": "Agent", "tool_input": {"subagent_type": agent_type, "prompt": brief}})
        return self.out("subagent-start", {"agent_id": agent_id, "agent_type": agent_type})

    def stop(self, agent_id: str, report: str, agent_type: str = "dt:builder") -> dict[str, Any]:
        return self.out("subagent-stop", {"agent_id": agent_id, "agent_type": agent_type, "last_assistant_message": report})

    def stats(self) -> dict[str, Any]:
        return json.loads((self.repo / ".harness" / "lesson-stats.json").read_text(encoding="utf-8"))["lessons"]


class RegistrationTests(unittest.TestCase):
    def test_hooks_registered_without_reordering(self) -> None:
        hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertIn("dt:builder", hooks["SubagentStop"][0]["matcher"])
        for event in ("SubagentStart", "SubagentStop", "PreToolUse", "PostToolUse", "Stop", "SessionStart", "SessionEnd"):
            commands = [h["command"] for g in hooks[event] for h in g["hooks"]]
            self.assertTrue(any("agent-telemetry.sh" in c for c in commands), event)
        self.assertIn("stop-checks.sh", hooks["Stop"][0]["hooks"][0]["command"])
        self.assertIn("session-lessons.sh", hooks["SessionStart"][0]["hooks"][0]["command"])
        post = [g for g in hooks["PostToolUse"] if "agent-telemetry" in json.dumps(g)][0]
        for tool in ("Edit", "Write", "MultiEdit", "Agent", "SubagentHandback"):
            self.assertIn(tool, post["matcher"])
        self.assertTrue(os.access(HOOKS / "agent-telemetry.sh", os.X_OK))


class StartTests(HookCase):
    def test_start_records_event_and_injects_matching_lessons(self) -> None:
        self.lessons("- [L-001] Validate input. {paths: src/api/**}", "- [L-002] Docs only. {paths: docs/**}")
        result = self.spawn("agent-aaaa1111")
        hook = result["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "SubagentStart")
        self.assertIn("[L-001] Validate input.", hook["additionalContext"])
        self.assertNotIn("L-002", hook["additionalContext"])
        self.assertIn("Lessons: L-001 helpful|not-helpful|unused", hook["additionalContext"])
        start = [r for r in self.rows(".harness/agents.jsonl") if r["kind"] == "agent-start"][0]
        self.assertEqual((start["agent_id"], start["agent_name"], start["agent_class"], start["session_id"]),
                         ("agent-aaaa1111", "dt:builder", "builder", SESSION))
        self.assertEqual(start["brief_chars"], len(BRIEF.strip()))
        inj = self.rows(".harness/injections.jsonl")[0]
        for field in ("inj_id", "ts", "session_id", "run", "agent_id", "agent_class", "lesson_id", "tier", "reason"):
            self.assertIn(field, inj)
        self.assertEqual((inj["lesson_id"], inj["tier"]), ("L-001", 2))
        self.assertEqual(self.incidents(), [])

    def test_injection_is_capped_by_setting(self) -> None:
        self.lessons(*[f"- [L-00{i}] Rule {i}." for i in range(1, 6)])
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nincident_inject_max: 2\n---\n", encoding="utf-8")
        self.spawn("agent-aaaa1111")
        self.assertEqual(len(self.rows(".harness/injections.jsonl")), 2)

    def test_thin_brief_is_a_near_miss_and_queues_a_correction(self) -> None:
        self.spawn("agent-aaaa1111", "fix it")
        found = self.incidents()
        self.assertEqual([(i["category"], i["severity"]) for i in found], [("bad-brief", "near-miss")])
        note = self.out("post-tool-use", {"tool_name": "Agent", "tool_input": {}})
        self.assertIn("thin brief", note["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.out("post-tool-use", {"tool_name": "Agent", "tool_input": {}}), {})

    def test_no_lessons_means_no_output(self) -> None:
        self.assertEqual(self.spawn("agent-aaaa1111"), {})

    def test_prompt_mode_rewrites_prompt_and_logs_at_start(self) -> None:
        self.lessons("- [L-001] Validate input.")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nincident_inject_mode: prompt\n---\n", encoding="utf-8")
        pre = self.out("pre-agent", {"tool_name": "Agent", "tool_input": {"subagent_type": "dt:builder", "prompt": BRIEF}})
        updated = pre["hookSpecificOutput"]["updatedInput"]
        self.assertTrue(updated["prompt"].startswith(BRIEF))
        self.assertIn("[L-001] Validate input.", updated["prompt"])
        self.assertEqual(self.out("subagent-start", {"agent_id": "agent-aaaa1111", "agent_type": "dt:builder"}), {})
        self.assertEqual(self.rows(".harness/injections.jsonl")[0]["lesson_id"], "L-001")

    def test_disabled_or_unset_up_repo_does_nothing(self) -> None:
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nincident_capture: false\n---\n", encoding="utf-8")
        self.spawn("agent-aaaa1111", "fix it")
        self.assertFalse((self.repo / ".harness" / "agents.jsonl").exists())
        bare = make_tmp_home()
        done = self.run_hook("subagent-start", {"agent_id": "x", "agent_type": "dt:builder"}, repo=bare)
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertFalse((bare / ".harness").exists())

    def test_garbage_input_never_fails(self) -> None:
        for event in ("subagent-start", "subagent-stop", "post-tool-use", "stop", "session-end", "session-start", "pre-agent"):
            done = self.run_hook(event, "not json at all")
            self.assertEqual((done.returncode, done.stdout), (0, ""), event)
            done = self.run_hook(event, "[1, 2]")
            self.assertEqual((done.returncode, done.stdout), (0, ""), event)

    def test_unknown_telemetry_event_is_harmless(self) -> None:
        self.assertEqual(self.run_hook("bogus", {}).returncode, 0)

    def test_hook_is_fast_in_process(self) -> None:
        import sys
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        import incidents
        self.lessons("- [L-001] Validate input.")
        timings: list[float] = []
        for run in range(HOOK_TIMING_RUNS):
            started = time.perf_counter()
            incidents.run_hook("subagent-start", {"session_id": SESSION, "cwd": str(self.repo), "agent_id": f"z{run}", "agent_type": "dt:builder"})
            timings.append(time.perf_counter() - started)
        self.assertLess(min(timings), HOOK_BUDGET_S)


class StopTests(HookCase):
    def test_complete_report_has_no_incident_and_records_duration(self) -> None:
        self.spawn("agent-aaaa1111")
        self.assertEqual(self.stop("agent-aaaa1111", GOOD_REPORT), {})
        stop = [r for r in self.rows(".harness/agents.jsonl") if r["kind"] == "agent-stop"][0]
        self.assertEqual((stop["report_ok"], stop["partial"], stop["missing_sections"]), (True, False, []))
        self.assertGreaterEqual(stop["duration_s"], 0)
        self.assertEqual(self.incidents(), [])

    def test_tiny_report_is_no_report_with_live_message(self) -> None:
        self.spawn("agent-aaaa1111")
        result = self.stop("agent-aaaa1111", "done")
        self.assertIn("empty or tiny report", result["systemMessage"])
        self.assertEqual([i["category"] for i in self.incidents()], ["no-report"])

    def test_partial_report(self) -> None:
        self.spawn("agent-aaaa1111")
        self.stop("agent-aaaa1111", "PARTIAL: hit turn cap at step 4\nmore detail follows here")
        self.assertEqual([i["category"] for i in self.incidents()], ["partial"])

    def test_missing_sections_is_a_near_miss_without_blocking(self) -> None:
        self.spawn("agent-aaaa1111")
        result = self.stop("agent-aaaa1111", "## Files changed\n- a\n" + "x" * 30)
        self.assertNotIn("decision", result)
        found = self.incidents()
        self.assertEqual([(i["category"], i["severity"]) for i in found], [("report-incomplete", "near-miss")])
        self.assertEqual(found[0]["evidence"]["missing_sections"], ["commands run", "concerns"])

    def test_other_agents_are_not_held_to_a_contract(self) -> None:
        self.spawn("agent-bbbb2222", agent_type="dt:scout")
        self.stop("agent-bbbb2222", "free text findings that are long enough", agent_type="dt:scout")
        self.assertEqual(self.incidents(), [])

    def test_stop_twice_is_counted_once(self) -> None:
        self.spawn("agent-aaaa1111")
        self.stop("agent-aaaa1111", "done")
        self.stop("agent-aaaa1111", "done")
        self.assertEqual(len(self.incidents()), 1)

    def test_internal_agent_without_start_is_not_flagged(self) -> None:
        self.stop("agent-cccc3333", "", agent_type="")
        self.assertEqual(self.incidents(), [])

    def test_handback_report_is_used_instead_of_closing_text(self) -> None:
        self.spawn("agent-aaaa1111")
        self.out("post-tool-use", {"tool_name": "SubagentHandback", "agent_id": "agent-aaaa1111",
                                   "tool_input": {"message": GOOD_REPORT}})
        self.assertEqual(self.stop("agent-aaaa1111", "Handed back."), {})
        self.assertEqual(self.incidents(), [])

    def test_lessons_line_updates_counters(self) -> None:
        self.lessons("- [L-001] One.", "- [L-002] Two.", "- [L-003] Three.")
        self.spawn("agent-aaaa1111")
        self.stop("agent-aaaa1111", GOOD_REPORT + "\nLessons: L-001 helpful, L-002 not-helpful\n")
        stats = self.stats()
        self.assertEqual((stats["L-001"]["helpful"], stats["L-001"]["harmful"], stats["L-001"]["unused_streak"]), (1, 0, 0))
        self.assertEqual((stats["L-002"]["helpful"], stats["L-002"]["harmful"]), (0, 1))
        self.assertEqual((stats["L-003"]["unused"], stats["L-003"]["unused_streak"]), (1, 1))

    def test_incident_in_targeted_category_is_harmful_even_if_agent_said_helpful(self) -> None:
        self.lessons("- [L-001] Report properly. {cat: partial}")
        self.spawn("agent-aaaa1111")
        self.stop("agent-aaaa1111", "PARTIAL: hit turn cap\nLessons: L-001 helpful")
        stats = self.stats()["L-001"]
        self.assertEqual((stats["helpful"], stats["harmful"]), (1, 1))

    def test_lesson_is_demoted_and_then_never_injected(self) -> None:
        self.lessons("- [L-001] Report properly. {cat: no-report}")
        for n in range(3):
            self.spawn(f"agent-{n}")
            self.stop(f"agent-{n}", "x\nLessons: L-001 not-helpful")
        self.assertEqual(self.spawn("agent-late"), {})
        self.assertGreaterEqual(self.stats()["L-001"]["harmful"], 2)

    def test_lesson_expires_after_ten_unused_spawns(self) -> None:
        self.lessons("- [L-001] Never mentioned.")
        for n in range(10):
            self.assertIn("additionalContext", self.spawn(f"agent-{n}").get("hookSpecificOutput", {}))
            self.stop(f"agent-{n}", GOOD_REPORT)
        self.assertEqual(self.spawn("agent-late"), {})


class ReworkTests(HookCase):
    def edit(self, agent_id: str, agent_type: str, path: str = "src/x.py") -> dict[str, Any]:
        return self.out("post-tool-use", {"tool_name": "Edit", "agent_id": agent_id, "agent_type": agent_type,
                                          "tool_input": {"file_path": str(self.repo / path)}})

    def test_second_agent_editing_a_file_is_rework_and_main_session_edits_are_ignored(self) -> None:
        self.spawn("agent-aaaa1111")
        self.spawn("agent-bbbb2222", agent_type="dt:reviewer")
        self.edit("agent-aaaa1111", "dt:builder")
        self.out("post-tool-use", {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / "src/x.py")}})
        self.assertEqual(self.incidents(), [])
        self.edit("agent-bbbb2222", "dt:reviewer")
        found = self.incidents()
        self.assertEqual([(i["category"], i["agent_id"]) for i in found], [("rework-other-agent", "agent-bbbb2222")])
        note = self.out("post-tool-use", {"tool_name": "Agent", "tool_input": {}})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("src/x.py", note)
        self.assertIn("reviewer", note)

    def test_different_files_are_fine(self) -> None:
        self.edit("agent-aaaa1111", "dt:builder", "src/a.py")
        self.edit("agent-bbbb2222", "dt:reviewer", "src/b.py")
        self.assertEqual(self.incidents(), [])

    def test_other_tools_do_nothing(self) -> None:
        self.assertEqual(self.out("post-tool-use", {"tool_name": "Bash", "agent_id": "a", "tool_input": {"command": "ls"}}), {})


class SessionTests(HookCase):
    def old_start(self, agent_id: str, minutes: int) -> None:
        row = {"v": 1, "ts": int(time.time()) - minutes * 60, "run": "-", "lane": "-", "kind": "agent-start", "id": f"s-{agent_id}",
               "agent_id": agent_id, "agent_class": "builder", "agent_name": "dt:builder", "session_id": "old-session",
               "parent_agent_id": None}
        with (self.repo / ".harness" / "agents.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def test_stop_is_throttled_and_writes_brief_with_one_line(self) -> None:
        self.spawn("agent-aaaa1111")
        self.stop("agent-aaaa1111", GOOD_REPORT)
        first = self.out("stop", {})
        self.assertIn("1 spawned, 1 finished, 0 incidents", first["systemMessage"])
        self.assertTrue((self.repo / ".harness" / "briefs" / f"{SESSION}.md").is_file())
        self.assertEqual(self.out("stop", {}), {})
        self.assertIn("briefs", {r["kind"] for r in self.rows(".harness/metrics.jsonl")})

    def test_session_end_always_writes_brief(self) -> None:
        self.spawn("agent-aaaa1111")
        self.out("stop", {})
        self.assertIn("1 spawned", self.out("session-end", {"reason": "other"})["systemMessage"])

    def test_watchdog_runs_at_stop(self) -> None:
        self.old_start("zombie", 45)
        self.out("stop", {"session_id": "old-session"})
        self.assertEqual([i["category"] for i in self.incidents()], ["hung-spawn"])
        self.assertEqual(self.incidents()[0]["severity"], "blocking")

    def test_stop_with_nothing_to_report_is_silent(self) -> None:
        self.assertEqual(self.out("stop", {}), {})
        self.assertFalse((self.repo / ".harness" / "briefs").exists())

    def test_session_end_debriefs_and_marks_trend(self) -> None:
        for n in range(3):
            payload = {"session_id": f"s{n}", "cwd": str(self.repo)}
            self.run_hook("pre-agent", {**payload, "tool_name": "Agent", "tool_input": {"subagent_type": "dt:builder", "prompt": "fix it"}})
            self.run_hook("subagent-start", {**payload, "agent_id": f"agent-{n}", "agent_type": "dt:builder"})
            self.run_hook("session-end", payload)
        labels = [r["label"] for r in self.rows(".harness/ledgers/head.jsonl")]
        self.assertEqual(labels, ["isolated", "isolated", "trend"])

    def test_session_start_note(self) -> None:
        self.assertEqual(self.run_hook("session-start", {}).stdout, "")
        self.old_start("zombie", 45)
        self.out("stop", {"session_id": "old-session"})
        note = self.run_hook("session-start", {}).stdout
        self.assertIn("1 open (1 hung-spawn)", note)
        self.assertIn("possibly hung", note)


class CliTests(HookCase):
    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", "-I", str(SCRIPT), "--repo", str(self.repo), *args], capture_output=True, text=True,
                              env=self.env, check=False)

    def test_list_resolve_brief_live_and_review_input(self) -> None:
        self.spawn("agent-aaaa1111", "fix it")
        listing = json.loads(self.cli("list", "--open", "--json").stdout)
        self.assertEqual([i["category"] for i in listing], ["bad-brief"])
        self.assertIn("bad-brief", self.cli("list").stdout)
        self.assertEqual(json.loads(self.cli("live").stdout)["running"][0]["agent_id"], "agent-aaaa1111")
        self.assertIn("| builder | 1 | 0 |", self.cli("brief").stdout)
        self.assertIn("| builder | 1 | 0 |", self.cli("brief", "--session", SESSION).stdout)
        review = json.loads(self.cli("review-input").stdout)
        self.assertEqual(len(review["open_incidents"]), 1)
        done = self.cli("resolve", listing[0]["incident_id"], "--root-cause", "lead wrote a one-liner", "--how", "lesson added")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(self.cli("list", "--open", "--json").stdout), [])
        missing = self.cli("resolve", "INC-nope", "--root-cause", "x", "--how", "y")
        self.assertEqual(missing.returncode, 1)

    def test_lessons_stats_and_promote_flow(self) -> None:
        self.lessons("- [L-001] Report properly. {cat: no-report}")
        self.spawn("agent-aaaa1111")
        stats = json.loads(self.cli("lessons", "stats").stdout)
        self.assertEqual((stats[0]["id"], stats[0]["injected"], stats[0]["status"]), ("L-001", 1, "active"))
        harness = json.loads(self.cli("promote", "--tier", "harness", "L-001").stdout)
        self.assertEqual(harness["id"], "H-001")
        self.assertIn("[H-001]", (self.home / "lessons.md").read_text(encoding="utf-8"))
        skipped = self.cli("promote", "--tier", "knowledge", "L-001")
        self.assertEqual(skipped.returncode, 0)
        self.assertTrue(json.loads(skipped.stdout)["skipped"])


class EventWiringTests(HookCase):
    def run_event(self, script: str, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        body = json.dumps({"session_id": SESSION, "cwd": str(self.repo), **payload})
        return subprocess.run(["bash", str(HOOKS / script)], input=body, capture_output=True, text=True, cwd=str(self.repo),
                              env=self.env, check=False)

    def test_stop_failure_adds_api_error_incident_and_cooldown(self) -> None:
        done = self.run_event("stop-failure.sh", {"error": "rate_limit", "error_details": "You've hit your usage limit. resets in 3 hours"})
        self.assertEqual(done.returncode, 0, done.stderr)
        found = self.incidents()
        self.assertEqual([(i["category"], i["severity"]) for i in found], [("api-error", "blocking")])
        self.assertTrue((self.home / "agent-status.json").is_file())

    def test_stop_failure_plain_error_leaves_cooldowns_alone(self) -> None:
        self.run_event("stop-failure.sh", {"error": "server_error", "error_details": "boom"})
        self.assertEqual(len(self.incidents()), 1)
        self.assertFalse((self.home / "agent-status.json").exists())

    def test_permission_denied_adds_incident_once_per_tool(self) -> None:
        for _ in range(2):
            self.run_event("permission-denied.sh", {"tool_name": "Bash", "reason": "not allowed"})
        self.assertEqual([i["category"] for i in self.incidents()], ["permission-denied"])
        self.assertIn("PermissionDenied for Bash", (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
                      if (self.repo / ".harness" / "action-items.md").is_file() else "PermissionDenied for Bash")


if __name__ == "__main__":
    unittest.main()
