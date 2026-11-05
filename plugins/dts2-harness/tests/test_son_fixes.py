"""Review fixes for son containment: launch without --bare, widened write scope, who merges, merge-guard bypasses and son
guard gaps, and the real-launch preflight. Fake git, gh and claude only; no network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import guard  # noqa: E402
import son_launch  # noqa: E402

LANES: Final[Path] = SCRIPTS / "lanes.py"
PREFIX: Final[str] = "dts2/20261104-5/lane-a"
FAKE_GIT: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
refs = json.loads(os.environ.get("FAKE_REFS", "{}"))
if a[:1] == ["--version"]:
    print("git version 2.40.0")
elif "--git-common-dir" in a:
    print(os.environ.get("FAKE_COMMON", ""))
elif a[:1] == ["rev-parse"] and a[-1].endswith("^{commit}"):
    name = a[-1][:-len("^{commit}")]
    print(refs.get(name, os.environ.get("FAKE_HEAD", "aaaaaaa1")))
elif a[:2] == ["rev-parse", "HEAD"]:
    print(os.environ.get("FAKE_HEAD", "aaaaaaa1"))
elif a[:2] == ["rev-parse", "--abbrev-ref"]:
    print(os.environ.get("FAKE_BRANCH", "feature"))
elif a[:1] == ["rev-parse"] and "refs/remotes/origin/" in a[-1]:
    print(os.environ.get("FAKE_TIP", "bbbbbbb1"))
elif a[:1] == ["ls-remote"]:
    sys.exit(int(os.environ.get("DTS2_FAKE_LSREMOTE", "0")))
elif a[:1] == ["config"]:
    sys.exit(1)
'''
FAKE_GH: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
print(json.dumps({"baseRefName": os.environ.get("FAKE_BASE", "main"), "headRefOid": os.environ.get("FAKE_HEAD", "aaaaaaa1")}))
'''
FAKE_CLAUDE: Final[str] = '''#!/usr/bin/env python3
import os, sys
if "--version" in sys.argv:
    print("2.1.250"); sys.exit(0)
open(os.environ["DTS2_FAKE_ARGV_LOG"], "w").write("\\n".join(sys.argv[1:]) + "\\n" + os.environ.get("DTS2_SON", "") + "\\n")
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
'''


def bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class SonSettingsTests(unittest.TestCase):
    def test_write_scope_covers_common_dir_lane_dir_and_builders(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="dts2-scope-")).resolve() / "repo"
        root.mkdir()
        git = root.parent / "git.py"
        git.write_text(FAKE_GIT, encoding="utf-8")
        manifest = {"stamp": "s1", "lanes": [{"id": "a"}]}
        old = dict(os.environ)
        os.environ.update({"DTS2_GIT_BIN": str(git), "FAKE_COMMON": str(root / ".git")})
        try:
            settings = son_launch.son_settings(root, manifest, "a", root.parent / "wt")
        finally:
            os.environ.clear()
            os.environ.update(old)
        fs = settings["sandbox"]["filesystem"]
        self.assertIn(str(root / ".git"), fs["allowWrite"])
        self.assertIn(str(root / ".harness" / "runs" / "s1" / "a"), fs["allowWrite"])
        self.assertIn(str(root.parent / "repo-dts2-a-builders"), fs["allowWrite"])  # an exact path: no mid-path wildcard on Linux
        self.assertIn(str(root / ".harness" / "cache"), fs["allowWrite"])
        self.assertEqual(fs["denyWrite"], [str(root / ".git" / "hooks"), str(root / ".git" / "config"),
                                           str(root / ".claude" / "settings.local.json"),
                                           str(root.parent / "wt" / ".claude" / "settings.local.json"),
                                           str(root / ".harness" / "runs" / "s1" / "a" / "merge-go.md")])

    def test_no_bare_and_guard_hook_present(self) -> None:
        flags = son_launch.launch_flags(Path(tempfile.mkdtemp()), "dontAsk", {"stamp": "s", "lanes": [{"id": "a"}]}, "a", Path("/w"))
        self.assertNotIn("--bare", flags)
        self.assertEqual(flags[flags.index("--setting-sources") + 1], "local")
        hook = json.loads(flags[flags.index("--settings") + 1])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("guard.py", hook)

    def test_son_env_carries_the_marker_and_deny_list_the_grant_commands(self) -> None:
        env = son_launch.lane_env({"stamp": "s", "lanes": [{"id": "a"}]}, "a", Path(tempfile.mkdtemp()))
        self.assertEqual(env["DTS2_SON"], "1")
        self.assertIn("Bash(*lanes.py merge-go*)", son_launch.DISALLOWED)
        self.assertIn("Bash(*lanes.py merge-target*)", son_launch.DISALLOWED)


class LanesSonRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-son-ref-"))
        runs = self.root / ".harness" / "runs" / "20261104-5"
        (runs / "a").mkdir(parents=True)
        (runs / "a" / "status.json").write_text(json.dumps({"lane": "a", "status": "pr-open"}), encoding="utf-8")
        self.manifest = self.root / "lanes.json"
        self.manifest.write_text(json.dumps({"stamp": "20261104-5", "base": "abc1234", "scope": "single", "lanes": [
            {"id": "a", "item": "S", "files": ["a.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}), encoding="utf-8")
        (self.root / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        self.runs = runs

    def lanes(self, args: list[str], **env: str) -> dict[str, Any]:
        base = {k: v for k, v in os.environ.items() if k not in ("DTS2_SON", "DTS2_SON_BRANCH_PREFIX")}
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), *args], capture_output=True, text=True,
                              env={**base, "DTS2_GIT_BIN": str(self.root / "git.py"), **env}, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_son_cannot_grant_or_change_merge_state(self) -> None:
        for env in ({"DTS2_SON": "1"}, {"DTS2_SON_BRANCH_PREFIX": PREFIX}):
            self.assertFalse(self.lanes(["merge-go", str(self.manifest), "--lane", "a", "--head", "aaaaaaa1"], **env)["ok"])
            self.assertFalse(self.lanes(["merge-target", "20261104-5", "--yes-default-branch"], **env)["ok"])
            self.assertFalse(self.lanes(["gc-restore", "20261104-5"], **env)["ok"])
        self.assertFalse((self.runs / "a" / "merge-go.md").exists())

    def test_merge_target_is_written_for_the_guard(self) -> None:
        self.lanes(["merge-target", "20261104-5", "--set", "release"])
        self.assertEqual((self.runs / "merge-target.txt").read_text(encoding="utf-8").strip(), "release")

    def test_head_still_grants(self) -> None:
        self.assertTrue(self.lanes(["merge-go", str(self.manifest), "--lane", "a", "--head", "aaaaaaa1"])["ok"])

    def test_son_deny_hook_blocks_the_grant_commands(self) -> None:
        for command in ("python3 -I scripts/lanes.py merge-go m.json --lane a --head x", "python3 lanes.py merge-target s --set main"):
            self.assertIsNotNone(guard.son_denial(bash(command), PREFIX), command)


class MergeGuardBypassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-bypass-"))
        (self.root / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        (self.root / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        self.run_dir = self.root / ".harness" / "runs" / "s" / "a"
        self.run_dir.mkdir(parents=True)

    def grant(self, head: str = "aaaaaaa1", base: str = "bbbbbbb1", ref: str = "main") -> None:
        (self.run_dir / "merge-go.md").write_text(f"# Merge go\n\nVerified head: {head}\nBase: {ref} {base}\nGranted: 1\n", encoding="utf-8")

    def check(self, command: str, **env: str) -> str | None:
        old = dict(os.environ)
        os.environ.update({"DTS2_GIT_BIN": str(self.root / "git.py"), "DTS2_GH_BIN": str(self.root / "gh.py"), **env})
        try:
            return guard.merge_denial(bash(command), self.root)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_global_flags_before_the_subcommand(self) -> None:
        for command in ("gh -R o/r pr merge 3", "gh --repo o/r pr merge 3", "git -C . push origin main",
                        "git -c k=v push origin main", "git -C /x -c a=b push origin main"):
            self.assertIsNotNone(self.check(command), command)

    def test_wrappers_subshells_and_nested_shells(self) -> None:
        for command in ("(gh pr merge 3)", "{ gh pr merge 3; }", "timeout 5 git push origin main", "time git push origin main",
                        "nice -n 5 git push origin main", "nohup git push origin main", "stdbuf -oL git push origin main",
                        "builtin exec git push origin main", "echo x | xargs git push origin main",
                        'bash -c "git push origin main"', "sh -c 'gh pr merge 3'", "eval git push origin main",
                        "echo $(git push origin main)", "echo `gh pr merge 3`", "true && (timeout 9 gh pr merge 3)",
                        "git push origin main &", 'bash -lc "echo hi; git push origin main"'):
            self.assertIsNotNone(self.check(command), command)

    def test_unparsable_line_with_a_watched_word_is_denied(self) -> None:
        self.assertIsNotNone(self.check('git push origin "main'))
        self.assertIsNone(self.check('echo "unbalanced'))  # no watched word: not the guard's business

    def test_pr_url_selector_is_gated_and_unsafe_selector_fails_closed(self) -> None:
        self.assertIsNotNone(self.check("gh pr merge https://github.com/o/r/pull/9"))
        self.grant()
        self.assertIsNone(self.check("gh pr merge https://github.com/o/r/pull/9"))
        self.assertIsNotNone(self.check("gh pr merge 'a;b'"))
        self.assertIsNotNone(self.check("gh pr merge $(echo 9)"))

    def test_merge_flag_values_are_not_taken_for_the_selector(self) -> None:
        self.assertEqual(guard.merge_selector(["--subject", "fix it", "7", "--squash"]), "7")
        self.assertEqual(guard.merge_selector(["--squash"]), "")
        self.assertIsNone(guard.merge_selector(["bad;ref"]))

    def test_push_is_authorized_by_the_source_commit_not_head(self) -> None:
        self.grant(head="aaaaaaa1")
        refs = json.dumps({"main": "ccccccc1", "feature": "aaaaaaa1"})
        self.assertIsNotNone(self.check("git push origin main", FAKE_REFS=refs, FAKE_HEAD="aaaaaaa1"))
        self.assertIsNone(self.check("git push origin feature:main", FAKE_REFS=refs))
        self.assertIsNotNone(self.check("git push origin main:main", FAKE_REFS=refs))

    def test_target_and_grant_bases_are_gated(self) -> None:
        self.assertIsNone(self.check("gh pr merge 7", FAKE_BASE="dev"))  # no lanes run yet: dev is not gated
        (self.run_dir / "status.json").write_text("{}", encoding="utf-8")
        self.assertIsNotNone(self.check("gh pr merge 7", FAKE_BASE="dev"))  # the run's default dev target is
        self.grant(ref="dev")
        self.assertIsNone(self.check("gh pr merge 7", FAKE_BASE="dev"))
        self.assertIsNotNone(self.check("gh pr merge 7", FAKE_BASE="dev", FAKE_TIP="cccccc01"))
        self.assertIsNone(self.check("gh pr merge 7", FAKE_BASE="feature-x"))

    def test_recorded_merge_target_and_configured_branch_are_gated(self) -> None:
        (self.root / ".harness" / "runs" / "s" / "merge-target.txt").write_text("release\n", encoding="utf-8")
        self.assertIsNotNone(self.check("gh pr merge 7", FAKE_BASE="release"))
        (self.root / ".harness" / "config.yaml").write_text("merge:\n  default_branch: trunk\n", encoding="utf-8")
        self.assertIsNotNone(self.check("gh pr merge 7", FAKE_BASE="trunk"))

    def test_gh_api_merge_and_graphql_merge(self) -> None:
        self.assertIsNotNone(self.check("gh api -X PUT repos/o/r/pulls/9/merge"))
        self.assertIsNotNone(self.check("gh api repos/o/r/pulls/9/merge -f merge_method=squash"))
        self.assertIsNotNone(self.check("gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'"))
        self.assertIsNone(self.check("gh api repos/o/r/pulls/9"))
        self.grant()
        self.assertIsNone(self.check("gh api -X PUT repos/o/r/pulls/9/merge"))


class SonGuardGapTests(unittest.TestCase):
    def deny(self, command: str) -> str | None:
        return guard.son_denial(bash(command), PREFIX)

    def test_redirect_without_space_to_protected_path(self) -> None:
        for command in ("echo x>.git/hooks/pre-commit", "echo x>>.claude/settings.json", "cat a >.mcp.json", "echo x 2>.git/hooks/h"):
            self.assertIsNotNone(self.deny(command), command)
        self.assertIsNone(self.deny("echo x>out.txt"))

    def test_lane_branch_check_is_exact_or_builder_suffix(self) -> None:
        self.assertIsNotNone(self.deny("git push origin dts2/20261104-5/lane-ab"))
        self.assertIsNone(self.deny("git push origin " + PREFIX))
        self.assertIsNone(self.deny("git push origin " + PREFIX + "-b2"))

    def test_wrappers_subshells_and_gh_flags_are_seen(self) -> None:
        for command in ("(gh pr merge 3)", "timeout 5 git push origin main", 'bash -c "git push origin main"',
                        "eval git push origin main", "gh -R o/r pr merge 3", "gh --repo o/r pr merge 3",
                        "echo $(gh pr merge 3)", "git -C . push origin main", 'git push origin "main',
                        "nohup gh api -X DELETE repos/o/r &"):
            self.assertIsNotNone(self.deny(command), command)

    def test_ordinary_work_still_passes(self) -> None:
        for command in ("timeout 60 python3 -m unittest", "(cd sub && ls)", "bash -c 'echo hi'", "git push -u origin " + PREFIX,
                        "gh -R o/r pr view 3", "echo $(date)"):
            self.assertIsNone(self.deny(command), command)


class PreflightLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-pre-"))
        (self.root / "claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
        (self.root / "git.py").write_text(FAKE_GIT, encoding="utf-8")
        self.log = self.root / "argv.log"

    def preflight(self, **env: str) -> dict[str, Any]:
        full = {**os.environ, "DTS2_CLAUDE_BIN": str(self.root / "claude.py"), "DTS2_GIT_BIN": str(self.root / "git.py"),
                "DTS2_FAKE_ARGV_LOG": str(self.log), "GH_TOKEN": "secret", **env}
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.root), "preflight", "20261104-5"],
                              capture_output=True, text=True, env=full, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_preflight_runs_the_real_son_launch(self) -> None:
        # fake claude prints no JSON result, so the answer check fails; the point is the argv and env it was given
        self.preflight()
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertIn("--setting-sources", lines)
        self.assertIn("--strict-mcp-config", lines)
        self.assertIn("-p", lines)
        self.assertNotIn("--bare", lines)
        self.assertEqual(lines[-1], "1")  # DTS2_SON reached the child

    def test_unreachable_remote_names_the_pass_through_variable(self) -> None:
        result = self.preflight(DTS2_FAKE_LSREMOTE="2")
        self.assertTrue(any("DTS2_SON_ENV_PASS" in p for p in result["problems"]), result)
        self.assertFalse(result["ok"])

    def test_reachable_remote_adds_no_access_problem(self) -> None:
        result = self.preflight()
        self.assertFalse(any("DTS2_SON_ENV_PASS" in p for p in result["problems"]), result)


if __name__ == "__main__":
    unittest.main()
