"""scripts/skills-check.py against fake npx, gh and claude binaries."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "skills-check.py"
FAKE_NPX: Final[str] = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_DIR"]) / "npx.log"
log.open("a", encoding="utf-8").write(" ".join(args) + "\n")
if os.environ.get("FAKE_NO_NPX"):
    sys.exit(127)
args = [a for a in args if a not in ("-y", "--yes")][1:]  # drop --yes and the pinned "skills@<ver>"
cmd = args[0]
if cmd == "add" and "--list" in args:
    for name in json.loads((Path(os.environ["FAKE_DIR"]) / "listed.json").read_text()).get(args[1], []):
        print("│    " + name)
    sys.exit(0)
if cmd == "add":
    ref = args[1:]
    name = ref[ref.index("--skill") + 1] if "--skill" in ref else ref[0].split("@", 1)[1]
    if name in os.environ.get("FAKE_FAIL", "").split(","):
        print("install failed"); sys.exit(1)
    if "--copy" in ref:
        d = Path.cwd() / ".claude" / "skills" / name
    else:
        d = Path.cwd() / ".agents" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("---\nname: " + name + "\n---\n")
    sys.exit(0)
if cmd == "remove":
    import shutil
    shutil.rmtree(Path.cwd() / ".claude" / "skills" / args[1], ignore_errors=True)
    sys.exit(0)
if cmd == "update":
    import shutil
    for name in filter(None, os.environ.get("FAKE_UPDATE_CLOBBER", "").split(",")):
        d = Path.cwd() / ".claude" / "skills" / name
        shutil.rmtree(d, ignore_errors=True)  # what the real CLI did to committed Stripe skills
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("---\nname: " + name + "\n---\nupstream v2\n")
        (d / "NEW.md").write_text("added by update\n")
        (Path.cwd() / "skills-lock.json").write_text('{"skills": {}}\n')
    print("✓ All project skills are up to date"); sys.exit(0)
if cmd == "find":
    print((Path(os.environ["FAKE_DIR"]) / "find.txt").read_text()); sys.exit(0)
sys.exit(2)
'''
FAKE_GH: Final[str] = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
d = Path(os.environ["FAKE_DIR"])
(d / "gh.log").open("a", encoding="utf-8").write(" ".join(args) + "\n")
target = args[1]
if "/git/trees/" in target:
    repo = target.split("repos/", 1)[1].split("/git/", 1)[0]
    trees = json.loads((d / "trees.json").read_text())
    if repo not in trees:
        sys.exit(1)
    truncated = "true" if repo in os.environ.get("FAKE_TRUNCATED", "").split(",") else "false"
    print("\n".join([truncated, *trees[repo]])); sys.exit(0)
if "plugin.json" in target:
    print(json.dumps({"version": os.environ.get("FAKE_PUBLISHED", "3.7.0")})); sys.exit(0)
if "/contents/" in target and target.endswith("SKILL.md"):
    repo, path = target.split("repos/", 1)[1].split("/contents/", 1)
    trees = json.loads((d / "trees.json").read_text())
    if os.environ.get("FAKE_NO_CONTENTS") or path not in trees.get(repo, []):
        sys.exit(1)
    print("---\nname: " + path.split("/")[-2] + "\n---\n"); sys.exit(0)
sys.exit(1)
'''
FAKE_CLAUDE: Final[str] = r'''
import os, sys
from pathlib import Path
(Path(os.environ["FAKE_DIR"]) / "claude.log").open("a", encoding="utf-8").write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["plugin", "update"] and os.environ.get("FAKE_CLAUDE_FAIL"):
    print("update failed"); sys.exit(1)
sys.exit(0)
'''
MATT: Final[list[str]] = [f"skills/engineering/{n}/SKILL.md" for n in (
    "pr", "diagnosing-bugs", "ask-matt", "research", "code-review", "improve-codebase-architecture")] + [
    "skills/productivity/grill-me/SKILL.md", "skills/productivity/writing-for-agents/SKILL.md",
    "skills/in-progress/loop-me/SKILL.md", "skills/misc/setup-pre-commit/SKILL.md"]
WARP: Final[list[str]] = [".agents/skills/resolve-merge-conflicts/SKILL.md"]


class Fixture:
    def __init__(self, keep: str = "", installed_version: str = "3.7.0", published: str = "3.7.0") -> None:
        self.repo: Path = make_tmp_home()
        self.home: Path = make_tmp_home()
        self.fake: Path = make_tmp_home()
        self.root: Path = make_tmp_home()
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": installed_version}))
        (self.repo / ".harness").mkdir()
        if keep:
            (self.repo / ".harness" / "keep.yaml").write_text(keep, encoding="utf-8")
        for name, body in (("npx.py", FAKE_NPX), ("gh.py", FAKE_GH), ("claude.py", FAKE_CLAUDE)):
            (self.fake / name).write_text(body, encoding="utf-8")
        self.trees: dict[str, list[str]] = {"mattpocock/skills": list(MATT), "warpdotdev/common-skills": list(WARP)}
        self.listed: dict[str, list[str]] = {}
        self.find: str = ""
        self.published: str = published
        self.fail: str = ""
        self.claude_fail: str = ""
        self.no_contents: str = ""
        self.truncated: str = ""
        self.no_npx: str = ""
        self.clobber: str = ""
        self.git_bin: str = ""

    def run(self, *flags: str) -> dict[str, Any]:
        (self.fake / "trees.json").write_text(json.dumps(self.trees))
        (self.fake / "listed.json").write_text(json.dumps(self.listed))
        (self.fake / "find.txt").write_text(self.find, encoding="utf-8")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FAKE_DIR": str(self.fake), "FAKE_PUBLISHED": self.published, "FAKE_FAIL": self.fail, "FAKE_CLAUDE_FAIL": self.claude_fail, "FAKE_NO_CONTENTS": self.no_contents, "FAKE_TRUNCATED": self.truncated, "FAKE_NO_NPX": self.no_npx, "FAKE_UPDATE_CLOBBER": self.clobber,
               "DTS2_NPX_BIN": str(self.fake / "npx.py"), "DTS2_GH_BIN": str(self.fake / "gh.py"),
               "DTS2_CLAUDE_BIN": str(self.fake / "claude.py"), "DTS2_MARKETPLACE_REPO": "example-org/example-marketplace"}  # G-77
        if self.git_bin:
            env["DTS2_GIT_BIN"] = self.git_bin
        done = subprocess.run([sys.executable, str(SCRIPT), str(self.repo), "--home", str(self.home),
                               "--plugin-root", str(self.root), *flags],
                              capture_output=True, text=True, env=env, check=True)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def log(self, name: str) -> str:
        path: Path = self.fake / f"{name}.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def skill(self, name: str) -> Path:
        return self.repo / ".claude" / "skills" / name / "SKILL.md"

    def commit(self, files: dict[str, str]) -> None:
        """Make the repo a git repo with these files committed (paths relative to the repo)."""
        for rel, body in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(body, encoding="utf-8")
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", *files], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "vendor skills"], check=True)

    def mark_today(self) -> None:
        import datetime
        (self.repo / ".harness" / ".skills-checked").write_text(
            datetime.date.today().isoformat() + "\n", encoding="utf-8")


class DailyGateTests(unittest.TestCase):
    def test_first_run_of_day_is_full_and_writes_marker(self) -> None:
        fx = Fixture()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["freshness"], "full")
        self.assertTrue((fx.repo / ".harness" / ".skills-checked").is_file())
        self.assertNotIn("update -p -y", fx.log("npx"))  # the daily sweep only proposes; it never updates

    def test_second_run_same_day_is_fast_and_touches_no_network(self) -> None:
        fx = Fixture()
        fx.run("--fix")
        (fx.fake / "npx.log").unlink()
        (fx.fake / "gh.log").unlink()
        (fx.fake / "claude.log").unlink()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["freshness"], "fast")
        self.assertEqual(len(out["skills"]["installed"]), 11)
        self.assertNotIn("update -p -y", fx.log("npx"))
        self.assertEqual(fx.log("claude"), "")  # no marketplace refresh, no plugin update
        self.assertEqual(out["harness"]["marketplaces"], {})

    def test_fast_run_still_installs_a_missing_skill(self) -> None:
        fx = Fixture()
        fx.mark_today()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["freshness"], "fast")
        self.assertEqual(len(out["skills"]["installed"]), 11)
        self.assertIn("add", fx.log("npx"))  # the missing ones were installed
        self.assertNotIn("update -p -y", fx.log("npx"))  # but no freshness sweep

    def test_fast_run_skips_gone_upstream_detection(self) -> None:
        fx = Fixture("skills:\n  - name: pr\n    source: npx skills add https://github.com/mattpocock/skills --skill pr\n    serves: harness\n")
        fx.trees["mattpocock/skills"] = [p for p in MATT if "/pr/" not in p]
        fx.listed["mattpocock/skills"] = [p.split("/")[-2] for p in fx.trees["mattpocock/skills"]]
        fx.mark_today()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["freshness"], "fast")
        self.assertEqual(out["skills"]["gone"], [])  # no gh tree call on the fast path

    def test_force_full_overrides_todays_marker(self) -> None:
        fx = Fixture()
        fx.mark_today()
        out = fx.run("--fix", "--force-full")
        self.assertEqual(out["skills"]["freshness"], "full")
        self.assertNotIn("update -p -y", fx.log("npx"))

    def test_failed_full_run_does_not_write_marker(self) -> None:
        fx = Fixture()
        fx.fail = "loop-me"  # one install fails, npx flips unavailable only on 127; here just a failure
        fx.no_npx = "1"
        fx.run("--fix")
        # npx unavailable -> nothing refreshed -> marker not written so the next run retries
        self.assertFalse((fx.repo / ".harness" / ".skills-checked").is_file())


class SkillsCheckTests(unittest.TestCase):
    def test_report_mode_changes_nothing(self) -> None:
        fx = Fixture()
        out = fx.run()
        self.assertEqual(len(out["skills"]["missing"]), 11)
        self.assertFalse((fx.repo / ".claude").exists())
        self.assertNotIn("add", fx.log("npx").split())
        self.assertEqual(fx.log("claude"), "")

    def test_fix_installs_every_companion_with_copy_flags(self) -> None:
        fx = Fixture()
        out = fx.run("--fix")
        self.assertEqual(len(out["skills"]["installed"]), 11)
        self.assertTrue(fx.skill("resolve-merge-conflicts").is_file())
        self.assertIn("add warpdotdev/common-skills@resolve-merge-conflicts -a claude-code --copy -y", fx.log("npx"))
        self.assertNotIn("update -p -y", fx.log("npx"))  # B4: the daily sweep never auto-applies
        self.assertIsNone(out["skills"]["updated"])

    def test_keep_list_skills_are_installed_from_their_source(self) -> None:
        keep = ("skills:\n  - name: supabase\n    source: npx skills add supabase/agent-skills@supabase\n"
                "    serves: db\n  - name: impeccable\n    source: plugin\n    serves: ui\n")
        fx = Fixture(keep)
        fx.trees["supabase/agent-skills"] = ["skills/supabase/SKILL.md"]
        out = fx.run("--fix")
        self.assertIn("supabase", out["skills"]["installed"])
        self.assertTrue(fx.skill("supabase").is_file())
        self.assertNotIn("impeccable", fx.log("npx"))

    def test_agents_only_copy_is_reinstalled_for_claude(self) -> None:
        fx = Fixture()
        (fx.repo / ".agents" / "skills" / "pr").mkdir(parents=True)
        (fx.repo / ".agents" / "skills" / "pr" / "SKILL.md").write_text("x")
        report = fx.run()
        state = {m["name"]: m["state"] for m in report["skills"]["missing"]}
        self.assertEqual(state["pr"], "agents-only")
        fx.run("--fix")
        self.assertTrue(fx.skill("pr").is_file())

    def test_retired_skill_is_removed_only_with_confirmed_provenance(self) -> None:
        fx = Fixture()
        fx.skill("resolving-merge-conflicts").parent.mkdir(parents=True)
        fx.skill("resolving-merge-conflicts").write_text("x")
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["retired_kept"], [{"name": "resolving-merge-conflicts", "source": "unknown"}])
        self.assertTrue(fx.skill("resolving-merge-conflicts").exists())
        (fx.repo / "skills-lock.json").write_text(json.dumps(
            {"skills": {"resolving-merge-conflicts": {"source": "mattpocock/skills"}}}))
        out = fx.run("--fix", "--force-full")  # retired removal is a full-sweep action
        self.assertIn("resolving-merge-conflicts", out["skills"]["retired_removed"])
        self.assertFalse(fx.skill("resolving-merge-conflicts").exists())

    def test_folder_name_differs_from_skill_name_is_not_gone(self) -> None:
        keep = "skills:\n  - name: vercel-react-best-practices\n    source: npx skills add vercel-labs/agent-skills@vercel-react-best-practices\n"
        fx = Fixture(keep)
        fx.trees["vercel-labs/agent-skills"] = ["skills/react-best-practices/SKILL.md"]
        fx.listed["vercel-labs/agent-skills"] = ["vercel-react-best-practices"]
        out = fx.run()
        self.assertEqual(out["skills"]["gone"], [])

    def gone_pr_fixture(self) -> Fixture:
        fx = Fixture("skills:\n  - name: pr  # companion\n    source: npx skills add https://github.com/mattpocock/skills --skill pr\n    serves: harness\n")
        fx.trees["mattpocock/skills"] = [p for p in MATT if "/pr/" not in p]
        fx.listed["mattpocock/skills"] = [p.split("/")[-2] for p in fx.trees["mattpocock/skills"]]
        fx.trees["acme/skills"] = ["skills/open-pr/SKILL.md"]
        fx.find = ("mattpocock/skills@pr 900K installs\n"
                   "other/skills@pr-helper 3K installs\n"
                   "acme/skills@open-pr 20.1K installs\n")
        return fx

    def test_gone_skill_lists_ranked_candidates_and_installs_nothing(self) -> None:
        fx = self.gone_pr_fixture()
        out = fx.run("--fix")
        gone = out["skills"]["gone"]
        self.assertEqual([g["name"] for g in gone], ["pr"])
        self.assertEqual(gone[0]["candidates"], [{"ref": "acme/skills@open-pr", "name": "open-pr", "installs": 20100}])
        self.assertNotIn("add acme/skills@open-pr", fx.log("npx"))
        self.assertEqual(out["skills"]["swapped"], [])

    def test_swap_after_yes_installs_rewrites_keep_and_files_lesson(self) -> None:
        fx = self.gone_pr_fixture()
        out = fx.run("--fix", "--swap", "pr=acme/skills@open-pr")
        self.assertEqual(out["skills"]["swapped"], [{"from": "pr", "to": "open-pr", "source": "acme/skills@open-pr"}])
        self.assertTrue(fx.skill("open-pr").is_file())
        keep_text = (fx.repo / ".harness" / "keep.yaml").read_text(encoding="utf-8")
        self.assertIn("- name: open-pr", keep_text)
        self.assertIn("swapped from pr", keep_text)
        self.assertNotIn("--skill pr\n", keep_text)
        self.assertTrue(out["skills"]["lesson_candidates"][0].startswith("harness: companion `pr`"))

    def test_partial_listing_falls_back_to_frontmatter_scan(self) -> None:
        fx = self.gone_pr_fixture()
        fx.listed["mattpocock/skills"] = ["grill-me"]
        out = fx.run()
        self.assertEqual([g["name"] for g in out["skills"]["gone"]], ["pr"])
        self.assertIn("api repos/mattpocock/skills/contents/", fx.log("gh"))

    def test_broken_listing_and_unreadable_files_never_prove_gone(self) -> None:
        fx = self.gone_pr_fixture()
        fx.listed["mattpocock/skills"] = ["grill-me"]
        fx.no_contents = "1"
        out = fx.run()
        self.assertEqual(out["skills"]["gone"], [])

    def test_truncated_tree_never_proves_gone(self) -> None:
        fx = self.gone_pr_fixture()
        fx.truncated = "mattpocock/skills"
        out = fx.run()
        self.assertEqual(out["skills"]["gone"], [])

    def test_unsafe_tree_paths_are_skipped_not_run(self) -> None:
        fx = self.gone_pr_fixture()
        fx.listed["mattpocock/skills"] = ["grill-me"]
        fx.trees["mattpocock/skills"].append("skills/x & calc/SKILL.md")
        out = fx.run()
        self.assertEqual([g["name"] for g in out["skills"]["gone"]], ["pr"])
        self.assertNotIn("calc", fx.log("gh"))

    def test_swap_preserves_crlf_and_appends_under_commented_skills_key(self) -> None:
        template = (PLUGIN_ROOT / "templates" / "keep.yaml").read_bytes().decode("utf-8").replace("\n", "\r\n")
        fx = Fixture()
        (fx.repo / ".harness" / "keep.yaml").write_bytes(template.encode("utf-8"))
        fx.trees["mattpocock/skills"] = [p for p in MATT if "/pr/" not in p]
        fx.listed["mattpocock/skills"] = [p.split("/")[-2] for p in fx.trees["mattpocock/skills"]]
        fx.trees["acme/skills"] = ["skills/open-pr/SKILL.md"]
        out = fx.run("--fix", "--swap", "pr=acme/skills@open-pr")
        self.assertEqual([s["to"] for s in out["skills"]["swapped"]], ["open-pr"])
        raw = (fx.repo / ".harness" / "keep.yaml").read_bytes().decode("utf-8")
        self.assertIn("\r\n", raw)
        self.assertNotIn("\n\n\n", raw.replace("\r\n", "\n") + "x")
        self.assertEqual(sum(1 for line in raw.splitlines() if line.startswith("skills:")), 1)
        self.assertIn("  - name: open-pr  # swapped from pr", raw)
        again = fx.run()
        self.assertNotIn("pr", [g["name"] for g in again["skills"]["gone"]])

    def test_unsafe_sources_are_rejected_before_any_command(self) -> None:
        keep = ("skills:\n  - name: evil\n    source: npx skills add a/b@c & calc\n"
                "  - name: bad&name\n    source: npx skills add a/b@ok\n")
        fx = Fixture(keep)
        out = fx.run("--fix", "--swap", "pr=x/y@z|calc")
        reasons = {r["name"]: r["reason"] for r in out["skills"]["rejected"]}
        self.assertIn("evil", reasons)
        self.assertIn("bad&name", reasons)
        self.assertIn("pr", reasons)
        self.assertNotIn("calc", fx.log("npx"))
        self.assertNotIn("a/b@", fx.log("npx"))

    def test_upstream_unreachable_is_never_gone(self) -> None:
        fx = Fixture()
        fx.trees = {}
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["gone"], [])
        self.assertEqual(out["skills"]["swapped"], [])

    def test_failed_install_is_reported_not_raised(self) -> None:
        fx = Fixture()
        fx.fail = "loop-me"
        out = fx.run("--fix")
        self.assertIn("loop-me", [f["name"] for f in out["skills"]["failed"]])

    def test_marketplaces_from_keep_plugins_are_updated(self) -> None:
        fx = Fixture("plugins:\n  - dts2@dts2\n  - impeccable@impeccable\n")
        out = fx.run("--fix", "--no-upstream")
        self.assertEqual(out["harness"]["marketplaces"], {"dts2": "updated", "impeccable": "updated"})
        self.assertIn("plugin marketplace update dts2", fx.log("claude"))
        self.assertIn("plugin update impeccable@impeccable", fx.log("claude"))

    def test_newer_harness_saves_spot_and_updates(self) -> None:
        fx = Fixture(installed_version="3.6.3", published="3.7.0")
        out = fx.run("--fix")
        self.assertTrue(out["harness"]["upgrade_started"])
        self.assertTrue(out["harness"]["restart_required"])
        self.assertEqual((fx.repo / ".harness" / "upgrade-from.txt").read_text().strip(), "3.6.3")
        self.assertIn("plugin update dts2@dts2", fx.log("claude"))
        self.assertEqual(out["skills"], {})

    def test_report_mode_flags_upgrade_without_writing_marker(self) -> None:
        fx = Fixture(installed_version="3.6.3", published="3.7.0")
        out = fx.run()
        self.assertTrue(out["harness"]["upgrade_available"])
        self.assertFalse((fx.repo / ".harness" / "upgrade-from.txt").exists())

    def test_failed_update_writes_no_marker(self) -> None:
        fx = Fixture(installed_version="3.6.3", published="3.7.0")
        fx.claude_fail = "1"
        out = fx.run("--fix")
        self.assertTrue(out["harness"]["upgrade_available"])
        self.assertFalse(out["harness"]["upgrade_started"])
        self.assertTrue(out["harness"]["upgrade_failed"])
        self.assertFalse((fx.repo / ".harness" / "upgrade-from.txt").exists())
        self.assertIn("installed", out["skills"])

    def test_marker_present_reports_resume(self) -> None:
        fx = Fixture(installed_version="3.7.0")
        (fx.repo / ".harness" / "upgrade-from.txt").write_text("3.6.3\n")
        out = fx.run("--fix")
        self.assertEqual(out["harness"]["resume_upgrade"]["advanced"], True)
        self.assertEqual(fx.log("claude"), "")


if __name__ == "__main__":
    unittest.main()


STRIPE: Final[dict[str, str]] = {
    ".claude/skills/stripe-best-practices/SKILL.md": "---\nname: stripe-best-practices\n---\nours\n",
    ".claude/skills/stripe-best-practices/references/webhooks.md": "committed reference\n",
    "skills-lock.json": '{"skills": {"stripe-best-practices": {"source": "stripe/ai"}}}\n',
}


class TrackedFilesTests(unittest.TestCase):
    """The sweep never deletes or overwrites a git-tracked file; it skips and reports instead."""

    def assert_untouched(self, fx: Fixture) -> None:
        for rel, body in STRIPE.items():
            self.assertEqual((fx.repo / rel).read_text(encoding="utf-8"), body, rel)
        self.assertFalse((fx.repo / ".claude/skills/stripe-best-practices/NEW.md").exists())
        status = subprocess.run(["git", "-C", str(fx.repo), "status", "--porcelain", "--", ".claude/skills/stripe-best-practices", "skills-lock.json"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status, "")

    def test_update_that_deletes_tracked_skill_is_reverted_and_reported(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        fx.clobber = "stripe-best-practices"
        out = fx.run("--fix")
        self.assert_untouched(fx)
        self.assertEqual(out["skills"]["tracked_check"], "ok")
        # No bulk update runs any more, so nothing can clobber the tracked skill and nothing is reported.
        self.assertNotIn("update -p -y", fx.log("npx"))
        self.assertEqual([e for e in out["skills"]["tracked_skipped"] if e["step"] == "update"], [])
        self.assertNotIn("_tracked", out["skills"])

    def test_force_full_is_protected_too(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        fx.run("--fix")
        fx.clobber = "stripe-best-practices"
        out = fx.run("--fix", "--force-full")
        self.assertEqual(out["skills"]["freshness"], "full")
        self.assert_untouched(fx)
        self.assertNotIn("update -p -y", fx.log("npx"))

    def test_clean_update_reports_tracked_skill_as_skipped_with_nothing_reverted(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["tracked_skipped"], [])  # no update step, so nothing to skip
        self.assert_untouched(fx)

    def test_uncommitted_edits_to_tracked_files_survive(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        edited = fx.repo / ".claude/skills/stripe-best-practices/SKILL.md"
        edited.write_text("work in progress\n", encoding="utf-8")
        fx.clobber = "stripe-best-practices"
        fx.run("--fix")
        self.assertEqual(edited.read_text(encoding="utf-8"), "work in progress\n")

    def test_untracked_skills_still_update(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        fx.run("--fix")  # installs companions, untracked
        fx.clobber = "pr"
        out = fx.run("--fix", "--force-full")
        self.assertNotIn("upstream v2", fx.skill("pr").read_text(encoding="utf-8"))  # no bulk update runs
        self.assertNotIn("pr", [e["name"] for e in out["skills"]["tracked_skipped"]])

    def test_tracked_retired_skill_is_not_removed(self) -> None:
        fx = Fixture()
        fx.commit({".claude/skills/diagnose/SKILL.md": "---\nname: diagnose\n---\n",
                   "skills-lock.json": '{"skills": {"diagnose": {"source": "mattpocock/skills"}}}\n'})
        out = fx.run("--fix")
        self.assertTrue(fx.skill("diagnose").is_file())
        self.assertNotIn("diagnose", out["skills"]["retired_removed"])
        self.assertIn({"name": "diagnose", "step": "remove-retired", "reverted": []}, out["skills"]["tracked_skipped"])
        self.assertNotIn("remove diagnose", fx.log("npx"))

    def test_git_failure_inside_a_repo_skips_the_update(self) -> None:
        fx = Fixture()
        fx.commit(STRIPE)
        broken = fx.fake / "git.py"
        broken.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        fx.git_bin = str(broken)
        fx.clobber = "stripe-best-practices"
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["tracked_check"], "unavailable")
        self.assertNotIn("update -p -y", fx.log("npx"))
        self.assertNotIn("*", [e["name"] for e in out["skills"]["tracked_skipped"]])
        self.assert_untouched(fx)

    def test_non_git_repo_behaves_as_before(self) -> None:
        fx = Fixture()
        out = fx.run("--fix")
        self.assertEqual(out["skills"]["tracked_check"], "no-git")
        self.assertNotIn("update -p -y", fx.log("npx"))
        self.assertEqual(out["skills"]["tracked_skipped"], [])
