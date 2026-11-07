"""Batch 16: hooks hardening (G-30..G-41)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"
TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "dts2-harness.local.md"
WORKFLOW: Final[Path] = PLUGIN_ROOT.parent.parent / ".github" / "workflows" / "test.yml"
SENTINEL: Final[str] = "SENTINEL-DEFAULT"
PLANTED: Final[str] = "open('PLANTED-RAN', 'w').write('x')\n"
SETTINGS_REL: Final[str] = ".claude/dts2-harness.local.md"
sys.path.insert(0, str(SCRIPTS))

from lanes.planner import read_setting  # noqa: E402


def run_hook(name: str, cwd: Path, stdin: str = "", env: dict[str, str] | None = None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOKS / name), *args], cwd=str(cwd), input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, check=False)


def make_repo() -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    return repo


def write_settings(repo: Path, body: str) -> None:
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / SETTINGS_REL).write_bytes(f"---\n{body}\n---\n".encode("utf-8"))


def bash_setting(repo: Path, key: str) -> str:
    script: str = f'source "{HOOKS / "lib-settings.sh"}"; setting "$1" "{SENTINEL}"'
    done = subprocess.run(["bash", "-c", script, "bash", key], cwd=str(repo), capture_output=True, text=True, check=True)
    return done.stdout.rstrip("\n")


class PythonIsolationTests(unittest.TestCase):
    """G-30: every python3 a hook starts runs with -I, so a json.py in the repo is never imported."""

    def test_no_hook_runs_python3_without_isolation(self) -> None:
        bare = re.compile(r"python3(?! -I)(?! >/dev/null)")
        for hook in sorted(HOOKS.glob("*.sh")):
            for number, line in enumerate(hook.read_text(encoding="utf-8").splitlines(), 1):
                code: str = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
                if "command -v python3" in code:
                    continue
                self.assertIsNone(bare.search(code), f"{hook.name}:{number} runs python3 without -I")

    def plant(self, repo: Path) -> None:
        (repo / "json.py").write_text(PLANTED, encoding="utf-8")

    def test_session_lessons_ignores_planted_json(self) -> None:
        repo: Path = make_repo()
        (repo / ".harness" / "lessons.md").write_text("- lesson one\n", encoding="utf-8")
        self.plant(repo)
        result = run_hook("session-lessons.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertIn("dts2-harness scope", result.stdout)  # the scope-check python ran
        self.assertFalse((repo / "PLANTED-RAN").exists())

    def test_stop_checks_ignores_planted_json(self) -> None:
        repo: Path = make_repo()
        self.plant(repo)
        result = run_hook("stop-checks.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((repo / ".harness" / "handoff" / "latest.md").is_file())
        self.assertFalse((repo / "PLANTED-RAN").exists())

    def test_pre_compact_ignores_planted_json(self) -> None:
        repo: Path = make_repo()
        self.plant(repo)
        result = run_hook("pre-compact.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((repo / ".harness" / "handoff" / "latest.md").is_file())
        self.assertFalse((repo / "PLANTED-RAN").exists())

    def test_session_end_ignores_planted_json(self) -> None:
        repo: Path = make_repo()
        self.plant(repo)
        result = run_hook("session-end.sh", repo, json.dumps({"reason": "other", "session_id": "s"}))
        self.assertEqual(result.returncode, 0)
        self.assertFalse((repo / "PLANTED-RAN").exists())


class SettingsParityTests(unittest.TestCase):
    """G-31: hooks/lib-settings.sh and lanes.read_setting read the same value for the same file."""

    def test_every_template_key_reads_the_same(self) -> None:
        repo: Path = make_tmp_home()
        (repo / ".claude").mkdir()
        shutil.copy(TEMPLATE, repo / SETTINGS_REL)
        keys: list[str] = re.findall(r"^([a-z_]+):", TEMPLATE.read_text(encoding="utf-8").split("---")[1], re.M)
        self.assertGreater(len(keys), 15)
        for key in keys:
            self.assertEqual(bash_setting(repo, key), read_setting(repo, key, SENTINEL), key)

    def test_comments_crlf_and_quotes_read_the_same(self) -> None:
        repo: Path = make_tmp_home()
        (repo / ".claude").mkdir()
        body: str = ('enabled: true # keep\r\nname: "quoted value"  # note\r\nsingle: \'x y\'\r\nhashed: "a#b"\r\n'
                     'empty:\r\nspaced:    padded   \r\ntabbed:\t7\r\n')
        (repo / SETTINGS_REL).write_bytes(f"---\r\n{body}---\r\nlate: 1\r\n".encode("utf-8"))
        for key in ("enabled", "name", "single", "hashed", "empty", "spaced", "tabbed", "late", "missing"):
            self.assertEqual(bash_setting(repo, key), read_setting(repo, key, SENTINEL), key)
        self.assertEqual(bash_setting(repo, "enabled"), "true")
        self.assertEqual(bash_setting(repo, "name"), "quoted value")


class StopChecksTests(unittest.TestCase):
    def blocking_repo(self, extra: str = "") -> Path:
        repo: Path = make_repo()
        (repo / ".harness" / "checks.sh").write_text("echo RED-CHECK; exit 1\n", encoding="utf-8")
        write_settings(repo, "stop_checks_block: true\n" + extra)
        return repo

    def test_red_check_blocks_once_when_enabled(self) -> None:
        repo: Path = self.blocking_repo()
        result = run_hook("stop-checks.sh", repo, "{}")
        reply: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(reply["decision"], "block")
        self.assertIn("RED-CHECK", reply["reason"])

    def test_stop_hook_active_never_blocks_twice(self) -> None:
        repo: Path = self.blocking_repo()
        result = run_hook("stop-checks.sh", repo, json.dumps({"stop_hook_active": True}))
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual(result.returncode, 0)

    def test_default_never_blocks(self) -> None:
        repo: Path = make_repo()
        (repo / ".harness" / "checks.sh").write_text("echo RED-CHECK; exit 1\n", encoding="utf-8")
        result = run_hook("stop-checks.sh", repo, "{}")
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("RED-CHECK", result.stderr)

    def test_son_mode_skips_repo_defined_checks(self) -> None:
        repo: Path = self.blocking_repo()
        result = run_hook("stop-checks.sh", repo, "{}", {"DTS2_SON": "1"})
        self.assertNotIn("RED-CHECK", result.stderr + result.stdout)
        self.assertEqual(result.returncode, 0)

    def fake_node_repo(self) -> Path:
        repo: Path = make_repo()
        (repo / "package.json").write_text("{}", encoding="utf-8")
        (repo / "tsconfig.json").write_text("{}", encoding="utf-8")
        (repo / "eslint.config.js").write_text("", encoding="utf-8")
        (repo / "a.ts").write_text("x\n", encoding="utf-8")
        bindir: Path = repo / "node_modules" / ".bin"
        bindir.mkdir(parents=True)
        for tool in ("tsc", "eslint"):
            (bindir / tool).write_text(f'#!/usr/bin/env bash\necho "{tool} $*" >> "$LOG"\n', encoding="utf-8")
            (bindir / tool).chmod(0o755)
        subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
        subprocess.run(["git", "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-qm", "i"], cwd=str(repo), check=True)
        (repo / "a.ts").write_text("y\n", encoding="utf-8")
        return repo

    def test_local_binaries_only_with_double_dash_and_never_npx(self) -> None:
        repo: Path = self.fake_node_repo()
        fake: Path = make_tmp_home()
        log: Path = fake / "log"
        npx: Path = fake / "npx"
        npx.write_text(f'#!/usr/bin/env bash\necho NPX >> "{log}"\n', encoding="utf-8")
        npx.chmod(0o755)
        run_hook("stop-checks.sh", repo, "", {"LOG": str(log), "PATH": f"{fake}:{os.environ['PATH']}"})
        text: str = log.read_text(encoding="utf-8")
        self.assertIn("tsc --noEmit", text)
        self.assertIn("eslint --no-error-on-unmatched-pattern -- a.ts", text)
        self.assertNotIn("NPX", text)

    def test_missing_local_binaries_skip_quietly(self) -> None:
        repo: Path = self.fake_node_repo()
        shutil.rmtree(repo / "node_modules" / ".bin")
        result = run_hook("stop-checks.sh", repo)
        self.assertEqual(result.returncode, 0)

    def test_deadline_below_hook_timeout_saves_partial_fingerprint(self) -> None:
        timeout: int = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["timeout"]
        text: str = (HOOKS / "stop-checks.sh").read_text(encoding="utf-8")
        self.assertIn("DEADLINE_MARGIN_S", text)
        self.assertIn("hooks.json", text)
        self.assertGreater(timeout, 10)
        repo: Path = make_repo()
        (repo / ".harness" / "checks.sh").write_text("sleep 30\n", encoding="utf-8")
        fake: Path = make_tmp_home()
        copy: Path = fake / "plugin"
        shutil.copytree(PLUGIN_ROOT / "hooks", copy / "hooks")
        shutil.copytree(PLUGIN_ROOT / "scripts", copy / "scripts")
        data: dict[str, Any] = json.loads((copy / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        data["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 7  # deadline = 7 - 5 margin = 2 seconds
        (copy / "hooks" / "hooks.json").write_text(json.dumps(data), encoding="utf-8")
        result = run_hook("stop-checks.sh", repo, "", {"CLAUDE_PLUGIN_ROOT": str(copy)})
        self.assertEqual(result.returncode, 0)
        marker: str = (repo / ".harness" / "cache" / "stop-fingerprint").read_text(encoding="utf-8")
        self.assertTrue(marker.endswith(" partial"), marker)


class ContextGuardTests(unittest.TestCase):
    def payload(self, repo: Path, event: str = "PostToolUse") -> str:
        transcript: Path = repo / "t.jsonl"
        transcript.write_text('{"type": "tool_use"}\n' * 5, encoding="utf-8")
        return json.dumps({"session_id": "g35", "cwd": str(repo), "transcript_path": str(transcript), "hook_event_name": event})

    def run_guard(self, repo: Path, event: str = "PostToolUse", extra: str = "") -> str:
        write_settings(repo, "context_guard_tool_calls: 3\n" + extra)
        tmp: Path = make_tmp_home()
        return run_hook("context-guard.sh", repo, self.payload(repo, event), {"TMPDIR": str(tmp)}).stdout

    def make_runs(self, repo: Path) -> None:
        for stamp, plan in (("20260101-000001", True), ("20260202-000002", False)):
            run: Path = repo / ".harness" / "runs" / stamp
            run.mkdir(parents=True)
            if plan:
                (run / "plan.md").write_text("plan\n", encoding="utf-8")

    def test_old_run_plan_does_not_silence_the_current_run(self) -> None:
        repo: Path = make_repo()
        self.make_runs(repo)
        out: str = self.run_guard(repo)
        self.assertIn("CONTEXT GUARD (spike)", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_current_run_plan_silences_the_guard(self) -> None:
        repo: Path = make_repo()
        self.make_runs(repo)
        (repo / ".harness" / "runs" / "20260202-000002" / "plan.md").write_text("plan\n", encoding="utf-8")
        self.assertEqual(self.run_guard(repo), "")

    def test_stop_output_is_opt_in(self) -> None:
        repo: Path = make_repo()
        plain: dict[str, Any] = json.loads(self.run_guard(repo))
        self.assertNotIn("continue", plain)
        stopping: dict[str, Any] = json.loads(self.run_guard(make_repo(), extra="context_guard_stop: true"))
        self.assertIs(stopping["continue"], False)
        self.assertIn("context guard", stopping["stopReason"])

    def test_batch_event_names_itself_in_the_output(self) -> None:
        out: dict[str, Any] = json.loads(self.run_guard(make_repo(), "PostToolBatch"))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolBatch")


class IgnoredPathsTests(unittest.TestCase):
    def test_cache_and_locks_are_ignored(self) -> None:
        text: str = (SCRIPTS / "ensure-ignored.py").read_text(encoding="utf-8")
        self.assertIn('".harness/cache/"', text)
        self.assertIn('".harness/.locks/"', text)


class HooksJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks: dict[str, Any] = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    def test_gh_api_hook_has_an_if_matcher(self) -> None:
        conditions: set[str] = {h.get("if", "") for g in self.hooks["PostToolUse"] for h in g["hooks"] if "pr-receipt" in h["command"]}
        self.assertEqual(conditions, {"Bash(gh pr create *)", "Bash(gh pr edit *)", "Bash(gh api *)"})

    def test_context_guard_also_runs_on_post_tool_batch(self) -> None:
        self.assertIn("context-guard.sh", json.dumps(self.hooks["PostToolBatch"]))

    def test_every_hook_script_is_executable(self) -> None:
        for hook in HOOKS.glob("*.sh"):
            self.assertTrue(os.access(hook, os.X_OK), hook.name)


class PrReceiptTests(unittest.TestCase):
    """G-36: receipt chosen by branch, gh api POST recognised, template push opt-in."""
    marker = "## Change receipt"

    def receipts(self, repo: Path) -> None:
        for name, text in (("20260101-000001", "ONE"), ("ship-20260301-000003", "SHIP"), ("zz-named", "NAMED"),
                           ("20260202-000002/a", "LANE")):
            folder: Path = repo / ".harness" / "runs" / name
            folder.mkdir(parents=True)
            (folder / "receipt.md").write_text(f"{self.marker}\n{text}\n", encoding="utf-8")

    def pick(self, branch: str) -> str:
        repo: Path = make_tmp_home()
        self.receipts(repo)
        code: str = ("import sys; sys.path.insert(0, sys.argv[1]); import pr_receipt; "
                     "found = pr_receipt.branch_receipt(sys.argv[2]) or pr_receipt.newest_receipt(); print(found or '')")
        done = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPTS), branch], cwd=str(repo), capture_output=True,
                              text=True, check=False)
        return done.stdout.strip()

    def test_branch_stamp_selects_its_run(self) -> None:
        self.assertEqual(self.pick("dts2/20260101-000001/main"), ".harness/runs/20260101-000001/receipt.md")
        self.assertEqual(self.pick("dts2/20260202-000002/lane-a"), ".harness/runs/20260202-000002/a/receipt.md")

    def test_other_branches_take_newest_stamped_or_ship_run_not_a_named_folder(self) -> None:
        self.assertEqual(self.pick("feature"), ".harness/runs/ship-20260301-000003/receipt.md")

    def test_gh_api_post_to_pulls_is_a_pr_create(self) -> None:
        api: list[str] = [sys.executable, "-I", str(SCRIPTS / "pr_payload.py"), "api"]
        command: str = "gh api repos/o/r/pulls -X POST -f title=t -f head=h -f base=main"
        payload: str = json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command},
                                   "tool_response": {"stdout": '{"html_url": "https://github.com/o/r/pull/9"}'}})
        done = subprocess.run(api, input=payload, capture_output=True, text=True, check=False)
        self.assertEqual(done.stdout.split("\n")[:2], ["s1", "https://github.com/o/r/pull/9"])
        get = json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh api repos/o/r/pulls"}})
        refused = subprocess.run(api, input=get, capture_output=True, text=True, check=False)
        self.assertEqual(refused.returncode, 1)

    def test_template_push_is_off_by_default_and_in_son_mode(self) -> None:
        text: str = (SCRIPTS / "pr_receipt.py").read_text(encoding="utf-8")
        self.assertIn('SETTINGS_KEY: Final[str] = "pr_receipt_template_push"', text)
        self.assertIn('SETTINGS_KEY, "false"', text)
        self.assertIn("DTS2_SON", text)


class AtomicWriteTests(unittest.TestCase):
    """G-39: machine-prep settings and agent memory files go through state_io.atomic_write."""

    def test_scripts_use_atomic_write(self) -> None:
        for name in ("machine-prep.py", "agent-memory.py"):
            text: str = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("atomic_write", text, name)
            self.assertNotRegex(text, r"path\.write_text\(", name)


class DocsTests(unittest.TestCase):
    def test_readme_lists_every_template_key(self) -> None:
        keys: list[str] = re.findall(r"^([a-z_]+):", TEMPLATE.read_text(encoding="utf-8").split("---")[1], re.M)
        readme: str = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual([k for k in keys if f"`{k}`" not in readme], [])

    def test_new_settings_are_in_the_template(self) -> None:
        template: str = TEMPLATE.read_text(encoding="utf-8")
        for key in ("stop_checks_block", "context_guard_stop", "pr_receipt_template_push"):
            self.assertRegex(template, rf"(?m)^{key}: false", key)

    def test_dpp_skill_quotes_are_balanced(self) -> None:
        for number, line in enumerate((PLUGIN_ROOT / "skills" / "dpp" / "SKILL.md").read_text(encoding="utf-8").splitlines(), 1):
            if "task-ledger.py" in line:
                self.assertEqual(line.count('"') % 2, 0, f"line {number}")

    def test_evolve_names_bump_version_and_fragments(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "evolve" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("bump-version.py", text)
        self.assertIn("changelog.d", text)


class WorkflowTests(unittest.TestCase):
    def test_actions_are_pinned_to_full_shas(self) -> None:
        if not WORKFLOW.is_file():
            self.skipTest("workflow lives outside the plugin checkout")
        uses: list[str] = re.findall(r"uses:\s*(\S+)(.*)", WORKFLOW.read_text(encoding="utf-8"))
        self.assertTrue(uses)
        for ref, rest in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)
            self.assertRegex(rest, r"#\s*v\d+\.\d+\.\d+", ref)

    def test_installer_lint_and_optional_validate(self) -> None:
        if not WORKFLOW.is_file():
            self.skipTest("workflow lives outside the plugin checkout")
        text: str = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("shellcheck -x install.sh", text)
        self.assertIn("command -v claude", text)


class ScriptSmokeTests(unittest.TestCase):
    """G-41: env-detect and prep-tiers had no test of their own."""

    def test_env_detect_reports_its_contract(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "env-detect.py")], capture_output=True, text=True, check=True)
        data: dict[str, Any] = json.loads(done.stdout)
        for key in ("os", "wsl", "claudeBinary", "claudeWrapsWindows", "liveClaudeHome", "tools"):
            self.assertIn(key, data)
        self.assertIn("python3", data["tools"])

    def test_env_detect_live_home(self) -> None:
        import _load
        module = _load.load("env-detect")
        self.assertIn("Windows home", module.live_claude_home(True, True))
        self.assertTrue(module.live_claude_home(False, True).endswith(".claude"))
        self.assertFalse(module.wraps_windows_claude(None))

    def test_prep_tiers_plans(self) -> None:
        import _load
        tiers = _load.load("prep-tiers")
        synced = [{"id": "a@synced", "preference": "optional", "root": "/nope"},
                  {"id": "b@synced", "preference": "required", "root": "/nope"}]
        usage: dict[str, int] = {"a": 3}
        self.assertEqual(tiers.switchable_ids(synced), ["a@synced"])
        self.assertEqual(tiers.top_synced(synced, usage, 1), {"a@synced"})
        self.assertEqual(tiers.pick_keep(["x@m", "a@synced"], usage), "a@synced")
        self.assertEqual(tiers.plan_marketplace({"m1": True, "s@synced": True}, {"m2"}), {"m1": False, "m2": True})
        strict = tiers.strict_plugins({"s@synced": True}, {"enabledPlugins": []}, synced)
        self.assertIs(strict["a@synced"], False)
        self.assertTrue(tiers.required_by_harness("dts2-harness@x", ["dts2-*"]))


class RepoSizeSmokeTests(unittest.TestCase):
    def test_repo_size_runs_on_an_empty_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "repo-size.py"), "--json", tmp], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout))


if __name__ == "__main__":
    unittest.main()
