"""scripts/next_step.py: every rung of the router, the ladder view, the STOP file and the CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import next_step  # noqa: E402
import roadmap  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "next_step.py"
RUNG_COUNT: Final[int] = 11
HEADER: Final[str] = """# End state

- rounds: 2
- clarity: 90
- threshold: 80
- status: approved
- continuedAnyway: no
"""
DEPLOY_PLANNED: Final[str] = """
## Deploy

```
deploy:
  provider: vercel
  plan: ship it
  status: planned
```
"""
DEPLOY_LIVE: Final[str] = DEPLOY_PLANNED.replace("planned", "live")
ACTION_ITEMS: Final[str] = """## Decisions

| item | context | status | owner | added |
|---|---|---|---|---|
| pick a name | - | open | | 2026-01-01 |
"""
ACTION_ITEMS_DONE: Final[str] = ACTION_ITEMS.replace("| open |", "| done |")


def sections(*statuses: str) -> str:
    head: str = "\n## Sections\n| # | section | serves component | files / area | depends on | complexity | status |\n|---|---|---|---|---|---|---|\n"
    rows: list[str] = [f"| {n} | part {n} | api | src/ | - | normal | {s} |" for n, s in enumerate(statuses, start=1)]
    return head + "\n".join(rows) + "\n\n## Acceptance criteria\n\n### api\n\n- [x] it works\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def approve_roadmap(repo: Path) -> None:
    key: str = roadmap.status(repo)["key"]
    write(repo / ".claude" / "settings.local.json", json.dumps({"dts2_approvals": {"roadmap": [key]}}))


class Fixture:
    """A temp repo and a temp DTS2 home, so the real home is never read."""

    def __init__(self) -> None:
        self.repo: Path = Path(tempfile.mkdtemp(prefix="dts2-next-repo-"))
        self.home: Path = Path(tempfile.mkdtemp(prefix="dts2-next-home-"))

    def end_state(self, text: str) -> None:
        write(self.repo / ".harness" / "end-state.md", text)

    def decide(self, open_prs: int | None = None) -> dict[str, Any]:
        return next_step.decide(self.repo, self.home, open_prs)


def ready_fixture(*statuses: str, tail: str = "") -> Fixture:
    """Composio decided, end state approved, roadmap approved, with the given section statuses."""
    fixture: Fixture = Fixture()
    write(fixture.home / "composio.json", "{}")
    fixture.end_state(HEADER + sections(*statuses) + tail)
    approve_roadmap(fixture.repo)
    return fixture


def run_cli(repo: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env: dict[str, str] = {**os.environ, next_step.HOME_ENV: str(home)}
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True, text=True, check=False, env=env,
    )


class RungTests(unittest.TestCase):
    def check(self, result: dict[str, Any], rung: int, state: str, command: str | None) -> None:
        self.assertEqual(set(result), {"rung", "state", "next_command", "reason", "blocked_on"})
        self.assertEqual((result["rung"], result["state"], result["next_command"]), (rung, state, command))
        self.assertIsInstance(result["reason"], str)
        self.assertTrue(result["reason"])

    def test_rung_0_stopped_wins_over_everything(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        next_step.stop(fixture.repo, "pause for review")
        result: dict[str, Any] = fixture.decide()
        self.check(result, 0, "stopped", None)
        self.assertEqual(result["blocked_on"], "a person deletes .harness/STOP")

    def test_rung_1_no_composio_decision(self) -> None:
        fixture: Fixture = Fixture()
        self.check(fixture.decide(), 1, "no-composio-decision", "composio")

    def test_rung_1_reads_the_dts2_home_variable(self) -> None:
        fixture: Fixture = Fixture()
        write(fixture.home / "composio.json", "{}")
        saved: str | None = os.environ.get(next_step.HOME_ENV)
        os.environ[next_step.HOME_ENV] = str(fixture.home)
        try:
            result: dict[str, Any] = next_step.decide(fixture.repo)
        finally:
            if saved is None:
                os.environ.pop(next_step.HOME_ENV, None)
            else:
                os.environ[next_step.HOME_ENV] = saved
        self.assertEqual(result["rung"], 2)

    def test_rung_2_no_end_state(self) -> None:
        fixture: Fixture = Fixture()
        write(fixture.home / "composio.json", "{}")
        self.check(fixture.decide(), 2, "no-end-state", "setup")

    def test_rung_3_end_state_not_approved(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        fixture.end_state((HEADER + sections("todo")).replace("- status: approved", "- status: pending approval"))
        self.check(fixture.decide(), 3, "end-state-not-approved", "setup")

    def test_rung_3_low_clarity_without_continue_anyway(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        fixture.end_state((HEADER + sections("todo")).replace("- clarity: 90", "- clarity: 40"))
        self.check(fixture.decide(), 3, "end-state-not-approved", "setup")

    def test_rung_3_low_clarity_with_continue_anyway_passes(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        text: str = (HEADER + sections("todo")).replace("- clarity: 90", "- clarity: 40").replace("continuedAnyway: no", "continuedAnyway: yes")
        fixture.end_state(text)
        approve_roadmap(fixture.repo)
        self.assertEqual(fixture.decide()["rung"], 5)

    def test_rung_3_non_numeric_clarity_counts_as_not_below(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        text: str = (HEADER + sections("todo")).replace("- clarity: 90", "- clarity: high")
        fixture.end_state(text)
        approve_roadmap(fixture.repo)
        self.assertEqual(fixture.decide()["rung"], 5)

    def test_rung_4_roadmap_not_approved(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        (fixture.repo / ".claude" / "settings.local.json").unlink()
        result: dict[str, Any] = fixture.decide()
        self.check(result, 4, "roadmap-not-approved", None)
        info: dict[str, Any] = roadmap.status(fixture.repo)
        phrase: str = info["lock_phrase"]
        key: str = info["key"]
        self.assertEqual(result["blocked_on"], f"the owner says \"lock it in\" in chat, or types: {phrase} (any harness: approvals.py lock-roadmap {key})")

    def test_rung_4_without_scope_says_to_run_setup(self) -> None:
        fixture: Fixture = Fixture()
        write(fixture.home / "composio.json", "{}")
        fixture.end_state(HEADER)
        result: dict[str, Any] = fixture.decide()
        self.check(result, 4, "roadmap-not-approved", None)
        self.assertEqual(result["blocked_on"], "the end state has no sections; run setup")

    def test_rung_5_one_todo_section_runs(self) -> None:
        self.check(ready_fixture("done", "todo").decide(), 5, "sections-outstanding", "run")

    def test_rung_5_two_todo_sections_fan_out(self) -> None:
        self.check(ready_fixture("todo", "todo", "done").decide(), 5, "sections-outstanding", "dpp")

    def test_rung_5_in_progress_sections_do_not_fan_out(self) -> None:
        self.check(ready_fixture("in-progress", "blocked", "todo").decide(), 5, "sections-outstanding", "run")

    def test_rung_6_open_pull_requests(self) -> None:
        fixture: Fixture = ready_fixture("done")
        self.check(fixture.decide(open_prs=2), 6, "open-pull-requests", "pr-sweep")

    def test_rung_6_zero_or_unknown_pull_requests_pass(self) -> None:
        fixture: Fixture = ready_fixture("done")
        self.assertEqual(fixture.decide(open_prs=0)["rung"], 10)
        self.assertEqual(fixture.decide(open_prs=None)["rung"], 10)

    def test_rung_7_open_action_items(self) -> None:
        fixture: Fixture = ready_fixture("done")
        write(fixture.repo / ".harness" / "action-items.md", ACTION_ITEMS)
        self.check(fixture.decide(), 7, "action-items-open", "action-items")

    def test_rung_7_closed_action_items_pass(self) -> None:
        fixture: Fixture = ready_fixture("done")
        write(fixture.repo / ".harness" / "action-items.md", ACTION_ITEMS_DONE)
        self.assertEqual(fixture.decide()["rung"], 10)

    def test_rung_8_deploy_planned(self) -> None:
        fixture: Fixture = ready_fixture("done", tail=DEPLOY_PLANNED)
        self.check(fixture.decide(), 8, "deploy-planned", "run")

    def test_rung_8_live_deploy_and_template_prose_pass(self) -> None:
        live: Fixture = ready_fixture("done", tail=DEPLOY_LIVE)
        self.assertEqual(live.decide()["rung"], 10)
        template: str = (PLUGIN_ROOT / "templates" / "end-state.md").read_text(encoding="utf-8")
        prose: Fixture = ready_fixture("done", tail="\n" + template[template.index("## Deploy"):template.index("## Related repos")])
        self.assertEqual(prose.decide()["rung"], 10)

    def test_rung_9_unmet_acceptance_criteria_run_again(self) -> None:
        fixture: Fixture = Fixture()
        write(fixture.home / "composio.json", "{}")
        fixture.end_state(HEADER + sections("done").replace("- [x] it works", "- [ ] it works"))
        approve_roadmap(fixture.repo)
        self.check(fixture.decide(), 9, "acceptance-outstanding", "run")
        self.assertEqual(fixture.decide()["reason"], "1 acceptance criterion not met yet")

    def test_rung_10_complete(self) -> None:
        self.check(ready_fixture("done").decide(), 10, "complete", "learn")

    def test_earlier_rungs_win(self) -> None:
        fixture: Fixture = ready_fixture("todo", "todo", tail=DEPLOY_PLANNED)
        write(fixture.repo / ".harness" / "action-items.md", ACTION_ITEMS)
        self.assertEqual(fixture.decide(open_prs=3)["rung"], 5)


class StopAndLadderTests(unittest.TestCase):
    def test_stop_writes_the_reason_then_decide_gives_rung_zero(self) -> None:
        fixture: Fixture = ready_fixture("done")
        path: Path = next_step.stop(fixture.repo, "hold the line")
        self.assertEqual(path, fixture.repo / ".harness" / "STOP")
        self.assertEqual(path.read_text(encoding="utf-8"), "hold the line\n")
        self.assertEqual(fixture.decide()["rung"], 0)

    def test_nothing_in_the_module_removes_the_stop_file(self) -> None:
        names: list[str] = [name for name in dir(next_step) if not name.startswith("_")]
        self.assertFalse([n for n in names if n.startswith(("clear", "unstop", "resume", "remove", "delete"))])

    def test_ladder_has_ten_rungs_and_one_current(self) -> None:
        for fixture in (Fixture(), ready_fixture("todo"), ready_fixture("done")):
            entries: list[dict[str, Any]] = next_step.ladder(fixture.repo, fixture.home)
            self.assertEqual([e["rung"] for e in entries], list(range(RUNG_COUNT)))
            self.assertEqual(sum(1 for e in entries if e["current"]), 1)
            current: dict[str, Any] = next(e for e in entries if e["current"])
            self.assertEqual(current["rung"], fixture.decide()["rung"])
            self.assertEqual(set(entries[0]), {"rung", "state", "current"})

    def test_ladder_passes_open_prs_through(self) -> None:
        fixture: Fixture = ready_fixture("done")
        entries: list[dict[str, Any]] = next_step.ladder(fixture.repo, fixture.home, open_prs=1)
        self.assertEqual([e["rung"] for e in entries if e["current"]], [6])


class CliTests(unittest.TestCase):
    def test_next_prints_the_decision_as_json(self) -> None:
        fixture: Fixture = ready_fixture("todo", "todo")
        result = run_cli(fixture.repo, fixture.home, "next")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), fixture.decide())

    def test_open_prs_flag_reaches_the_router(self) -> None:
        fixture: Fixture = ready_fixture("done")
        result = run_cli(fixture.repo, fixture.home, "--open-prs", "4", "next")
        self.assertEqual(json.loads(result.stdout)["state"], "open-pull-requests")

    def test_status_marks_the_current_rung(self) -> None:
        fixture: Fixture = ready_fixture("todo")
        result = run_cli(fixture.repo, fixture.home, "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines: list[str] = result.stdout.splitlines()
        self.assertEqual(len(lines), RUNG_COUNT)
        self.assertEqual([line for line in lines if line.startswith(">")], ["> 5 sections-outstanding"])
        self.assertIn("  0 stopped", lines)
        self.assertIn("  10 complete", lines)

    def test_stop_writes_the_file(self) -> None:
        fixture: Fixture = ready_fixture("done")
        result = run_cli(fixture.repo, fixture.home, "stop", "--reason", "pause")
        target: Path = fixture.repo / ".harness" / "STOP"
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"stopped": str(target)})
        self.assertEqual(target.read_text(encoding="utf-8"), "pause\n")
        self.assertEqual(json.loads(run_cli(fixture.repo, fixture.home, "next").stdout)["rung"], 0)

    def test_stop_requires_a_reason(self) -> None:
        fixture: Fixture = ready_fixture("done")
        self.assertNotEqual(run_cli(fixture.repo, fixture.home, "stop").returncode, 0)
        self.assertFalse((fixture.repo / ".harness" / "STOP").exists())


if __name__ == "__main__":
    unittest.main()
