"""B1 (lead): the lead gets a one-page brief, not raw roster, probe and ledger JSON dumps."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import briefs  # noqa: E402

BRIEFS: Final[Path] = PLUGIN_ROOT / "scripts" / "briefs.py"
ROSTER: Final[dict[str, Any]] = {
    "enabled": ["claude", "codex", "gemini"],
    "assignments": {"builder": ["codex", "claude"], "reviewer": ["claude"], "second-opinion": ["gemini", "codex"]},
    "handoff": ["gemini"], "live": ["claude", "codex"], "costOrder": ["codex", "gemini", "claude"],
}
PROBE: Final[dict[str, Any]] = {
    "agents": {"claude": {"available": True, "reason": "ok", "budget": "ok", "costTier": 3, "roles": ["builder"], "auth": "subscription"},
               "codex": {"available": True, "reason": "ok", "budget": "low", "costTier": 2, "roles": ["second-opinion"], "auth": "api-key"},
               "gemini": {"available": False, "reason": "not logged in", "budget": "unknown", "costTier": 1, "roles": [], "auth": "none"}},
    "usable": ["claude", "codex"], "dropped": [{"name": "gemini", "reason": "not logged in"}],
}
LEDGER: Final[list[dict[str, Any]]] = [
    {"kind": "check", "name": "test", "status": "pass", "duration_ms": 1200, "log_path": ".harness/runs/s/checks/test.log", "head": "abc"},
    {"kind": "check", "name": "lint", "status": "fail", "duration_ms": 300, "log_path": ".harness/runs/s/checks/lint.log", "head": "abc"},
    {"kind": "env", "missing": ["STRIPE_KEY"]},
]
TASK: Final[str] = "Add a /health endpoint and a test for it."


class LeadBriefTests(unittest.TestCase):
    def build(self) -> str:
        return briefs.lead_brief(TASK, ROSTER, PROBE, LEDGER, "s1")

    def test_one_page_with_the_task_verbatim(self) -> None:
        text: str = self.build()
        self.assertIn(TASK, text)
        self.assertLessEqual(len(text.encode()), 4000)
        self.assertLessEqual(len(text.splitlines()), 60)

    def test_no_raw_json_dump(self) -> None:
        text: str = self.build()
        for raw in ('"assignments"', '"costOrder"', '"agents":', '"duration_ms"', "{"):
            self.assertNotIn(raw, text)

    def test_roster_probe_and_checks_are_summarised(self) -> None:
        text: str = self.build()
        for needle in ("builder: codex, claude", "second-opinion: gemini, codex", "handoff: gemini", "usable: claude, codex",
                       "gemini (not logged in)", "codex: budget low", "| lint | fail |", "STRIPE_KEY"):
            self.assertIn(needle, text)

    def test_points_at_the_files_instead_of_inlining_them(self) -> None:
        text: str = self.build()
        for needle in (".harness/end-state.md", ".harness/discipline.md", ".harness/lessons.md", ".harness/config.yaml"):
            self.assertIn(needle, text)

    def test_empty_ledger_says_no_checks_yet(self) -> None:
        self.assertIn("no checks recorded yet", briefs.lead_brief(TASK, ROSTER, PROBE, [], "s1"))

    def test_cli_builds_from_json_files_and_records_the_probe(self) -> None:
        root: Path = Path(tempfile.mkdtemp(prefix="dts2-lead-"))
        (root / "roster.json").write_text(json.dumps(ROSTER), encoding="utf-8")
        (root / "probe.json").write_text(json.dumps(PROBE), encoding="utf-8")
        (root / "task.txt").write_text(TASK, encoding="utf-8")
        run_dir: Path = root / ".harness" / "runs" / "s1"
        run_dir.mkdir(parents=True)
        (run_dir / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in LEDGER) + "\n", encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(BRIEFS), "lead-brief", "--cwd", str(root), "--stamp", "s1",
                               "--task-file", str(root / "task.txt"), "--roster-json", str(root / "roster.json"),
                               "--probe-json", str(root / "probe.json")], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("| lint | fail |", done.stdout)
        self.assertEqual(json.loads((run_dir / "probe.json").read_text(encoding="utf-8")), PROBE)


if __name__ == "__main__":
    unittest.main()
