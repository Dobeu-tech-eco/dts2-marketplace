"""A stray API key in the parent shell never bills a Max agent (batch B): the one scrubbed child-env builder."""
from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import roster  # noqa: E402
import son_launch  # noqa: E402

FAKE: Final[str] = "sk-test-FAKE"
SOURCE: Final[dict[str, str]] = {
    "PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "GH_TOKEN": "g",
    "ANTHROPIC_API_KEY": FAKE, "ANTHROPIC_AUTH_TOKEN": FAKE, "ANTHROPIC_BASE_URL": "https://proxy.invalid",
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-FAKE", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1",
    "CODEX_API_KEY": FAKE, "OPENAI_API_KEY": FAKE, "XAI_API_KEY": FAKE, "GEMINI_API_KEY": FAKE,
    "AWS_ACCESS_KEY_ID": "a", "GOOGLE_APPLICATION_CREDENTIALS": "/c.json", "DTS2_MARK": "1",
}
KEYS: Final[frozenset[str]] = frozenset(k for k in SOURCE if son_launch.credential_name(k))


class SubscriptionTests(unittest.TestCase):
    def test_claude_subscription_keeps_oauth_and_drops_every_key(self) -> None:
        env = son_launch.scrub_env(SOURCE)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "oauth-FAKE")
        self.assertEqual({k for k in env if son_launch.credential_name(k)}, set())
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["DTS2_MARK"], "1")

    def test_bedrock_and_vertex_switches_are_stripped(self) -> None:
        env = son_launch.scrub_env(SOURCE)
        self.assertFalse({"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"} & set(env))

    def test_son_env_never_carries_a_stray_anthropic_key(self) -> None:
        manifest = {"stamp": "s", "lanes": [{"id": "a"}]}
        env = son_launch.son_env(manifest, "a", Path("/tmp"), source=SOURCE)
        self.assertFalse({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"} & set(env))
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_codex_child_gets_no_anthropic_key_and_no_claude_token(self) -> None:
        env = son_launch.provider_env(SOURCE, claude=False)
        self.assertFalse(KEYS & set(env))
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_codex_clean_env_from_roster_is_keyless_by_default(self) -> None:
        with unittest.mock.patch.dict(os.environ, SOURCE, clear=True):
            env = roster.clean_env(roster.load_profiles()["codex"], auth="subscription")
        self.assertFalse(KEYS & set(env))


class ApiKeyTests(unittest.TestCase):
    def test_api_key_agent_gets_only_its_own_key(self) -> None:
        env = son_launch.scrub_env(SOURCE, auth="api-key", key_env="CODEX_API_KEY", claude=False)
        self.assertEqual({k for k in env if son_launch.credential_name(k)}, {"CODEX_API_KEY"})

    def test_claude_api_key_agent_drops_the_max_token(self) -> None:
        env = son_launch.scrub_env(SOURCE, auth="api-key", key_env="ANTHROPIC_API_KEY", claude=True)
        self.assertEqual({k for k in env if son_launch.credential_name(k)}, {"ANTHROPIC_API_KEY"})
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_unset_key_env_adds_nothing(self) -> None:
        env = son_launch.scrub_env({"PATH": "/bin"}, auth="api-key", key_env="CODEX_API_KEY", claude=False)
        self.assertEqual(env, {"PATH": "/bin"})

    def test_roster_clean_env_follows_declared_auth(self) -> None:
        with unittest.mock.patch.dict(os.environ, SOURCE, clear=True):
            env = roster.clean_env(roster.load_profiles()["codex"], auth="api-key")
        self.assertEqual({k for k in env if son_launch.credential_name(k)}, {"CODEX_API_KEY"})

    def test_codex_profile_reads_codex_api_key(self) -> None:
        profile = roster.load_profiles()["codex"]
        self.assertEqual(profile["apiKeyEnv"], "CODEX_API_KEY")
        self.assertTrue(roster.has_api_key(profile, {"CODEX_API_KEY": FAKE}))
        self.assertFalse(roster.has_api_key(profile, {"OPENAI_API_KEY": FAKE}))


class EscapeHatchTests(unittest.TestCase):
    def test_env_pass_hands_a_named_variable_to_a_son(self) -> None:
        source = {**SOURCE, son_launch.PASS_VAR: "ANTHROPIC_API_KEY"}
        env = son_launch.scrub_env(source)
        self.assertEqual(env["ANTHROPIC_API_KEY"], FAKE)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_env_pass_pattern_matches_a_family(self) -> None:
        env = son_launch.scrub_env({**SOURCE, son_launch.PASS_VAR: "XAI_*, FAKE_*"})
        self.assertIn("XAI_API_KEY", env)
        self.assertNotIn("CODEX_API_KEY", env)


class SecretShapedTests(unittest.TestCase):
    def test_detects_key_shapes(self) -> None:
        for text in ("sk-" + "a" * 24, "sk-ant-" + "b" * 12, "xai-" + "c" * 24, "ghp_" + "d" * 36):
            self.assertTrue(son_launch.secret_shaped(f"token={text}"), text)

    def test_plain_text_and_short_fakes_pass(self) -> None:
        for text in ("api-key:CODEX_API_KEY", "subscription", "task-1234", "sk-test-FAKE"):
            self.assertFalse(son_launch.secret_shaped(text), text)


if __name__ == "__main__":
    unittest.main()
