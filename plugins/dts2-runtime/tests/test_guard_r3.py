"""Merge-guard round 3: reserved words, line continuations, aliases, globs, xargs and gh api writes. Fake git and gh only."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

import sys

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import guard  # noqa: E402

PREFIX: Final[str] = "lane-a"


def bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class MergeR3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-r3-"))
        (self.root / "git.py").write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8")
        (self.root / "gh.py").write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8")

    def check(self, command: str) -> str | None:
        old = dict(os.environ)
        os.environ.update({"DTS2_GIT_BIN": str(self.root / "git.py"), "DTS2_GH_BIN": str(self.root / "gh.py")})
        try:
            return guard.merge_denial(bash(command), self.root)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def assert_denied(self, *commands: str) -> None:
        for command in commands:
            self.assertIsNotNone(self.check(command), command)

    def test_reserved_words(self) -> None:
        self.assert_denied("if true; then git push origin main; fi", "for x in 1; do git push origin main; done",
                           "! git push origin main", "then gh pr merge 3", "while true; do git push origin main; done",
                           "{ git push origin main; }", "case x in x) git push origin main;; esac")

    def test_function_definitions(self) -> None:
        self.assert_denied("f(){ git push origin main; }; f", "function f { git push origin main; }; f")

    def test_line_continuation(self) -> None:
        self.assert_denied("git push \\\n origin main", "git pu\\\nsh origin main", "gh pr \\\nmerge 3")

    def test_glob_and_brace(self) -> None:
        self.assert_denied("git push origin {main,}", "git push origin ma*", "git push origin mai?", "git push origin [m]ain",
                           "gh pr merge {3,4}", "gh api -X PUT repos/o/r/pulls/[3]/merge")

    def test_alias_and_config(self) -> None:
        self.assert_denied("git -c alias.p=push p origin main", "git -calias.p=push p origin main",
                           "git --config-env=alias.p=X p origin main; echo push", "git p origin main; echo push",
                           "git --config-env=alias.p=X p origin main", "git -c alias.p=X p origin main")

    def test_xargs(self) -> None:
        self.assert_denied("echo main | xargs git push origin", "echo 3 | xargs gh pr merge", "xargs -n1 git push origin")

    def test_gh_api_writes(self) -> None:
        self.assert_denied("gh api repos/o/r/merges -f base=main -f head=feature",
                           "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc -F force=true",
                           "gh api -X PUT repos/o/r/contents/a.txt -f message=m -f content=Yg==",
                           "gh api -X POST repos/o/r/git/refs -f ref=refs/heads/main -f sha=abc",
                           "gh api -X PUT repos/o/r/branches/main/protection --input x.json")

    def test_positive_controls(self) -> None:
        for command in ("if make test; then echo ok; fi", "git push origin feature", "gh pr view 12", "gh api repos/o/r/pulls",
                        "gh api repos/o/r/contents/a.txt", "gh api -X PUT repos/o/r/contents/a.txt -f branch=feature -f message=m"):
            self.assertIsNone(self.check(command), command)

    def test_continuation_inside_single_quotes_is_kept(self) -> None:
        self.assertEqual(guard.join_continuations("echo 'a\\\nb'"), "echo 'a\\\nb'")
        self.assertEqual(guard.join_continuations("a \\\n b"), "a  b")


class SonR3Tests(unittest.TestCase):
    def deny(self, command: str) -> str | None:
        return guard.son_denial(bash(command), PREFIX)

    def test_reserved_words_do_not_hide_son_checks(self) -> None:
        for command in ("then cat ~/.ssh/id_rsa", "if true; then python3 x.py >.claude/settings.json; fi",
                        "! cat .env", "then python3 /x/lanes.py merge-go a"):
            self.assertIsNotNone(self.deny(command), command)

    def test_redirect_only_segment_checked(self) -> None:
        self.assertIsNotNone(self.deny("> .claude/settings.json"))
        self.assertIsNone(self.deny("if make test; then echo ok; fi"))


if __name__ == "__main__":
    unittest.main()
