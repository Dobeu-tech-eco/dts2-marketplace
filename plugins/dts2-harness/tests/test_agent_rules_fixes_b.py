"""Batch 54 (fixes B): no_secrets by default, key agents always restricted, SDK second opinion keeps subscription billing."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import agent_rules  # noqa: E402


def load_sdk() -> Any:
    spec = importlib.util.spec_from_file_location("dts2_run_fixes_b", PLUGIN_ROOT / "sdk" / "dts2-run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DefaultsTests(unittest.TestCase):
    def test_no_secrets_is_a_default(self) -> None:
        self.assertIs(agent_rules.DEFAULTS["no_secrets"], True)
        rules = agent_rules.effective_rules({"name": "x", "rules": {}}, "api-key")
        self.assertIs(rules["no_secrets"], True)

    def test_an_explicit_false_still_wins(self) -> None:
        rules = agent_rules.effective_rules({"name": "x", "rules": {"no_secrets": "false"}}, "api-key")
        self.assertIs(rules["no_secrets"], False)


class ForcedAuthTests(unittest.TestCase):
    def test_key_required_profile_is_api_key(self) -> None:
        self.assertEqual(agent_rules.forced_auth({"keyRequired": True}, "subscription"), "api-key")
        self.assertEqual(agent_rules.forced_auth({"keyRequired": True}, None), "api-key")

    def test_other_profiles_keep_the_declared_auth(self) -> None:
        self.assertEqual(agent_rules.forced_auth({"keyRequired": False}, "api-key"), "api-key")
        self.assertEqual(agent_rules.forced_auth({}, None), "subscription")
        self.assertEqual(agent_rules.forced_auth(None, None), "subscription")

    def test_subscription_roster_line_for_grok_api_is_still_restricted(self) -> None:
        profile = json.loads((PLUGIN_ROOT / "profiles" / "agents" / "grok-api.json").read_text(encoding="utf-8"))
        entry = {"name": "grok-api", "auth": "subscription"}
        rules = agent_rules.effective_rules(entry, agent_rules.forced_auth(profile, entry["auth"]))
        self.assertIs(rules["read_only"], True)
        for task in ("deploy", "merge", "release"):
            self.assertIn(task, rules["deny_tasks"])


class SecondOpinionBillingTests(unittest.TestCase):
    ENV = {"GH_TOKEN": "g", "ANTHROPIC_API_KEY": "a", "CODEX_API_KEY": "c-FAKE", "XAI_API_KEY": "x-FAKE"}

    def env(self, backend: str) -> dict[str, str]:
        with mock.patch.dict(os.environ, self.ENV):
            return load_sdk().second_opinion_env(None, backend)

    def test_subscription_backends_get_no_provider_key(self) -> None:
        for backend, key in (("codex", "CODEX_API_KEY"), ("grok", "XAI_API_KEY")):
            env = self.env(backend)
            self.assertNotIn(key, env)
            self.assertNotIn("GH_TOKEN", env)

    def test_explicit_api_backends_get_only_their_key(self) -> None:
        codex = self.env("codex-api")
        self.assertEqual(codex["CODEX_API_KEY"], "c-FAKE")
        self.assertNotIn("XAI_API_KEY", codex)
        grok = self.env("grok-api")
        self.assertEqual(grok["XAI_API_KEY"], "x-FAKE")
        self.assertNotIn("CODEX_API_KEY", grok)

    def test_profiles_load_without_the_cwd_project_layer(self) -> None:
        import profiles
        seen: list[Any] = []
        real = profiles.Profiles.load

        def spy(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("project"))
            return real(*args, **kwargs)

        with mock.patch.object(profiles.Profiles, "load", side_effect=spy), mock.patch.dict(os.environ, self.ENV):
            load_sdk().second_opinion_env(None, "codex-api")
        self.assertEqual(seen, [PLUGIN_ROOT])


if __name__ == "__main__":
    unittest.main()
