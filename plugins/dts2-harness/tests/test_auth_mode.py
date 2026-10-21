"""Tests for auth mode: subscription login first, API key by opt-in."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
ROSTER: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"
SETUP: Final[Path] = PLUGIN_ROOT / "skills" / "setup" / "SKILL.md"
SECRET: Final[str] = "sk-test-NEVER-PRINT"
SUBSCRIPTIONS: Final[dict[str, str | None]] = {
    "claude": "Claude Max", "codex": "ChatGPT Pro (Codex)", "gemini": "Gemini Pro",
    "antigravity": "Gemini Pro (Antigravity)", "grok": "Grok Build",
    "copilot": "GitHub Copilot", "opencode": None, "cursor": "Cursor Pro",
}
API_KEY_ENVS: Final[dict[str, str | None]] = {
    "claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "grok": "XAI_API_KEY", "opencode": None, "copilot": None, "cursor": None, "antigravity": None,
}


def fake_codex(status_ok: bool) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-auth-"))
    script: Path = folder / "codex"
    script.write_text(f"#!/bin/sh\nexit {0 if status_ok else 1}\n")
    script.chmod(0o755)
    return str(folder)


def run(args: list[str], path: str, extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env: dict[str, str] = {"PATH": path, "DTS2_PROBE_PATH": path, **extra}
    return subprocess.run(
        [sys.executable, "-I", str(ROSTER), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env=env,
    )


def probe_codex(status_ok: bool, extra: dict[str, str], body: str = "") -> subprocess.CompletedProcess[str]:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-cfg-"))
    config: Path = folder / "config.yaml"
    config.write_text(f"roster:\n  - name: codex\n{body}", encoding="utf-8")
    return run(["probe", "--config", str(config)], fake_codex(status_ok), extra)


def detect_codex(status_ok: bool, extra: dict[str, str]) -> dict[str, Any]:
    project: str = tempfile.mkdtemp(prefix="dts2-proj-")
    result = run(["detect", "--project", project], fake_codex(status_ok), extra)
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


class ProfileKeyTests(unittest.TestCase):
    def test_subscription_and_env_values(self) -> None:
        for name, subscription in SUBSCRIPTIONS.items():
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["subscriptionName"], subscription, name)
            self.assertEqual(data["apiKeyEnv"], API_KEY_ENVS[name], name)


class DetectAuthTests(unittest.TestCase):
    def test_login_wins_over_api_key(self) -> None:
        data = detect_codex(True, {"OPENAI_API_KEY": SECRET})
        self.assertEqual(data["auth"]["codex"], "subscription")

    def test_failed_login_with_key_is_api_key(self) -> None:
        data = detect_codex(False, {"OPENAI_API_KEY": SECRET})
        self.assertEqual(data["auth"]["codex"], "api-key")

    def test_failed_login_without_key_is_none(self) -> None:
        data = detect_codex(False, {})
        self.assertEqual(data["auth"]["codex"], "none")

    def test_empty_key_is_none(self) -> None:
        data = detect_codex(False, {"OPENAI_API_KEY": ""})
        self.assertEqual(data["auth"]["codex"], "none")


class ProbeAuthTests(unittest.TestCase):
    def test_probe_reports_auth(self) -> None:
        out: dict[str, Any] = json.loads(probe_codex(True, {"OPENAI_API_KEY": SECRET}).stdout)
        self.assertEqual(out["agents"]["codex"]["auth"], "subscription")
        out = json.loads(probe_codex(False, {"OPENAI_API_KEY": SECRET}).stdout)
        self.assertEqual(out["agents"]["codex"]["auth"], "api-key")

    def test_included_false_is_dropped(self) -> None:
        out: dict[str, Any] = json.loads(probe_codex(True, {}, "    included: false\n").stdout)
        self.assertIn({"name": "codex", "reason": "excluded by user"}, out["dropped"])
        self.assertNotIn("codex", out["usable"])

    def test_auth_and_included_parsed(self) -> None:
        body: str = "    auth: api-key\n    included: true\n"
        out: dict[str, Any] = json.loads(probe_codex(False, {"OPENAI_API_KEY": SECRET}, body).stdout)
        self.assertIn("codex", out["usable"] + [d["name"] for d in out["dropped"]])

    def test_secret_value_never_printed(self) -> None:
        env: dict[str, str] = {"OPENAI_API_KEY": SECRET, "ANTHROPIC_API_KEY": SECRET}
        for status_ok in (True, False):
            result = probe_codex(status_ok, env)
            self.assertNotIn(SECRET, result.stdout + result.stderr)
            detected = run(["detect", "--project", tempfile.mkdtemp()], fake_codex(status_ok), env)
            self.assertNotIn(SECRET, detected.stdout + detected.stderr)


class SetupTextTests(unittest.TestCase):
    def test_agents_round_wording(self) -> None:
        text: str = SETUP.read_text(encoding="utf-8")
        for phrase in ("pay-per-use", "Include or exclude", "included:", "auth: subscription"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
