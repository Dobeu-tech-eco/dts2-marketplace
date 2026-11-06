"""API agent profiles (batch E): claude-api, codex-api and grok-api, key resolution through api_keys, billing isolation, the
lead and sign-off ban, receipts, the SDK second-opinion env and doctor. Temp dirs and fake binaries only; never the real home
or a real key."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import agent_rules  # noqa: E402
import api_keys  # noqa: E402
import delegate  # noqa: E402
import doctor  # noqa: E402
import failover  # noqa: E402
import roster  # noqa: E402
import son_launch  # noqa: E402
from profiles import PROFILE_DIR, Profiles  # noqa: E402

API: Final[tuple[str, ...]] = ("claude-api", "codex-api", "grok-api")
KEY_VARS: Final[dict[str, str]] = {"claude-api": "ANTHROPIC_API_KEY", "codex-api": "CODEX_API_KEY", "grok-api": "XAI_API_KEY"}
FAKE: Final[str] = "sk-test-FAKE" + "0123456789abcdefghij"
GROK_SHA: Final[str] = "0e24d10a22a0e804c2df4411dc8caee13ef64d8c0cc0fc6672ff8be35d2ecc45"


def script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class ApiCase(unittest.TestCase):
    """A temp home (user agents dir and agents-home under it) and a clean environment with only PATH."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dts2-api-"))
        self.agents = self.tmp / "home" / "agents"
        self.agents.mkdir(parents=True)
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.prompt = self.tmp / "prompt.txt"
        self.prompt.write_text("review this\n", encoding="utf-8")
        self.base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp), "DTS2_USER_AGENTS_DIR": str(self.agents)}
        self.extra: dict[str, str] = {}
        self.set_env({})

    def set_env(self, extra: dict[str, str]) -> None:
        """Add variables to the clean environment (earlier additions stay)."""
        self.extra.update(extra)
        patcher = mock.patch.dict(os.environ, {**self.base, **self.extra}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def profiles(self) -> dict[str, dict[str, Any]]:
        return Profiles.load(project=self.work, user_dir=self.agents).as_dict()

    def user_profile(self, name: str, **fields: Any) -> None:
        (self.agents / f"{name}.json").write_text(json.dumps({"name": name, **fields}), encoding="utf-8")


class ProfileShapeTests(ApiCase):
    def test_three_profiles_load_with_api_key_auth_and_batch_d_defaults(self) -> None:
        profiles = self.profiles()
        for name in API:
            profile = profiles[name]
            self.assertEqual(profile["auth"], "api-key")
            self.assertEqual(profile["apiKeyEnv"], KEY_VARS[name])
            rules = roster.entry_rules({"name": name}, profile)[0]
            self.assertTrue(rules["read_only"])
            self.assertEqual(rules["allow_tasks"], ["review", "docs", "research"])
            self.assertEqual(rules["max_tier"], "standard")
            self.assertEqual(rules["max_cost_usd_per_run"], 0.5)
            self.assertEqual(rules["max_cost_usd_per_day"], 5.0)
            self.assertTrue(set(agent_rules.FORCED_DENY) <= set(rules["deny_tasks"]))

    def test_roles(self) -> None:
        profiles = self.profiles()
        self.assertEqual(set(profiles["claude-api"]["roles"]), {"reviewer", "builder"})
        self.assertIn("second-opinion", profiles["codex-api"]["roles"])
        self.assertEqual(set(profiles["grok-api"]["roles"]), {"reviewer", "reviewer:security"})
        for name in API:
            self.assertFalse({"lead", "signoff", "sign-off"} & set(profiles[name]["roles"]))

    def test_existing_grok_profile_is_unchanged(self) -> None:
        raw = (PROFILE_DIR / "grok.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), GROK_SHA)
        grok = self.profiles()["grok"]
        self.assertEqual(grok["subscriptionName"], "Grok Build")
        self.assertNotIn("keyRequired", grok)
        self.assertNotIn("auth", grok)

    def test_claude_api_command_has_budget_and_never_bare(self) -> None:
        profile = self.profiles()["claude-api"]
        for role in ("reviewer", "builder"):
            argv = roster.resolve_command(profile, role, "standard", self.prompt, self.work)["argv"]
            self.assertNotIn("--bare", argv)
            self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.5")
            self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
            self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        for field in ("command", "readOnlyCommand", "roleCommands", "headlessFlag"):
            self.assertNotIn("--bare", json.dumps(profile.get(field)))

    def test_codex_and_grok_commands(self) -> None:
        profiles = self.profiles()
        codex = roster.resolve_command(profiles["codex-api"], "second-opinion", "standard", self.prompt, self.work)["argv"]
        self.assertEqual(codex[:2], ["codex", "exec"])
        self.assertEqual(codex[codex.index("-m") + 1], "gpt-6.1-sol")
        self.assertEqual(codex[codex.index("--sandbox") + 1], "read-only")
        self.assertIn("--json", codex)
        grok = roster.resolve_command(profiles["grok-api"], "reviewer", "standard", self.prompt, self.work)["argv"]
        self.assertEqual(grok[:2], ["grok", "-p"])
        self.assertEqual(grok[grok.index("-m") + 1], "grok-build-0.1")
        self.assertEqual(grok[grok.index("--permission-mode") + 1], "plan")

    def test_builder_needs_rules_that_allow_build(self) -> None:
        self.set_env({"ANTHROPIC_API_KEY": FAKE})
        profiles = self.profiles()
        with self.assertRaises(roster.RosterError):
            roster.resolve([{"name": "claude-api"}], profiles, task_class="build")
        allowed = {"name": "claude-api", "rules": {"allow_tasks": ["review", "build"]}}
        self.assertEqual(roster.resolve([allowed], profiles, task_class="build")["enabled"], ["claude-api"])


class DetectTests(ApiCase):
    def test_api_agents_count_as_installed_only_with_a_key(self) -> None:
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name in ("claude", "codex"):
            script(bindir / name, "exit 0\n")
        self.set_env({"DTS2_PROBE_PATH": str(bindir)})
        with mock.patch.object(roster, "is_installed", side_effect=lambda p, *_: p["command"] is not None and p["command"][0] in ("claude", "codex")):
            self.assertEqual(roster.detect(self.work)["installed"], ["claude", "codex"])
            self.set_env({"CODEX_API_KEY": FAKE})
            data = roster.detect(self.work)
        self.assertCountEqual(data["installed"], ["claude", "codex", "codex-api"])
        self.assertNotIn(FAKE, json.dumps(data))


class HomeTests(ApiCase):
    def test_claude_config_dir_is_private_and_under_the_harness_user_dir(self) -> None:
        profile = self.profiles()["claude-api"]
        env = roster.clean_env(profile, workspace=self.work)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.agents.parent / "agents-home" / "claude-api"))
        self.assertNotIn(".harness", env["CLAUDE_CONFIG_DIR"])
        self.assertFalse(Path(env["CLAUDE_CONFIG_DIR"]).exists(), "a preview creates nothing")

    def test_codex_home_gets_forced_api_login_on_first_launch(self) -> None:
        self.set_env({"CODEX_API_KEY": FAKE})
        profile = self.profiles()["codex-api"]
        env, source = roster.launch_env(profile, roster.clean_env(profile, workspace=self.work))
        home = Path(env["CODEX_HOME"])
        self.assertEqual(home, self.agents.parent / "agents-home" / "codex-api")
        toml = home / "config.toml"
        self.assertEqual(toml.read_text(encoding="utf-8"), 'forced_login_method = "api"\n')
        self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(toml.stat().st_mode), 0o600)
        self.assertEqual(source, "env:CODEX_API_KEY")
        toml.write_text('forced_login_method = "api"\n# mine\n', encoding="utf-8")
        roster.launch_env(profile, roster.clean_env(profile, workspace=self.work))
        self.assertIn("# mine", toml.read_text(encoding="utf-8"), "an existing file is never overwritten")


class ResolveKeyTests(ApiCase):
    def fake(self, name: str, body: str) -> Path:
        return script(self.tmp / name, body)

    def test_env_ref_and_fallback(self) -> None:
        self.set_env({"MY_VAR": "v1", "XAI_API_KEY": "v2"})
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "env:MY_VAR", "apiKeyEnv": "XAI_API_KEY"}), ("v1", "env:MY_VAR"))
        self.assertEqual(api_keys.resolve_key({"apiKeyEnv": "XAI_API_KEY"}), ("v2", "env:XAI_API_KEY"))
        self.assertEqual(api_keys.resolve_key({"apiKeyEnv": "NOPE_API_KEY"}), (None, "env:NOPE_API_KEY"))

    def test_keyring_via_secret_tool(self) -> None:
        tool = self.fake("secret-tool", '[ "$*" = "lookup service dts2 username claude-api" ] && echo kr-FAKE-value\n')
        self.set_env({api_keys.SECRET_TOOL_BIN: str(tool)})
        with mock.patch.dict(sys.modules, {"keyring": None}):
            self.assertEqual(api_keys.resolve_key({"apiKeyRef": "keyring:dts2/claude-api"}), ("kr-FAKE-value", "keyring"))
            self.assertEqual(api_keys.resolve_key({"apiKeyRef": "keyring:dts2/other"}), (None, "keyring"))

    def test_keyring_via_python_module(self) -> None:
        module = types.ModuleType("keyring")
        module.get_password = lambda service, user: "py-FAKE" if (service, user) == ("dts2", "x") else None  # type: ignore[attr-defined]
        with mock.patch.dict(sys.modules, {"keyring": module}):
            self.assertEqual(api_keys.resolve_key({"apiKeyRef": "keyring:dts2/x"}), ("py-FAKE", "keyring"))

    def test_op_ref(self) -> None:
        tool = self.fake("op", '[ "$1 $2" = "read op://vault/item/field" ] && echo op-FAKE-value\n')
        self.set_env({api_keys.OP_BIN: str(tool)})
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "op://vault/item/field"}), ("op-FAKE-value", "op"))
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "op://vault/item/other"}), (None, "op"))

    def test_doppler_ref(self) -> None:
        tool = self.fake("doppler", '[ "$*" = "secrets get NAME --plain --project PROJ --config prd" ] && echo dp-FAKE-value\n')
        self.set_env({api_keys.DOPPLER_BIN: str(tool)})
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "doppler:PROJ/prd/NAME"}), ("dp-FAKE-value", "doppler"))
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "doppler:NAME"}), (None, "doppler"))

    def test_missing_binary_is_just_no_key(self) -> None:
        self.set_env({api_keys.OP_BIN: str(self.tmp / "no-such-op")})
        self.assertEqual(api_keys.resolve_key({"apiKeyRef": "op://v/i/f"}), (None, "op"))

    def test_labels_never_hold_the_value(self) -> None:
        for ref in ("keyring:dts2/a", "op://v/i/f", "doppler:P/C/N", "env:X"):
            self.assertNotIn("/", api_keys.source_label({"apiKeyRef": ref}))


class LaunchTests(ApiCase):
    def fake_claude(self) -> Path:
        out = self.tmp / "child-env.txt"
        fake = script(self.tmp / "fake-claude", f'env > "{out}"\nprintf \'{{"total_cost_usd": 0.12, "result": "ok"}}\'\n')
        self.set_env({"DTS2_BIN_CLAUDE": str(fake)})
        return out

    def run_exec(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = roster.run_exec("claude-api", "reviewer", "standard", str(self.prompt), str(self.work), None)
        return code, out.getvalue(), err.getvalue()

    def test_missing_key_refuses_launch_naming_the_variable(self) -> None:
        out = self.fake_claude()
        code, stdout, stderr = self.run_exec()
        self.assertEqual(code, roster.EXIT_REFUSED)
        self.assertIn("ANTHROPIC_API_KEY", stderr)
        self.assertIn("apiKeyRef", stderr)
        self.assertFalse(out.exists(), "nothing was started")
        self.assertFalse((self.agents.parent / "agents-home").exists(), "nothing was created")

    def test_missing_ref_names_the_ref(self) -> None:
        self.user_profile("claude-api", apiKeyRef="env:NOT_SET_ANYWHERE")
        self.fake_claude()
        code, _, stderr = self.run_exec()
        self.assertEqual(code, roster.EXIT_REFUSED)
        self.assertIn("env:NOT_SET_ANYWHERE", stderr)

    def test_missing_key_is_a_recorded_dispatch_skip(self) -> None:
        profiles = self.profiles()
        result = roster.resolve([{"name": "claude"}, {"name": "claude-api"}], profiles)
        self.assertEqual(result["enabled"], ["claude"])
        skipped = result["skipped"]
        self.assertEqual([s["name"] for s in skipped], ["claude-api"])
        self.assertIn("ANTHROPIC_API_KEY", skipped[0]["reason"])
        with self.assertRaises(roster.RosterError):
            roster.resolve([{"name": "claude-api"}], profiles)
        self.set_env({"ANTHROPIC_API_KEY": FAKE})
        self.assertIn("claude-api", roster.resolve([{"name": "claude"}, {"name": "claude-api"}], profiles)["enabled"])

    def test_key_reaches_only_the_api_child(self) -> None:
        out = self.fake_claude()
        self.set_env({"ANTHROPIC_API_KEY": FAKE, "XAI_API_KEY": FAKE + "x", "GH_TOKEN": "gh-FAKE"})
        code, stdout, stderr = self.run_exec()
        self.assertEqual(code, 0, stderr)
        child = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines() if "=" in line)
        self.assertEqual(child["ANTHROPIC_API_KEY"], FAKE)
        self.assertEqual(child["DTS2_AGENT"], "claude-api")
        self.assertEqual(child["CLAUDE_CONFIG_DIR"], str(self.agents.parent / "agents-home" / "claude-api"))
        self.assertNotIn("XAI_API_KEY", child)
        self.assertNotIn("GH_TOKEN", child)
        profiles = self.profiles()
        for max_agent in ("claude", "codex", "grok"):
            env = roster.clean_env(profiles[max_agent], workspace=self.work)
            self.assertNotIn(FAKE, env.values(), max_agent)
            self.assertFalse(any(son_launch.credential_name(k) for k in env), max_agent)
        self.assertNotIn(FAKE, json.dumps(roster.resolve_command(profiles["claude-api"], "reviewer", "standard", self.prompt, self.work)))

    def test_receipt_and_ledger_record_the_source_not_the_value(self) -> None:
        self.fake_claude()
        self.user_profile("claude-api", apiKeyRef="env:MY_CLAUDE_KEY")
        self.set_env({"MY_CLAUDE_KEY": FAKE})
        code, _, stderr = self.run_exec()
        self.assertEqual(code, 0, stderr)
        ledger = (self.work / ".harness" / "spend.jsonl").read_text(encoding="utf-8")
        row = json.loads(ledger.splitlines()[0])
        self.assertEqual((row["agent"], row["usd"], row["credential"]), ("claude-api", 0.12, "env:MY_CLAUDE_KEY"))
        self.assertNotIn(FAKE, ledger)
        profile = self.profiles()["claude-api"]
        line = delegate.receipt_line(profile, "advisory", "medium", "sonnet")
        self.assertIn("credential=env:MY_CLAUDE_KEY", line)
        self.assertNotIn(FAKE, line)
        self.assertNotIn("credential", delegate.receipt_line(self.profiles()["claude"], "advisory", "medium"))

    def test_credential_label_in_command_output(self) -> None:
        result = roster.resolve_command(self.profiles()["grok-api"], "reviewer", "standard", self.prompt, self.work)
        self.assertEqual(result["credential"], "env:XAI_API_KEY")
        self.assertIn(" exec ", result["shell"])
        self.assertNotIn("XAI_API_KEY=", result["shell"])


class SeatBanTests(ApiCase):
    def test_never_picked_as_lead_by_failover(self) -> None:
        profiles = self.profiles()
        self.assertFalse(set(API) & set(failover.lead_eligible(profiles)))
        for current in ("claude", "codex", "grok", "gemini"):
            self.assertNotIn(failover.next_lead(profiles, current, cooling=[]), API)
        only_api = {name: profiles[name] for name in API}
        self.assertIsNone(failover.next_lead(only_api, "claude", cooling=[]))

    def test_never_signs_off(self) -> None:
        profiles = self.profiles()
        self.assertEqual(delegate.signoff_agent(profiles, "claude-api"), "claude")
        with self.assertRaises(delegate.DelegationError):
            delegate.delegate(profiles["claude-api"], "signoff", "normal")
        with self.assertRaises(delegate.DelegationError):
            delegate.delegate(profiles["grok-api"], "signoff", "normal", lead_provider=None)
        for lead in ("claude", "claude-api", "grok-api"):
            names = [p["name"] for p in delegate.seat_candidates(profiles["claude"], "signoff", lead, profiles)]
            self.assertFalse(set(API) & set(names), names)

    def test_roster_refuses_lead_seats(self) -> None:
        profiles = self.profiles()
        for name in API:
            for role in ("lead", "signoff"):
                with self.assertRaises(roster.RosterError):
                    roster.resolve([{"name": name, "roles": [role]}], profiles)
                with self.assertRaises(roster.RosterError):
                    roster.resolve_command(profiles[name], role, "standard", self.prompt, self.work)
        user = dict(profiles["claude-api"], roles=["reviewer", "lead"])
        with self.assertRaises(roster.RosterError):
            roster.resolve([{"name": "claude-api"}], {**profiles, "claude-api": user})

    def test_derived_profile_inherits_the_ban(self) -> None:
        self.user_profile("claude-api-2", extends="claude-api")
        profiles = self.profiles()
        self.assertIs(profiles["claude-api-2"]["leadEligible"], False)
        self.assertNotIn("claude-api-2", failover.lead_eligible(profiles))


class SecondOpinionTests(ApiCase):
    def module(self) -> Any:
        spec = importlib.util.spec_from_file_location("dts2_run_api", PLUGIN_ROOT / "sdk" / "dts2-run.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_env_is_scrubbed_and_holds_only_its_own_key(self) -> None:
        self.set_env({"GH_TOKEN": "g", "ANTHROPIC_API_KEY": "a", "CODEX_API_KEY": "c-FAKE", "XAI_API_KEY": "x-FAKE",
                      "OPENAI_API_KEY": "o", "AWS_SECRET_ACCESS_KEY": "s", "SSH_AUTH_SOCK": "/s"})
        module = self.module()
        codex = module.second_opinion_env({"GROK_WORKFLOWS": "0", "XAI_API_KEY": "from-profile"}, "codex")
        self.assertEqual(codex["CODEX_API_KEY"], "c-FAKE")
        self.assertEqual(codex["GROK_WORKFLOWS"], "0")
        for name in ("GH_TOKEN", "ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK"):
            self.assertNotIn(name, codex)
        grok = module.second_opinion_env(None, "grok")
        self.assertEqual(grok["XAI_API_KEY"], "x-FAKE")
        self.assertNotIn("CODEX_API_KEY", grok)

    def test_key_comes_through_api_keys_ref(self) -> None:
        self.user_profile("codex-api", apiKeyRef="env:MY_CODEX_VAR")
        self.set_env({"MY_CODEX_VAR": "ref-FAKE", "CODEX_API_KEY": "ignored-FAKE"})
        env = self.module().second_opinion_env(None, "codex")
        self.assertEqual(env["CODEX_API_KEY"], "ref-FAKE")
        self.assertNotIn("MY_CODEX_VAR", env)


class DoctorTests(ApiCase):
    def rows(self) -> dict[str, dict[str, str]]:
        previous = os.getcwd()
        os.chdir(self.work)
        try:
            return {row["name"]: row for row in doctor.check_api_keys()}
        finally:
            os.chdir(previous)

    def test_reports_set_with_source_and_missing_without_values(self) -> None:
        self.set_env({"XAI_API_KEY": FAKE})
        rows = self.rows()
        self.assertEqual(rows["api-key grok-api"]["detail"], "set (env:XAI_API_KEY)")
        self.assertEqual(rows["api-key claude-api"]["detail"], "missing")
        self.assertEqual(rows["api-key codex-api"]["detail"], "missing")
        self.assertNotIn(FAKE, json.dumps(rows))

    def test_missing_warns_only_for_an_agent_in_the_roster(self) -> None:
        self.assertEqual(self.rows()["api-key claude-api"]["status"], doctor.PASS)
        config = self.work / ".harness" / "config.yaml"
        config.parent.mkdir()
        config.write_text("roster:\n  - name: claude\n  - name: claude-api\n", encoding="utf-8")
        self.assertEqual(self.rows()["api-key claude-api"]["status"], doctor.WARN)


if __name__ == "__main__":
    unittest.main()
