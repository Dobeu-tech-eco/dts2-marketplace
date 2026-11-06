"""D74: every son in a 3.11.0 autopilot run parked before building. Three causes, one test class each."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

SCRIPTS: Final[Path] = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import guard  # noqa: E402
import son_launch  # noqa: E402

PREFIX: Final[str] = "dts2/s/lane-a"
LANES: Final[str] = str(SCRIPTS / "lanes.py")


def bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def deny(command: str) -> str | None:
    return guard.son_denial(bash(command), PREFIX)


class HarnessScriptExecTests(unittest.TestCase):
    """Cause 1: python3 counts as a write command, and the plugin's own path contains `.claude/`."""

    def test_running_a_harness_script_by_absolute_path_is_allowed(self) -> None:
        for command in (f'python3 -I "{LANES}" status s', f"python3 -I {LANES} heartbeat s --lane a",
                        f"python3 {SCRIPTS / 'checks.py'} --repo .", f"/usr/bin/python3 -I {LANES} reconcile s"):
            self.assertIsNone(deny(command), command)

    def test_the_plugin_path_really_contains_dot_claude_in_an_install(self) -> None:
        installed: str = "/Users/u/.claude/plugins/cache/dts2/dts2-harness/3.11.0/scripts/lanes.py"
        self.assertTrue(guard.is_protected_write(installed))  # the rule that used to fire
        self.assertFalse(guard.is_harness_script(installed))  # not this checkout's scripts/, so no exemption

    def test_writing_into_dot_claude_is_still_denied(self) -> None:
        for command in (f"python3 -I {LANES} status s > .claude/settings.json",
                        f"python3 -I {LANES} export .claude/settings.local.json",
                        "python3 .claude/hooks/evil.py", "python3 -c 'x' .claude/settings.json",
                        "cp x .claude/settings.json"):
            self.assertIsNotNone(deny(command), command)

    def test_a_lookalike_outside_the_plugin_is_not_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake: Path = Path(tmp) / ".claude" / "scripts" / "lanes.py"
            self.assertFalse(guard.is_harness_script(str(fake)))
            self.assertIsNotNone(deny(f"python3 -I {fake}"))

    def test_merge_granting_commands_stay_denied(self) -> None:
        self.assertIsNotNone(deny(f"python3 -I {LANES} merge-go m.json --lane a --head abc"))

    def test_interpreter_script_parsing(self) -> None:
        self.assertEqual(guard.interpreter_script(["python3", "-I", "a.py", "x"]), "a.py")
        self.assertIsNone(guard.interpreter_script(["python3", "-c", "print(1)"]))
        self.assertIsNone(guard.interpreter_script(["python3", "-m", "unittest"]))
        self.assertIsNone(guard.interpreter_script(["cp", "a", "b"]))


class SonEnvTests(unittest.TestCase):
    """Causes 2 and 3: CLAUDE_PLUGIN_ROOT missing, pnpm store and lock outside the writable paths."""

    def setUp(self) -> None:
        self.root: Path = Path(tempfile.mkdtemp())
        self.env: dict[str, str] = son_launch.lane_env({"stamp": "s", "lanes": [{"id": "a"}]}, "a", self.root)

    def test_plugin_root_is_set_to_this_plugin(self) -> None:
        self.assertEqual(Path(self.env["CLAUDE_PLUGIN_ROOT"]), SCRIPTS.parent)
        self.assertTrue((Path(self.env["CLAUDE_PLUGIN_ROOT"]) / "scripts" / "lanes.py").is_file())

    def test_pnpm_store_and_state_live_in_a_sandbox_writable_path(self) -> None:
        allow, _deny = son_launch.write_scope({"stamp": "s", "lanes": [{"id": "a"}]}, "a", self.root, self.root)
        for key in ("npm_config_store_dir", "pnpm_config_store_dir", "npm_config_state_dir", "pnpm_config_state_dir"):
            value: Path = Path(self.env[key])
            self.assertTrue(any(value.is_relative_to(Path(a)) for a in allow), f"{key}={value} not under {allow}")

    def test_son_env_keeps_plugin_root_after_the_allowlist(self) -> None:
        env = son_launch.son_env({"stamp": "s", "lanes": [{"id": "a"}]}, "a", self.root, source={"PATH": "/bin"})
        self.assertIn("CLAUDE_PLUGIN_ROOT", env)


if __name__ == "__main__":
    unittest.main()
