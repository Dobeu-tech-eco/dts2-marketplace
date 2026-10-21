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
if [[ "$1" == "api" ]]; then exit 1; fi
exit 0
"""


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Fixture:
    def __init__(self, body: str) -> None:
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
        view = {"number": 7, "body": body, "headRefName": BRANCH}
        (self.fake_dir / "view.json").write_text(json.dumps(view), encoding="utf-8")
        gh: Path = self.fake_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)

    def run(self, command: str = PR_COMMAND, tool: str = "Bash", gh_bin: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DTS2_GH_BIN": gh_bin or str(self.fake_dir / "gh"),
               "FAKE_GH_DIR": str(self.fake_dir), "TMPDIR": str(self.fake_dir)}
        payload: str = json.dumps({"session_id": "s", "tool_name": tool, "tool_input": {"command": command}})
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

    def test_missing_gh_exits_zero_with_message(self) -> None:
        fx = Fixture("body\n")
        result = fx.run(gh_bin="/nonexistent/gh")
        self.assertEqual(result.returncode, 0)
        self.assertIn("gh", result.stderr)


if __name__ == "__main__":
    unittest.main()
