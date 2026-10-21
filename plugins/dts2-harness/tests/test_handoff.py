"""handoff-write.py: renders .harness/handoff/latest.md; Stop hook calls it; run/setup text."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home
from test_hooks import make_repo as make_git_repo, run_hook

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "handoff-write.py"
TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "handoff-latest.md"
SECRET_VALUE: Final[str] = "sk-test-NEVER-PRINT"
SECTIONS: Final[list[str]] = ["## State", "## Open items", "## Next action", "## Resume", "## Recommended agent"]
POINTER: Final[str] = "Harness state for any agent: .harness/handoff/latest.md (resume with /dts2-harness:run resume)."


def make_repo() -> Path:
    repo: Path = make_tmp_home()
    harness: Path = repo / ".harness"
    run_dir: Path = harness / "runs" / "20261020-101500"
    run_dir.mkdir(parents=True)
    (repo / ".env").write_text(f"STRIPE_KEY={SECRET_VALUE}\n", encoding="utf-8")
    (harness / "state.md").write_text(
        "# Harness state\n\n## Decisions\n- 2026-10-20 shipped checkout, receipt .harness/runs/20261020-101500/receipt.md\n\n"
        "## Failures and escalations\n- 2026-10-19 builder 2 failed 3 times on lint\n\n"
        f"## Open items\n- 2026-10-20 wire webhook STRIPE_KEY={SECRET_VALUE}\n", encoding="utf-8")
    (harness / "action-items.md").write_text(
        "## Secrets\n\n| name | unlocks | consumed in | how to add | status | owner | added |\n|---|---|---|---|---|---|---|\n"
        "| STRIPE_KEY | payments | src/pay.ts | .env | open | | 2026-10-01 |\n", encoding="utf-8")
    (harness / "end-state.md").write_text(
        "# End state: shop\n\n## Deploy\n\n```\ndeploy:\n  provider: vercel\n  productionUrl: https://shop.example.com\n"
        "  checkCommand: null\n```\n", encoding="utf-8")
    (run_dir / "receipt.md").write_text("## Change receipt\n\n### Review verdict\n\napproved, reviewer, 2026-10-20\n", encoding="utf-8")
    (run_dir / "1-plan.md").write_text("### Builder 1\ncomplexity: mechanical\n### Builder 2\ncomplexity: design\n", encoding="utf-8")
    return repo


def write(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), str(repo)], capture_output=True, text=True, check=False)


def latest(repo: Path) -> str:
    return (repo / ".harness" / "handoff" / "latest.md").read_text(encoding="utf-8")


class HandoffWriteTests(unittest.TestCase):
    def test_renders_five_sections(self) -> None:
        repo: Path = make_repo()
        result = write(repo)
        self.assertEqual(result.returncode, 0)
        out: dict[str, Any] = json.loads(result.stdout)
        self.assertTrue(out["written"])
        text: str = latest(repo)
        positions: list[int] = [text.find(s) for s in SECTIONS]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn("/dts2-harness:run resume", text)

    def test_content_comes_from_sources(self) -> None:
        repo: Path = make_repo()
        write(repo)
        text: str = latest(repo)
        self.assertIn("20261020-101500", text)
        self.assertIn("vercel", text)
        self.assertIn("https://shop.example.com", text)
        self.assertIn("STRIPE_KEY", text)
        self.assertIn("run add secret STRIPE_KEY", text)
        self.assertIn("approved", text)

    def test_recommended_agent_tiers(self) -> None:
        repo: Path = make_repo()
        write(repo)
        text: str = latest(repo).split("## Recommended agent")[1]
        self.assertIn("lead: claude (frontier)", text)
        self.assertIn("builder: claude (frontier)", text)
        (repo / ".harness" / "runs" / "20261020-101500" / "1-plan.md").write_text("complexity: mechanical\n", encoding="utf-8")
        write(repo)
        self.assertIn("builder: claude (economy)", latest(repo))

    def test_idempotent(self) -> None:
        repo: Path = make_repo()
        write(repo)
        first: str = latest(repo)
        write(repo)
        self.assertEqual(first, latest(repo))

    def test_never_includes_secret_values(self) -> None:
        repo: Path = make_repo()
        result = write(repo)
        self.assertNotIn(SECRET_VALUE, latest(repo))
        self.assertNotIn(SECRET_VALUE, result.stdout + result.stderr)
        self.assertIn("STRIPE_KEY=<redacted>", latest(repo))

    def test_empty_harness_still_renders(self) -> None:
        repo: Path = make_tmp_home()
        (repo / ".harness").mkdir()
        self.assertEqual(write(repo).returncode, 0)
        text: str = latest(repo)
        for section in SECTIONS:
            self.assertIn(section, text)
        self.assertIn("/dts2-harness:run <task>", text)

    def test_no_harness_dir_skips(self) -> None:
        repo: Path = make_tmp_home()
        out: dict[str, Any] = json.loads(write(repo).stdout)
        self.assertFalse(out["written"])
        self.assertFalse((repo / ".harness").exists())

    def test_template_has_sections(self) -> None:
        text: str = TEMPLATE.read_text(encoding="utf-8")
        for section in SECTIONS:
            self.assertIn(section, text)


class StopHookTests(unittest.TestCase):
    def test_stop_hook_writes_handoff(self) -> None:
        repo: Path = make_git_repo()
        result = run_hook("stop-checks.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((repo / ".harness" / "handoff" / "latest.md").is_file())

    def test_stop_hook_survives_writer_failure(self) -> None:
        repo: Path = make_git_repo()
        (repo / ".harness" / "handoff").write_text("not a directory", encoding="utf-8")
        (repo / ".harness" / "checks.sh").write_text("echo CHECKS-RAN\n", encoding="utf-8")
        result = run_hook("stop-checks.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertIn("CHECKS-RAN", result.stderr)


class SkillTextTests(unittest.TestCase):
    def test_run_skill_has_resume_and_write_handoff(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("run resume", ".harness/handoff/latest.md", "handoff-write.py"):
            self.assertIn(needle, text)
        self.assertLess(text.find("run resume"), text.find("1. **Harness change.**"))

    def test_setup_skill_has_agents_pointer(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(POINTER, text)

    def test_action_items_template_has_owner(self) -> None:
        text: str = (PLUGIN_ROOT / "templates" / "action-items.md").read_text(encoding="utf-8")
        for group in ("## Secrets", "## Decisions", "## Handoff", "## Deploy", "## Promotions"):
            self.assertIn(group, text)
        self.assertIn("owner", text)


if __name__ == "__main__":
    unittest.main()
