"""Tests for agent profiles and scripts/roster.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, run_script

PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
PROFILE_NAMES: Final[tuple[str, ...]] = (
    "claude", "codex", "gemini", "opencode", "copilot", "cursor", "antigravity", "grok",
)
SCHEMA_KEYS: Final[frozenset[str]] = frozenset({
    "name", "displayName", "form", "rulesFile", "invocation", "command",
    "headlessFlag", "roles", "specialty", "verified",
    "costTier", "statusCommand", "models", "modelsVerified",
    "subscriptionName", "apiKeyEnv",
})
VERIFIED: Final[frozenset[str]] = frozenset({"claude", "codex", "gemini", "opencode"})
COST_TIERS: Final[dict[str, int]] = {
    "claude": 3, "codex": 2, "gemini": 1, "opencode": 1,
    "copilot": 2, "cursor": 2, "antigravity": 2, "grok": 2,
}
MODEL_TIERS: Final[tuple[str, ...]] = ("frontier", "standard", "economy")
LIVE_AGENTS: Final[frozenset[str]] = frozenset({"claude", "codex", "gemini", "opencode", "copilot", "grok"})
ROSTER: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"


def write_config(text: str) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-roster-"))
    path: Path = folder / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def raw_run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(ROSTER), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env=env,
    )


class ProfileTests(unittest.TestCase):
    def test_every_profile_has_schema(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(set(data), SCHEMA_KEYS, name)
            self.assertEqual(data["name"], name)
            self.assertEqual(data["verified"], name in VERIFIED, name)

    def test_claude_roles(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "claude.json").read_text())
        self.assertIn("lead", data["roles"])
        self.assertIn("verifier", data["roles"])

    def test_ide_profiles_are_handoff(self) -> None:
        for name in ("cursor", "antigravity"):
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["invocation"], "handoff")
            self.assertIsNone(data["command"])


class ProfileExtensionTests(unittest.TestCase):
    def test_cost_tiers_and_model_keys(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["costTier"], COST_TIERS[name], name)
            self.assertEqual(set(data["models"]), set(MODEL_TIERS), name)
            self.assertIsInstance(data["modelsVerified"], bool)
            self.assertEqual(data["modelsVerified"], name == "claude", name)

    def test_status_commands(self) -> None:
        expected: dict[str, Any] = {
            "claude": ["claude", "auth", "status"], "codex": ["codex", "login", "status"],
            "gemini": ["gemini", "--version"], "opencode": ["opencode", "--version"],
            "copilot": ["gh", "auth", "status"], "grok": ["grok", "--version"],
            "cursor": None, "antigravity": None,
        }
        for name, command in expected.items():
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["statusCommand"], command, name)

    def test_grok_profile(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "grok.json").read_text())
        self.assertEqual(data["form"], "cli")
        self.assertEqual(data["rulesFile"], "AGENTS.md")
        self.assertEqual(data["invocation"], "live")
        self.assertEqual(data["command"], ["grok"])
        self.assertIsNone(data["headlessFlag"])
        self.assertEqual(data["roles"], ["second-opinion"])
        self.assertFalse(data["verified"])


class ModelTests(unittest.TestCase):
    def model(self, agent: str, tier: str) -> str:
        return raw_run("model", "--agent", agent, "--tier", tier).stdout.strip()

    def test_claude_models(self) -> None:
        self.assertEqual(self.model("claude", "frontier"), "opus")
        self.assertEqual(self.model("claude", "standard"), "sonnet")
        self.assertEqual(self.model("claude", "economy"), "haiku")

    def test_null_model(self) -> None:
        self.assertEqual(self.model("cursor", "frontier"), "null")

    def test_grok_model(self) -> None:
        self.assertEqual(self.model("grok", "economy"), "grok-4-fast")


def fake_bin(names: list[str]) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-fake-"))
    for name in names:
        script: Path = folder / name
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
    return str(folder)


def probe(config_text: str, path: str) -> dict[str, Any]:
    env: dict[str, str] = {"PATH": path, "DTS2_PROBE_PATH": path}
    cfg: str = write_config(config_text)
    result = raw_run("probe", "--config", cfg, env=env)
    return json.loads(result.stdout)


ALL_LIVE_ROSTER: Final[str] = (
    "roster:\n" + "".join(f"  - name: {n}\n" for n in sorted(LIVE_AGENTS))
)


class ProbeTests(unittest.TestCase):
    def test_empty_path_drops_everything(self) -> None:
        data: dict[str, Any] = probe(ALL_LIVE_ROSTER, tempfile.mkdtemp(prefix="dts2-path-"))
        self.assertEqual(data["usable"], [])
        self.assertEqual({d["name"] for d in data["dropped"]}, set(LIVE_AGENTS))
        for dropped in data["dropped"]:
            self.assertEqual(dropped["reason"], "not installed")

    def test_fake_codex_available(self) -> None:
        data: dict[str, Any] = probe("roster:\n  - name: codex\n", fake_bin(["codex"]))
        entry: dict[str, Any] = data["agents"]["codex"]
        self.assertTrue(entry["available"])
        self.assertEqual(entry["budget"], "unknown")
        self.assertEqual(entry["costTier"], 2)
        self.assertEqual(data["usable"], ["codex"])
        self.assertEqual(entry["roles"], ["builder", "second-opinion"])

    def test_low_budget_second_opinion_only(self) -> None:
        cfg: str = "roster:\n  - name: codex\nbudget:\n  codex:\n    status: low\n"
        data: dict[str, Any] = probe(cfg, fake_bin(["codex"]))
        entry: dict[str, Any] = data["agents"]["codex"]
        self.assertEqual(entry["budget"], "low")
        self.assertEqual(entry["roles"], ["second-opinion"])
        self.assertIn("codex", data["usable"])

    def test_exhausted_budget_dropped(self) -> None:
        cfg: str = "roster:\n  - name: codex\nbudget:\n  codex:\n    status: exhausted\n"
        data: dict[str, Any] = probe(cfg, fake_bin(["codex"]))
        self.assertEqual(data["usable"], [])
        self.assertEqual(data["dropped"], [{"name": "codex", "reason": "budget exhausted"}])

    def test_ide_agent_available_without_command(self) -> None:
        data: dict[str, Any] = probe("roster:\n  - name: cursor\n", tempfile.mkdtemp())
        self.assertEqual(data["usable"], ["cursor"])

    def test_failing_status_command_dropped(self) -> None:
        folder: str = fake_bin([])
        script: Path = Path(folder) / "codex"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        data: dict[str, Any] = probe("roster:\n  - name: codex\n", folder)
        self.assertEqual(data["dropped"][0]["reason"], "status check failed")


class CostOrderTests(unittest.TestCase):
    def test_cost_order_ascending(self) -> None:
        cfg: str = write_config("roster:\n  - name: claude\n  - name: gemini\n  - name: codex\n")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["costOrder"], ["gemini", "codex", "claude"])


class DetectTests(unittest.TestCase):
    def test_empty_path_is_claude_only(self) -> None:
        empty: str = tempfile.mkdtemp(prefix="dts2-path-")
        project: str = tempfile.mkdtemp(prefix="dts2-proj-")
        result = raw_run("detect", "--project", project, env={"PATH": empty})
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude"])
        self.assertTrue(data["claudeOnly"])

    def test_fake_binary_and_ide_marker(self) -> None:
        bindir: Path = Path(tempfile.mkdtemp(prefix="dts2-bin-"))
        fake: Path = bindir / "codex"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        project: Path = Path(tempfile.mkdtemp(prefix="dts2-proj-"))
        (project / ".cursor").mkdir()
        result = raw_run("detect", "--project", str(project), env={"PATH": str(bindir)})
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude", "codex", "cursor"])
        self.assertFalse(data["claudeOnly"])


class ResolveTests(unittest.TestCase):
    def test_no_roster_is_claude_on_all_roles(self) -> None:
        missing: str = str(Path(tempfile.mkdtemp()) / "nope.yaml")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", missing)
        self.assertEqual(data["enabled"], ["claude"])
        for role in ("lead", "verifier", "builder", "reviewer"):
            self.assertEqual(data["assignments"][role], ["claude"])
        self.assertEqual(data["handoff"], [])
        self.assertEqual(data["live"], ["claude"])

    def test_cursor_builder_is_handoff(self) -> None:
        cfg: str = write_config(
            "roster:\n  - name: claude\n  - name: cursor\n    roles: [builder]\n"
        )
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["handoff"], ["cursor"])
        self.assertEqual(data["live"], ["claude"])
        self.assertIn("cursor", data["assignments"]["builder"])

    def test_cursor_lead_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: cursor\n    roles: [lead]\n")
        result = raw_run("resolve", "--config", cfg)
        self.assertEqual(result.returncode, 1)
        self.assertIn("lead", result.stderr + result.stdout)

    def test_unknown_agent_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: nonesuch\n")
        self.assertEqual(raw_run("resolve", "--config", cfg).returncode, 1)

    def test_config_without_roster_block(self) -> None:
        cfg: str = write_config("other: 1\n")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["enabled"], ["claude"])


if __name__ == "__main__":
    unittest.main()
