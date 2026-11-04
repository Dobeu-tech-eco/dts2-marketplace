"""Second review of batch 5: the merge guard only blocks an active run, an autopilot step can be granted a merge, the hook runs for
every Bash call, more guard bypasses are closed, the sandbox keeps merge-go.md away from a son, and a guard crash fails closed.
Fake git, gh and claude only; no network."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Final
from unittest import mock

import test_supervisor as sup
from test_son_fixes import FAKE_GIT, LANES, PLUGIN_ROOT, PREFIX, bash, guard, son_launch

FAKE_GH_LOG: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_GH_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
print(json.dumps({"baseRefName": os.environ.get("FAKE_BASE", "main"), "headRefOid": os.environ.get("FAKE_HEAD", "aaaaaaa1")}))
'''


class GuardBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-rev2-"))
        (self.root / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        (self.root / "gh.py").write_text(FAKE_GH_LOG, encoding="utf-8")
        self.gh_log = self.root / "gh.log"
        self.runs = self.root / ".harness" / "runs"

    def env(self, **extra: str) -> dict[str, str]:
        return {"DTS2_GIT_BIN": str(self.root / "git.py"), "DTS2_GH_BIN": str(self.root / "gh.py"),
                "FAKE_GH_LOG": str(self.gh_log), **extra}

    def check(self, command: str, **extra: str) -> str | None:
        old = dict(os.environ)
        os.environ.update(self.env(**extra))
        try:
            return guard.merge_denial(bash(command), self.root)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def gh_calls(self) -> list[list[str]]:
        if not self.gh_log.exists():
            return []
        return [json.loads(line) for line in self.gh_log.read_text(encoding="utf-8").splitlines()]

    def write(self, rel: str, text: str) -> Path:
        path = self.runs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def grant(self, stamp: str, lane: str, ref: str, head: str = "aaaaaaa1", base: str = "bbbbbbb1") -> None:
        self.write(f"{stamp}/{lane}/merge-go.md", f"# Merge go\n\nVerified head: {head}\nBase: {ref} {base}\nGranted: 1\n")


class ActiveRunOnlyTests(GuardBase):
    def test_a_finished_old_run_does_not_protect_the_target(self) -> None:
        self.write("old/a/status.json", json.dumps({"lane": "a", "status": "done"}))
        self.grant("old", "a", "dev")
        self.assertIsNone(self.check("gh pr merge 5", FAKE_BASE="dev"))

    def test_merge_pending_decides_when_present(self) -> None:
        self.write("run/a/status.json", json.dumps({"lane": "a", "status": "pr-open"}))
        self.write("run/merge-pending.txt", "")
        self.assertIsNone(self.check("gh pr merge 5", FAKE_BASE="dev"))
        self.write("run/merge-pending.txt", "a\n")
        self.assertIsNotNone(self.check("gh pr merge 5", FAKE_BASE="dev"))

    def test_a_lane_that_is_not_done_keeps_the_run_active(self) -> None:
        self.write("run/a/status.json", json.dumps({"lane": "a", "status": "pr-open"}))
        self.assertIsNotNone(self.check("gh pr merge 5", FAKE_BASE="dev"))

    def test_a_finished_run_keeps_main_protected(self) -> None:
        self.write("old/a/status.json", json.dumps({"lane": "a", "status": "done"}))
        self.assertIsNotNone(self.check("gh pr merge 5", FAKE_BASE="main"))

    def test_a_recorded_target_of_a_finished_run_is_dropped(self) -> None:
        self.write("old/a/status.json", json.dumps({"status": "done"}))
        self.write("old/merge-target.txt", "release\n")
        self.assertIsNone(self.check("gh pr merge 5", FAKE_BASE="release"))

    def test_lanes_py_writes_the_pending_list(self) -> None:
        manifest = self.root / "lanes.json"
        manifest.write_text(json.dumps({"stamp": "s9", "base": "abc1234", "scope": "single", "lanes": [
            {"id": "a", "item": "S", "files": ["a.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}), encoding="utf-8")
        self.write("s9/a/status.json", json.dumps({"lane": "a", "status": "pr-open"}))
        env = {**os.environ, **self.env()}
        subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), "merge-order", str(manifest)], env=env,
                       capture_output=True, check=True)
        self.assertEqual((self.runs / "s9" / "merge-pending.txt").read_text(encoding="utf-8"), "a\n")
        subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), "merge-go", str(manifest), "--lane", "a",
                        "--head", "aaaaaaa1", "--base", "bbbbbbb1"], env=env, capture_output=True, check=True)
        subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), "merge-done", str(manifest), "--lane", "a"],
                       env=env, capture_output=True, check=True)
        self.assertEqual((self.runs / "s9" / "merge-pending.txt").read_text(encoding="utf-8"), "")
        self.assertIsNone(self.check("gh pr merge 5", FAKE_BASE="dev"))


class StepGrantTests(GuardBase):
    def lanes(self, *args: str, **extra: str) -> dict[str, Any]:
        base = {k: v for k, v in os.environ.items() if k not in ("DTS2_SON", "DTS2_SON_BRANCH_PREFIX")}
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), *args], capture_output=True, text=True,
                              env={**base, **self.env(), **extra}, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_autopilot_merges_into_dev_after_an_old_run_and_without_a_grant(self) -> None:
        self.write("old/a/status.json", json.dumps({"status": "done"}))
        self.assertIsNone(self.check("gh pr merge 5 --squash", FAKE_BASE="dev"))

    def test_default_branch_merge_needs_the_recorded_yes_and_then_the_step_grant(self) -> None:
        refused = self.lanes("merge-go-step", "s1", "--step", "3", "--head", "aaaaaaa1", "--base", "bbbbbbb1")
        self.assertTrue(refused["ok"], "dev is the default target and needs no yes")
        self.lanes("merge-target", "s2", "--set", "main")
        self.assertFalse(self.lanes("merge-go-step", "s2", "--step", "3", "--head", "aaaaaaa1", "--base", "bbbbbbb1")["ok"])
        self.assertIsNotNone(self.check("gh pr merge 5", FAKE_BASE="main"))
        self.lanes("merge-target", "s2", "--set", "main", "--yes-default-branch")
        granted = self.lanes("merge-go-step", "s2", "--step", "3", "--head", "aaaaaaa1", "--base", "bbbbbbb1")
        self.assertTrue(granted["ok"], granted)
        text = (self.runs / "s2" / "3" / "merge-go.md").read_text(encoding="utf-8")
        self.assertIn("Verified head: aaaaaaa1", text)
        self.assertIn("Base: main bbbbbbb1", text)
        self.assertIsNone(self.check("gh pr merge 5", FAKE_BASE="main"))
        self.assertIsNotNone(self.check("gh pr merge 5", FAKE_BASE="main", FAKE_HEAD="ccccccc1"))

    def test_base_defaults_to_the_origin_tip(self) -> None:
        self.lanes("merge-target", "s3", "--set", "main", "--yes-default-branch")
        granted = self.lanes("merge-go-step", "s3", "--step", "1", "--head", "aaaaaaa1", FAKE_TIP="dddddd01")
        self.assertEqual(granted["base"], "dddddd01")

    def test_a_son_cannot_grant_a_step_and_bad_input_is_refused(self) -> None:
        for env in ({"DTS2_SON": "1"}, {"DTS2_SON_BRANCH_PREFIX": PREFIX}):
            self.assertFalse(self.lanes("merge-go-step", "s4", "--step", "1", "--head", "aaaaaaa1", "--base", "bbbbbbb1", **env)["ok"])
        self.assertFalse((self.runs / "s4" / "1" / "merge-go.md").exists())
        self.assertFalse(self.lanes("merge-go-step", "s4", "--step", "1", "--head", "not-a-sha", "--base", "bbbbbbb1")["ok"])
        self.assertFalse(self.lanes("merge-go-step", "s4", "--step", "../x", "--head", "aaaaaaa1", "--base", "bbbbbbb1")["ok"])

    def test_son_deny_hook_blocks_merge_go_step_through_any_command_word(self) -> None:
        for command in ("python3 scripts/lanes.py merge-go-step s --step 1 --head x", '"/x/scripts/lanes.py" merge-go-step s --step 1 --head x'):
            self.assertIsNotNone(guard.son_denial(bash(command), PREFIX), command)


class HookTests(GuardBase):
    def run_hook(self, command: str) -> subprocess.CompletedProcess[str]:
        payload = json.dumps(bash(command))
        env = {**os.environ, **self.env(), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
        return subprocess.run(["bash", str(PLUGIN_ROOT / "hooks" / "merge-guard.sh")], input=payload, capture_output=True, text=True,
                              cwd=self.root, env=env, check=False)

    def test_hook_json_has_no_if_filter_and_a_long_enough_timeout(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        merge = [h for e in hooks for h in e["hooks"] if "merge-guard" in h["command"]]
        self.assertTrue(merge)
        self.assertTrue(all("if" not in h and h["timeout"] >= 60 for h in merge))
        self.assertLessEqual(guard.GIT_TIMEOUT_S * 2 + 5, 60)

    def test_hook_runs_the_guard_for_wrapped_push_forms(self) -> None:
        for command in ('bash -c "git push origin main"', "/usr/bin/git push origin main", "env git push origin main",
                        "sudo git push origin main", "eval git push origin main", "echo | xargs git push origin main"):
            done = self.run_hook(command)
            self.assertIn('"deny"', done.stdout, command)

    def test_hook_exits_quietly_unless_the_payload_names_push_or_merge(self) -> None:
        done = self.run_hook("ls -la")
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertFalse(self.gh_log.exists())


class BypassTests(GuardBase):
    def test_glued_redirects_do_not_hide_the_destination(self) -> None:
        for command in ("git push origin main>/dev/null", "git push origin main 2>/dev/null", "git push origin main>>log.txt",
                        "git push origin main &>/dev/null", "git push origin main 2>&1", "git push origin main </dev/null"):
            self.assertIsNotNone(self.check(command), command)
        for command in ("git push origin feature>/dev/null", "git push origin feature 2>&1"):
            self.assertIsNone(self.check(command), command)

    def test_tokenizer_drops_redirects_and_keeps_quoted_symbols(self) -> None:
        self.assertEqual(guard.tokenize("git push origin main>/dev/null"), (["git", "push", "origin", "main"], [(">", "/dev/null")]))
        self.assertEqual(guard.tokenize("echo 'a>b' 2>err"), (["echo", "a>b"], [(">", "err")]))
        with self.assertRaises(ValueError):
            guard.tokenize('echo "x')

    def test_son_redirect_targets_are_still_checked(self) -> None:
        for command in ("echo x>.git/hooks/pre-commit", "echo x 2>>.claude/s.json", "cat < ~/.ssh/id_rsa"):
            self.assertIsNotNone(guard.son_denial(bash(command), PREFIX), command)
        self.assertIsNone(guard.son_denial(bash("echo x>out.txt 2>&1"), PREFIX))

    def test_shell_expansion_fails_closed(self) -> None:
        for command in ("B=main; git push origin $B", "git push origin $'main'", "git push origin ${B}", "git push origin $(echo main)",
                        "gh pr merge $N", "gh api repos/o/r/pulls/$N/merge -X PUT", "gh api graphql -f query=$Q",
                        "G=gh; $G pr merge 5"):
            self.assertIsNotNone(self.check(command, FAKE_BASE="feature"), command)

    def test_a_merge_body_may_hold_a_dollar_sign(self) -> None:
        self.assertIsNone(self.check("gh pr merge 5 --body 'saves $5'", FAKE_BASE="feature"))

    def test_api_merge_path_with_a_query_string_and_the_repo_it_names(self) -> None:
        self.assertIsNotNone(self.check("gh api -X PUT 'repos/o/r/pulls/5/merge?x=1'", FAKE_BASE="main"))
        self.assertIsNotNone(self.check("gh api -X PUT repos/o/r/pulls/5/merge#frag", FAKE_BASE="main"))
        self.assertIn(["pr", "view", "5", "--repo", "o/r", "--json", "baseRefName,headRefOid"], self.gh_calls())
        self.assertIsNone(self.check("gh api -X PUT repos/o/r/pulls/5/merge", FAKE_BASE="feature"))

    def test_graphql_query_from_a_file_or_stdin_is_denied(self) -> None:
        for command in ("gh api graphql -F query=@q.graphql", "gh api graphql -f query=@-", "gh api graphql --input q.json",
                        "gh api graphql --input=q.json", "gh api -f query=@q.graphql graphql"):
            self.assertIsNotNone(self.check(command, FAKE_BASE="feature"), command)
        self.assertIsNone(self.check("gh api graphql -f query='query{viewer{login}}'", FAKE_BASE="feature"))

    def test_repo_flag_after_the_subcommand_is_passed_on(self) -> None:
        for flag in (["--repo", "other/repo"], ["-R", "other/repo"], ["--repo=other/repo"]):
            self.gh_log.unlink(missing_ok=True)
            self.assertIsNone(self.check("gh pr merge 5 " + " ".join(flag), FAKE_BASE="feature"))
            self.assertIn(["pr", "view", "5", "--repo", "other/repo", "--json", "baseRefName,headRefOid"], self.gh_calls(), flag)
        self.assertIsNotNone(self.check("gh pr merge 5 --repo other/repo", FAKE_BASE="main"))


class SonLanesCallTests(unittest.TestCase):
    def deny(self, command: str) -> str | None:
        return guard.son_denial(bash(command), PREFIX)

    def test_direct_and_quoted_lanes_calls_are_denied(self) -> None:
        for command in ('"/x/scripts/lanes.py" merge-go m --lane a --head x', "./scripts/lanes.py merge-target s --set main",
                        "/x/lanes.py --cwd . gc-restore s", "unset DTS2_SON DTS2_SON_BRANCH_PREFIX; /x/scripts/lanes.py merge-go m --lane a --head x",
                        "env -u DTS2_SON /x/scripts/lanes.py merge-go m --lane a --head x", "sh -c '/x/lanes.py merge-go m'",
                        "python3 -I /x/lanes.py merge-go-step s --step 1 --head x"):
            self.assertIsNotNone(self.deny(command), command)

    def test_other_lanes_commands_pass(self) -> None:
        for command in ("python3 -I /x/scripts/lanes.py heartbeat s --lane a", "/x/scripts/lanes.py status s", "git log --oneline"):
            self.assertIsNone(self.deny(command), command)


class WriteScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-scope2-")).resolve() / "repo"
        (self.root / ".git" / "worktrees" / "wt1").mkdir(parents=True)
        (self.root / ".git" / "worktrees" / "wt1" / "config.worktree").write_text("[core]\n", encoding="utf-8")
        (self.root / ".git" / "modules").mkdir()
        (self.root.parent / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        self.manifest = {"stamp": "s1", "lanes": [{"id": "a"}]}

    def scope(self, lane: str = "a") -> tuple[list[str], list[str]]:
        old = dict(os.environ)
        os.environ.update({"DTS2_GIT_BIN": str(self.root.parent / "git.py"), "FAKE_COMMON": str(self.root / ".git")})
        try:
            return son_launch.write_scope(self.manifest, lane, self.root, self.root.parent / "wt")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_lane_dir_is_writable_but_its_merge_go_is_not(self) -> None:
        allow, deny = self.scope()
        lane_dir = self.root / ".harness" / "runs" / "s1" / "a"
        self.assertIn(str(lane_dir), allow)
        self.assertIn(str(lane_dir / "merge-go.md"), deny)

    def test_no_wildcards_and_an_exact_builders_dir(self) -> None:
        allow, deny = self.scope()
        self.assertFalse([p for p in [*allow, *deny] if "*" in p])
        self.assertIn(str(self.root.parent / "repo-dts2-a-builders"), allow)

    def test_submodule_and_worktree_config_are_denied(self) -> None:
        _allow, deny = self.scope()
        self.assertIn(str(self.root / ".git" / "modules"), deny)
        self.assertIn(str(self.root / ".git" / "worktrees" / "wt1" / "config.worktree"), deny)

    def test_probe_lane_has_no_builders_or_grant_path(self) -> None:
        allow, deny = self.scope("preflight")
        self.assertFalse([p for p in [*allow, *deny] if "builders" in p or "merge-go" in p])

    def test_env_names_the_builders_dir(self) -> None:
        env = son_launch.lane_env(self.manifest, "a", self.root)
        self.assertEqual(env["DTS2_BUILDERS_DIR"], str(self.root.parent / "repo-dts2-a-builders"))

    def test_placeholder_is_ignored_by_the_guard_and_a_real_grant_survives(self) -> None:
        son_launch.prepare_lane(self.root, "s1", "a")
        placeholder = self.root / ".harness" / "runs" / "s1" / "a" / "merge-go.md"
        self.assertTrue(placeholder.is_file())
        self.assertTrue((self.root.parent / "repo-dts2-a-builders").is_dir())
        self.assertEqual(guard.grants(self.root), [])
        placeholder.write_text("# x\n\nVerified head: aaaaaaa1\nBase: main bbbbbbb1\n", encoding="utf-8")
        son_launch.prepare_lane(self.root, "s1", "a")
        self.assertEqual(len(guard.grants(self.root)), 1)


class SpawnTests(sup.SupervisorBase):
    def test_preflight_probe_carries_plugin_dir(self) -> None:
        self.assertTrue(self.preflight()["ok"])
        probe = self.calls()[0]
        self.assertEqual(probe[probe.index("--plugin-dir") + 1], str(PLUGIN_ROOT))

    def test_spawn_prepares_the_builders_dir_and_the_grant_placeholder(self) -> None:
        self.preflight()
        self.assertTrue(self.spawn()["ok"])
        self.assertTrue((self.root / "repo-dts2-a-builders").is_dir())
        self.assertTrue((self.lane_dir / "merge-go.md").is_file())
        self.assertEqual(guard.grants(self.repo), [])


class CrashFailsClosedTests(GuardBase):
    def run_main(self, command: str, mode: str = "merge") -> str:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["guard.py", "--mode", mode, "--cwd", str(self.root)]), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(bash(command)))), \
                mock.patch.object(guard, "decide", side_effect=RuntimeError("boom")), redirect_stdout(out):
            self.assertEqual(guard.main(), 0)
        return out.getvalue()

    def test_a_crash_on_a_watched_command_is_a_deny(self) -> None:
        self.assertIn('"deny"', self.run_main("git push origin main"))
        self.assertIn('"deny"', self.run_main("gh pr merge 3", "son"))
        self.assertIn("denied", (self.root / ".harness" / "merge-guard.log").read_text(encoding="utf-8"))

    def test_a_crash_on_any_other_command_lets_it_through(self) -> None:
        self.assertEqual(self.run_main("ls"), "")


if __name__ == "__main__":
    unittest.main()
