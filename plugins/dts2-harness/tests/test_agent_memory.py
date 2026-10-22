"""scripts/agent-memory.py: one seeded project memory file per distinct rulesFile, idempotent."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "agent-memory.py"
PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
START: Final[str] = "<!-- dts2-harness:start -->"
END: Final[str] = "<!-- dts2-harness:end -->"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agent_memory_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["agent_memory_under_test"] = module
    spec.loader.exec_module(module)
    return module


def all_profiles() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        loaded[data["name"]] = data
    return loaded


def write(folder: Path, agents: str, project: str = "proj") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--write", str(folder), "--agents", agents, "--project", project],
        capture_output=True, text=True, check=True,
    )


class PureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()
        self.profiles: dict[str, dict[str, Any]] = all_profiles()

    def test_dedups_agents_md_across_codex_and_muse(self) -> None:
        files: list[str] = self.mod.rules_files(self.profiles, ["claude", "codex", "muse"])
        self.assertEqual(files, ["AGENTS.md", "CLAUDE.md"])

    def test_includes_claude_md_and_gemini_md(self) -> None:
        files: list[str] = self.mod.rules_files(self.profiles, ["claude", "gemini"])
        self.assertIn("CLAUDE.md", files)
        self.assertIn("GEMINI.md", files)
        self.assertEqual(files, sorted(files))

    def test_missing_rules_file_defaults_to_agents_md(self) -> None:
        bare: dict[str, dict[str, Any]] = {"x": {"name": "x"}}
        self.assertEqual(self.mod.rules_files(bare, ["x"]), ["AGENTS.md"])

    def test_unknown_agent_is_skipped(self) -> None:
        self.assertEqual(self.mod.rules_files(self.profiles, ["nope"]), [])

    def test_seed_contains_project_name(self) -> None:
        self.assertIn("proj", self.mod.memory_seed("proj"))


class WriteTests(unittest.TestCase):
    def test_creates_files_and_second_run_is_identical(self) -> None:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-mem-"))
        write(folder, "claude,codex,muse")
        names: list[str] = sorted(p.name for p in folder.iterdir())
        self.assertEqual(names, ["AGENTS.md", "CLAUDE.md"])
        first: dict[str, bytes] = {n: (folder / n).read_bytes() for n in names}
        second = write(folder, "claude,codex,muse")
        self.assertEqual({n: (folder / n).read_bytes() for n in names}, first)
        self.assertNotIn("wrote", second.stdout)
        self.assertNotIn("updated", second.stdout)

    def test_existing_file_keeps_user_content_and_gets_one_block(self) -> None:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-mem-"))
        (folder / "CLAUDE.md").write_text("# My rules\nKeep this.\n", encoding="utf-8")
        write(folder, "claude")
        write(folder, "claude")
        text: str = (folder / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# My rules\nKeep this.\n"))
        self.assertEqual(text.count(START), 1)
        self.assertEqual(text.count(END), 1)
        self.assertIn("proj", text)

    def test_existing_managed_block_is_not_duplicated(self) -> None:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-mem-"))
        body: str = f"intro\n{START}\ncustom\n{END}\n"
        (folder / "AGENTS.md").write_text(body, encoding="utf-8")
        write(folder, "codex")
        self.assertEqual((folder / "AGENTS.md").read_text(encoding="utf-8"), body)

    def test_handoff_pointer_is_in_the_seed(self) -> None:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-mem-"))
        write(folder, "codex")
        text: str = (folder / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".harness/handoff/latest.md", text)

    def test_not_a_directory_exits_one(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--write", "/nonexistent-dts2-dir"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
