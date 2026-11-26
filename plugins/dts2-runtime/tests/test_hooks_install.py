"""scripts/hooks_install.py (per-agent hook installer) and the hook scripts running without CLAUDE_PLUGIN_ROOT."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "hooks_install.py"
HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"
AGENTS: Final[tuple[str, ...]] = ("claude", "codex", "cursor", "antigravity", "grok", "muse")
# Project-scope config path per agent, relative to --repo.
PROJECT_PATHS: Final[dict[str, tuple[str, ...]]] = {
    "claude": (".claude", "settings.local.json"), "codex": (".codex", "hooks.json"), "cursor": (".cursor", "hooks.json"),
    "antigravity": (".agents", "hooks.json"), "grok": (".grok", "hooks", "dts2.json"), "muse": (".muse", "hooks.json"),
}
HAVE_BASH: Final[bool] = shutil.which("bash") is not None


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def run_json(*args: str) -> dict[str, Any]:
    result = run(*args)
    assert result.returncode == 0, result.stderr + result.stdout
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def commands_in(doc: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for entries in (doc.get("hooks") or {}).values():
        for entry in entries:
            if "command" in entry:
                found.append(entry["command"])
            for hook in entry.get("hooks", []):
                found.append(hook["command"])
    return found


class HooksInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.home = Path(self._tmp.name) / "home"
        self.repo.mkdir()
        self.home.mkdir()

    def args(self, agent: str, *extra: str) -> list[str]:
        return ["--agent", agent, "--repo", str(self.repo), "--home", str(self.home), *extra]

    def config(self, agent: str) -> Path:
        return self.repo.joinpath(*PROJECT_PATHS[agent])

    def load(self, agent: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.config(agent).read_text(encoding="utf-8"))
        return loaded

    def test_install_each_agent_uses_absolute_paths(self) -> None:
        for agent in AGENTS:
            with self.subTest(agent=agent):
                out = run_json(*self.args(agent))["results"][0]
                self.assertEqual(out["action"], "created")
                self.assertTrue(self.config(agent).is_file())
                commands = commands_in(self.load(agent))
                self.assertTrue(commands)
                for command in commands:
                    self.assertNotIn("CLAUDE_PLUGIN_ROOT", command)
                    self.assertIn(PLUGIN_ROOT.as_posix() + "/hooks/", command)

    def test_event_mapping_and_skips(self) -> None:
        run_json(*self.args("cursor"))
        cursor = self.load("cursor")
        self.assertEqual(cursor["version"], 1)
        self.assertIn("beforeSubmitPrompt", cursor["hooks"])
        self.assertIn("preToolUse", cursor["hooks"])
        self.assertNotIn("PostToolBatch", cursor["hooks"])
        out = run_json(*self.args("claude", "--dry-run"))["results"][0]
        self.assertEqual(out["skipped"], [])
        out = run_json(*self.args("codex", "--dry-run"))["results"][0]
        self.assertIn("PostToolBatch", {s["event"] for s in out["skipped"]})
        self.assertFalse(self.config("codex").exists())

    def test_claude_keeps_if_filters_and_groups(self) -> None:
        run_json(*self.args("claude"))
        text = self.config("claude").read_text(encoding="utf-8")
        self.assertIn('"if": "Bash(gh pr create *)"', text)
        self.assertIn('"matcher": "dt:builder|dt:reviewer|dt:verifier"', text)
        run_json(*self.args("codex"))
        self.assertNotIn('"if"', self.config("codex").read_text(encoding="utf-8"))
        self.assertNotIn("dt:builder", self.config("codex").read_text(encoding="utf-8"))

    def test_idempotent(self) -> None:
        for agent in AGENTS:
            with self.subTest(agent=agent):
                run_json(*self.args(agent))
                first = self.config(agent).read_bytes()
                out = run_json(*self.args(agent))["results"][0]
                self.assertEqual(out["action"], "unchanged")
                self.assertFalse(out["wrote"])
                self.assertEqual(self.config(agent).read_bytes(), first)

    def test_merge_keeps_existing_entries_and_other_keys(self) -> None:
        claude = self.config("claude")
        claude.parent.mkdir(parents=True)
        mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        claude.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [mine], "Notification": [mine]}}), encoding="utf-8")
        cursor = self.config("cursor")
        cursor.parent.mkdir(parents=True)
        theirs = {"command": "./audit.sh"}
        cursor.write_text(json.dumps({"version": 1, "hooks": {"stop": [theirs]}}), encoding="utf-8")
        run_json(*self.args("all"))
        doc = self.load("claude")
        self.assertEqual(doc["model"], "opus")
        self.assertEqual(doc["hooks"]["PreToolUse"][0], mine)
        self.assertEqual(doc["hooks"]["Notification"], [mine])
        self.assertGreater(len(doc["hooks"]["PreToolUse"]), 1)
        self.assertEqual(self.load("cursor")["hooks"]["stop"][0], theirs)
        self.assertGreater(len(self.load("cursor")["hooks"]["stop"]), 1)

    def test_rerun_after_user_adds_entry_changes_nothing_else(self) -> None:
        run_json(*self.args("claude"))
        doc = self.load("claude")
        extra = {"hooks": [{"type": "command", "command": "echo later"}]}
        doc["hooks"]["Stop"].append(extra)
        self.config("claude").write_text(json.dumps(doc), encoding="utf-8")
        out = run_json(*self.args("claude"))["results"][0]
        self.assertEqual(out["action"], "unchanged")
        self.assertEqual(self.load("claude")["hooks"]["Stop"][-1], extra)

    def test_uninstall_removes_only_ours(self) -> None:
        claude = self.config("claude")
        claude.parent.mkdir(parents=True)
        mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        claude.write_text(json.dumps({"hooks": {"PreToolUse": [mine]}}), encoding="utf-8")
        run_json(*self.args("all"))
        out = run_json(*self.args("all", "--uninstall"))
        self.assertTrue(all(r["action"] == "removed" for r in out["results"]))
        self.assertEqual(self.load("claude"), {"hooks": {"PreToolUse": [mine]}})
        for agent in AGENTS[1:]:
            self.assertFalse(self.config(agent).exists(), agent)
        again = run_json(*self.args("all", "--uninstall"))
        self.assertTrue(all(r["action"] == "unchanged" for r in again["results"]))

    def test_uninstall_keeps_foreign_hook_inside_shared_group(self) -> None:
        run_json(*self.args("claude"))
        doc = self.load("claude")
        doc["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "echo keep"})
        self.config("claude").write_text(json.dumps(doc), encoding="utf-8")
        run_json(*self.args("claude", "--uninstall"))
        self.assertEqual(commands_in(self.load("claude")), ["echo keep"])

    def test_claude_keeps_every_if_variant_of_one_command(self) -> None:
        run_json(*self.args("claude"))
        text = self.config("claude").read_text(encoding="utf-8")
        for rule in ("Bash(gh pr create *)", "Bash(gh pr edit *)", "Bash(gh api *)"):
            self.assertIn(f'"if": "{rule}"', text)

    def test_user_hook_with_same_script_name_is_not_ours(self) -> None:
        claude = self.config("claude")
        claude.parent.mkdir(parents=True)
        mine = {"hooks": [{"type": "command", "command": "bash ./hooks/session-end.sh"}]}
        claude.write_text(json.dumps({"hooks": {"SessionEnd": [mine]}}), encoding="utf-8")
        run_json(*self.args("claude"))
        self.assertEqual(self.load("claude")["hooks"]["SessionEnd"][0], mine)
        run_json(*self.args("claude", "--uninstall"))
        self.assertEqual(self.load("claude"), {"hooks": {"SessionEnd": [mine]}})

    def test_dry_run_writes_nothing(self) -> None:
        out = run_json(*self.args("all", "--dry-run"))
        for result in out["results"]:
            self.assertTrue(result["dryRun"])
            self.assertFalse(result["wrote"])
            self.assertIn("hooks", result["wouldWrite"])
        self.assertEqual(list(self.repo.rglob("*")), [])
        self.assertEqual(list(self.home.rglob("*")), [])

    def test_user_scope_writes_under_home(self) -> None:
        out = run_json(*self.args("claude", "--user"))["results"][0]
        self.assertEqual(out["scope"], "user")
        self.assertTrue((self.home / ".claude" / "settings.json").is_file())
        self.assertEqual(list(self.repo.rglob("*")), [])

    def test_antigravity_project_path_and_events(self) -> None:
        run_json(*self.args("antigravity"))
        doc = json.loads((self.repo / ".agents" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(doc["hooks"]), {"PreInvocation", "PreToolUse"})
        self.assertFalse((self.repo / ".agent").exists())

    def test_antigravity_user_path(self) -> None:
        out = run_json(*self.args("antigravity", "--user"))["results"][0]
        self.assertEqual(Path(out["path"]), self.home / ".gemini" / "config" / "hooks.json")
        self.assertTrue(Path(out["path"]).is_file())

    def test_muse_user_scope_is_a_block_in_settings_json(self) -> None:
        settings = self.home / ".config" / "muse" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        run_json(*self.args("muse", "--user"))
        doc = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(doc["theme"], "dark")
        self.assertEqual(doc["schema_version"], 1)
        self.assertTrue(commands_in(doc))
        run_json(*self.args("muse", "--user", "--uninstall"))
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), {"theme": "dark", "schema_version": 1})

    def test_unknown_agent_refused(self) -> None:
        result = run("--agent", "emacs", "--repo", str(self.repo))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.repo.rglob("*")), [])

    def test_invalid_json_is_not_overwritten(self) -> None:
        path = self.config("codex")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        result = run(*self.args("codex"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")


@unittest.skipUnless(HAVE_BASH, "bash is not installed")
class HookScriptsWithoutPluginRootTests(unittest.TestCase):
    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
        env.pop("CLAUDE_PROJECT_DIR", None)
        return env

    def test_roadmap_lock_runs_with_empty_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(["bash", str(HOOKS / "roadmap-lock.sh")], input="", capture_output=True, text=True,
                                    cwd=cwd, env=self.env(), check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_script_requires_the_plugin_variable(self) -> None:
        for script in sorted(HOOKS.glob("*.sh")):
            if script.name == "lib-settings.sh":
                continue
            with self.subTest(script=script.name):
                text = script.read_text(encoding="utf-8")
                self.assertNotIn('[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0', text)
                self.assertNotIn("${CLAUDE_PLUGIN_ROOT}/", text)


if __name__ == "__main__":
    unittest.main()
