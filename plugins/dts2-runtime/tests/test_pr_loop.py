"""Tests for scripts/pr_loop.py: the PR-end loop check and the Loop gate PR body check, on temp git repos."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "pr_loop.py"
RT: Final[str] = "plugins/dts2-runtime/"
GOOD_BODY: Final[str] = "## Loop gate\n\n### Setup gap pass\n\nNot applicable.\n\n### PR-end check\n\nNothing newly missing.\n"


def git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def write(repo: Path, rel: str, text: str) -> None:
    path: Path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                          capture_output=True, text=True, check=False)


def make_repo(tmp: str) -> Path:
    repo: Path = Path(tmp)
    git(repo, "init", "-q")
    write(repo, RT + ".claude-plugin/plugin.json", json.dumps({"version": "1.0.0"}))
    write(repo, RT + "CHANGELOG.md", "# Changelog\n\n## [1.0.0]\n")
    write(repo, RT + "scripts/old.py", "x = 1\n")
    write(repo, RT + "tests/test_old.py", "# covers old.py\n")
    write(repo, "README.md", "old.py\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "branch", "base")
    return repo


def commit(repo: Path, msg: str = "change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


class CheckTests(unittest.TestCase):
    def test_clean_change_reports_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/old.py", "x = 2\n")
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("## Loop gate", out)
            self.assertIn("### Setup gap pass", out)
            self.assertIn("Not applicable: this PR does not change the roadmap scope.", out)
            self.assertIn("### PR-end check", out)
            self.assertIn("plugins (", out)
            self.assertIn("Nothing newly missing.", out)

    def test_changed_script_without_test_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/fresh.py", "x = 1\n")
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("scripts/fresh.py changed with no test that names it", out)
            self.assertIn("not yet fixed or filed", out)

    def test_runtime_change_without_changelog_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/old.py", "x = 2\n")
            write(repo, RT + ".claude-plugin/plugin.json", json.dumps({"version": "1.1.0"}))
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("no CHANGELOG entry for version 1.1.0", out)

    def test_added_marker_line_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            marker: str = "TO" + "DO"
            write(repo, RT + "scripts/old.py", f"x = 1  # {marker} tidy\n")
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("marker line added in plugins/dts2-runtime/scripts/old.py", out)

    def test_new_script_not_in_docs_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/brand_new.py", "x = 1\n")
            write(repo, RT + "tests/test_brand_new.py", "# brand_new.py\n")
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("brand_new.py is not mentioned in any README or docs page", out)
            self.assertNotIn("no test that names it", out)
            write(repo, "README.md", "old.py brand_new.py\n")
            commit(repo, "docs")
            self.assertNotIn("not mentioned", run(repo, "check", "--base", "base").stdout)

    def test_new_skill_is_checked_against_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "skills/shiny/SKILL.md", "---\nname: shiny\n---\n")
            commit(repo)
            self.assertIn("skills/shiny/SKILL.md is not mentioned", run(repo, "check", "--base", "base").stdout)

    def test_roadmap_touched_without_pass_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, "docs/end-state.md", "# end\n")
            commit(repo)
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("Missing: run gap_research.py pass before requesting", out)

    def test_gap_pass_summary_lists_open_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, ".harness/research/gap-pass.json", json.dumps(
                {"key": "k1", "ran": "2026-11-27T00:00:00Z", "found": 2, "open": ["G-1"],
                 "counts": {"owner": 1, "section": 0, "dependency": 1, "assumption": 0}}))
            rows = [{"id": "G-1", "kind": "gap", "category": "owner", "text": "no owner for X", "status": "proposed"},
                    {"id": "G-2", "kind": "gap", "category": "section", "text": "closed", "status": "resolved"}]
            write(repo, ".harness/research/gaps.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
            out = run(repo, "check", "--base", "base").stdout
            self.assertIn("scope k1", out)
            self.assertIn("G-1 [owner] no owner for X", out)
            self.assertNotIn("G-2", out)

    def test_file_items_files_each_item_in_a_temp_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/fresh.py", "x = 1\n")
            commit(repo)
            result = run(repo, "check", "--base", "base", "--file-items")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r"filed as D\d+")
            ledger = (repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
            self.assertIn("[Loop gate]", ledger)
            self.assertIn("fresh.py", ledger)

    def test_bad_base_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            self.assertEqual(run(repo, "check", "--base", "nope").returncode, 2)


class VerifyBodyTests(unittest.TestCase):
    def verify(self, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(text, encoding="utf-8")
            return run(Path(tmp), "verify-body", str(path))

    def test_complete_body_passes(self) -> None:
        self.assertEqual(self.verify("intro\n\n" + GOOD_BODY).returncode, 0)

    def test_missing_heading_fails_and_names_it(self) -> None:
        result = self.verify("## Loop gate\n\n### Setup gap pass\n\nok\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("### PR-end check", result.stderr)

    def test_empty_section_fails(self) -> None:
        result = self.verify("## Loop gate\n\n### Setup gap pass\n\n### PR-end check\n\ntext\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("### Setup gap pass", result.stderr)
        self.assertNotIn("### PR-end check", result.stderr)

    def test_no_block_fails_all(self) -> None:
        result = self.verify("just a body\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("## Loop gate", result.stderr)

    def test_rendered_check_output_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/old.py", "x = 2\n")
            commit(repo)
            body = Path(tmp) / "body.txt"
            body.write_text(run(repo, "check", "--base", "base").stdout, encoding="utf-8")
            self.assertEqual(run(repo, "verify-body", str(body)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
