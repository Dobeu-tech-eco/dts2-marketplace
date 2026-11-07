"""Batch 21: verified review findings on the policy gate, G-54 dedupe, council instances, probe hooks and the publish deny."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import guard  # noqa: E402
import policy_gate  # noqa: E402


def run_script(name: str, *args: str) -> dict[str, Any]:
    out = subprocess.run(["python3", "-I", str(SCRIPTS / name), *args], capture_output=True, text=True, check=False)
    return json.loads(out.stdout)


def load_script(name: str, module: str) -> Any:
    spec = importlib.util.spec_from_file_location(module, SCRIPTS / name)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def denied(command: str) -> str | None:
    return policy_gate.deny_reason(policy_gate.load_policy(), command)


class PolicyGateFindings(unittest.TestCase):
    def test_F1_bundled_env_flags_still_reach_force_push(self) -> None:
        for command in ("env -iu PATH git push --force", "env -i -u PATH git push -f", "env -uPATH git push -f",
                        "env -iC /tmp git push -f", "env -S 'git push -f'"):
            self.assertIsNotNone(denied(command), command)
        self.assertEqual(guard.strip_wrappers(["env", "-iu", "PATH", "git", "push"]), ["git", "push"])
        self.assertEqual(guard.strip_wrappers(["env", "-i", "-u", "PATH", "FOO=1", "git", "push"]), ["git", "push"])

    def test_F2_expansion_hides_flag_only_rules(self) -> None:
        self.assertIn("admin-flag", denied("gh pr merge 3 $X") or "")
        self.assertIn("deploy-vercel-prod", denied("vercel $X") or "")
        self.assertIsNone(denied("gh pr view 3"))

    def test_F3_single_quoted_substitution_is_text(self) -> None:
        self.assertIsNone(denied("git commit -m '$(env)'"))
        self.assertIsNotNone(denied('echo "$(env)"'))
        self.assertIsNotNone(denied("echo $(env)"))
        self.assertIsNotNone(denied("echo `env`"))

    def test_F4_secret_in_an_option_value_is_not_gh_secret(self) -> None:
        self.assertIsNone(denied("gh pr create --title secret"))
        self.assertIsNone(denied("gh pr create secret"))
        self.assertIsNotNone(denied("gh secret set A"))
        self.assertIsNotNone(denied("gh -R o/r secret list"))
        self.assertIsNotNone(denied("gh repo delete o/r --yes"))
        self.assertIsNotNone(denied("git push -u origin --force"))


class DedupeOnlyAfterWrite(unittest.TestCase):
    def repo(self) -> Path:
        repo = Path(tempfile.mkdtemp(prefix="dts2-b21-")).resolve()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        (repo / ".harness").mkdir()
        return repo

    def test_F5_lessons_failed_regress_does_not_consume_the_id(self) -> None:
        repo = self.repo()
        flags = ("--stamp", "20261105-0000", "--step", "s1", "--attempt", "1")
        (repo / ".harness" / "lessons.md").write_text("# L\n\n- [L-001] A. (seen 2x, last 2026-10-17, source: r)\n", encoding="utf-8")
        self.assertFalse(run_script("lessons.py", str(repo), "regress", "L-001", *flags)["ok"])  # not promoted: nothing written
        run_script("lessons.py", str(repo), "promote", "L-001")
        retry = run_script("lessons.py", str(repo), "regress", "L-001", *flags)
        self.assertNotIn("duplicate", retry)
        self.assertEqual(retry["regressed"], 1)

    def test_F5_action_items_failed_add_does_not_consume_the_id(self) -> None:
        repo = self.repo()
        (repo / ".harness" / "action-items.md").write_text(
            "# Action items\n\n## Decisions\n\n| item | context | status | owner | added |\n|---|---|---|---|---|\n", encoding="utf-8")
        flags = ("--stamp", "20261105-0000", "--step", "s1", "--attempt", "1")
        first = run_script("action-items.py", str(repo), "add", "NoSuchGroup", "x", *flags)
        self.assertIn("error", first)
        retry = run_script("action-items.py", str(repo), "add", "Decisions", "pick a domain", *flags)
        self.assertNotIn("duplicate", retry)
        self.assertIn("pick a domain", (repo / ".harness" / "action-items.md").read_text(encoding="utf-8"))

    def test_F5_council_failed_ledger_write_does_not_consume_the_id(self) -> None:
        council = load_script("council.py", "council_f5")
        work = Path(tempfile.mkdtemp(prefix="dts2-b21-"))
        decision, out, ballots = work / "decision.md", work / "decisions.md", work / "ballots"
        ballots.mkdir()
        with self.assertRaises(OSError):
            council.write_ledger(ballots, {}, decision, "s1", "20261105-0000", out)
        decision.write_text("DECISION: APPROVE\n\n## Head of council brief\nok\n", encoding="utf-8")
        retry = council.write_ledger(ballots, {}, decision, "s1", "20261105-0000", out)
        self.assertNotIn("duplicate", retry)
        self.assertTrue(out.is_file())


class CouncilSequenceSeed(unittest.TestCase):
    def test_F6_sequence_is_seeded_from_existing_allocations(self) -> None:
        council = load_script("council.py", "council_f6")
        with tempfile.TemporaryDirectory() as tmp:
            votes = Path(tmp)  # an instances.json from before the `#seq` counter: two instances of s3 were already handed out
            (votes / "instances.json").write_text(json.dumps({"s3:plan:r1": 2, "s4:plan:r1": 1}), encoding="utf-8")
            resumed = council.next_round(votes, "s3", "plan", retry="HTTP 429")
            other = council.next_round(votes, "s4", "plan")
        self.assertEqual(resumed["instance"], "s3+3")
        self.assertEqual(other["instance"], "s4+2")


class HeadProbeSkipsHooks(unittest.TestCase):
    def test_F7_push_probe_runs_without_the_repo_hooks(self) -> None:
        from lanes import supervisor
        work = Path(tempfile.mkdtemp(prefix="dts2-b21-"))
        log = work / "argv.json"
        fake = work / "git.py"
        fake.write_text(f"#!/usr/bin/env python3\nimport json, sys\nopen({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"DTS2_GIT_BIN": str(fake)}):
            self.assertIsNone(supervisor.head_push_problem(work))
        argv = json.loads(log.read_text(encoding="utf-8"))
        self.assertIn("core.hooksPath=/dev/null", argv)
        self.assertIn("--no-verify", argv)
        self.assertLess(argv.index("core.hooksPath=/dev/null"), argv.index("push"))
        self.assertIn("--dry-run", argv)


class PublishIsHeadOnly(unittest.TestCase):
    def test_F8_son_deny_lists_name_publish(self) -> None:
        import son_launch
        self.assertIn("Bash(*lanes.py publish*)", son_launch.DISALLOWED)
        self.assertIsNotNone(guard.son_bash_denial(["python3", "scripts/lanes.py", "publish", "20261105-1", "--lane", "a"], "dts2/x/lane-a"))

    def test_F8_call_refuses_to_wrap_a_son_marker_change(self) -> None:
        from lanes import supervisor
        work = Path(tempfile.mkdtemp(prefix="dts2-b21-"))
        for argv in (["env", "-u", "DTS2_SON", "python3", "x.py"], ["env", "DTS2_SON=", "python3", "x.py"],
                     ["env", "-iu", "DTS2_SON_BRANCH_PREFIX", "python3", "x.py"], ["DTS2_SON=0", "python3", "x.py"],
                     ["env", "--unset=DTS2_SON", "python3", "x.py"]):
            result = supervisor.model_call(work / "runs", "20261105-1", work, "t", argv, 5, None, None, "none")
            self.assertFalse(result["ok"], argv)
            self.assertIn("DTS2_SON", result["detail"])

    def test_F8_publish_is_refused_for_a_son_role_without_env_markers(self) -> None:
        import lanes as lanes_cli  # noqa: F401  (the package; the CLI module is loaded below)
        spec = importlib.util.spec_from_file_location("lanes_cli_b21", SCRIPTS / "lanes.py")
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        args = cli.build_parser().parse_args(["publish", "20261105-1", "--lane", "a"])
        env = {k: v for k, v in os.environ.items() if k not in ("DTS2_SON", "DTS2_SON_BRANCH_PREFIX")}
        for role in ("son", "vote", "council"):
            with mock.patch.dict(os.environ, {**env, "DTS2_ROLE": role}, clear=True), \
                    mock.patch.object(cli, "publish_lane", return_value={"ok": True}) as publish:
                self.assertFalse(cli.publish_command(args, Path(tempfile.mkdtemp()))["ok"], role)
                publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
