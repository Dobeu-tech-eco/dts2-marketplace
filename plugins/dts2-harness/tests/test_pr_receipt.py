"""Run hooks/pr-receipt.sh against a fake gh and a local bare origin."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "pr-receipt.sh"
BRANCH: Final[str] = "feature"
MARKER: Final[str] = "## Change receipt"
PR_COMMAND: Final[str] = "gh pr create --title t --body b"
FAKE_GH: Final[str] = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_GH_DIR/gh.log"
if [[ "$1 $2" == "pr view" ]]; then cat "$FAKE_GH_DIR/view.json"; exit 0; fi
if [[ "$1 $2" == "pr edit" ]]; then
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--body-file" ]]; then cp "$2" "$FAKE_GH_DIR/edited-body.md"; fi
    shift
  done
  exit 0
fi
if [[ "$1" == "api" ]]; then echo "${FAKE_GH_API_ERR:-gh: Not Found (HTTP 404)}" >&2; exit 1; fi
exit 0
"""


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Fixture:
    def __init__(self, body: str, head: str = BRANCH, cross: bool = False, raw_view: str | None = None) -> None:
        self.repo: Path = make_tmp_home()
        self.fake_dir: Path = make_tmp_home()
        self.bare: Path = make_tmp_home()
        git(self.bare, "init", "-q", "--bare")
        git(self.repo, "init", "-q", "-b", BRANCH)
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "remote", "add", "origin", str(self.bare))
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-q", "-m", "init")
        view = {"number": 7, "body": body, "headRefName": head, "isCrossRepository": cross}
        text: str = raw_view if raw_view is not None else json.dumps(view)
        (self.fake_dir / "view.json").write_text(text, encoding="utf-8")
        gh: Path = self.fake_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)

    def run(self, command: str = PR_COMMAND, tool: str = "Bash", gh_bin: str | None = None,
            response: str = "", api_err: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DTS2_GH_BIN": gh_bin or str(self.fake_dir / "gh"),
               "FAKE_GH_DIR": str(self.fake_dir), "TMPDIR": str(self.fake_dir)}
        if api_err is not None:
            env["FAKE_GH_API_ERR"] = api_err
        payload: str = json.dumps({"session_id": "s", "tool_name": tool, "tool_input": {"command": command},
                                   "tool_response": {"stdout": response}})
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.repo), input=payload, env=env,
                              capture_output=True, text=True, check=False)

    def log(self) -> str:
        path: Path = self.fake_dir / "gh.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def edited(self) -> str:
        return (self.fake_dir / "edited-body.md").read_text(encoding="utf-8")

    def write_local_template(self, text: str) -> None:
        (self.repo / ".github").mkdir(exist_ok=True)
        (self.repo / ".github" / "pull_request_template.md").write_text(text, encoding="utf-8")


class PrReceiptTests(unittest.TestCase):
    def test_body_with_receipt_is_left_alone(self) -> None:
        fx = Fixture(f"## Summary\nx\n\n{MARKER}\n")
        fx.write_local_template(f"{MARKER}\n")
        result = fx.run()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("pr edit", fx.log())

    def test_body_without_receipt_gets_one_edit(self) -> None:
        fx = Fixture("## Summary\nx\n")
        fx.write_local_template(f"{MARKER}\n")
        self.assertEqual(fx.run().returncode, 0)
        self.assertEqual(fx.log().count("pr edit"), 1)
        self.assertIn("--body-file", fx.log())
        body: str = fx.edited()
        self.assertIn(MARKER, body)
        self.assertIn("## Summary", body)
        self.assertIn("not recorded", body)

    def test_latest_run_receipt_is_used(self) -> None:
        fx = Fixture("body\n")
        fx.write_local_template(f"{MARKER}\n")
        for run, text in (("2026-10-20-a", "OLD"), ("2026-10-21-b", "NEWEST")):
            folder: Path = fx.repo / ".harness" / "runs" / run
            folder.mkdir(parents=True)
            (folder / "receipt.md").write_text(f"{MARKER}\n{text}\n", encoding="utf-8")
        fx.run()
        self.assertIn("NEWEST", fx.edited())
        self.assertNotIn("OLD", fx.edited())

    def test_missing_template_is_created_committed_and_pushed(self) -> None:
        fx = Fixture(f"{MARKER}\nalready\n")
        result = fx.run()
        self.assertEqual(result.returncode, 0)
        self.assertIn("repos/Dobeu-tech-eco/.github/contents/.github/pull_request_template.md", fx.log())
        template: Path = fx.repo / ".github" / "pull_request_template.md"
        self.assertIn(MARKER, template.read_text(encoding="utf-8"))
        self.assertEqual(git(fx.repo, "log", "-1", "--format=%s"), "chore: add change receipt to PR template")
        pushed: str = git(fx.bare, "rev-parse", f"refs/heads/{BRANCH}")
        self.assertEqual(pushed, git(fx.repo, "rev-parse", "HEAD"))

    def test_existing_template_without_section_is_extended(self) -> None:
        fx = Fixture(f"{MARKER}\n")
        fx.write_local_template("## Notes\nkeep me\n")
        fx.run()
        text: str = (fx.repo / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        self.assertIn("keep me", text)
        self.assertIn(MARKER, text)

    def test_org_template_cached_for_session(self) -> None:
        fx = Fixture(f"{MARKER}\n")
        fx.run()
        self.assertEqual(fx.log().count("api repos"), 1)
        git(fx.repo, "rm", "-q", "-f", ".github/pull_request_template.md")
        git(fx.repo, "commit", "-q", "-m", "drop")
        fx.run()
        self.assertEqual(fx.log().count("api repos"), 1)

    def test_other_commands_and_tools_ignored(self) -> None:
        fx = Fixture("body\n")
        self.assertEqual(fx.run(command="gh pr view 7").returncode, 0)
        self.assertEqual(fx.run(tool="Edit").returncode, 0)
        self.assertEqual(fx.log(), "")

    def test_commit_is_path_scoped(self) -> None:
        fx = Fixture(f"{MARKER}\n")
        (fx.repo / "other.txt").write_text("x\n", encoding="utf-8")
        git(fx.repo, "add", "other.txt")
        fx.run()
        self.assertEqual(git(fx.repo, "show", "--name-only", "--format=", "HEAD"), ".github/pull_request_template.md")
        self.assertEqual(git(fx.repo, "diff", "--cached", "--name-only"), "other.txt")

    def test_edit_selector_is_passed_to_pr_view(self) -> None:
        fx = Fixture("body\n")
        fx.write_local_template(f"{MARKER}\n")
        fx.run(command="gh pr edit 12 --title x")
        self.assertIn("pr view 12 --json", fx.log())
        self.assertIn("pr edit 7", fx.log())

    def test_create_uses_url_from_response(self) -> None:
        fx = Fixture("body\n")
        fx.write_local_template(f"{MARKER}\n")
        url: str = "https://github.com/o/r/pull/9"
        fx.run(response=f"{url}\n")
        self.assertIn(f"pr view {url} --json", fx.log())

    def test_quoted_command_is_ignored(self) -> None:
        fx = Fixture("body\n")
        self.assertEqual(fx.run(command='echo "gh pr create"').returncode, 0)
        self.assertEqual(fx.log(), "")

    def test_chained_command_is_recognised(self) -> None:
        fx = Fixture("body\n")
        fx.write_local_template(f"{MARKER}\n")
        fx.run(command="git push && gh pr create --fill")
        self.assertIn("pr edit", fx.log())

    def _assert_staged_not_pushed(self, fx: Fixture, result: subprocess.CompletedProcess[str]) -> None:
        self.assertIn("PR template staged; commit and push it to", result.stderr)
        self.assertEqual(git(fx.repo, "diff", "--cached", "--name-only"), ".github/pull_request_template.md")
        self.assertEqual(git(fx.repo, "log", "--format=%s"), "init")
        self.assertEqual(git(fx.bare, "branch", "--list"), "")

    def test_branch_mismatch_stages_without_push(self) -> None:
        fx = Fixture(f"{MARKER}\n", head="other")
        self._assert_staged_not_pushed(fx, fx.run())

    def test_cross_repository_pr_stages_without_push(self) -> None:
        fx = Fixture(f"{MARKER}\n", cross=True)
        self._assert_staged_not_pushed(fx, fx.run())

    def test_unparseable_view_never_edits(self) -> None:
        fx = Fixture("body\n", raw_view="not json")
        result = fx.run()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("pr edit", fx.log())

    def test_non_404_api_failure_is_not_cached(self) -> None:
        fx = Fixture(f"{MARKER}\n")
        fx.run(api_err="gh: HTTP 502")
        git(fx.repo, "rm", "-q", "-f", ".github/pull_request_template.md")
        git(fx.repo, "commit", "-q", "-m", "drop")
        fx.run(api_err="gh: HTTP 502")
        self.assertEqual(fx.log().count("api repos"), 2)

    def test_empty_body_has_no_leading_blank_lines(self) -> None:
        fx = Fixture("")
        fx.write_local_template(f"{MARKER}\n")
        fx.run()
        self.assertTrue(fx.edited().startswith(MARKER))

    def test_missing_gh_exits_zero_with_message(self) -> None:
        fx = Fixture("body\n")
        result = fx.run(gh_bin="/nonexistent/gh")
        self.assertEqual(result.returncode, 0)
        self.assertIn("gh", result.stderr)


if __name__ == "__main__":
    unittest.main()
