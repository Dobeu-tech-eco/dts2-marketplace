"""A new lead gets the orchestrator's current dt plugin, not an older dts2-harness cache."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lead_skills.py"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("lead_skills_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["lead_skills_under_test"] = module
    spec.loader.exec_module(module)
    return module


def write_plugin(root: Path, name: str, version: str, skills: list[str], repo: str) -> None:
    meta: Path = root / ".claude-plugin"
    meta.mkdir(parents=True)
    (meta / "plugin.json").write_text(json.dumps({
        "name": name, "version": version, "repository": repo,
    }), encoding="utf-8")
    for skill in skills:
        folder: Path = root / "skills" / skill
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")


class LeadSkillSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load()
        self.tmp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.home: Path = Path(self.tmp.name)
        self.plugin: Path = self.home / "src"
        self.repo: str = "https://github.com/Dobeu-tech-eco/dts2-marketplace"
        write_plugin(self.plugin, "dt", "9.9.9", ["model", "setup"], self.repo)
        user_skill: Path = self.home / ".claude" / "skills" / "grill-me"
        user_skill.mkdir(parents=True)
        (user_skill / "SKILL.md").write_text("---\nname: grill-me\n---\n", encoding="utf-8")
        old: Path = self.home / ".codex" / "plugins" / "cache" / "dts2" / "dts2-harness" / "4.0.0"
        write_plugin(old, "dts2-harness", "4.0.0", ["run"], self.repo)
        (self.home / ".codex" / "config.toml").write_text(
            'model = "gpt-6.1-sol"\n\n[plugins."dts2-harness@dts2"]\nenabled = true\n\n[other]\nkeep = true\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gap_names_the_legacy_plugin(self) -> None:
        identity: dict[str, Any] = self.mod.plugin_identity(self.plugin)
        skills: list[str] = self.mod.orchestrator_skill_list(self.plugin, self.home)
        gap: dict[str, Any] | None = self.mod.gap_for("codex", self.home, identity, skills)
        assert gap is not None
        self.assertIn("dts2-harness 4.0.0", gap["reason"])
        self.assertIn("dt@dts2 9.9.9", gap["reason"])
        self.assertIn("grill-me", gap["missing_skills"])
        self.assertIsNone(self.mod.gap_for("claude", self.home, identity, skills))

    def test_sync_installs_dt_and_disables_the_legacy_id(self) -> None:
        result: dict[str, Any] = self.mod.sync_agent("codex", self.home, self.plugin)
        self.assertTrue(result["updated"])
        installed: Path = self.home / ".codex" / "plugins" / "cache" / "dts2" / "dt" / "9.9.9"
        meta: dict[str, Any] = json.loads((installed / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "dt")
        self.assertTrue((installed / "skills" / "model" / "SKILL.md").is_file())
        self.assertTrue((installed / "skills" / "setup" / "SKILL.md").is_file())
        self.assertFalse((installed / "tests").exists())
        overlay: dict[str, Any] = json.loads((installed / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(overlay["name"], "dt")
        self.assertTrue((self.home / ".codex" / "skills" / "grill-me" / "SKILL.md").is_file())
        config: str = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('[plugins."dt@dts2"]\nenabled = true', config)
        self.assertIn('[plugins."dts2-harness@dts2"]\nenabled = false', config)
        self.assertIn('[plugins."dts2@dts2"]\nenabled = false', config)
        self.assertIn('source = "Dobeu-tech-eco/dts2-marketplace"', config)
        self.assertIn("[other]\nkeep = true", config)
        manifest: dict[str, Any] = json.loads((self.home / ".dts2" / "lead-skills" / "codex.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], ["model", "setup", "grill-me"])
        again: dict[str, Any] = self.mod.sync_agent("codex", self.home, self.plugin)
        self.assertFalse(again["updated"])
        self.assertIsNone(self.mod.gap_for("codex", self.home, self.mod.plugin_identity(self.plugin), manifest["skills"]))

    def test_other_agents_land_in_the_harness_backend(self) -> None:
        self.mod.sync_agent("gemini", self.home, self.plugin)
        self.assertTrue((self.home / ".dts2" / "agent-plugins" / "gemini" / "plugins" / "cache" / "dts2" / "dt" / "9.9.9").is_dir())
        self.assertFalse((self.home / ".codex" / "plugins" / "cache" / "dts2" / "dt").exists())


class SkillInstructionTests(unittest.TestCase):
    def test_model_setup_and_onboard_call_the_sync(self) -> None:
        model: str = (PLUGIN_ROOT / "skills" / "model" / "SKILL.md").read_text(encoding="utf-8")
        setup: str = (PLUGIN_ROOT / "skills" / "setup" / "phase-1-interview-a.md").read_text(encoding="utf-8")
        onboard: str = (PLUGIN_ROOT / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8")
        for text in (model, setup, onboard):
            self.assertIn("lead_skills.py", text)
        self.assertIn("sync --agents", model)
        self.assertIn("do not ask", setup)
        self.assertIn("do not ask", onboard)


if __name__ == "__main__":
    unittest.main()
