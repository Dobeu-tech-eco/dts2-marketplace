"""Batch 18 round 2: the declarative policy gate (G-70), SDK runner hardening (G-71) and the lead wiring. No network."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from unittest import mock

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "policy-gate.sh"
CONTEXT_HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "context-guard.sh"
RUNNER: Final[Path] = PLUGIN_ROOT / "sdk" / "dts2-run.py"
LANES: Final[Path] = SCRIPTS / "lanes.py"
sys.path.insert(0, str(SCRIPTS))
import policy_gate  # noqa: E402
import state_io  # noqa: E402

CLEAN_ENV: Final[dict[str, str]] = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")}

FORCE_VARIANTS: Final[tuple[str, ...]] = (
    "git push --force origin feat", "git push -f origin feat", "git push origin +feat", "git push --force-with-lease origin feat",
    "git push origin feat -f", "git push -fu origin feat", 'git push "--force" origin feat', "git push --for''ce origin feat",
    "git push --force-with-lease=feat:abc origin feat", "git push --force-if-includes origin feat",
    'bash -lc "git push --force origin feat"', "sh -c 'git push -f'", "env -i git push --force", "env -i FOO=1 git push -f",
    "command git push -f", "git -C other push --force", "git -C other -c a=b push -f", "git status && git push -f origin feat",
    "git status; git push -f", "echo ok | git push -f", "sudo git push -f", "timeout 5 git push -f", "nohup git push -f &",
    "eval 'git push -f'", "echo $(git push -f)", "xargs git push -f", "ssh host 'git push -f origin feat'",
    "/usr/bin/git push -f", "FOO=1 git push --force", 'bash -c "echo hi; git push -f"', "git push --forc origin feat",
)
BYPASS_DENIED: Final[tuple[tuple[str, str], ...]] = (
    ("gh pr merge 3 --admin", "admin-flag"), ("env -i gh pr merge 3 --admin", "admin-flag"), ("gh api -X PUT x --admin", "admin-flag"),
    ("vercel deploy", "deploy-vercel"), ("npx vercel deploy --prod", "deploy-vercel"), ("vercel --prod", "deploy-vercel-prod"),
    ("wrangler deploy", "deploy-wrangler"), ("npx wrangler publish", "deploy-wrangler-publish"),
    ("pnpm dlx wrangler deploy", "deploy-wrangler"), ("fly deploy", "deploy-fly"), ("flyctl deploy --remote-only", "deploy-fly"),
    ("npm exec -- fly deploy", "deploy-fly"), ("netlify deploy --prod", "deploy-netlify"), ("supabase db push", "deploy-supabase"),
    ("gh secret set A", "gh-secret"), ("gh -R o/r secret list", "gh-secret"), ("vercel env pull", "vercel-env"),
    ("vercel --token x env ls", "vercel-env"), ("gh repo delete o/r --yes", "gh-repo-delete"),
    ("env", "env-dump"), ("printenv", "env-dump"), ("env | sort", "env-dump"), ("sudo env", "env-dump"), ("env -0", "env-dump"),
    ('bash -c "echo hi; env"', "env-dump"), ("cd x && printenv", "env-dump"), ("env > /tmp/x", "env-dump"),
)
ALLOWED: Final[tuple[str, ...]] = (
    "git push -u origin feat", "git push origin feat", "git status", "git commit -m 'git push --force'", "echo git push -f",
    "grep -r 'git push -f' docs", "printenv HOME", "env FOO=1 python3 x.py", "env -i gh pr list", "gh pr create --title t --body '$B'",
    "gh pr view 3", "vercel logs", "git push --follow-tags origin feat", "SHA=$(git rev-parse HEAD)", "python3 -m unittest",
    "git log --oneline | head", "wrangler dev", "supabase db diff", "git add src/a.py", "ls && pwd",
)


def payload(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="dts2-b18-")).resolve()
    subprocess.run(["git", "init", "-q", "-b", "feat", str(repo)], check=True)
    return repo


def approve(repo: Path, kind: str, *keys: str) -> None:
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({"dts2_approvals": {kind: list(keys)}}), encoding="utf-8")


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PolicyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo()
        self.policy: dict[str, Any] = policy_gate.load_policy()

    def decide(self, command: str) -> str | None:
        with mock.patch.dict(os.environ, {"DTS2_SON": "", "DTS2_UNATTENDED": ""}):
            return policy_gate.decide(payload(command), self.repo, self.policy)

    def test_force_push_variants_are_denied(self) -> None:
        for command in FORCE_VARIANTS:
            reason = self.decide(command)
            self.assertIsNotNone(reason, command)
            self.assertTrue(str(reason).startswith("force-push"), f"{command}: {reason}")

    def test_deny_table_names_the_rule(self) -> None:
        for command, rule_id in BYPASS_DENIED:
            reason = self.decide(command)
            self.assertIsNotNone(reason, command)
            self.assertTrue(str(reason).startswith(rule_id), f"{command}: {reason}")

    def test_ordinary_commands_pass(self) -> None:
        for command in ALLOWED:
            self.assertIsNone(self.decide(command), command)

    def test_expansion_hiding_the_command_or_flags_is_refused(self) -> None:
        self.assertIsNotNone(self.decide("$GIT push origin feat"))
        self.assertIsNotNone(self.decide('git push origin "$BRANCH"'))
        self.assertIsNotNone(self.decide("git push $FLAGS origin feat"))
        self.assertIsNone(self.decide("$HOME/bin/tool run"))

    def test_non_bash_tools_and_junk_payloads_pass(self) -> None:
        self.assertIsNone(policy_gate.decide({"tool_name": "Read", "tool_input": {"file_path": "x"}}, self.repo, self.policy))
        self.assertIsNone(policy_gate.decide({"tool_name": "Bash", "tool_input": "x"}, self.repo, self.policy))

    def test_pr_merge_needs_the_human_approval_for_that_number(self) -> None:
        self.assertIn("pr-merge", str(self.decide("gh pr merge 42 --squash")))
        approve(self.repo, "merge", "42")
        self.assertIsNone(self.decide("gh pr merge 42 --squash"))
        self.assertIsNone(self.decide("env -i gh -R o/r pr merge 42"))
        self.assertIn("pr-merge", str(self.decide("gh pr merge 43")))
        self.assertIn("pr-merge", str(self.decide("gh pr merge")), "the current-branch form names no number")
        self.assertIn("pr-merge", str(self.decide("gh pr merge feature-branch")))
        self.assertIsNone(self.decide("gh pr merge https://github.com/o/r/pull/42"))

    def test_approvals_of_another_kind_do_not_count(self) -> None:
        approve(self.repo, "recorded_yes", "42")
        self.assertIn("pr-merge", str(self.decide("gh pr merge 42")))

    def test_push_to_the_default_branch_needs_the_branch_approval(self) -> None:
        for command in ("git push origin main", "git push origin HEAD:main", "git push origin feat:master", "bash -lc 'git push origin main'",
                        "command git -C . push origin main", "git push origin main && echo ok"):
            self.assertIn("push-default", str(self.decide(command)), command)
        approve(self.repo, "merge", "main")
        self.assertIsNone(self.decide("git push origin main"))
        self.assertIn("push-default", str(self.decide("git push origin master")))
        self.assertIsNone(self.decide("git push origin feat"))
        self.assertIn("force-push", str(self.decide("git push --force origin main")), "an approval never lifts a deny rule")

    def test_secret_scanner_absent_is_red_when_unattended(self) -> None:
        env = {"DTS2_SON": "1", "PATH": "/nonexistent", "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(policy_gate.secret_scan_red())
            for command in ("git add -A", "git add --all", "git add .", "git -C x add -A"):
                self.assertIn("add-all", str(policy_gate.decide(payload(command), self.repo, self.policy)), command)
            self.assertIsNone(policy_gate.decide(payload("git add src/a.py"), self.repo, self.policy))
        with mock.patch.dict(os.environ, {**env, "DTS2_GITLEAKS_BIN": "/bin/true"}, clear=True):
            self.assertFalse(policy_gate.secret_scan_red())
            self.assertIsNone(policy_gate.decide(payload("git add -A"), self.repo, self.policy))
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}, clear=True):
            self.assertFalse(policy_gate.secret_scan_red(), "an attended session is not red")
            self.assertIsNone(policy_gate.decide(payload("git add -A"), self.repo, self.policy))

    def test_policy_file_is_valid_and_every_rule_has_an_id_and_reason(self) -> None:
        for table in ("deny", "require_approval", "scanner_required"):
            for rule in self.policy[table]:
                self.assertTrue(rule["id"] and rule["reason"], rule)

    def test_hook_end_to_end_prints_the_documented_deny_json(self) -> None:
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload("bash -lc 'git push -f'")), capture_output=True, text=True,
                              cwd=self.repo, env={**CLEAN_ENV, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}, check=False)
        out = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual((done.returncode, out["permissionDecision"]), (0, "deny"))
        self.assertIn("force-push", out["permissionDecisionReason"])
        log = (self.repo / state_io.rel("policy-gate.log")).read_text(encoding="utf-8")
        self.assertIn("force-push", log)
        quiet = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload("git status")), capture_output=True, text=True,
                               cwd=self.repo, env={**CLEAN_ENV, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}, check=False)
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ""))

    def test_hook_is_registered_and_switchable(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        commands = [h["command"] for entry in hooks for h in entry["hooks"]]
        self.assertTrue(any("policy-gate.sh" in c for c in commands))
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\npolicy_gate: false\n---\n", encoding="utf-8")
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload("git push -f")), capture_output=True, text=True,
                              cwd=self.repo, env={**CLEAN_ENV, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}, check=False)
        self.assertEqual(done.stdout, "")

    def test_python_invocation_is_isolated(self) -> None:
        self.assertIn("python3 -I", HOOK.read_text(encoding="utf-8"))


class SdkRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner: ModuleType = load_module("dts2_run_b18", RUNNER)
        self.repo: Path = make_repo()

    def test_only_the_verifier_gets_bash(self) -> None:
        for role in ("lead", "builder", "reviewer"):
            self.assertNotIn("Bash", self.runner.role_tools(role), role)
        self.assertIn("Bash", self.runner.role_tools("verifier"))
        self.assertNotIn("Bash", self.runner.role_tools("unknown-role"))
        self.assertIn("Write", self.runner.role_tools("builder"))
        self.assertNotIn("Write", self.runner.role_tools("reviewer"))

    def test_options_pin_tools_user_settings_and_caps(self) -> None:
        agent = self.runner.load_agent("verifier")
        kwargs = self.runner.agent_options_kwargs(agent, self.repo, write=False)
        self.assertEqual(kwargs["setting_sources"], ["user"])
        self.assertEqual(kwargs["tools"], kwargs["allowed_tools"])
        self.assertIn("Bash", kwargs["tools"])
        self.assertEqual((kwargs["max_turns"], kwargs["max_budget_usd"]), (self.runner.DEFAULT_MAX_TURNS, self.runner.DEFAULT_MAX_BUDGET_USD))
        builder = self.runner.agent_options_kwargs(self.runner.load_agent("builder"), self.repo, write=True)
        self.assertNotIn("Bash", builder["tools"])
        self.assertEqual(builder["permission_mode"], "acceptEdits")

    def test_options_are_accepted_by_the_installed_sdk(self) -> None:
        try:
            from claude_agent_sdk import ClaudeAgentOptions
        except ImportError:
            self.skipTest("claude-agent-sdk is not installed")
        kwargs = self.runner.agent_options_kwargs(self.runner.load_agent("lead"), self.repo, write=False)
        options = ClaudeAgentOptions(**kwargs)
        self.assertEqual(options.setting_sources, ["user"])

    def test_caps_follow_the_budget_settings(self) -> None:
        (self.repo / state_io.CONFIG_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / state_io.CONFIG_REL).write_text("budget:\n  max_turns: 7\n  max_usd: 1.5\n", encoding="utf-8")
        self.assertEqual(self.runner.budget_caps(self.repo), (7, 1.5))

    def test_requirements_pin_an_exact_version(self) -> None:
        line = (PLUGIN_ROOT / "sdk" / "requirements.txt").read_text(encoding="utf-8").strip()
        self.assertRegex(line, r"^claude-agent-sdk==\d+\.\d+\.\d+$")

    def test_second_opinion_env_never_carries_the_anthropic_credentials(self) -> None:
        source = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "o",
                  "GH_TOKEN": "g", "CODEX_API_KEY": "ok"}
        with mock.patch.dict(os.environ, source, clear=True):
            env = self.runner.second_opinion_env({"ANTHROPIC_API_KEY": "from-profile"}, "codex-api")
        self.assertEqual({k for k in env if k.startswith(("ANTHROPIC", "CLAUDE_CODE", "GH_"))}, set())
        self.assertEqual(env["CODEX_API_KEY"], "ok")

    def test_secret_scan_gate_is_red_without_a_scanner_and_before_add(self) -> None:
        (self.repo / "a.txt").write_text("x", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent", "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}):
            self.assertIn("no secret scanner", str(self.runner.secret_scan_gate(self.repo)))
            with mock.patch.object(self.runner.subprocess, "run") as run:
                self.assertFalse(self.runner.commit_changes(self.repo, "task"))
            run.assert_not_called()  # git add -A never ran

    def test_secret_scan_gate_passes_with_a_clean_scanner_and_fails_on_findings(self) -> None:
        folder = Path(tempfile.mkdtemp())
        ok = folder / "ok.py"
        ok.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        bad = folder / "bad.py"
        bad.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DTS2_GITLEAKS_BIN": str(ok), "DTS2_TRUFFLEHOG_BIN": ""}):
            self.assertIsNone(self.runner.secret_scan_gate(self.repo))
        with mock.patch.dict(os.environ, {"DTS2_GITLEAKS_BIN": str(bad), "DTS2_TRUFFLEHOG_BIN": ""}):
            self.assertIn("failed", str(self.runner.secret_scan_gate(self.repo)))


class LeadWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo()

    def lanes(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        base = {k: v for k, v in os.environ.items() if k not in ("DTS2_SON", "DTS2_SON_BRANCH_PREFIX")}
        return subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.repo), *args], capture_output=True, text=True,
                              env={**base, **env}, check=False)

    def test_publish_subcommand_calls_publish_lane_and_refuses_a_son(self) -> None:
        lanes_cli = load_module("lanes_cli_b18", LANES)
        args = lanes_cli.build_parser().parse_args(["publish", "20261105-1", "--lane", "a"])
        with mock.patch.object(lanes_cli, "publish_lane", return_value={"ok": True, "pr": "9"}) as publish:
            result = lanes_cli.publish_command(args, self.repo)
        self.assertEqual(result["pr"], "9")
        publish.assert_called_once()
        call = publish.call_args.args
        self.assertEqual((call[1], call[2], call[3]), ("a", "dts2/20261105-1/lane-a", "dev"))
        with mock.patch.dict(os.environ, {"DTS2_SON": "1"}):
            self.assertFalse(lanes_cli.publish_command(args, self.repo)["ok"])

    def test_call_runs_under_a_scrubbed_env(self) -> None:
        script = self.repo / "show.py"
        script.write_text("import json, os\nprint(json.dumps(sorted(k for k in os.environ if k in "
                          "('GH_TOKEN', 'ANTHROPIC_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'PATH'))))\n", encoding="utf-8")
        done = self.lanes("call", "20261105-1", "--label", "t", "--cost-source", "none", "--", sys.executable, str(script),
                          GH_TOKEN="g", ANTHROPIC_API_KEY="k", AWS_SECRET_ACCESS_KEY="a")
        result = json.loads(done.stdout)
        self.assertEqual(json.loads(result["stdout"]), ["PATH"])

    def test_preflight_fails_on_auth_and_on_plugin_errors(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        from lanes import supervisor as sup
        text = Path(sup.__file__).read_text(encoding="utf-8")
        for needle in ("auth_problem(", "init_plugin_errors(", "head_push_problem(", "stream-json"):
            self.assertIn(needle, text)

    def test_preflight_end_to_end_reports_each_problem(self) -> None:
        folder = Path(tempfile.mkdtemp())
        claude = folder / "claude.py"
        claude.write_text(
            "import json, sys\n"
            "if '--version' in sys.argv:\n    print('2.1.250'); sys.exit(0)\n"
            "if sys.argv[1:3] == ['auth', 'status']:\n    sys.exit(1)\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init', 'plugin_errors': ['hooks.json invalid']}))\n"
            "print(json.dumps({'type': 'result', 'is_error': True, 'result': 'not logged in'}))\n", encoding="utf-8")
        git = folder / "git.py"
        git.write_text("import sys\nsys.exit(1 if 'push' in sys.argv[1:] else 0)\n", encoding="utf-8")
        done = self.lanes("preflight", "20261105-1", DTS2_CLAUDE_BIN=str(claude), DTS2_GIT_BIN=str(git))
        problems = " | ".join(json.loads(done.stdout)["problems"])
        self.assertIn("no login", problems)
        self.assertIn("hooks.json invalid", problems)
        self.assertIn("git push --dry-run", problems)

    def test_son_command_uses_the_son_model_setting_and_can_wrap(self) -> None:
        from lanes.planner import son_command
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nson_model: sonnet\n---\n", encoding="utf-8")
        manifest = {"stamp": "20261105-1", "lanes": [{"id": "a"}]}
        plain = son_command(manifest, "a", self.repo, self.repo)
        self.assertEqual(plain["argv"][plain["argv"].index("--model") + 1], "sonnet")
        lane_dir = self.repo / "lane-a"
        lane_dir.mkdir()
        wrapped = son_command(manifest, "a", self.repo, self.repo, lane_dir=lane_dir)
        self.assertIn("--session-id", wrapped["argv"])
        self.assertIn("stream-json", wrapped["argv"])
        self.assertTrue((lane_dir / "son.json").is_file())

    def test_son_permission_mode_defaults_to_dont_ask(self) -> None:
        import settings_cache
        self.assertEqual(settings_cache.DEFAULTS["local"]["son_permission_mode"], "dontAsk")

    def test_override_kind_maps_to_the_approvals_channel_name(self) -> None:
        from lanes import policy
        approve(self.repo, "lane_override", "b")
        # Patch Path.cwd, not os.getcwd: Python 3.10's pathlib binds os.getcwd at import time.
        with mock.patch.dict(os.environ, {}), mock.patch.object(Path, "cwd", return_value=self.repo):
            self.assertTrue(policy.human_approved("override", "b"))
            self.assertFalse(policy.human_approved("override", "c"))
            self.assertFalse(policy.human_approved("no-such-kind", "b"))

    def test_son_brief_says_commit_and_stop(self) -> None:
        brief = (PLUGIN_ROOT / "templates" / "son-brief.md").read_text(encoding="utf-8")
        self.assertIn("the head publishes", brief)
        self.assertNotIn("Open one PR", brief)
        self.assertNotIn("Push only", brief)

    def test_skill_text_describes_the_scrubbed_call_and_publish(self) -> None:
        for name in ("phase-0-preflight.md", "phase-1-gate.md"):
            text = (PLUGIN_ROOT / "skills" / "autopilot" / name).read_text(encoding="utf-8")
            self.assertIn("lanes.py publish", text, name)
            self.assertIn("scrubbed environment", text, name)

    def test_council_ledger_appends_once_per_attempt(self) -> None:
        import council
        ballots = self.repo / "ballots"
        ballots.mkdir()
        (ballots / "seat-a.md").write_text("VOTE: APPROVE\nreason\n", encoding="utf-8")
        decision = self.repo / "decision.md"
        decision.write_text("DECISION: APPROVE\n## Head of council brief\nbrief\n", encoding="utf-8")
        out = self.repo / "council.md"
        tally = {"approve": 3, "reject": 2}
        council.write_ledger(ballots, tally, decision, "step-1", "20261105-1", out)
        again = council.write_ledger(ballots, tally, decision, "step-1", "20261105-1", out)
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(out.read_text(encoding="utf-8").count("## Council 20261105-1"), 1)
        council.write_ledger(ballots, tally, decision, "step-1", "20261105-1", out, attempt=2)
        self.assertEqual(out.read_text(encoding="utf-8").count("## Council 20261105-1"), 2)

    def test_action_item_add_with_a_stamp_is_idempotent(self) -> None:
        (self.repo / state_io.ACTION_ITEMS_REL).parent.mkdir(parents=True, exist_ok=True)
        script = SCRIPTS / "action-items.py"

        def add(attempt: str) -> dict[str, Any]:
            done = subprocess.run([sys.executable, "-I", str(script), str(self.repo), "add", "Decisions", "decide X", "--stamp", "s1",
                                   "--step", "3", "--attempt", attempt], capture_output=True, text=True, check=False)
            parsed: dict[str, Any] = json.loads(done.stdout)
            return parsed

        self.assertNotIn("duplicate", add("1"))
        self.assertTrue(add("1")["duplicate"])
        self.assertNotIn("duplicate", add("2"))
        rows = (self.repo / state_io.ACTION_ITEMS_REL).read_text(encoding="utf-8").count("decide X")
        self.assertEqual(rows, 2)

    def test_lessons_regress_with_a_stamp_counts_once(self) -> None:
        lessons = SCRIPTS / "lessons.py"
        path = self.repo / state_io.rel("lessons.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Lessons\n\n- [L-001] never do X (files: a.py, promoted_at: 2026-11-05)\n", encoding="utf-8")

        def regress() -> dict[str, Any]:
            done = subprocess.run([sys.executable, "-I", str(lessons), str(self.repo), "regress", "L-001", "--stamp", "s1", "--step", "3"],
                                  capture_output=True, text=True, check=False)
            parsed: dict[str, Any] = json.loads(done.stdout)
            return parsed

        self.assertNotIn("duplicate", regress())
        self.assertTrue(regress()["duplicate"])

    def test_context_guard_hook_parks_a_son_through_the_mailbox(self) -> None:
        text = CONTEXT_HOOK.read_text(encoding="utf-8")
        self.assertIn("lanes.py", text)
        self.assertIn("mailbox park", text)
        self.assertIn("--reason context-guard", text)
        self.assertNotIn("status.json", text)
        folder = Path(tempfile.mkdtemp())
        (folder / "lanes.py").write_text("import json, sys\nopen(sys.argv[0] + '.args', 'w').write(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        plugin = folder / "plugin"
        (plugin / "scripts").mkdir(parents=True)
        (plugin / "hooks").mkdir()
        shutil.copy(PLUGIN_ROOT / "hooks" / "lib-settings.sh", plugin / "hooks" / "lib-settings.sh")
        (plugin / "scripts" / "context-guard.py").write_text("print('{\"additionalContext\": \"fired\"}')\n", encoding="utf-8")
        (plugin / "scripts" / "lanes.py").write_text(
            "import json, sys\nopen(sys.argv[0] + '.args', 'w').write(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        env = {**CLEAN_ENV, "CLAUDE_PLUGIN_ROOT": str(plugin), "DTS2_SON_BRANCH_PREFIX": "dts2/20261105-1/lane-a", "CLAUDE_CODE_SESSION_ID": "sess-1"}
        done = subprocess.run(["bash", str(CONTEXT_HOOK)], input="{}", capture_output=True, text=True, cwd=self.repo, env=env, check=False)
        self.assertEqual(done.returncode, 0)
        self.assertIn("fired", done.stdout)
        args = json.loads((plugin / "scripts" / "lanes.py.args").read_text(encoding="utf-8"))
        self.assertEqual(args[:5], ["mailbox", "park", "20261105-1", "--lane", "a"])
        self.assertIn("context-guard", args)
        self.assertIn("sess-1", args)

    def test_context_guard_hook_outside_a_son_does_not_park(self) -> None:
        plugin = Path(tempfile.mkdtemp()) / "plugin"
        (plugin / "scripts").mkdir(parents=True)
        (plugin / "hooks").mkdir()
        shutil.copy(PLUGIN_ROOT / "hooks" / "lib-settings.sh", plugin / "hooks" / "lib-settings.sh")
        (plugin / "scripts" / "context-guard.py").write_text("print('fired')\n", encoding="utf-8")
        (plugin / "scripts" / "lanes.py").write_text("raise SystemExit('must not run')\n", encoding="utf-8")
        env = {**CLEAN_ENV, "CLAUDE_PLUGIN_ROOT": str(plugin)}
        done = subprocess.run(["bash", str(CONTEXT_HOOK)], input="{}", capture_output=True, text=True, cwd=self.repo, env=env, check=False)
        self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, "fired", ""))


if __name__ == "__main__":
    unittest.main()
