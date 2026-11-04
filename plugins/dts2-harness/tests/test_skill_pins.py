"""B4: commit pins, update proposals, 24h lock skip, and the once-per-repo / diff-size companion gates."""
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
from test_skills_check import FAKE_GH, Fixture

SHA_A: Final[str] = "a" * 40
SHA_B: Final[str] = "b" * 40
SHA_C: Final[str] = "c" * 40
GATE: Final[Path] = PLUGIN_ROOT / "scripts" / "companion-gate.py"
MATT_URL: Final[str] = "https://github.com/mattpocock/skills"
PIN_KEEP: Final[str] = (f"skills:\n  - name: grill-me\n    source: npx skills add {MATT_URL} --skill grill-me\n"
                        f"    pin: {SHA_A}\n    serves: harness\n")
GH_HEADS: Final[str] = """
if "/commits/HEAD" in target:
    heads = json.loads((d / "heads.json").read_text())
    repo = target.split("repos/", 1)[1].split("/commits", 1)[0]
    if repo not in heads:
        sys.exit(1)
    print(heads[repo]); sys.exit(0)
if "/compare/" in target:
    print("\\n".join(json.loads((d / "compare.json").read_text()))); sys.exit(0)
"""


class PinFixture(Fixture):
    def __init__(self, keep: str = "") -> None:
        super().__init__(keep)
        self.heads: dict[str, str] = {}
        self.compare: list[str] = []

    def run(self, *flags: str) -> dict[str, Any]:
        (self.fake / "heads.json").write_text(json.dumps(self.heads))
        (self.fake / "compare.json").write_text(json.dumps(self.compare))
        out = super().run(*flags)
        return out

    def write_fakes(self) -> None:
        (self.fake / "gh.py").write_text(FAKE_GH.replace("target = args[1]\n", "target = args[1]\n" + GH_HEADS), encoding="utf-8")

    def keep_text(self) -> str:
        return (self.repo / ".harness" / "keep.yaml").read_text(encoding="utf-8")


def pin_fixture(keep: str = PIN_KEEP) -> PinFixture:
    fx = PinFixture(keep)
    fx.write_fakes()
    # Fixture.run rewrites gh.py only at construction, so the patched fake stays.
    return fx


class PinInstallTests(unittest.TestCase):
    def test_pinned_skill_installs_the_exact_commit(self) -> None:
        fx = pin_fixture()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["pinned"], ["grill-me"])
        self.assertIn(f"{MATT_URL}/tree/{SHA_A} --skill grill-me", fx.log("npx"))
        self.assertIn(f"{MATT_URL} --skill pr", fx.log("npx"))  # unpinned companions keep the plain ref

    def test_bad_pin_is_rejected_and_the_plain_ref_is_used(self) -> None:
        fx = pin_fixture(PIN_KEEP.replace(SHA_A, "main"))
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["pinned"], [])
        self.assertTrue(any(r["name"] == "grill-me" and "SHA" in r["reason"] for r in out["skills"]["rejected"]))
        self.assertNotIn("/tree/main", fx.log("npx"))

    def test_pinned_skills_stop_the_blanket_update(self) -> None:
        fx = pin_fixture()
        out = fx.run("--fix")
        self.assertNotIn("update -p -y", fx.log("npx"))
        self.assertIn("approved proposal", out["skills"]["update_skipped"])

    def test_unpinned_repos_still_get_the_update(self) -> None:
        fx = pin_fixture("")
        fx.run("--fix")
        self.assertIn("update -p -y", fx.log("npx"))


class ProposalTests(unittest.TestCase):
    def test_changed_upstream_becomes_a_proposal_and_nothing_is_applied(self) -> None:
        fx = pin_fixture()
        fx.heads = {"mattpocock/skills": SHA_B}
        fx.compare = ["skills/productivity/grill-me/SKILL.md", "skills/other/x/notes.txt"]
        before = fx.keep_text()
        out = fx.run("--fix")
        proposal = next(p for p in out["skills"]["proposals"] if p["name"] == "grill-me")
        self.assertEqual((proposal["kind"], proposal["pinned"], proposal["upstream"]), ("update", SHA_A, SHA_B))
        self.assertEqual(proposal["changed_files"], ["skills/productivity/grill-me/SKILL.md"])
        self.assertTrue(proposal["instruction_files_changed"])
        self.assertIn(f"compare/{SHA_A}...{SHA_B}", proposal["compare_url"])
        self.assertEqual(fx.keep_text(), before)  # keep.yaml untouched
        self.assertNotIn(f"tree/{SHA_B}", fx.log("npx"))  # new commit never installed
        stored = json.loads((fx.repo / ".harness" / "skill-updates.json").read_text(encoding="utf-8"))
        self.assertIn("grill-me", [p["name"] for p in stored])

    def test_unpinned_skill_gets_a_pin_offer(self) -> None:
        fx = pin_fixture("")
        fx.heads = {"mattpocock/skills": SHA_C}
        out = fx.run("--fix")
        offers = {p["name"]: p for p in out["skills"]["proposals"]}
        self.assertEqual(offers["pr"]["kind"], "pin")
        self.assertIsNone(offers["pr"]["compare_url"])

    def test_pin_equal_to_head_proposes_nothing(self) -> None:
        fx = pin_fixture()
        fx.heads = {"mattpocock/skills": SHA_A}
        out = fx.run("--fix")
        self.assertNotIn("grill-me", [p["name"] for p in out["skills"]["proposals"]])

    def test_unreachable_upstream_proposes_nothing(self) -> None:
        fx = pin_fixture()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["proposals"], [])

    def test_apply_update_installs_the_proposed_commit_and_moves_the_pin(self) -> None:
        fx = pin_fixture()
        fx.heads = {"mattpocock/skills": SHA_B}
        fx.run("--fix")
        out = fx.run("--fix", "--apply-update", f"grill-me={SHA_B}")
        self.assertEqual(out["skills"]["applied"], [{"name": "grill-me", "pin": SHA_B}])
        self.assertIn(f"{MATT_URL}/tree/{SHA_B} --skill grill-me", fx.log("npx"))
        self.assertIn(f"pin: {SHA_B}", fx.keep_text())
        self.assertNotIn(SHA_A, fx.keep_text())

    def test_apply_update_refuses_a_sha_that_was_never_proposed(self) -> None:
        fx = pin_fixture()
        fx.heads = {"mattpocock/skills": SHA_B}
        fx.run("--fix")
        before = fx.keep_text()
        out = fx.run("--fix", "--apply-update", f"grill-me={SHA_C}")
        self.assertEqual(out["skills"]["applied"], [])
        self.assertTrue(out["skills"]["rejected"])
        self.assertEqual(fx.keep_text(), before)

    def test_apply_update_adds_a_keep_entry_for_a_default_companion(self) -> None:
        fx = pin_fixture("")
        fx.heads = {"mattpocock/skills": SHA_C}
        fx.run("--fix")
        out = fx.run("--fix", "--apply-update", f"pr={SHA_C}")
        self.assertEqual(out["skills"]["applied"], [{"name": "pr", "pin": SHA_C}])
        self.assertIn(f"  - name: pr\n    source: npx skills add {MATT_URL} --skill pr\n    pin: {SHA_C}", fx.keep_text())

    def test_report_only_mode_never_applies(self) -> None:
        fx = pin_fixture()
        fx.heads = {"mattpocock/skills": SHA_B}
        fx.run("--fix")
        out = fx.run("--apply-update", f"grill-me={SHA_B}")
        self.assertEqual(out["skills"]["applied"], [])


class LockSkipTests(unittest.TestCase):
    def lock(self, fx: Fixture, age_s: float) -> None:
        path = fx.repo / "skills-lock.json"
        path.write_text(json.dumps({"skills": {"grill-me": {"source": "mattpocock/skills"}}}), encoding="utf-8")
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))

    def test_fresh_lock_that_lists_the_skill_skips_its_install(self) -> None:
        fx = pin_fixture("")
        self.lock(fx, 3600)
        out = fx.run("--fix")
        self.assertEqual([s["name"] for s in out["skills"]["install_skipped"]], ["grill-me"])
        self.assertNotIn("--skill grill-me", fx.log("npx"))

    def test_old_lock_does_not_skip(self) -> None:
        fx = pin_fixture("")
        self.lock(fx, 3 * 86400)
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["install_skipped"], [])
        self.assertIn("--skill grill-me", fx.log("npx"))

    def test_fresh_lock_without_the_skill_still_installs(self) -> None:
        fx = pin_fixture("")
        (fx.repo / "skills-lock.json").write_text('{"skills": {}}', encoding="utf-8")
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["install_skipped"], [])


class PinTextTests(unittest.TestCase):
    def test_valid_pin(self) -> None:
        self.assertTrue(pins.valid_pin(SHA_A))
        for bad in ("main", SHA_A[:-1], SHA_A.upper(), SHA_A + "0", ""):
            self.assertFalse(pins.valid_pin(bad), bad)

    def test_pinned_ref_forms(self) -> None:
        self.assertEqual(pins.pinned_ref(f"{MATT_URL} --skill pr", SHA_A), f"{MATT_URL}/tree/{SHA_A} --skill pr")
        self.assertEqual(pins.pinned_ref("warpdotdev/common-skills@resolve-merge-conflicts", SHA_A),
                         f"https://github.com/warpdotdev/common-skills/tree/{SHA_A} --skill resolve-merge-conflicts")
        self.assertIsNone(pins.pinned_ref("x; rm -rf /", SHA_A))
        self.assertIsNone(pins.pinned_ref(f"{MATT_URL} --skill pr", "main"))

    def test_set_pin_replaces_and_keeps_neighbours(self) -> None:
        text = PIN_KEEP + "  - name: other\n    source: plugin\n"
        out = pins.set_pin_text(text, "grill-me", SHA_B)
        self.assertEqual(out.count("pin:"), 1)
        self.assertIn(f"    pin: {SHA_B}\n", out)
        self.assertIn("  - name: other\n    source: plugin\n", out)
        self.assertEqual(pins.set_pin_text(text, "missing", SHA_B), text)

    def test_lock_age_and_skip_use_an_injected_clock(self) -> None:
        repo = make_tmp_home()
        self.assertIsNone(pins.lock_age_s(repo))
        (repo / "skills-lock.json").write_text('{"skills": {"a": {}}}', encoding="utf-8")
        now = time.time()
        self.assertTrue(pins.skip_install(repo, "a", now + 3600))
        self.assertFalse(pins.skip_install(repo, "a", now + 90000))
        self.assertFalse(pins.skip_install(repo, "b", now))


def gate(repo: Path, *args: str, git: str | None = None) -> dict[str, Any]:
    env = {**os.environ, **({"DTS2_GIT_BIN": git} if git else {})}
    done = subprocess.run([sys.executable, str(GATE), *args, "--repo", str(repo)], capture_output=True, text=True,
                          env=env, check=True)
    parsed: dict[str, Any] = json.loads(done.stdout)
    return parsed


def fake_git(numstat: str, code: int = 0) -> str:
    path = make_tmp_home() / "git.py"
    path.write_text(f"import sys\nsys.stdout.write({numstat!r})\nsys.exit({code})\n", encoding="utf-8")
    return str(path)


class CompanionGateTests(unittest.TestCase):
    def test_pre_commit_runs_once_per_repo(self) -> None:
        repo = make_tmp_home()
        (repo / ".harness").mkdir()
        first = gate(repo, "check", "--skill", "setup-pre-commit")
        self.assertTrue(first["run"])
        self.assertTrue(gate(repo, "record", "--skill", "setup-pre-commit")["recorded"])
        second = gate(repo, "check", "--skill", "setup-pre-commit")
        self.assertFalse(second["run"])
        self.assertEqual(second["reason"], "already-ran")

    def test_recording_twice_keeps_the_first_date(self) -> None:
        repo = make_tmp_home()
        (repo / ".harness").mkdir()
        (repo / ".harness" / "companions-ran.json").write_text('{"setup-pre-commit": "2026-01-02"}', encoding="utf-8")
        self.assertEqual(gate(repo, "record", "--skill", "setup-pre-commit")["ran_on"], "2026-01-02")

    def test_architecture_runs_only_over_150_changed_lines(self) -> None:
        repo = make_tmp_home()
        small = gate(repo, "check", "--skill", "improve-codebase-architecture", git=fake_git("100\t50\ta.py\n-\t-\timg.png\n"))
        self.assertEqual((small["run"], small["changed_lines"]), (False, 150))
        big = gate(repo, "check", "--skill", "improve-codebase-architecture", git=fake_git("100\t51\ta.py\n"))
        self.assertEqual((big["run"], big["changed_lines"]), (True, 151))

    def test_unmeasurable_diff_runs_the_pass(self) -> None:
        repo = make_tmp_home()
        out = gate(repo, "check", "--skill", "improve-codebase-architecture", git=fake_git("", code=128))
        self.assertTrue(out["run"])
        self.assertEqual(out["reason"], "diff-unmeasurable")

    def test_unsafe_base_ref_is_not_passed_to_git(self) -> None:
        repo = make_tmp_home()
        out = gate(repo, "check", "--skill", "improve-codebase-architecture", "--base=--output=x", git=fake_git("1\t1\ta\n"))
        self.assertEqual(out["reason"], "diff-unmeasurable")

    def test_other_skills_are_ungated(self) -> None:
        self.assertTrue(gate(make_tmp_home(), "check", "--skill", "grill-me")["run"])


if __name__ == "__main__":
    unittest.main()
