"""Contracts for the dpp, dpp-full and fullauto skills and for lanes.py plan / report-check."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT
from test_lanes import FAKE_GH, FAKE_GIT, lane, manifest
from test_son_mode import RULE_SOURCES, SON_HEADING, _read, windows
from test_text_contracts import TextContractMixin

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
DPP: Final[Path] = PLUGIN_ROOT / "skills" / "dpp" / "SKILL.md"
DPP_FULL: Final[Path] = PLUGIN_ROOT / "skills" / "dpp-full" / "SKILL.md"
FULLAUTO: Final[Path] = PLUGIN_ROOT / "skills" / "fullauto" / "SKILL.md"
AUTOPILOT: Final[Path] = PLUGIN_ROOT / "skills" / "autopilot" / "SKILL.md"
DPP_SECTIONS: Final[tuple[str, ...]] = (
    "## 0. Pre-check", "## 1. Lane sources", "## 2. Lane plan and feasibility", "## 3. Approval",
    "## 4. Start sons", "## 5. Supervise", "## 6. Merge order", "## 7. Lessons and memory roll-up",
    "## 8. Final report", "## Guardrails",
)
RULE_REFERENCE: Final[re.Pattern[str]] = re.compile(r"\(Rule \d+(\.\d+)?\)|\(autopilot §\w+\)|discipline\.md")
MIN_REFERENCES: Final[int] = 8
SHORT_SKILL_LINES: Final[int] = 5
NONE_FOUND: Final[str] = "no further parallel work found"
FRONTMATTER_FENCE: Final[str] = "---"


def body_lines(path: Path) -> list[str]:
    """Non-empty lines after the frontmatter."""
    text: str = _read(path)
    parts: list[str] = text.split(FRONTMATTER_FENCE, 2)
    body: str = parts[2] if len(parts) == 3 else text
    return [line for line in body.splitlines() if line.strip()]


def autopilot_before_son_mode() -> str:
    text: str = _read(AUTOPILOT)
    return text[: text.index(SON_HEADING)]


class DppSkillTextTests(TextContractMixin):
    def test_dpp_skill_sections(self) -> None:
        self.assert_contains(DPP, [*DPP_SECTIONS, "lanes.py plan", "lanes.py check", "dry-run", "outside check-in",
                                   "estimated_spend", "son-command", "merge-go.md", "status.json", "send-back",
                                   "second opinion", "out-of-lane", "$(git config user.name)", "agent-memory.py",
                                   "dpp-report.md", "Linked work", "report-check", "## Spend", "task-ledger.py",
                                   "## Task ledger", NONE_FOUND, "stalled", "--full", "TASK_", "lanes.py status",
                                   "lanes.py sendback", "lanes.py fold", "lanes.py release"])

    def test_dpp_full_defers_to_dpp(self) -> None:
        self.assert_contains(DPP_FULL, ["--full", "skills/dpp/SKILL.md", "delegation scan"])
        self.assertLessEqual(len(body_lines(DPP_FULL)), SHORT_SKILL_LINES)

    def test_fullauto_defers_to_dpp(self) -> None:
        self.assert_contains(FULLAUTO, ["dpp-full", "autopilot", "skills/dpp/SKILL.md"])
        self.assertLessEqual(len(body_lines(FULLAUTO)), SHORT_SKILL_LINES)

    def test_fullauto_names_stop_condition(self) -> None:
        self.assert_contains(FULLAUTO, ["nothing outstanding", "`done`", "`blocked`", "task ledger",
                                        "hard stop", "council", "remaining items", "lanes.py stop-check"])

    def test_fullauto_reruns_check_in_between_rounds(self) -> None:
        self.assert_contains(FULLAUTO, ["/dts2-harness:check-in", "after each son reports", "before the next dispatch"])

    def test_resume_merges_resolved_prs(self) -> None:
        self.assert_contains(DPP, ["task-ledger.py <stamp> --resolved", "merge son", "resume"])

    def test_dpp_questions_never_reach_user(self) -> None:
        self.assert_contains(DPP, ["questions/<n>.md", "head alone", "never forwarded to the user", "(autopilot §6)"])

    def test_dpp_mentions_rules_only_by_reference(self) -> None:
        text: str = _read(DPP)
        self.assertGreaterEqual(len(RULE_REFERENCE.findall(text)), MIN_REFERENCES)
        self.assertIn("discipline.md", text)

    def test_no_copied_rules(self) -> None:
        sources: list[tuple[str, str]] = [(p.name, _read(p)) for p in RULE_SOURCES]
        sources.append(("autopilot sections 0-5", autopilot_before_son_mode()))
        for skill in (DPP, DPP_FULL, FULLAUTO):
            own: set[tuple[str, ...]] = windows("\n".join(body_lines(skill)))
            for name, source in sources:
                shared = own & windows(source)
                self.assertEqual(shared, set(), f"{skill.parent.name} restates a rule from {name}: {sorted(shared)[:1]}")


class LanesPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-dpp-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        (self.fake / "git.py").write_text(FAKE_GIT, encoding="utf-8")

    def run_cmd(self, *args: str) -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake / "gh.py"), "DTS2_GIT_BIN": str(self.fake / "git.py"),
               "FAKE_PRS": "[]", "FAKE_REFS": ""}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, env=env, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        parsed["_code"] = done.returncode
        return parsed

    def write(self, name: str, data: Any) -> str:
        path: Path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def checkin(self, outstanding: list[str], complete: list[str] | None = None) -> str:
        done: list[str] = complete or []
        return self.write("check-in.json", {"total": len(outstanding) + len(done), "complete": len(done),
                                            "outstanding": len(outstanding), "percent": 0,
                                            "complete_items": done, "outstanding_items": outstanding})

    def test_plan_refuses_non_checkin_item_without_marker(self) -> None:
        draft = self.write("draft.json", manifest([lane("a", ["src/a.py"]), lane("9", ["src/z.py"])]))
        result = self.run_cmd("plan", "--from-checkin", self.checkin(["Sa"]), "--draft", draft)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["_code"], 2)
        self.assertEqual([r["item"] for r in result["refused"]], ["S9"])
        self.assertEqual([ln["id"] for ln in result["manifest"]["lanes"]], ["a"])

    def test_plan_accepts_outside_marker(self) -> None:
        draft = self.write("draft.json", manifest([lane("a", ["src/a.py"]), lane("9", ["src/z.py"])]))
        result = self.run_cmd("plan", "--from-checkin", self.checkin(["Sa"]), "--draft", draft,
                              "--outside", "S9: hotfix the login redirect")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["refused"], [])
        lanes = {ln["id"]: ln for ln in result["manifest"]["lanes"]}
        self.assertTrue(lanes["9"]["outside_checkin"])
        self.assertNotIn("outside_checkin", lanes["a"])
        for item in lanes.values():
            self.assertGreater(item["estimated_spend"]["total"], 0)
            self.assertEqual(item["estimated_spend"]["tier"], "standard")

    def test_full_never_pads_and_reports_none_found(self) -> None:
        draft = self.write("draft.json", manifest([lane("a", ["src/a.py"]), lane("b", ["src/b.py"]),
                                                   lane("c", ["src/a.py"])]))
        result = self.run_cmd("plan", "--from-checkin", self.checkin(["Sa", "Sb", "Sc"]), "--draft", draft, "--full")
        self.assertTrue(result["ok"], result)
        self.assertEqual([ln["id"] for ln in result["manifest"]["lanes"]], ["a", "b"])
        self.assertEqual([r["lane"] for r in result["reported"]], ["c"])
        self.assertEqual(result["note"], NONE_FOUND)
        self.assertTrue(result["feasibility"]["ok"])

    def test_full_caps_at_max(self) -> None:
        lanes = [lane(ln, [f"src/{ln}.py"]) for ln in "abcdefg"]
        draft = self.write("draft.json", manifest(lanes))
        result = self.run_cmd("plan", "--from-checkin", self.checkin([f"S{ln}" for ln in "abcdefg"]), "--draft", draft,
                              "--full", "--max", "5")
        self.assertEqual(len(result["manifest"]["lanes"]), 5)
        self.assertNotIn("note", result)

    def test_report_check_flags_missing_section(self) -> None:
        report = self.root / "dpp-report.md"
        complete = "## Lane a\n" + "".join(f"### {s}\nx\n" for s in self.lane_sections())
        partial = "## Lane b\n" + "".join(f"### {s}\nx\n" for s in self.lane_sections() if s != "Votes")
        report.write_text(complete + partial + "## Spend\nx\n## Task ledger\nx\n", encoding="utf-8")
        result = self.run_cmd("report-check", str(report), "--lanes", "a,b")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], [{"lane": "b", "section": "Votes"}])
        report.write_text(complete + "## Spend\nx\n", encoding="utf-8")
        result = self.run_cmd("report-check", str(report), "--lanes", "a")
        self.assertEqual(result["missing"], [{"lane": "*", "section": "Task ledger"}])

    @staticmethod
    def lane_sections() -> tuple[str, ...]:
        namespace: dict[str, Any] = {}
        source: str = (SCRIPT.parent / "lanes" / "common.py").read_text(encoding="utf-8")  # moved there by AC-3
        match = re.search(r"^LANE_SECTIONS: Final\[tuple\[str, \.\.\.\]\] = (\([^)]*\))", source, re.M | re.S)
        assert match is not None, "LANE_SECTIONS missing from lanes/common.py"
        exec(f"value = {match.group(1)}", namespace)  # noqa: S102 - the tuple literal from our own script
        return tuple(namespace["value"])


if __name__ == "__main__":
    unittest.main()
