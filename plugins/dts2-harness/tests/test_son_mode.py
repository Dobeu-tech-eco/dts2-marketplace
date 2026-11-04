"""Contracts for son mode: autopilot's section 6, lanes.py son-command, bundle and post-merge steps, and no copied rules."""
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
from test_text_contracts import TextContractMixin

AUTOPILOT: Final[Path] = PLUGIN_ROOT / "skills" / "autopilot" / "SKILL.md"
VERIFIER: Final[Path] = PLUGIN_ROOT / "agents" / "verifier.md"
LOCAL_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "dts2-harness.local.md"
LANES: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
RULE_SOURCES: Final[tuple[Path, ...]] = (
    PLUGIN_ROOT / "templates" / "discipline.md",
    PLUGIN_ROOT / "skills" / "run" / "SKILL.md",
    PLUGIN_ROOT / "skills" / "ship" / "SKILL.md",
)
SON_HEADING: Final[str] = "## 6. Son mode"
GUARDRAILS_HEADING: Final[str] = "## Guardrails"
# A run of this many consecutive words shared with a rule source is a copied rule, not a reference.
COPY_WINDOW: Final[int] = 12
FAKE_CLAUDE: Final[str] = "#!/usr/bin/env python3\nprint('fake claude')\n"
DEFAULT_PERMISSION_MODE: Final[str] = "bypassPermissions"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def son_section() -> str:
    text: str = _read(AUTOPILOT)
    start: int = text.index(SON_HEADING)
    end: int = text.index(GUARDRAILS_HEADING, start)
    return text[start:end]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def windows(text: str) -> set[tuple[str, ...]]:
    tokens: list[str] = words(text)
    return {tuple(tokens[i:i + COPY_WINDOW]) for i in range(len(tokens) - COPY_WINDOW + 1)}


class SonModeTextTests(TextContractMixin):
    def test_autopilot_has_son_mode_section(self) -> None:
        self.assert_contains(AUTOPILOT, [
            SON_HEADING, "--son <stamp>/<lane>", "brief.md", "questions/", "merge-go.md", "report.md",
            "status.json", "harness-lock.py", "--role son", "never the user", "never runs setup or onboard",
        ])

    def test_son_section_refers_to_rules_without_restating(self) -> None:
        section: str = son_section()
        self.assertIn("discipline.md", section)
        self.assertIn("sections 0", section)
        own: set[tuple[str, ...]] = windows(section)
        for source in RULE_SOURCES:
            shared = own & windows(_read(source))
            self.assertEqual(shared, set(), f"son mode restates a rule from {source.name}: {sorted(shared)[:1]}")
        earlier: str = _read(AUTOPILOT)[: _read(AUTOPILOT).index(SON_HEADING)]
        shared_self = own & windows(earlier)
        self.assertEqual(shared_self, set(), f"son mode restates an autopilot rule: {sorted(shared_self)[:1]}")

    def test_autopilot_bundle_step_present(self) -> None:
        self.assert_contains(AUTOPILOT, ["**Bundle**", "MAX_BUNDLE", "checkpoint <k>/<n>", '"checkpoints"'])

    def test_autopilot_post_merge_gate_present(self) -> None:
        self.assert_contains(AUTOPILOT, ["**Post-merge check**", "Mode: post-merge", "never SKIP"])

    def test_autopilot_does_not_park_on_missing_secret(self) -> None:
        self.assert_absent(AUTOPILOT, ["a `SECRET NEEDED` with no value present"])
        self.assert_contains(AUTOPILOT, ["TASK_", "never slows or stops"])

    def test_autopilot_has_adjudication_phase(self) -> None:
        self.assert_contains(AUTOPILOT, ["## 5a. Adjudication", "task-ledger.md", "as few open PRs", "never merged"])

    def test_verifier_has_post_merge_mode(self) -> None:
        self.assert_contains(VERIFIER, ["**Post-merge walkthrough**", "Mode: post-merge", "merged-<screen>.png"])

    def test_local_template_has_son_permission_mode(self) -> None:
        self.assert_contains(LOCAL_TEMPLATE, [f"son_permission_mode: {DEFAULT_PERMISSION_MODE}"])

    def test_autopilot_untouched_outside_addendum_lines(self) -> None:
        self.assert_contains(AUTOPILOT, [
            "## 1b. The council", "## 4. Parking, hard stops, and resume", "## 5. Final report",
            "The panel is always three distinct providers at frontier",
        ])


class SonCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-son-"))
        self.manifest = self.root / "lanes.json"
        self.manifest.write_text(json.dumps({
            "stamp": "20261104-7", "base": "b21f442", "scope": "single",
            "lanes": [{"id": "a", "item": "S1", "files": ["src/a.py"], "ids": {}, "depends_on": [], "tier": "standard"}],
        }), encoding="utf-8")
        self.fake = self.root / "claude.py"
        self.fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.worktree = self.root / "wt" / "a"
        self.worktree.mkdir(parents=True)

    def run_son(self, env_extra: dict[str, str] | None = None) -> dict[str, Any]:
        env: dict[str, str] = {**os.environ, "DTS2_CLAUDE_BIN": str(self.fake), **(env_extra or {})}
        done = subprocess.run(
            [sys.executable, "-I", str(LANES), "--cwd", str(self.root), "son-command", str(self.manifest),
             "--lane", "a", "--worktree", str(self.worktree)],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_son_command_uses_worktree_and_fake_bin(self) -> None:
        result = self.run_son()
        self.assertEqual(result["cwd"], str(self.worktree))
        argv: list[str] = result["argv"]
        self.assertEqual(argv[:2], [sys.executable, str(self.fake)])
        self.assertIn("-p", argv)
        self.assertIn("/dts2-harness:autopilot --son 20261104-7/a", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], DEFAULT_PERMISSION_MODE)
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], str(PLUGIN_ROOT))
        self.assertIn("--model", argv)

    def test_son_command_reads_permission_mode_setting(self) -> None:
        settings: Path = self.root / ".claude" / "dts2-harness.local.md"
        settings.parent.mkdir()
        settings.write_text("---\nenabled: true\nson_permission_mode: acceptEdits\n---\n", encoding="utf-8")
        argv: list[str] = self.run_son()["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")

    def test_son_command_unknown_lane_fails(self) -> None:
        done = subprocess.run(
            [sys.executable, "-I", str(LANES), "--cwd", str(self.root), "son-command", str(self.manifest),
             "--lane", "zz", "--worktree", str(self.worktree)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 1)
        self.assertFalse(json.loads(done.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
