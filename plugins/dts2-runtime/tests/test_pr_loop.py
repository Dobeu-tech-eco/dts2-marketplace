"""Tests for scripts/pr_loop.py: the PR-end loop check and the Loop gate PR body check, on temp git repos."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gap_research  # noqa: E402
import pr_loop  # noqa: E402

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "pr_loop.py"
RT: Final[str] = "plugins/dts2-runtime/"
END_STATE: Final[str] = (
    "# End state\n\n## Sections\n| # | section | serves component | owner | status |\n|---|---|---|---|---|\n"
    "| 1 | core | api | alice | todo |\n\n## Acceptance criteria\n\n### api\n\n- [ ] records persist\n"
)
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
            write(repo, ".harness/end-state.md", "# end\n")
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

    def test_roadmap_touched_matches_only_the_harness_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "templates/end-state.md", "# template\n")
            commit(repo)
            self.assertIn("Not applicable", run(repo, "check", "--base", "base").stdout)
            write(repo, ".harness/end-state.md", END_STATE)
            commit(repo, "end state")
            self.assertIn("Missing: run gap_research.py pass", run(repo, "check", "--base", "base").stdout)

    def test_gap_pass_for_an_old_scope_is_stale_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, ".harness/end-state.md", END_STATE)
            write(repo, ".harness/research/gap-pass.json", json.dumps(
                {"key": "oldkey000000", "ran": "2026-11-27T00:00:00Z", "found": 0, "open": [], "counts": {}}))
            out = run(repo, "check", "--base", "base").stdout
            self.assertRegex(out, r"Stale: gap pass ran for oldkey000000, scope is now \w{12}; re-run gap_research.py pass\.")
            self.assertIn("Missing: run gap_research.py pass", out)
            self.assertNotIn("No open gaps", out)
            body = Path(tmp) / "rendered.md"
            body.write_text(out, encoding="utf-8")
            self.assertEqual(run(repo, "verify-body", str(body)).returncode, 1)

    def test_gap_pass_for_the_current_scope_is_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, ".harness/end-state.md", END_STATE)
            key: str = str(gap_research.scope_key(END_STATE))
            write(repo, ".harness/research/gap-pass.json", json.dumps(
                {"key": key, "ran": "2026-11-27T00:00:00Z", "found": 0, "open": [], "counts": {}}))
            out = run(repo, "check", "--base", "base").stdout
            self.assertNotIn("Stale", out)
            self.assertIn("No open gaps", out)

    def test_file_items_skips_an_item_that_is_already_filed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, RT + "scripts/fresh.py", "x = 1\n")
            commit(repo)
            first = run(repo, "check", "--base", "base", "--file-items")
            self.assertRegex(first.stdout, r"filed as D\d+")
            ledger_path = repo / ".harness" / "action-items.md"
            filed = ledger_path.read_text(encoding="utf-8").count("[Loop gate]")
            second = run(repo, "check", "--base", "base", "--file-items")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already filed", second.stdout)
            self.assertNotIn("filed as D", second.stdout)
            self.assertEqual(ledger_path.read_text(encoding="utf-8").count("[Loop gate]"), filed)

    def test_file_items_dedupes_an_item_whose_text_is_rewritten_when_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            marker: str = "TO" + "DO"
            write(repo, RT + "scripts/old.py", f"x = 1  # {marker} a | b\n")
            commit(repo)
            first = run(repo, "check", "--base", "base", "--file-items")
            self.assertRegex(first.stdout, r"filed as D\d+")
            ledger_path = repo / ".harness" / "action-items.md"
            filed = ledger_path.read_text(encoding="utf-8").count("[Loop gate]")
            second = run(repo, "check", "--base", "base", "--file-items")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotIn("filed as D", second.stdout)
            self.assertEqual(ledger_path.read_text(encoding="utf-8").count("[Loop gate]"), filed)

    def test_filed_items_raises_when_action_items_fails(self) -> None:
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(pr_loop.subprocess, "run", return_value=failed):
            with self.assertRaises(RuntimeError):
                pr_loop.filed_items(Path("."))

    def test_paths_with_spaces_are_kept_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            write(repo, "my docs/a b.txt", "x\n")
            commit(repo)
            self.assertIn("my docs (1)", run(repo, "check", "--base", "base").stdout)

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

    def test_comment_only_heading_fails(self) -> None:
        body = "## Loop gate\n\n### Setup gap pass\n\n<!-- paste the output here -->\n\n### PR-end check\n\ntext\n"
        result = self.verify(body)
        self.assertEqual(result.returncode, 1)
        self.assertIn("### Setup gap pass", result.stderr)

    def test_missing_gap_pass_line_fails(self) -> None:
        result = self.verify(GOOD_BODY.replace("Not applicable.", pr_loop.MISSING_PASS))
        self.assertEqual(result.returncode, 1)
        self.assertIn("gap pass is missing", result.stderr)

    def test_item_not_yet_fixed_or_filed_fails(self) -> None:
        body = GOOD_BODY.replace("Nothing newly missing.", "Newly missing (1):\n- x changed with no test (not yet fixed or filed)")
        result = self.verify(body)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not yet fixed or filed", result.stderr)

    def test_failing_phrases_outside_the_loop_gate_block_are_ignored(self) -> None:
        prose = f'Earlier I saw "{pr_loop.MISSING_PASS}" and "not yet fixed or filed" in a log.\n\n'
        self.assertEqual(self.verify(prose + GOOD_BODY + "\n## Notes\n\nnot yet fixed or filed, said a log\n").returncode, 0)

    def test_failing_phrase_inside_the_block_still_fails_before_a_later_section(self) -> None:
        body = GOOD_BODY.replace("Nothing newly missing.", "- x (not yet fixed or filed)") + "\n## Notes\n\nok\n"
        self.assertEqual(self.verify(body).returncode, 1)

    def test_unclosed_comment_hides_the_rest(self) -> None:
        body = "## Loop gate\n\n### Setup gap pass\n\nNot applicable.\n\n### PR-end check\n\n<!-- Nothing newly missing.\n"
        result = self.verify(body)
        self.assertEqual(result.returncode, 1)
        self.assertIn("### PR-end check", result.stderr)

    def test_filed_item_passes(self) -> None:
        body = GOOD_BODY.replace("Nothing newly missing.", "Newly missing (1):\n- x changed with no test (filed as D3)")
        self.assertEqual(self.verify(body).returncode, 0)

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


class WorkflowTextTests(unittest.TestCase):
    def test_run_blocks_have_no_expression_and_dependabot_is_skipped(self) -> None:
        text = (PLUGIN_ROOT.parent.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        in_run = False
        run_indent = 0
        for line in text.splitlines():
            indent = len(line) - len(line.lstrip())
            if in_run and line.strip() and indent <= run_indent:
                in_run = False
            if in_run:
                self.assertNotIn("${{", line)
            stripped = line.strip().removeprefix("- ")
            if stripped.startswith("run:"):
                if "${{" in stripped:
                    self.fail(f"expression in run: {line}")
                in_run = stripped.rstrip().endswith("|")
                run_indent = indent
        self.assertIn('"$PR_AUTHOR" != "dependabot[bot]"', text)


if __name__ == "__main__":
    unittest.main()
