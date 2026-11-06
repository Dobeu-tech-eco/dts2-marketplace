"""Per-agent rules (batch D): schema and validator, effective rules, dispatch, launch and runtime enforcement, the spend
ledger and the `roster.py rules` command. Temp dirs only; nothing here touches the real home."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT, isolate_agent_status

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import agent_rules  # noqa: E402
import delegate  # noqa: E402
import policy_gate  # noqa: E402
import roster  # noqa: E402
import son_launch  # noqa: E402
import state_io  # noqa: E402
from profiles import PROFILE_DIR, USER_AGENTS_ENV, Profiles  # noqa: E402

ROSTER_CLI: Final[Path] = SCRIPTS / "roster.py"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "policy-gate.sh"
FAKE_KEY: Final[str] = "sk-test-FAKE" + "0123456789abcdefghij"
CONFIG: Final[str] = """project: demo
roster:
  - name: claude
  # the pay-as-you-go agent
  - name: grok
    auth: api-key
    roles: [reviewer, second-opinion]
    included: true
  - name: codex
    roles: [builder]

budget:
  codex:
    status: ok
"""


def bundled() -> dict[str, dict[str, Any]]:
    return Profiles.load(PROFILE_DIR).as_dict()


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-rules-")).resolve()
        self.home = self.root / "home-agents"
        self.config = self.root / state_io.CONFIG_REL
        self.config.parent.mkdir(parents=True)
        self.config.write_text(CONFIG, encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {USER_AGENTS_ENV: str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        isolate_agent_status(self)

    def write_config(self, text: str) -> None:
        self.config.write_text(text, encoding="utf-8")

    def cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(ROSTER_CLI), *args], capture_output=True, text=True, check=False,
                              cwd=str(self.root), env={**os.environ, USER_AGENTS_ENV: str(self.home), **(env or {})})


class ValidatorTests(unittest.TestCase):
    def test_a_clean_block_has_no_errors(self) -> None:
        rules = {"allow_tasks": ["review"], "deny_tasks": ["merge"], "max_tier": "standard", "paths_deny": ["**/.env*"],
                 "no_secrets": True, "read_only": False, "max_cost_usd_per_run": 0.5, "max_cost_usd_per_day": 0}
        self.assertEqual(agent_rules.validate(rules), [])

    def test_unknown_key_class_tier_and_cost(self) -> None:
        errors = agent_rules.validate({"colour": "red", "allow_tasks": ["review", "teleport"], "max_tier": "ultra",
                                       "max_cost_usd_per_day": -1, "read_only": "maybe", "paths_deny": ["a,b"]})
        text = "\n".join(errors)
        for needle in ("unknown key 'colour'", "unknown task class 'teleport'", "max_tier 'ultra'",
                       "max_cost_usd_per_day must be a number", "read_only must be true or false", "holds a comma"):
            self.assertIn(needle, text)

    def test_a_class_in_both_lists_is_an_error(self) -> None:
        errors = agent_rules.validate({"allow_tasks": ["review", "merge"], "deny_tasks": ["merge"]})
        self.assertEqual(errors, ["task class 'merge' is in both allow_tasks and deny_tasks"])

    def test_not_a_mapping(self) -> None:
        self.assertEqual(len(agent_rules.validate(["review"])), 1)

    def test_policy_json_lists_exactly_the_task_classes(self) -> None:
        policy = json.loads((PLUGIN_ROOT / "templates" / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(policy["taskClasses"]), sorted(agent_rules.TASK_CLASSES))
        self.assertEqual(len(agent_rules.TASK_CLASSES), 11)

    def test_config_text_is_typed_before_validation(self) -> None:
        raw = {"allow_tasks": "review, docs", "read_only": "true", "max_cost_usd_per_run": "0.25", "max_cost_usd_per_day": "lots"}
        typed = agent_rules.coerce_rules(raw)
        self.assertEqual(typed["allow_tasks"], ["review", "docs"])
        self.assertIs(typed["read_only"], True)
        self.assertEqual(typed["max_cost_usd_per_run"], 0.25)
        self.assertEqual(typed["max_cost_usd_per_day"], "lots")
        self.assertEqual(len(agent_rules.validate(typed)), 1)


class EffectiveRulesTests(unittest.TestCase):
    def test_api_key_agent_without_rules_gets_the_defaults(self) -> None:
        rules, warnings = agent_rules.effective_rules_with_warnings({"name": "grok-api"}, "api-key")
        self.assertIs(rules["read_only"], True)
        self.assertEqual(rules["allow_tasks"], ["review", "docs", "research"])
        self.assertEqual(rules["max_tier"], "standard")
        self.assertEqual((rules["max_cost_usd_per_run"], rules["max_cost_usd_per_day"]), (0.5, 5.0))
        self.assertEqual(rules["deny_tasks"], list(agent_rules.FORCED_DENY))
        self.assertEqual(warnings, [])

    def test_the_forced_denies_cannot_be_overridden(self) -> None:
        entry = {"name": "grok-api", "rules": {"allow_tasks": ["review", "merge", "deploy"], "deny_tasks": ["infra"]}}
        rules, warnings = agent_rules.effective_rules_with_warnings(entry, "api-key")
        self.assertEqual(rules["allow_tasks"], ["review"])
        self.assertEqual(rules["deny_tasks"][0], "infra")
        self.assertTrue(set(agent_rules.FORCED_DENY) <= set(rules["deny_tasks"]))
        self.assertEqual(len(warnings), 1)
        self.assertIn("merge, deploy", warnings[0])
        self.assertFalse(agent_rules.permits(rules, "merge")[0])
        self.assertTrue(agent_rules.permits(rules, "review")[0])

    def test_written_keys_win_over_the_defaults_for_the_rest(self) -> None:
        rules = agent_rules.effective_rules({"name": "x", "rules": {"read_only": False, "max_cost_usd_per_day": 20}}, "api-key")
        self.assertIs(rules["read_only"], False)
        self.assertEqual((rules["max_cost_usd_per_day"], rules["max_tier"]), (20, "standard"))

    def test_subscription_agent_without_rules_is_unrestricted(self) -> None:
        for auth in ("subscription", None):
            self.assertEqual(agent_rules.effective_rules({"name": "claude"}, auth), {})
        self.assertEqual(agent_rules.effective_rules(None, "subscription"), {})
        self.assertEqual(agent_rules.permits({}, "merge", "frontier", ["x"]), (True, "ok"))

    def test_a_subscription_agent_keeps_only_what_it_wrote(self) -> None:
        rules = agent_rules.effective_rules({"name": "codex", "rules": {"deny_tasks": ["deploy"]}}, "subscription")
        self.assertEqual(rules, {"deny_tasks": ["deploy"]})
        self.assertTrue(agent_rules.permits(rules, "merge")[0])

    def test_permits_checks_class_tier_and_paths(self) -> None:
        rules = {"allow_tasks": ["review"], "max_tier": "standard", "paths_deny": ["**/.env*", "infra/**"], "no_secrets": True}
        self.assertTrue(agent_rules.permits(rules, "review", "economy", ["src/a.py"])[0])
        self.assertIn("allow_tasks", agent_rules.permits(rules, "build")[1])
        self.assertIn("max_tier", agent_rules.permits(rules, "review", "frontier")[1])
        self.assertIn("paths_deny", agent_rules.permits(rules, paths=["./infra/main.tf"])[1])
        self.assertFalse(agent_rules.permits(rules, paths=[".env"])[0])
        self.assertFalse(agent_rules.permits(rules, paths=["app/.env.local"])[0])
        self.assertIn("no_secrets", agent_rules.permits({"no_secrets": True}, "secrets")[1])

    def test_summary(self) -> None:
        rules = agent_rules.effective_rules({"name": "x"}, "api-key")
        self.assertEqual(agent_rules.summary(rules), "ro review,docs,research ≤standard $0.5/$5")
        self.assertEqual(agent_rules.summary({}), "-")


class DispatchTests(TempProject):
    def roster_entries(self) -> list[dict[str, Any]]:
        return [{"name": "claude"},
                {"name": "grok", "auth": "api-key", "roles": ["reviewer"], "rules": {"allow_tasks": ["review"]}},
                {"name": "codex", "roles": ["builder"]}]

    def test_without_a_task_class_nothing_changes(self) -> None:
        plain = roster.resolve(self.roster_entries(), bundled())
        self.assertNotIn("skipped", plain)
        self.assertEqual(plain["assignments"]["reviewer"], ["claude", "grok"])

    def test_resolve_skips_a_denied_agent_and_records_why(self) -> None:
        result = roster.resolve(self.roster_entries(), bundled(), task_class="build")
        self.assertEqual(result["assignments"]["reviewer"], ["claude"])
        self.assertNotIn("grok", result["enabled"])
        self.assertEqual([s["name"] for s in result["skipped"]], ["grok"])
        self.assertIn("not in this agent's allow_tasks", result["skipped"][0]["reason"])
        self.assertEqual(roster.resolve(self.roster_entries(), bundled(), task_class="review")["assignments"]["reviewer"], ["claude", "grok"])

    def test_resolve_skips_an_agent_above_its_max_tier(self) -> None:
        result = roster.resolve(self.roster_entries(), bundled(), tier="frontier")
        self.assertEqual([s["name"] for s in result["skipped"]], ["grok"])
        self.assertIn("max_tier", result["skipped"][0]["reason"])

    def test_entry_roles_records_the_skip(self) -> None:
        entry = self.roster_entries()[1]
        skipped: list[dict[str, str]] = []
        self.assertEqual(roster.entry_roles(entry, bundled()["grok"], "merge", None, skipped), [])
        self.assertEqual(skipped[0]["name"], "grok")
        self.assertEqual(roster.entry_roles(entry, bundled()["grok"]), ["reviewer"])

    def test_nothing_eligible_fails_with_every_reason(self) -> None:
        entries = [{"name": "grok", "auth": "api-key"}, {"name": "gemini", "auth": "api-key"}]
        with self.assertRaises(roster.RosterError) as ctx:
            roster.resolve(entries, bundled(), task_class="build")
        message = str(ctx.exception)
        self.assertIn("grok:", message)
        self.assertIn("gemini:", message)
        self.assertIn("task 'build'", message)

    def test_resolve_cli_takes_the_class(self) -> None:
        self.write_config("roster:\n  - name: claude\n  - name: grok\n    auth: api-key\n    roles: [reviewer]\n")
        done = self.cli("resolve", "--task-class", "merge")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["skipped"][0]["name"], "grok")
        self.write_config("roster:\n  - name: grok\n    auth: api-key\n")
        failed = self.cli("resolve", "--task-class", "merge")
        self.assertEqual(failed.returncode, 1)
        self.assertIn("grok:", failed.stderr)

    def test_pick_profile_fails_over_to_the_next_eligible_agent(self) -> None:
        pool = {name: bundled()[name] for name in ("claude", "grok")}
        rules = {"grok": agent_rules.effective_rules({"name": "grok"}, "api-key")}
        skipped: list[dict[str, str]] = []
        chosen = delegate.pick_profile(pool["claude"], "signoff", "grok", pool, tier="frontier", rules=rules, skipped=skipped)
        self.assertEqual(chosen["name"], "claude")
        self.assertEqual([s["name"] for s in skipped], ["grok"])
        self.assertIn("max_tier", skipped[0]["reason"])
        self.assertEqual(delegate.pick_profile(pool["claude"], "signoff", "grok", pool)["name"], "grok")  # old behaviour
        self.assertEqual(delegate.pick_profile(pool["claude"], "signoff", "grok", pool, rules=rules,
                                               task_class="review", tier="standard")["name"], "grok")

    def test_pick_profile_with_nobody_left_raises(self) -> None:
        pool = {name: bundled()[name] for name in ("claude", "grok")}
        rules = {n: agent_rules.effective_rules({"name": n, "rules": {"allow_tasks": ["docs"]}}, "api-key") for n in pool}
        with self.assertRaises(delegate.DelegationError) as ctx:
            delegate.pick_profile(pool["claude"], "advisory", "grok", pool, task_class="build", rules=rules)
        self.assertIn("grok:", str(ctx.exception))
        self.assertIn("claude:", str(ctx.exception))

    def test_delegate_reports_the_skip_and_uses_the_planned_tier(self) -> None:
        pool = {name: bundled()[name] for name in ("claude", "grok")}
        rules = {"grok": agent_rules.effective_rules({"name": "grok"}, "api-key")}
        result = delegate.delegate(pool["claude"], "advisory", "design", lead_provider="grok", profiles=pool, rules=rules)
        self.assertEqual(result["agent"], "claude")  # design advice runs on frontier, above grok's max_tier
        self.assertEqual(result["skipped"][0]["name"], "grok")
        plain = delegate.delegate(pool["claude"], "advisory", "design", lead_provider="grok", profiles=pool)
        self.assertEqual(plain["agent"], "grok")
        self.assertNotIn("skipped", plain)


class LaunchTests(TempProject):
    def test_dts2_agent_survives_the_scrub(self) -> None:
        self.assertIn("DTS2_AGENT", son_launch.ENV_ALLOW)
        env = son_launch.scrub_env({"PATH": "/bin"}, auth="api-key", claude=False, agent="grok-api")
        self.assertEqual(env["DTS2_AGENT"], "grok-api")
        inherited = son_launch.scrub_env({"PATH": "/bin", "DTS2_AGENT": "outer"})
        self.assertEqual(inherited["DTS2_AGENT"], "outer")
        self.assertEqual(son_launch.provider_env({"PATH": "/bin"}, agent="x")["DTS2_AGENT"], "x")

    def test_no_secrets_blocks_the_env_pass_through(self) -> None:
        source = {"PATH": "/bin", "DTS2_SON_ENV_PASS": "XAI_*,MY_*,PLAIN_*", "XAI_API_KEY": FAKE_KEY, "MY_TOKEN": "t", "MY_NOTE": FAKE_KEY,
                  "PLAIN_VAR": "ok"}
        open_env = son_launch.scrub_env(source, claude=False)
        self.assertTrue({"XAI_API_KEY", "MY_TOKEN", "MY_NOTE", "PLAIN_VAR"} <= set(open_env))
        closed = son_launch.scrub_env(source, claude=False, no_secrets=True)
        self.assertEqual(set(closed) & {"XAI_API_KEY", "MY_TOKEN", "MY_NOTE"}, set())
        self.assertEqual(closed["PLAIN_VAR"], "ok")

    def test_clean_env_carries_the_agent_and_honours_no_secrets(self) -> None:
        self.write_config("roster:\n  - name: grok\n    auth: api-key\n    rules:\n      no_secrets: true\n")
        source = {**os.environ, "DTS2_SON_ENV_PASS": "STRIPE_*", "STRIPE_SECRET_KEY": FAKE_KEY}
        with mock.patch.dict(os.environ, source, clear=True):
            env = roster.clean_env(bundled()["grok"], workspace=self.root)
        self.assertEqual(env["DTS2_AGENT"], "grok")
        self.assertNotIn("STRIPE_SECRET_KEY", env)

    def test_read_only_without_a_read_only_command_refuses_to_launch(self) -> None:
        self.write_config("roster:\n  - name: codex\n    auth: api-key\n    roles: [builder, second-opinion]\n")
        with self.assertRaises(roster.RosterError) as ctx:
            roster.resolve_command(bundled()["codex"], "builder", "standard", workspace=self.root)
        self.assertIn("read-only", str(ctx.exception))
        done = self.cli("command", "--agent", "codex", "--role", "builder", "--workspace", str(self.root))
        self.assertEqual(done.returncode, 1)
        self.assertIn("read-only", done.stderr)

    def test_read_only_uses_the_profiles_read_only_role_command(self) -> None:
        self.write_config("roster:\n  - name: codex\n    auth: api-key\n    roles: [builder, second-opinion]\n")
        result = roster.resolve_command(bundled()["codex"], "second-opinion", "standard", workspace=self.root)
        self.assertIn("read-only", result["argv"])
        self.assertNotIn("workspace-write", result["argv"])
        self.assertEqual(result["clean_env"]["DTS2_AGENT"], "codex")
        self.assertTrue(result["rules"]["read_only"])

    def test_read_only_claude_runs_in_plan_mode_with_a_budget_cap(self) -> None:
        self.write_config("roster:\n  - name: claude\n    auth: api-key\n    rules:\n      max_cost_usd_per_run: 0.25\n")
        result = roster.resolve_command(bundled()["claude"], "reviewer", "standard", Path("/tmp/prompt.md"), self.root)
        argv = result["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.25")
        self.assertLess(argv.index("--max-budget-usd"), len(argv) - 1)
        self.assertTrue(argv[-1].startswith("Read the instructions in"))  # the prompt pointer stays last

    def test_the_budget_flag_goes_only_to_profiles_that_support_it(self) -> None:
        self.write_config("roster:\n  - name: grok\n    auth: api-key\n    rules:\n      read_only: false\n")
        result = roster.resolve_command(bundled()["grok"], "reviewer", "standard", workspace=self.root)
        self.assertNotIn("--max-budget-usd", result["argv"])

    def test_a_subscription_agent_without_rules_launches_as_before(self) -> None:
        self.write_config("roster:\n  - name: codex\n    roles: [builder]\n")
        empty = Path(tempfile.mkdtemp(prefix="dts2-rules-empty-"))
        with_config = roster.resolve_command(bundled()["codex"], "builder", "standard", workspace=self.root)
        without = roster.resolve_command(bundled()["codex"], "builder", "standard", workspace=empty)
        self.assertEqual(with_config["argv"], without["argv"])
        self.assertIn("workspace-write", with_config["argv"])
        self.assertNotIn("rules", with_config)


class PolicyGateTests(TempProject):
    def setUp(self) -> None:
        super().setUp()
        subprocess.run(["git", "init", "-q", "-b", "feat", str(self.root)], check=True)
        self.write_config(
            "roster:\n  - name: claude\n  - name: grok-api\n    profile: grok\n    auth: api-key\n"
            "  - name: builder-x\n    auth: subscription\n    rules:\n      read_only: false\n      allow_tasks: [build, test]\n"
            "      paths_deny: [\"**/.env*\", infra/**]\n")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.local.json").write_text(json.dumps({"dts2_approvals": {"merge": ["7"]}}), encoding="utf-8")

    def bash(self, command: str, agent: str | None = None) -> str | None:
        env = {k: v for k, v in os.environ.items() if k != "DTS2_AGENT"}
        if agent:
            env["DTS2_AGENT"] = agent
        with mock.patch.dict(os.environ, env, clear=True):
            return policy_gate.decide({"tool_name": "Bash", "tool_input": {"command": command}}, self.root)

    def tool(self, name: str, agent: str | None, **fields: str) -> str | None:
        env = {k: v for k, v in os.environ.items() if k != "DTS2_AGENT"}
        if agent:
            env["DTS2_AGENT"] = agent
        with mock.patch.dict(os.environ, env, clear=True):
            return policy_gate.decide({"tool_name": name, "tool_input": fields}, self.root)

    def test_gh_pr_merge_is_denied_for_a_limited_agent_and_allowed_without_one(self) -> None:
        self.assertIsNone(self.bash("gh pr merge 7"))  # the person approved PR 7
        denied = self.bash("gh pr merge 7", agent="grok-api")
        self.assertIsNotNone(denied)
        self.assertIn("agent-rules: grok-api", denied or "")
        self.assertIn("'merge'", denied or "")

    def test_classes_come_from_the_policy_table(self) -> None:
        for command, label in (("git branch -D old", "delete"), ("terraform apply", "infra"), ("rm -rf build", "delete"),
                               ("npm publish", "release"), ("git push origin feat", "merge"), ("pytest -q", "test")):
            self.assertIn(f"'{label}'", self.bash(command, agent="grok-api") or "", command)
        self.assertIsNone(self.bash("git status && ls", agent="grok-api"))
        self.assertIsNone(self.bash("git branch -D old"))

    def test_hidden_forms_are_classified_too(self) -> None:
        self.assertIsNotNone(self.bash('bash -lc "gh pr merge 7"', agent="grok-api"))
        self.assertIsNotNone(self.bash("env -i git branch -D old", agent="grok-api"))

    def test_global_deny_list_still_applies_to_an_agent_with_no_rules(self) -> None:
        self.assertIn("force-push", self.bash("git push --force origin feat", agent="claude") or "")
        self.assertIsNone(self.bash("git status", agent="claude"))

    def test_an_edit_to_a_paths_deny_path_is_denied(self) -> None:
        reason = self.tool("Edit", "builder-x", file_path=str(self.root / "infra" / "main.tf"))
        self.assertIn("paths_deny", reason or "")
        self.assertIsNone(self.tool("Edit", "builder-x", file_path=str(self.root / "src" / "a.py")))
        self.assertIsNone(self.tool("Edit", None, file_path=str(self.root / "infra" / "main.tf")))
        self.assertIn("paths_deny", self.tool("Read", "builder-x", file_path=".env.local") or "")
        self.assertIn("paths_deny", self.bash("cat app/.env", agent="builder-x") or "")

    def test_task_class_of_a_file_tool(self) -> None:
        self.assertIn("allow_tasks", self.tool("WebFetch", "builder-x", url="https://example.com") or "")
        self.assertIn("read-only", self.tool("Write", "grok-api", file_path="docs/a.md") or "")

    def test_the_hook_script_judges_file_tools_only_for_a_named_agent(self) -> None:
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "infra/main.tf"}})
        base = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
                USER_AGENTS_ENV: str(self.home)}
        named = subprocess.run(["bash", str(HOOK), "files"], input=payload, capture_output=True, text=True, cwd=self.root,
                               env={**base, "DTS2_AGENT": "builder-x"}, check=False)
        self.assertEqual(json.loads(named.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        anonymous = subprocess.run(["bash", str(HOOK), "files"], input=payload, capture_output=True, text=True, cwd=self.root,
                                   env=base, check=False)
        self.assertEqual((anonymous.returncode, anonymous.stdout), (0, ""))

    def test_hooks_json_registers_the_file_tool_matcher(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        entries = [e for e in hooks if any(h["command"].endswith("policy-gate.sh\" files") for h in e["hooks"])]
        self.assertEqual(len(entries), 1)
        self.assertIn("Edit", entries[0]["matcher"])


class SpendLedgerTests(TempProject):
    def test_record_and_sum_per_agent_and_day(self) -> None:
        today = date(2026, 11, 6)
        agent_rules.record_spend("grok-api", 0.4, "run-1", self.root, today)
        agent_rules.record_spend("grok-api", 0.35, "run-2", self.root, today)
        agent_rules.record_spend("other", 9.0, "run-3", self.root, today)
        agent_rules.record_spend("grok-api", 3.0, "run-0", self.root, today - timedelta(days=1))
        self.assertEqual(agent_rules.spent_today("grok-api", self.root, today), 0.75)
        self.assertEqual(agent_rules.spent_today("nobody", self.root, today), 0)
        ledger = self.root / state_io.SPEND_REL
        self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 4)

    def test_junk_costs_write_nothing(self) -> None:
        for value in (None, 0, -1, float("nan"), float("inf"), True):
            self.assertFalse(agent_rules.record_spend("a", value, "r", self.root), value)  # type: ignore[arg-type]
        self.assertFalse(agent_rules.record_spend("", 1.0, "r", self.root))
        self.assertFalse((self.root / state_io.SPEND_REL).exists())

    def test_a_damaged_ledger_line_is_skipped(self) -> None:
        path = self.root / state_io.SPEND_REL
        path.write_text("not json\n", encoding="utf-8")
        agent_rules.record_spend("a", 1.5, "r", self.root)
        self.assertEqual(agent_rules.spent_today("a", self.root), 1.5)

    def test_the_agent_is_exhausted_at_the_daily_cap(self) -> None:
        rules = agent_rules.effective_rules({"name": "grok-api"}, "api-key")  # $5 a day
        agent_rules.record_spend("grok-api", 4.99, "r1", self.root)
        self.assertFalse(agent_rules.day_exhausted("grok-api", rules, self.root))
        agent_rules.record_spend("grok-api", 0.01, "r2", self.root)
        self.assertTrue(agent_rules.day_exhausted("grok-api", rules, self.root))
        self.assertFalse(agent_rules.day_exhausted("grok-api", rules, self.root, date.today() + timedelta(days=1)))
        self.assertFalse(agent_rules.day_exhausted("grok-api", {}, self.root))  # no cap: never

    def synthetic_profile(self) -> dict[str, Any]:
        return {"name": "grok-api", "roles": ["builder"], "invocation": "live", "costTier": 1, "statusCommand": None,
                "loginCommand": None, "command": ["x"], "models": {"frontier": None, "standard": "m", "economy": None}}

    def test_probe_drops_an_exhausted_agent_so_dispatch_skips_it(self) -> None:
        entries = [{"name": "grok-api", "auth": "api-key", "included": True}, {"name": "plain"}]
        profiles = {"grok-api": self.synthetic_profile(), "plain": {**self.synthetic_profile(), "name": "plain"}}
        before = roster.probe(entries, profiles, {}, self.root)
        self.assertEqual(before["usable"], ["grok-api", "plain"])
        agent_rules.record_spend("grok-api", 5.0, "run-9", self.root)
        agent_rules.record_spend("plain", 500.0, "run-9", self.root)
        after = roster.probe(entries, profiles, {}, self.root)
        self.assertEqual(after["usable"], ["plain"])  # a subscription agent has no daily cap
        self.assertEqual(after["dropped"], [{"name": "grok-api", "reason": "budget exhausted"}])

    def test_probe_cli_reads_the_ledger_of_the_config_repo(self) -> None:
        profile = self.root / state_io.AGENT_PROFILES_REL / "grok-pay.json"
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps({"name": "grok-pay", "extends": "grok", "statusCommand": None, "loginCommand": None}), encoding="utf-8")
        self.write_config("roster:\n  - name: claude\n  - name: grok-pay\n    auth: api-key\n    included: true\n")
        agent_rules.record_spend("grok-pay", 5.0, "r", self.root)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "grok"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        done = self.cli("probe", "--config", str(self.config), env={roster.PROBE_PATH_ENV: str(bin_dir)})
        self.assertEqual(done.returncode, 0, done.stderr)
        agents = json.loads(done.stdout)["agents"]
        self.assertEqual((agents["grok-pay"]["available"], agents["grok-pay"]["reason"]), (False, "budget exhausted"))

    def test_a_model_call_as_a_named_agent_lands_in_the_ledger(self) -> None:
        from lanes import supervisor
        fake = self.root / "fake_claude.py"
        fake.write_text('import json\nprint(json.dumps({"type": "result", "total_cost_usd": 0.4, "session_id": "s-1"}))\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_AGENT": "grok-api"}):
            result = supervisor.model_call(self.root / "runs", "20261106-1", self.root, "seat", [sys.executable, str(fake)], 20, None, None,
                                           "claude")
        self.assertTrue(result["ok"], result)
        self.assertEqual(agent_rules.spent_today("grok-api", self.root), 0.4)

    def test_the_session_note_and_doctor_report_invalid_rules(self) -> None:
        self.write_config("roster:\n  - name: grok\n    auth: api-key\n    rules:\n      allow_tasks: [merge]\n      deny_tasks: [merge]\n      speed: fast\n")
        problems = agent_rules.config_problems(self.config)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(p.startswith("roster agent 'grok':") for p in problems))
        note = subprocess.run([sys.executable, "-I", str(SCRIPTS / "cooldowns.py"), "session-note"], capture_output=True, text=True,
                              cwd=self.root, check=False, env={**os.environ, "DTS2_AGENT_STATUS": str(self.root / "status.json")})
        self.assertIn("invalid agent rules", note.stdout)
        doctor = subprocess.run([sys.executable, "-I", str(SCRIPTS / "doctor.py"), "--json"], capture_output=True, text=True,
                                cwd=self.root, check=False)
        row = next(c for c in json.loads(doctor.stdout)["checks"] if c["name"] == "agent-rules")
        self.assertEqual(row["status"], "fail")


class RulesCliTests(TempProject):
    def test_show_set_reset_round_trip_and_keep_the_other_yaml(self) -> None:
        shown = json.loads(self.cli("rules", "grok", "--show").stdout)
        self.assertEqual(shown["written"], {})
        self.assertEqual(shown["effective"]["max_tier"], "standard")  # api-key defaults
        done = self.cli("rules", "grok", "--set", "allow_tasks=review,docs", "--set", "paths_deny=**/.env*,infra/**",
                        "--set", "read_only=false", "--set", "max_cost_usd_per_day=2.5", "--set", "max_tier=economy")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.config.read_text(encoding="utf-8")
        self.assertIn('    rules:\n      allow_tasks: [review, docs]\n      paths_deny: ["**/.env*", "infra/**"]\n', text)
        self.assertEqual(roster.read_roster(self.config)[1]["rules"]["max_cost_usd_per_day"], 2.5)
        again = json.loads(self.cli("rules", "grok", "--show").stdout)
        self.assertEqual(again["written"]["allow_tasks"], ["review", "docs"])
        self.assertIs(again["effective"]["read_only"], False)
        self.assertEqual(again["effective"]["max_tier"], "economy")
        self.assertEqual(again["summary"], "review,docs \u2264economy $0.5/$2.5")
        self.assertTrue(text.startswith(CONFIG.split("    rules:")[0].split("  - name: codex")[0]))  # everything above is untouched
        self.assertIn("  - name: codex\n    roles: [builder]\n\nbudget:\n  codex:\n    status: ok\n", text)  # and below
        self.assertEqual(self.cli("rules", "grok", "--reset").returncode, 0)
        self.assertEqual(self.config.read_text(encoding="utf-8"), CONFIG)

    def test_set_merges_into_the_existing_block(self) -> None:
        self.assertEqual(self.cli("rules", "codex", "--set", "deny_tasks=deploy").returncode, 0)
        self.assertEqual(self.cli("rules", "codex", "--set", "no_secrets=true").returncode, 0)
        rules = roster.read_roster(self.config)[2]["rules"]
        self.assertEqual(rules, {"deny_tasks": ["deploy"], "no_secrets": True})
        self.assertEqual(self.config.read_text(encoding="utf-8").count("rules:"), 1)
        self.assertIn("budget:\n  codex:\n    status: ok", self.config.read_text(encoding="utf-8"))

    def test_a_validation_error_exits_2_and_writes_nothing(self) -> None:
        for args in (["--set", "allow_tasks=review,teleport"], ["--set", "max_tier=ultra"], ["--set", "max_cost_usd_per_run=-1"],
                     ["--set", "colour=red"], ["--set", "read_only=maybe"], ["--set", "max_cost_usd_per_day=lots"], ["--set", "novalue"],
                     ["--set", "allow_tasks=merge", "--set", "deny_tasks=merge"]):
            done = self.cli("rules", "grok", *args)
            self.assertEqual(done.returncode, 2, args)
            self.assertIn("roster error", done.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), CONFIG)

    def test_unknown_agent_and_missing_config(self) -> None:
        self.assertEqual(self.cli("rules", "ghost", "--set", "read_only=true").returncode, 2)
        self.config.unlink()
        self.assertEqual(self.cli("rules", "claude", "--set", "read_only=true").returncode, 2)

    def test_exactly_one_action_is_required(self) -> None:
        self.assertEqual(self.cli("rules", "grok").returncode, 2)
        self.assertEqual(self.cli("rules", "grok", "--show", "--reset").returncode, 2)

    def test_add_edit_existing_keeps_the_rules_block(self) -> None:
        self.assertEqual(self.cli("rules", "grok", "--set", "allow_tasks=review").returncode, 0)
        before = roster.read_roster(self.config)[1]["rules"]
        text = roster.add_roster_entry(self.config.read_text(encoding="utf-8"), {"name": "grok", "auth": "api-key", "roles": ["reviewer"]})
        self.config.write_text(text, encoding="utf-8")
        self.assertEqual(roster.read_roster(self.config)[1]["rules"], before)

    def test_list_shows_the_rules_summary_and_todays_spend(self) -> None:
        self.assertEqual(self.cli("rules", "grok", "--set", "allow_tasks=review", "--set", "max_cost_usd_per_run=1").returncode, 0)
        agent_rules.record_spend("grok", 1.25, "r", self.root)
        rows = {r["name"]: r for r in json.loads(self.cli("list", "--json", "--config", str(self.config)).stdout)}
        self.assertEqual(rows["grok"]["rules"], "ro review ≤standard $1/$5")
        self.assertEqual(rows["grok"]["spent_today"], "$1.25")
        self.assertEqual((rows["claude"]["rules"], rows["claude"]["spent_today"]), ("-", "-"))
        table = self.cli("list", "--config", str(self.config)).stdout
        self.assertIn("ro review", table)
        self.assertIn("$1.25", table)


if __name__ == "__main__":
    unittest.main()
