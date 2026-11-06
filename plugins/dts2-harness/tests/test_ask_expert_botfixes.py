"""ask_expert.py review-bot fixes: bundle verify outside a repo, relative backup dest, 3-seat panel tally, state dir constant."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ask_expert.py"
REAL_GIT: Final[str] = shutil.which("git") or "git"
# Delegates to real git, but swaps the github URL of `clone --mirror` for a local source repo.
WRAP_GIT: Final[str] = f"""#!/bin/sh
args=""
for a; do
  case "$a" in https://github.com/*) a="$SOURCE_REPO" ;; esac
  args="$args '$a'"
done
eval exec {REAL_GIT} $args
"""
GIT_ENV: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False,
                          cwd=str(cwd), env={**os.environ, **GIT_ENV, **(env or {})})


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class BundleCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.source: Path = self.dir / "source"
        for argv in (["init", "-q", str(self.source)], ["-C", str(self.source), "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run([REAL_GIT, *argv], check=True, capture_output=True, env={**os.environ, **GIT_ENV})
        wrapper: Path = write(self.dir / "bin" / "git", WRAP_GIT)
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        self.env: dict[str, str] = {"DTS2_GIT_BIN": str(wrapper), "SOURCE_REPO": str(self.source), "DTS2_HOME": str(self.dir / "home")}
        self.elsewhere: Path = self.dir / "not-a-repo"
        self.elsewhere.mkdir()

    def test_backup_verifies_from_a_directory_that_is_not_a_repo(self) -> None:
        done = run("backup", "--repo", "me/demo", "--dest", str(self.dir / "out"), cwd=self.elsewhere, env=self.env)
        self.assertEqual(done.returncode, 0, done.stdout)
        out: dict[str, Any] = json.loads(done.stdout)
        self.assertTrue(out["verified"], out)

    def test_delete_verifies_bundle_from_a_directory_that_is_not_a_repo(self) -> None:
        backup = run("backup", "--repo", "me/demo", "--dest", str(self.dir / "out"), cwd=self.elsewhere, env=self.env)
        bundle: str = json.loads(backup.stdout)["bundle"]
        fake_gh: Path = write(self.dir / "bin" / "gh", "#!/bin/sh\nexit 0\n")
        fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)
        done = run("delete", "--repo", "me/demo", "--confirm", "demo", "--bundle", bundle, cwd=self.elsewhere,
                   env={**self.env, "DTS2_GH_BIN": str(fake_gh)})
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_delete_still_refuses_a_corrupt_bundle_outside_a_repo(self) -> None:
        bundle: Path = write(self.dir / "me__demo-1.bundle", "not a bundle")
        done = run("delete", "--repo", "me/demo", "--confirm", "demo", "--bundle", str(bundle), cwd=self.elsewhere, env=self.env)
        self.assertEqual(done.returncode, 2)
        self.assertIn("verify failed", json.loads(done.stdout)["error"])

    def test_relative_dest_is_resolved_against_the_callers_directory(self) -> None:
        done = run("backup", "--repo", "me/demo", "--dest", "rel/backups", cwd=self.elsewhere, env=self.env)
        self.assertEqual(done.returncode, 0, done.stdout)
        out: dict[str, Any] = json.loads(done.stdout)
        bundle: Path = Path(out["bundle"])
        self.assertTrue(bundle.is_absolute())
        self.assertEqual(bundle.parent, (self.elsewhere / "rel" / "backups").resolve())
        self.assertTrue(bundle.is_file())

    def test_tilde_dest_is_expanded(self) -> None:
        done = run("backup", "--repo", "me/demo", "--dest", "~/bk", cwd=self.elsewhere, env={**self.env, "HOME": str(self.dir / "h")})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(Path(json.loads(done.stdout)["bundle"]).parent, (self.dir / "h" / "bk").resolve())


class PanelTallyCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        self.addCleanup(shutil.rmtree, self.dir, True)

    count: int = 0

    def plan(self, seat: str, first: str) -> str:
        self.count += 1
        return f"{seat}={write(self.dir / f'plan-{self.count}-{seat}.md', first + chr(10) + 'Reasons follow.' + chr(10))}"

    def votes(self, seat: str, *lines: str) -> str:
        self.count += 1
        return f"{seat}={write(self.dir / f'vote-{self.count}-{seat}.md', chr(10).join(lines) + chr(10))}"

    def tally(self, plans: list[str], votes: list[str] | None = None) -> tuple[int, dict[str, Any]]:
        argv: list[str] = ["panel-tally", "--plans", *plans] + (["--votes", *votes] if votes else [])
        done = run(*argv, cwd=self.dir)
        return done.returncode, json.loads(done.stdout)

    def test_all_five_verdicts_survive(self) -> None:
        for line, expect in (("KEEP", "KEEP"), ("FOLD INTO acme-api", "FOLD"), ("SELL AS TEMPLATE", "TEMPLATE"),
                             ("TEMPLATE", "TEMPLATE"), ("ARCHIVE", "ARCHIVE"), ("DELETE", "DELETE")):
            plans = [self.plan(s, f"VERDICT: {line}") for s in "abc"]
            code, out = self.tally(plans)
            self.assertEqual((code, out["verdict"], out["unanimous"]), (0, expect, True), line)

    def test_two_of_three_is_a_majority_and_not_unanimous(self) -> None:
        code, out = self.tally([self.plan("a", "VERDICT: KEEP"), self.plan("b", "VERDICT: KEEP"), self.plan("c", "VERDICT: DELETE")])
        self.assertEqual((code, out["verdict"], out["unanimous"], out["counts"]), (0, "KEEP", False, {"KEEP": 2, "DELETE": 1}))

    def test_three_way_split_is_no_majority(self) -> None:
        code, out = self.tally([self.plan("a", "VERDICT: KEEP"), self.plan("b", "VERDICT: ARCHIVE"), self.plan("c", "VERDICT: DELETE")])
        self.assertEqual((code, out["verdict"]), (0, "no-majority"))
        self.assertFalse(out["pass"])

    def test_fold_with_different_targets_counts_as_one_verdict(self) -> None:
        plans = [self.plan("a", "VERDICT: FOLD INTO x"), self.plan("b", "VERDICT: FOLD INTO y"), self.plan("c", "VERDICT: KEEP")]
        self.assertEqual(self.tally(plans)[1]["verdict"], "FOLD")

    def test_cross_review_with_two_votes_per_seat(self) -> None:
        plans = [self.plan(s, "VERDICT: ARCHIVE") for s in "abc"]
        votes = [self.votes("a", "VOTE b: AGREE", "VOTE c: AGREE", "- a finding"), self.votes("b", "VOTE a: AGREE", "VOTE c: AGREE"),
                 self.votes("c", "VOTE a: AGREE", "VOTE b: AGREE")]
        code, out = self.tally(plans, votes)
        self.assertEqual((code, out["verdict"], out["disagree"], out["pass"]), (0, "ARCHIVE", 0, True))

    def test_any_disagree_blocks_the_pass(self) -> None:
        plans = [self.plan(s, "VERDICT: ARCHIVE") for s in "abc"]
        votes = [self.votes("a", "VOTE b: AGREE", "VOTE c: DISAGREE"), self.votes("b", "VOTE a: AGREE", "VOTE c: AGREE"),
                 self.votes("c", "VOTE a: AGREE", "VOTE b: AGREE")]
        out = self.tally(plans, votes)[1]
        self.assertEqual((out["verdict"], out["disagree"], out["pass"]), ("ARCHIVE", 1, False))

    def test_unanimous_plans_without_votes_do_not_pass(self) -> None:
        out = self.tally([self.plan(s, "VERDICT: KEEP") for s in "abc"])[1]
        self.assertEqual((out["verdict"], out["pass"]), ("KEEP", False))

    def test_bad_input_is_refused(self) -> None:
        good = [self.plan(s, "VERDICT: KEEP") for s in "ab"]
        for plans, votes in (
            (good + [self.plan("c", "I think we should keep it")], None),
            (good + [self.plan("c", "VERDICT: MAYBE")], None),
            (good[:1], None),
            (good + [self.plan("c", "VERDICT: KEEP")], [self.votes("a", "VOTE b: AGREE")]),
            (good + [self.plan("c", "VERDICT: KEEP")], [self.votes("a", "VOTE a: AGREE", "VOTE b: AGREE"),
                                                        self.votes("b", "VOTE a: AGREE", "VOTE c: AGREE"),
                                                        self.votes("c", "VOTE a: AGREE", "VOTE b: AGREE")]),
        ):
            code, out = self.tally(plans, votes)
            self.assertEqual(code, 2, (plans, votes, out))
            self.assertFalse(out["ok"])


class StateDirCase(unittest.TestCase):
    def test_state_dir_comes_from_state_io_only(self) -> None:
        text: str = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"""["']\.harness""")
        self.assertIn("state_io.ASK_EXPERT_REL", text)


if __name__ == "__main__":
    unittest.main()
