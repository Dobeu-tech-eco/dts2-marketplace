"""Follow-ups to the 14A work: renames in the audit, glob intersection and Foundation effort in the plan gate, FLAGS blank lines."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import flags_collect  # noqa: E402
import ownership_audit  # noqa: E402
from _load import load  # noqa: E402

gate = load("plan-gate")
AUDIT_CLI: Final[Path] = SCRIPTS / "builder-audit.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class StatusParseTests(unittest.TestCase):
    def test_rename_gives_both_paths(self) -> None:
        raw = "R  src/new.py\0src/old.py\0 M src/a.py\0?? docs/x.md\0"
        self.assertEqual(ownership_audit.parse_status_z(raw), ["src/new.py", "src/old.py", "src/a.py", "docs/x.md"])

    def test_empty_and_odd_fields(self) -> None:
        self.assertEqual(ownership_audit.parse_status_z(""), [])
        self.assertEqual(ownership_audit.parse_status_z("A  a b.py\0"), ["a b.py"])


class AuditRenameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-ren-"))
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "secret").mkdir()
        (self.repo / "secret" / "keep.txt").write_text("data\n" * 20, encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def audit(self) -> tuple[int, str]:
        done = subprocess.run([sys.executable, "-I", str(AUDIT_CLI), "--repo", str(self.repo), "--base", self.base, "--owned", "src/"],
                              capture_output=True, text=True, check=False)
        return done.returncode, done.stdout

    def test_committed_rename_out_of_the_owned_set_is_a_violation(self) -> None:
        git(self.repo, "mv", "secret/keep.txt", "src/keep.txt")
        git(self.repo, "commit", "-qm", "move")
        code, out = self.audit()
        self.assertEqual(code, 1)
        self.assertIn("secret/keep.txt", out)

    def test_staged_rename_is_a_violation(self) -> None:
        git(self.repo, "mv", "secret/keep.txt", "src/keep.txt")
        code, out = self.audit()
        self.assertEqual(code, 1)
        self.assertIn("secret/keep.txt", out)

    def test_untracked_file_in_a_new_folder_is_listed(self) -> None:
        (self.repo / "outside").mkdir()
        (self.repo / "outside" / "n.txt").write_text("n\n", encoding="utf-8")
        (self.repo / "src" / "b.py").write_text("y\n", encoding="utf-8")
        code, out = self.audit()
        self.assertEqual(code, 1)
        self.assertIn("outside/n.txt", out)

    def test_clean_work_inside_the_set_passes(self) -> None:
        (self.repo / "src" / "b.py").write_text("y\n", encoding="utf-8")
        self.assertEqual(self.audit()[0], 0)


PLAN: Final[str] = """## Plan: t
## Foundation
wave: 0
{foundation}
### Builder 1 (claude) — skills: none
complexity: normal
- T1 goal | owns: {own1} | depends: none | done when: ok
### Builder 2 (claude) — skills: none
complexity: mechanical
- T2 goal | owns: {own2} | depends: none | done when: ok
## Done
- x — check: tests `t`
Axes: correctness
"""
FOUNDATION_OK: Final[str] = "complexity: normal\n- T0 types | owns: core/types.ts | depends: none | done when: ok"


class PlanGateTests(unittest.TestCase):
    def verdict(self, own1: str, own2: str, foundation: str = FOUNDATION_OK) -> dict[str, object]:
        return gate.evaluate(PLAN.format(own1=own1, own2=own2, foundation=foundation))

    def test_disjoint_passes(self) -> None:
        self.assertEqual(self.verdict("src/a/*.py", "src/b/*.py")["verdict"], "PASS")

    def test_intersecting_globs_fail(self) -> None:
        for one, two in (("src/**", "src/api/*.py"), ("src/**/*.py", "src/api/*.py"), ("src/*", "src/*.py")):
            report = self.verdict(one, two)
            self.assertEqual(report["verdict"], "FAIL", (one, two))
            self.assertTrue(any("ownership" in f for f in report["failures"]))  # type: ignore[attr-defined]

    def test_globs_with_different_extensions_pass(self) -> None:
        self.assertEqual(self.verdict("src/*.py", "src/*.ts")["verdict"], "PASS")

    def test_foundation_needs_a_complexity(self) -> None:
        report = self.verdict("src/a/", "src/b/", "- T0 types | owns: core/types.ts | depends: none | done when: ok")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("Foundation" in f and "complexity" in f for f in report["failures"]))  # type: ignore[attr-defined]

    def test_foundation_gets_model_and_effort(self) -> None:
        dispatches = self.verdict("src/a/", "src/b/")["dispatches"]
        first = dispatches[0]  # type: ignore[index]
        self.assertEqual((first["builder"], first["model"], first["effort"]), ("Foundation", "sonnet", "medium"))

    def test_foundation_none_needed_passes_without_complexity(self) -> None:
        report = self.verdict("src/a/", "src/b/", "Foundation: none needed — nothing is shared")
        self.assertEqual(report["verdict"], "PASS")

    def test_text_requires_foundation_complexity(self) -> None:
        for path in ("agents/lead.md", "skills/run/phase-2-build.md"):
            text = (PLUGIN_ROOT / path).read_text(encoding="utf-8")
            self.assertIn("complexity", text[text.index("Foundation"):])
        self.assertIn("wave: 0\ncomplexity:", (PLUGIN_ROOT / "agents" / "lead.md").read_text(encoding="utf-8"))


class FlagsBlankLineTests(unittest.TestCase):
    def test_blank_lines_after_the_marker_are_skipped(self) -> None:
        report = "done\n\nFLAGS:\n\n\n- CONCERN: no backoff\n- SKIPPED: e2e\n"
        self.assertEqual(flags_collect.parse(report), [{"kind": "CONCERN", "text": "no backoff"}, {"kind": "SKIPPED", "text": "e2e"}])

    def test_a_blank_line_between_flags_still_ends_the_block(self) -> None:
        report = "FLAGS:\n- CONCERN: a\n\n- SKIPPED: b\n"
        self.assertEqual(flags_collect.parse(report), [{"kind": "CONCERN", "text": "a"}])


class CouncilCallTests(unittest.TestCase):
    def test_review_text_calls_swap_and_identical(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-3-review.md").read_text(encoding="utf-8")
        for needle in ("council.py\" swap --seats", "--failed <provider:model>", "council.py\" identical --votes-dir", "--prev", "--curr", "automatically"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
