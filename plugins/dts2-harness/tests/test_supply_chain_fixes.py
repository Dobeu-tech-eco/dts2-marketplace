"""B4/B8 review fixes: lock rule on the daily refresh, no bulk update, fail-closed pins, companion gate wiring."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Final

import skill_pins_loader  # noqa: F401  (puts scripts/ on sys.path)
import skill_pins as pins
from helpers import PLUGIN_ROOT, make_tmp_home
from skill_text import read_rel
from test_skill_pins import MATT_URL, PIN_KEEP, SHA_A, SHA_B, pin_fixture

GATE: Final[Path] = PLUGIN_ROOT / "scripts" / "companion-gate.py"


def read(relative: str) -> str:
    return read_rel(relative)


def age_lock(repo: Path, age_s: float, skills: tuple[str, ...] = ("grill-me",)) -> None:
    path = repo / "skills-lock.json"
    path.write_text(json.dumps({"skills": {s: {"source": "mattpocock/skills"} for s in skills}}), encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))


class LockRuleTests(unittest.TestCase):
    def test_fresh_lock_listing_a_missing_skill_still_installs_it(self) -> None:
        fx = pin_fixture("")
        age_lock(fx.repo, 600)
        self.assertFalse(fx.skill("grill-me").exists())
        out = fx.run("--fix")
        self.assertIn("--skill grill-me", fx.log("npx"))
        self.assertTrue(fx.skill("grill-me").is_file())
        self.assertIn("grill-me", out["skills"]["installed"])
        self.assertNotIn("grill-me", [m["name"] for m in out["skills"]["missing"]])

    def test_fresh_lock_skips_the_daily_refresh(self) -> None:
        fx = pin_fixture("")
        fx.heads["mattpocock/skills"] = SHA_B
        age_lock(fx.repo, 600)
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["update_skipped"], "skills-lock.json under 24h old")
        self.assertEqual(out["skills"]["proposals"], [])
        self.assertNotIn("commits/HEAD", fx.log("gh"))  # no upstream call for the refresh
        self.assertFalse((fx.repo / ".harness" / "skill-updates.json").exists())
        self.assertNotIn("update -p -y", fx.log("npx"))

    def test_old_lock_runs_the_daily_refresh(self) -> None:
        fx = pin_fixture("")
        fx.heads["mattpocock/skills"] = SHA_B
        age_lock(fx.repo, 3 * 86400)
        out = fx.run("--fix")
        self.assertIsNone(out["skills"]["update_skipped"])
        self.assertTrue(out["skills"]["proposals"])


class NoBlanketUpdateTests(unittest.TestCase):
    def test_every_skill_gets_a_proposal_and_no_update_runs(self) -> None:
        fx = pin_fixture("")
        fx.heads["mattpocock/skills"] = SHA_B
        out = fx.run("--fix", "--force-full")
        self.assertNotIn("update -p -y", fx.log("npx"))
        stored = json.loads((fx.repo / ".harness" / "skill-updates.json").read_text(encoding="utf-8"))
        self.assertEqual({p["name"] for p in stored}, {p["name"] for p in out["skills"]["proposals"]})
        self.assertIn("grill-me", {p["name"] for p in stored})

    def test_check_only_mode_writes_no_proposals_file(self) -> None:
        fx = pin_fixture("")
        fx.heads["mattpocock/skills"] = SHA_B
        out = fx.run("--force-full")
        self.assertTrue(out["skills"]["proposals"])  # reported, not stored
        self.assertFalse((fx.repo / ".harness" / "skill-updates.json").exists())


class PinFailClosedTests(unittest.TestCase):
    def test_malformed_pin_issues_no_install_for_that_skill(self) -> None:
        fx = pin_fixture(PIN_KEEP.replace(SHA_A, "v1.2"))
        out = fx.run("--fix")
        self.assertNotIn("--skill grill-me", fx.log("npx"))
        self.assertNotIn("/tree/", fx.log("npx").split("--skill grill-me")[0] if "--skill grill-me" in fx.log("npx") else "")
        reasons = [r["reason"] for r in out["skills"]["rejected"] if r["name"] == "grill-me"]
        self.assertEqual(len(reasons), 1)
        self.assertIn("fix the pin", reasons[0])
        self.assertNotIn("grill-me", out["skills"]["installed"])

    def test_apply_update_does_not_double_count_rejections(self) -> None:
        fx = pin_fixture(PIN_KEEP.replace(SHA_A, "v1.2"))
        out = fx.run("--fix", "--apply-update", f"pr={SHA_B}")
        names = [r["name"] for r in out["skills"]["rejected"]]
        self.assertEqual(names.count("grill-me"), 1)
        self.assertEqual(names.count("pr"), 1)  # the unmatched apply request, reported once


class ProposalCutTests(unittest.TestCase):
    def test_instruction_file_past_the_cut_is_still_flagged(self) -> None:
        files = [f"skills/grill-me/code{i}.py" for i in range(pins.MAX_FILES_SHOWN + 5)] + ["skills/grill-me/SKILL.md"]
        out = pins.build_proposals([{"name": "grill-me", "ref": f"{MATT_URL} --skill grill-me", "pin": SHA_A}],
                                   lambda r: SHA_B, lambda r, b, h: files)
        self.assertEqual(len(out[0]["changed_files"]), pins.MAX_FILES_SHOWN)
        self.assertNotIn("skills/grill-me/SKILL.md", out[0]["changed_files"])
        self.assertTrue(out[0]["instruction_files_changed"])


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True)


def gate(repo: Path, *args: str) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k != "DTS2_GIT_BIN"}
    done = subprocess.run([sys.executable, str(GATE), "check", "--repo", str(repo), "--skill", "improve-codebase-architecture", *args],
                          capture_output=True, text=True, env=env, check=True)
    parsed: dict[str, Any] = json.loads(done.stdout)
    return parsed


def feature_repo() -> Path:
    repo = make_tmp_home()
    git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "feature")
    return repo


class GateWorkingTreeTests(unittest.TestCase):
    def test_uncommitted_changes_over_150_lines_run_the_pass(self) -> None:
        repo = feature_repo()
        (repo / "base.txt").write_text("".join(f"line {i}\n" for i in range(200)), encoding="utf-8")  # tracked, uncommitted
        out = gate(repo, "--base", "main")
        self.assertTrue(out["run"])
        self.assertGreater(out["changed_lines"], 150)

    def test_untracked_files_count(self) -> None:
        repo = feature_repo()
        (repo / "new.py").write_text("".join(f"x = {i}\n" for i in range(160)), encoding="utf-8")
        out = gate(repo, "--base", "main")
        self.assertEqual((out["run"], out["changed_lines"]), (True, 160))

    def test_small_uncommitted_change_skips_the_pass(self) -> None:
        repo = feature_repo()
        (repo / "new.py").write_text("a = 1\n", encoding="utf-8")
        out = gate(repo, "--base", "main")
        self.assertEqual((out["run"], out["reason"]), (False, "diff-small"))

    def test_committed_and_uncommitted_work_add_up_against_the_merge_base(self) -> None:
        repo = feature_repo()
        (repo / "a.py").write_text("".join(f"{i}\n" for i in range(100)), encoding="utf-8")
        git(repo, "add", "a.py")
        git(repo, "commit", "-q", "-m", "a")
        (repo / "b.py").write_text("".join(f"{i}\n" for i in range(60)), encoding="utf-8")
        out = gate(repo, "--base", "main")
        self.assertEqual((out["run"], out["changed_lines"]), (True, 160))

    def test_default_base_is_the_repos_default_branch(self) -> None:
        repo = feature_repo()
        git(repo, "update-ref", "refs/remotes/origin/main", "main")
        git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.assertEqual(gate(repo)["base"], "main")
        git(repo, "branch", "trunk", "main")
        git(repo, "update-ref", "refs/remotes/origin/trunk", "main")
        git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.assertEqual(gate(repo)["base"], "trunk")

    def test_missing_origin_head_falls_back_to_main(self) -> None:
        self.assertEqual(gate(feature_repo())["base"], "main")


class TextContractTests(unittest.TestCase):
    def test_phase_4_names_check_and_record_and_drops_the_every_commit_rule(self) -> None:
        text = read("skills/run/phase-4-ship.md")
        self.assertIn("companion-gate.py\" check --repo . --skill setup-pre-commit", text)
        self.assertIn("companion-gate.py\" record --repo . --skill setup-pre-commit", text)
        self.assertNotIn("Before every commit", text)
        self.assertNotIn("improve-codebase-architecture", text)  # that pass is gated in Phase 2
        self.assertNotIn("before every commit", read("skills/onboard/SKILL.md"))
        self.assertNotIn("before every commit", read("templates/discipline.md"))

    def test_architecture_gate_is_wired_where_the_pass_runs(self) -> None:
        for path in ("skills/run/phase-2-build.md", "templates/discipline.md"):
            text = read(path)
            self.assertIn("companion-gate.py", text, path)
            self.assertIn("improve-codebase-architecture", text, path)
        self.assertIn("--skill improve-codebase-architecture", read("skills/run/phase-2-build.md"))

    def test_precheck_documents_the_new_report_keys_and_the_approval_step(self) -> None:
        text = read("skills/run/SKILL.md")
        for key in ("`proposals`", "`install_skipped`", "`update_skipped`", "`applied`"):
            self.assertIn(key, text)
        for field in ("compare_url", "changed_files", "instruction_files_changed"):
            self.assertIn(field, text)
        self.assertIn("--apply-update", text)
        self.assertIn("explicit yes", text)
        self.assertIn("Decisions action item", text)

    def test_onboard_and_run_do_not_promise_a_bulk_update(self) -> None:
        self.assertNotIn("updates them all", read("skills/onboard/SKILL.md"))
        self.assertNotIn("skills update -p -y", read("skills/run/SKILL.md"))

    def test_autopilot_warns_about_stale_council_models_without_blocking(self) -> None:
        text = read("skills/autopilot/SKILL.md")
        self.assertIn("`stale`", text)
        self.assertIn("`checked` date", text)
        self.assertIn("never blocks the council", text)


if __name__ == "__main__":
    unittest.main()
