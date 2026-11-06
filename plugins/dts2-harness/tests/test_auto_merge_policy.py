"""Phase 1 autonomy: the standing `merge_policy: auto-when-green` grant lets a direct `gh pr merge <n> --match-head-commit <sha>` pass
the policy gate when the sha was granted by merge-go-step, no hard-stop path is touched, the base requires checks and every
required check is green on the head. `--auto` is always refused. No network:
gh is a fake script behind DTS2_GH_BIN."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import approvals  # noqa: E402
import policy_gate  # noqa: E402

SHA: Final[str] = "a" * 40
OTHER_SHA: Final[str] = "b" * 40
FAKE_GH: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
cfg = json.load(open(os.environ["FAKE_GH_CONFIG"]))
if args[:2] == ["pr", "view"]:
    out = cfg.get("view")
elif args[:1] == ["api"] and "/check-runs" in args[1]:
    out = cfg.get("check_runs")
elif args[:1] == ["api"] and args[1].endswith("/status"):
    out = cfg.get("status")
elif args[:1] == ["api"] and "required_status_checks" in args[1]:
    out = cfg.get("protection")
elif args[:1] == ["api"] and "/rules/branches/" in args[1]:
    out = cfg.get("rules")
else:
    out = None
if out is None:
    sys.exit(1)
print(json.dumps(out))
'''
CHECKS: Final[dict[str, Any]] = {"contexts": ["test", "lint"], "checks": []}
GREEN_RUNS: Final[dict[str, Any]] = {"check_runs": [{"name": "test", "conclusion": "success"}, {"name": "lint", "conclusion": "success"}]}
NO_STATUS: Final[dict[str, Any]] = {"statuses": []}
VIEW: Final[dict[str, Any]] = {"baseRefName": "main", "headRefOid": SHA, "files": [{"path": "src/app.py"}]}


class AutoMergePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = Path(tempfile.mkdtemp(prefix="dts2-automerge-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, True)
        subprocess.run(["git", "init", "-q", "-b", "feat", str(self.repo)], check=True)
        self.gh: Path = self.repo / "fake_gh.py"
        self.gh.write_text(FAKE_GH, encoding="utf-8")
        self.config: Path = self.repo / "fake_gh.json"
        self.policy: dict[str, Any] = policy_gate.load_policy()
        self.set_gh(view={"baseRefName": "main", "headRefOid": SHA, "files": [{"path": "src/app.py"}]}, protection=CHECKS)
        self.grant_merge_go(SHA)
        self.set_approvals({"merge_policy": ["auto-when-green"]})

    def set_gh(self, **config: Any) -> None:
        """Write the fake gh answers; the head's checks are green unless a test passes its own `check_runs` / `status`."""
        config = {"check_runs": GREEN_RUNS, "status": NO_STATUS, **config}
        self.config.write_text(json.dumps(config), encoding="utf-8")

    def set_approvals(self, table: dict[str, list[str]]) -> None:
        (self.repo / ".claude").mkdir(exist_ok=True)
        (self.repo / ".claude" / "settings.local.json").write_text(json.dumps({"dts2_approvals": table}), encoding="utf-8")

    def grant_merge_go(self, head: str) -> None:
        run_dir = self.repo / ".harness" / "runs" / "20260101-000000" / "step-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "merge-go.md").write_text(f"# Merge go for step 1\n\nVerified head: {head}\nBase: main {'c' * 40}\n", encoding="utf-8")

    def decide(self, command: str) -> str | None:
        env = {"DTS2_SON": "", "DTS2_UNATTENDED": "", "DTS2_GH_BIN": str(self.gh), "FAKE_GH_CONFIG": str(self.config)}
        with mock.patch.dict(os.environ, env):
            return policy_gate.decide({"tool_name": "Bash", "tool_input": {"command": command}}, self.repo, self.policy)

    def auto(self, sha: str = SHA, pr: str = "42") -> str:
        return f"gh pr merge {pr} --squash --match-head-commit {sha}"

    def test_standing_grant_helper(self) -> None:
        self.assertTrue(approvals.standing_auto_merge(self.repo))
        self.set_approvals({"merge": ["auto-when-green"]})
        self.assertFalse(approvals.standing_auto_merge(self.repo))
        self.assertIn("merge_policy", approvals.KINDS)

    def test_grant_absent_denies_and_names_the_setup(self) -> None:
        self.set_approvals({})
        reason = str(self.decide(self.auto()))
        self.assertIn("pr-merge", reason)
        self.assertIn("merge_policy", reason)
        self.assertIn("auto-when-green", reason)

    def test_grant_with_direct_merge_and_matching_sha_allows(self) -> None:
        self.assertIsNone(self.decide(self.auto()))
        self.assertIsNone(self.decide(f"gh pr merge 42 --squash --match-head-commit={SHA}"))
        self.assertIsNone(self.decide(f"gh pr merge 42 --match-head-commit {SHA[:9]}"))
        self.assertIsNone(self.decide(f"env -i gh -R o/r pr merge 42 --match-head-commit {SHA}"))

    def test_auto_flag_is_refused_under_the_grant(self) -> None:
        for command in (f"gh pr merge 42 --auto --squash --match-head-commit {SHA}", f"gh pr merge 42 --squash --auto --match-head-commit={SHA}"):
            reason = str(self.decide(command))
            self.assertIn("pr-merge", reason)
            self.assertIn("never armed", reason)
            self.assertIn("--match-head-commit", reason)

    def test_missing_sha_falls_back_to_a_refusal_naming_the_flag(self) -> None:
        self.assertIn("pr-merge", str(self.decide("gh pr merge 42 --squash")))
        self.assertIn("--match-head-commit", str(self.decide("gh pr merge 42 --squash")))

    def test_required_check_pending_failing_or_missing_denies(self) -> None:
        cases = {
            "pending": {"check_runs": [{"name": "test", "conclusion": "success"}, {"name": "lint", "conclusion": None}]},
            "failing": {"check_runs": [{"name": "test", "conclusion": "success"}, {"name": "lint", "conclusion": "failure"}]},
            "missing": {"check_runs": [{"name": "test", "conclusion": "success"}]},
        }
        for label, config in cases.items():
            self.set_gh(view=VIEW, protection=CHECKS, check_runs=config)
            reason = str(self.decide(self.auto()))
            self.assertIn("wait for lint", reason, label)
            self.assertIn(SHA[:10], reason, label)

    def test_required_checks_green_through_runs_and_statuses(self) -> None:
        for conclusion in ("success", "neutral", "skipped"):
            self.set_gh(view=VIEW, protection=CHECKS,
                        check_runs={"check_runs": [{"name": "test", "conclusion": conclusion}, {"name": "lint", "conclusion": "success"}]})
            self.assertIsNone(self.decide(self.auto()), conclusion)
        self.set_gh(view=VIEW, protection=CHECKS, check_runs={"check_runs": [{"name": "test", "conclusion": "success"}]},
                    status={"statuses": [{"context": "lint", "state": "success"}]})
        self.assertIsNone(self.decide(self.auto()))
        self.set_gh(view=VIEW, protection=CHECKS, check_runs={"check_runs": [{"name": "test", "conclusion": "success"}]},
                    status={"statuses": [{"context": "lint", "state": "pending"}]})
        self.assertIn("wait for lint", str(self.decide(self.auto())))

    def test_checks_lookup_failure_denies(self) -> None:
        self.set_gh(view=VIEW, protection=CHECKS, check_runs=None)
        self.assertIn("cannot read the checks", str(self.decide(self.auto())))
        self.set_gh(view=VIEW, protection=CHECKS, status=None)
        self.assertIn("cannot read the checks", str(self.decide(self.auto())))
        self.set_gh(view=VIEW, protection=CHECKS, check_runs={"unexpected": 1})
        self.assertIn("cannot read the checks", str(self.decide(self.auto())))

    def test_required_check_names_come_from_checks_and_rulesets(self) -> None:
        self.set_gh(view=VIEW, protection={"contexts": [], "checks": [{"context": "test"}, {"context": "lint"}]})
        self.assertIsNone(self.decide(self.auto()))
        ruleset = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "test"}, {"context": "e2e"}]}}]
        self.set_gh(view=VIEW, rules=ruleset)
        self.assertIn("wait for e2e", str(self.decide(self.auto())))

    def test_missing_or_mismatched_sha_denies(self) -> None:
        self.assertIn("--match-head-commit", str(self.decide("gh pr merge 42 --squash")))
        self.assertIn("--match-head-commit", str(self.decide("gh pr merge 42 --match-head-commit abc")))
        self.assertIn("merge-go-step", str(self.decide(self.auto(OTHER_SHA))))

    def test_no_merge_go_record_denies_naming_merge_go_step(self) -> None:
        shutil.rmtree(self.repo / ".harness")
        self.assertIn("merge-go-step", str(self.decide(self.auto())))

    def test_head_moved_since_the_grant_denies(self) -> None:
        self.set_gh(view={"baseRefName": "main", "headRefOid": OTHER_SHA, "files": []}, protection=CHECKS)
        self.assertIn("head moved", str(self.decide(self.auto())))

    def test_admin_is_denied_even_with_the_grant(self) -> None:
        self.assertIn("admin-flag", str(self.decide(self.auto() + " --admin")))

    def test_hard_stop_paths_deny(self) -> None:
        for path in (".github/workflows/ci.yml", "plugins/x/templates/policy.json", "policy.json", ".claude/settings.local.json",
                     "settings.json", "app/.env.production", ".env", "migrations/001.sql", "db/migrations/002.sql"):
            self.set_gh(view={"baseRefName": "main", "headRefOid": SHA, "files": [{"path": "README.md"}, {"path": path}]},
                        protection=CHECKS)
            reason = str(self.decide(self.auto()))
            self.assertIn("auto_merge_never_paths", reason, path)
            self.assertIn(path, reason)

    def test_ordinary_paths_are_not_hard_stops(self) -> None:
        self.set_gh(view={"baseRefName": "main", "headRefOid": SHA,
                          "files": [{"path": "src/env.py"}, {"path": "docs/migrations.md"}, {"path": "src/settings.py"}]}, protection=CHECKS)
        self.assertIsNone(self.decide(self.auto()))

    def test_gh_lookup_failure_denies(self) -> None:
        self.set_gh(protection=CHECKS)  # pr view exits 1
        self.assertIn("cannot read PR 42", str(self.decide(self.auto())))
        self.set_gh(view={"baseRefName": "main", "headRefOid": SHA})  # malformed: no files
        self.assertIn("cannot read PR 42", str(self.decide(self.auto())))
        self.gh.unlink()
        self.assertIn("cannot read PR 42", str(self.decide(self.auto())))

    def test_too_many_listed_files_deny(self) -> None:
        files = [{"path": f"src/f{i}.py"} for i in range(policy_gate.MAX_LISTED_FILES)]
        self.set_gh(view={"baseRefName": "main", "headRefOid": SHA, "files": files}, protection=CHECKS)
        self.assertIn("cut short", str(self.decide(self.auto())))

    def test_no_required_checks_denies(self) -> None:
        view = {"baseRefName": "main", "headRefOid": SHA, "files": [{"path": "src/app.py"}]}
        self.set_gh(view=view)  # protection and rules lookups fail
        self.assertIn("no required status checks", str(self.decide(self.auto())))
        self.set_gh(view=view, protection={"contexts": [], "checks": []}, rules=[])
        self.assertIn("no required status checks", str(self.decide(self.auto())))

    def test_ruleset_required_checks_count(self) -> None:
        view = {"baseRefName": "main", "headRefOid": SHA, "files": [{"path": "src/app.py"}]}
        rules = [{"type": "pull_request"},
                 {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "test"}, {"context": "lint"}]}}]
        self.set_gh(view=view, rules=rules)
        self.assertIsNone(self.decide(self.auto()))

    def test_branch_or_current_branch_form_denies(self) -> None:
        self.assertIn("by number or URL", str(self.decide(f"gh pr merge feature --match-head-commit {SHA}")))
        self.assertIn("by number or URL", str(self.decide(f"gh pr merge --match-head-commit {SHA}")))

    def test_pr_url_form_allows(self) -> None:
        self.assertIsNone(self.decide(self.auto(pr="https://github.com/o/r/pull/42")))

    def test_per_pr_approval_still_works_without_the_grant(self) -> None:
        self.set_approvals({"merge": ["42"]})
        self.assertIsNone(self.decide("gh pr merge 42 --squash"))
        self.assertIn("pr-merge", str(self.decide("gh pr merge 43 --squash")))

    def test_per_pr_approval_wins_over_a_failing_grant_path(self) -> None:
        self.set_approvals({"merge": ["42"], "merge_policy": ["auto-when-green"]})
        self.set_gh()  # every gh lookup fails
        self.assertIsNone(self.decide("gh pr merge 42 --squash"))

    def test_policy_declares_the_hard_stop_paths(self) -> None:
        paths = self.policy["auto_merge_never_paths"]
        for expected in (".github/workflows/**", "**/policy.json", "**/settings*.json", "**/*.env*", "migrations/**"):
            self.assertIn(expected, paths)


if __name__ == "__main__":
    unittest.main()
