"""Follow-up fixes for per-agent rules: roster aliases keep their rules, launch keys are gated, second-opinion read-only,
paths_deny normalisation, project profiles may not set home/key fields, and exec honours --workspace."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT, isolate_agent_status

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import agent_rules  # noqa: E402
import policy_gate  # noqa: E402
import roster  # noqa: E402
import state_io  # noqa: E402
from profiles import USER_AGENTS_ENV, Profiles  # noqa: E402

ALIAS_CONFIG: Final[str] = "project: demo\nroster:\n  - name: scout\n    profile: grok\n    auth: api-key\n    roles: [reviewer, second-opinion]\n"


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-fixes-")).resolve()
        self.home = self.root / "home-agents"
        self.project = self.root / "repo"
        self.config = self.project / state_io.CONFIG_REL
        patcher = mock.patch.dict(os.environ, {USER_AGENTS_ENV: str(self.home), "XAI_API_KEY": "sk-test-FAKE0123456789abcdefghij"})
        patcher.start()
        self.addCleanup(patcher.stop)
        isolate_agent_status(self)
        write(self.config, ALIAS_CONFIG)

    def alias(self) -> dict[str, Any]:
        profile = roster.agent_profile("scout", self.config)
        assert profile is not None
        return profile


class AliasTests(Base):
    def test_alias_carries_roster_name_and_rules(self) -> None:
        profile = self.alias()
        self.assertEqual(profile["name"], "scout")
        rules, _ = roster.launch_rules(profile, self.project)
        self.assertIs(rules.get("read_only"), True)
        env = roster.clean_env(profile, workspace=self.project)
        self.assertEqual(env["DTS2_AGENT"], "scout")

    def test_alias_keeps_underlying_binary(self) -> None:
        result = roster.resolve_command(self.alias(), "reviewer", "standard", None, self.project)
        self.assertEqual(result["agent"], "scout")
        self.assertEqual(result["argv"][0], "grok")

    def test_explicit_rules_override_is_honoured(self) -> None:
        write(self.config, ALIAS_CONFIG + "    rules:\n      max_tier: frontier\n")
        rules, _ = roster.launch_rules(self.alias(), self.project)
        self.assertEqual(rules["max_tier"], "frontier")


class ReadOnlyTests(Base):
    def test_second_opinion_resolves_read_only(self) -> None:
        profile = dict(self.alias())
        profile["readOnlyRoles"] = ["reviewer"]
        profile["readOnlyCommand"] = None
        profile.pop("readOnlyCommand")
        profile["roleCommands"] = {k: v for k, v in (profile.get("roleCommands") or {}).items() if k not in roster.READ_ONLY_KEYS}
        template = roster.read_only_template(profile, "second-opinion")
        self.assertEqual(template, roster.role_template(profile, "second-opinion"))


class PathsDenyTests(unittest.TestCase):
    def test_dotdot_and_dot_prefix_normalised(self) -> None:
        cwd = Path(tempfile.mkdtemp(prefix="dts2-paths-")).resolve()
        for raw in ("src/../infra/main.tf", "./infra/main.tf"):
            rel = policy_gate.relative_path(raw, cwd)
            self.assertEqual(rel, "infra/main.tf")
            self.assertIsNotNone(agent_rules.path_denied(rel, ["infra/**"]))

    def test_outside_path_is_returned_as_is(self) -> None:
        cwd = Path(tempfile.mkdtemp(prefix="dts2-paths-")).resolve()
        self.assertEqual(policy_gate.relative_path("/etc/passwd", cwd), "/etc/passwd")
        self.assertEqual(policy_gate.relative_path("../outside/x", cwd), "../outside/x")


class UntrustedKeysTests(Base):
    KEYS: Final[dict[str, Any]] = {
        "readOnlyCommand": ["touch", "x"], "readOnlyRoles": ["builder"], "budgetFlag": "--evil",
        "homeEnv": "HOME", "homeFiles": {"a": "b"}, "apiKeyRef": "env:EVIL",
    }

    def load(self) -> Profiles:
        return Profiles.load(project=self.project)

    def test_untrusted_project_profile_is_stripped(self) -> None:
        write(self.project / ".harness" / "agents" / "grok.json", {"name": "grok", **self.KEYS})
        grok = self.load().get("grok") or {}
        for key in self.KEYS:
            self.assertNotEqual(grok.get(key), self.KEYS[key], key)

    def test_trusted_project_keeps_them(self) -> None:
        write(self.project / ".harness" / "agents" / "grok.json", {"name": "grok", **self.KEYS})
        write(self.home.parent / "trusted-projects", f"{self.project.resolve()}\n")
        grok = self.load().get("grok") or {}
        for key in self.KEYS:
            self.assertEqual(grok.get(key), self.KEYS[key], key)


class ExecWorkspaceTests(Base):
    def test_exec_uses_workspace_project_profile_and_alias(self) -> None:
        write(self.project / ".harness" / "agents" / "grok.json", {"name": "grok", "apiKeyRef": "env:MY_GROK_KEY"})
        write(self.home.parent / "trusted-projects", f"{self.project.resolve()}\n")
        prompt = self.root / "prompt.txt"
        prompt.write_text("hi", encoding="utf-8")
        seen: dict[str, Any] = {}

        def fake(profile: dict[str, Any], clean: dict[str, str]) -> tuple[dict[str, str], str]:
            seen["profile"] = profile
            raise roster.api_keys.KeyMissing("stop")

        other = self.root / "elsewhere"
        other.mkdir()
        cwd = os.getcwd()
        os.chdir(other)
        try:
            with mock.patch.object(roster, "launch_env", fake), mock.patch.object(roster, "refuse", lambda m: 2):
                with mock.patch.object(roster, "resolve_binary", lambda *a, **k: "/bin/true"):
                    roster.run_exec("scout", "reviewer", "standard", str(prompt), str(self.project), None)
        finally:
            os.chdir(cwd)
        self.assertEqual(seen["profile"]["apiKeyRef"], "env:MY_GROK_KEY")
        self.assertEqual(seen["profile"]["name"], "scout")


class ProtectedProfileTests(Base):
    def test_untrusted_override_of_a_key_agent_is_dropped(self) -> None:
        write(self.project / ".harness" / "agents" / "g.json", {
            "name": "grok-api", "auth": "subscription", "apiKeyRef": "env:GH_TOKEN", "leadEligible": True,
            "keyRequired": False, "homeEnv": "PYTHONPATH", "homeFiles": {"x": "y"}, "defaultModel": "evil", "displayName": "Mine"})
        loaded = Profiles.load(project=self.project)
        grok = loaded.get("grok-api") or {}
        bundled = Profiles.load().get("grok-api") or {}
        for key in ("auth", "apiKeyRef", "leadEligible", "keyRequired", "homeEnv", "homeFiles", "defaultModel", "displayName"):
            self.assertEqual(grok.get(key), bundled.get(key), key)
        self.assertNotIn("grok-api", loaded.lead_eligible())
        self.assertTrue(any("grok-api" in w for w in loaded.warnings))


class KeyAgentAuthTests(Base):
    def test_subscription_entry_on_a_key_profile_keeps_rules(self) -> None:
        write(self.config, "roster:\n  - name: grok-api\n    auth: subscription\n")
        profile = roster.agent_profile("grok-api", self.config)
        assert profile is not None
        rules, _ = roster.launch_rules(profile, self.project)
        self.assertIs(rules.get("read_only"), True)
        self.assertEqual(roster.key_agent_auth(profile, self.config), "api-key")

    def test_gate_profile_auth_is_api_key(self) -> None:
        write(self.config, "roster:\n  - name: grok-api\n    auth: subscription\n")
        self.assertEqual(policy_gate.agent_profile_auth("grok-api", self.project), "api-key")
        with mock.patch.dict(os.environ, {"DTS2_AGENT": "grok-api"}):
            self.assertIn("read-only", policy_gate.decide({"tool_name": "Write", "tool_input": {"file_path": "a.py"}}, self.project) or "")


class GateEdgeTests(Base):
    def test_key_agent_missing_from_roster_gets_default_rules(self) -> None:
        write(self.config, "roster:\n  - name: claude\n")
        with mock.patch.dict(os.environ, {"DTS2_AGENT": "grok-api"}):
            self.assertIn("read-only", policy_gate.decide({"tool_name": "Write", "tool_input": {"file_path": "a.py"}}, self.project) or "")

    def test_unknown_non_key_agent_is_not_restricted(self) -> None:
        write(self.config, "roster:\n  - name: claude\n")
        with mock.patch.dict(os.environ, {"DTS2_AGENT": "claude"}):
            self.assertIsNone(policy_gate.decide({"tool_name": "Write", "tool_input": {"file_path": "a.py"}}, self.project))

    def test_unreadable_config_denies_a_limited_agent(self) -> None:
        self.config.write_bytes(b"roster:\n  - name: grok-api\n\xff\xfe\x00")
        with mock.patch.dict(os.environ, {"DTS2_AGENT": "grok-api"}):
            self.assertIsNotNone(policy_gate.decide({"tool_name": "Write", "tool_input": {"file_path": "a.py"}}, self.project))


class CommandRedactionTests(Base):
    def test_no_key_text_in_resolved_command(self) -> None:
        write(self.config, "roster:\n  - name: grok\n    auth: api-key\n")
        prompt = self.root / "p.txt"
        prompt.write_text("x", encoding="utf-8")
        for name in ("grok", "grok-api"):
            profile = roster.agent_profile(name, self.config)
            assert profile is not None
            text = json.dumps(roster.resolve_command(profile, "reviewer", "standard", prompt, self.project))
            self.assertNotIn("FAKE0123456789", text, name)


class ExecGuardTests(Base):
    def run_exec(self) -> tuple[int, str]:
        import contextlib
        import io
        prompt = self.root / "p.txt"
        prompt.write_text("x", encoding="utf-8")
        err = io.StringIO()
        with mock.patch.object(roster, "resolve_binary", lambda *a, **k: "/bin/true"), contextlib.redirect_stderr(err):
            code = roster.run_exec("scout", "reviewer", "standard", str(prompt), str(self.project), None)
        return code, err.getvalue()

    def test_exhausted_day_refuses(self) -> None:
        write(self.config, ALIAS_CONFIG + "    rules:\n      max_cost_usd_per_day: 1\n")
        agent_rules.record_spend("scout", 2.0, "", self.project)
        code, err = self.run_exec()
        self.assertEqual(code, 2)
        self.assertIn("daily", err)

    def test_tier_above_max_refuses(self) -> None:
        write(self.config, ALIAS_CONFIG + "    rules:\n      max_tier: economy\n")
        code, err = self.run_exec()
        self.assertEqual(code, 2)
        self.assertIn("max_tier", err)


class ForcedAuthTests(Base):
    def test_key_profile_is_api_key_whatever_the_entry_says(self) -> None:
        write(self.config, "roster:\n  - name: grok-api\n    auth: subscription\n")
        profile = roster.agent_profile("grok-api", self.config)
        assert profile is not None
        entry = next(item for item in roster.read_roster(self.config) if item["name"] == "grok-api")
        self.assertEqual(roster.auth_for_entry(entry, profile), "api-key")
        rules, _ = roster.launch_rules(profile, self.project)
        self.assertIs(rules["read_only"], True)
        for task in ("deploy", "merge", "release"):
            self.assertFalse(agent_rules.permits(rules, task)[0], task)
        self.assertEqual(roster._forced_auth(profile, "subscription"), "api-key")
        self.assertEqual(roster._forced_auth({"name": "x"}, None), "subscription")
        self.assertEqual(roster._forced_auth({"name": "x"}, "api-key"), "api-key")


class PluginRootTests(Base):
    def test_claude_api_argv_loads_the_plugin(self) -> None:
        write(self.config, "roster:\n  - name: claude-api\n")
        profile = roster.agent_profile("claude-api", self.config)
        assert profile is not None
        root = str(PLUGIN_ROOT.resolve())
        for role in ("reviewer", "builder"):
            argv = roster.resolve_command(profile, role, "standard", None, self.project)["argv"]
            self.assertEqual(argv[argv.index("--plugin-dir") + 1], root, role)
        read_only = roster.resolve_command(profile, "reviewer", "standard", None, self.project)["argv"]
        self.assertIn("--plugin-dir", read_only)
        for template in [*profile["roleCommands"].values(), profile["command"], profile["readOnlyCommand"]]:
            self.assertIn("{pluginRoot}", template)


if __name__ == "__main__":
    unittest.main()
