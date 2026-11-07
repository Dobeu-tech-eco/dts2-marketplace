"""Q-21 (findings dedupe and calibration) and AA-7 (reviewer partitioning, final-reviewer digest)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import findings  # noqa: E402
import review_split  # noqa: E402

CORRECTNESS: Final[str] = """## Review: diff (axis: correctness)
### CRITICAL
- [src/a.py:10] null deref when the cart is empty — crashes checkout
### HIGH
- [src/b.py:5] race on the counter — lost update
### MEDIUM
- [src/c.py:7] off by one in the page size
### LOW
none
### Lesson candidates
- never trust the cart
### Verdict: BLOCK
"""
STYLE: Final[str] = """## Review: diff (axis: style)
### HIGH
- [src/a.py:10] naming of the cart variable
- [src/d.py:2] dead branch
### MEDIUM
- no location given for this note
### Verdict: BLOCK
"""
SIMPLIFY: Final[str] = """## Review: diff (axis: simplify)
### HIGH
- [src/e.py:9] duplicate loop that hides a defect in the retry count
"""


class ParseTests(unittest.TestCase):
    def test_parse_reads_severity_blocks_only(self) -> None:
        found = findings.parse_findings(CORRECTNESS)
        self.assertEqual([(f.severity, f.file, f.line) for f in found],
                         [("CRITICAL", "src/a.py", 10), ("HIGH", "src/b.py", 5), ("MEDIUM", "src/c.py", 7)])
        self.assertEqual(found[0].axes, ("correctness",))

    def test_axis_comes_from_the_header_or_the_caller(self) -> None:
        self.assertEqual(findings.header_axis("## Review: x (axis: Style and scope)"), "style")
        self.assertEqual(findings.header_axis("no header"), "all")
        self.assertEqual(findings.parse_findings(STYLE, "simplify")[0].axes, ("simplify",))

    def test_unplaced_bullet_has_no_key(self) -> None:
        unplaced = [f for f in findings.parse_findings(STYLE) if f.file is None]
        self.assertEqual(len(unplaced), 1)
        self.assertIsNone(unplaced[0].key)


class CalibrationTests(unittest.TestCase):
    def test_style_high_is_capped_at_medium(self) -> None:
        capped = findings.calibrate(findings.parse_findings(STYLE)[0])
        self.assertEqual(capped.severity, "MEDIUM")
        self.assertIn("capped at MEDIUM for style", capped.note)

    def test_a_defect_keeps_its_severity(self) -> None:
        kept = findings.calibrate(findings.parse_findings(SIMPLIFY)[0])
        self.assertEqual(kept.severity, "HIGH")

    def test_unplaced_high_is_lowered(self) -> None:
        f = findings.Finding(None, None, "CRITICAL", "something is wrong", ("correctness",))
        self.assertEqual(findings.calibrate(f).severity, "MEDIUM")
        self.assertEqual(findings.calibrate(findings.Finding(None, None, "LOW", "x", ("correctness",))).severity, "LOW")

    def test_the_dimension_table_covers_every_reviewer_axis(self) -> None:
        text = (PLUGIN_ROOT / "agents" / "reviewer.md").read_text(encoding="utf-8")
        for axis in ("correctness", "security", "performance", "completeness", "critique", "walkthrough-findings", "simplify", "optimize"):
            self.assertIn(axis, findings.DIMENSIONS)
            self.assertIn(axis, text.lower())
        self.assertEqual(findings.DIMENSIONS["style"], "MEDIUM")


class DedupeTests(unittest.TestCase):
    def merge(self) -> list[findings.Finding]:
        return findings.merge_reports([(CORRECTNESS, None), (STYLE, None), (SIMPLIFY, None)])

    def test_same_file_line_keeps_the_higher_severity_and_both_axes(self) -> None:
        merged = self.merge()
        at_a10 = [f for f in merged if f.key == ("src/a.py", 10)]
        self.assertEqual(len(at_a10), 1)
        self.assertEqual(at_a10[0].severity, "CRITICAL")
        self.assertEqual(at_a10[0].axes, ("correctness", "style"))
        self.assertIn("null deref", at_a10[0].text)

    def test_sorted_worst_first_and_counted(self) -> None:
        merged = self.merge()
        self.assertEqual([f.severity for f in merged], sorted((f.severity for f in merged), key=findings.rank))
        self.assertEqual(len(merged), 6)
        self.assertEqual(findings.verdict(merged), "BLOCK")
        self.assertEqual(findings.verdict([]), "APPROVE")
        self.assertEqual(findings.verdict([f for f in merged if f.severity == "MEDIUM"]), "APPROVE_WITH_CHANGES")

    def test_identical_unplaced_text_is_merged(self) -> None:
        a = findings.Finding(None, None, "MEDIUM", "Same note", ("style",))
        b = findings.Finding(None, None, "MEDIUM", "same note", ("simplify",))
        self.assertEqual(len(findings.dedupe([a, b])), 1)

    def test_render_and_cli(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="dts2-find-"))
        paths = []
        for name, text in (("c.md", CORRECTNESS), ("s.md", STYLE)):
            (root / name).write_text(text, encoding="utf-8")
            paths.append(str(root / name))
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "findings.py"), "merge", *paths], capture_output=True, text=True, check=False)
        self.assertIn("### CRITICAL\n- [src/a.py:10]", done.stdout)
        self.assertIn("(axes: correctness, style)", done.stdout)
        self.assertTrue(done.stdout.rstrip().endswith("### Verdict: BLOCK"))
        as_json = subprocess.run([sys.executable, "-I", str(SCRIPTS / "findings.py"), "merge", "--json", *paths], capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(as_json.stdout)[0]["severity"], "CRITICAL")

    def test_digest_has_counts_full_blockers_and_the_diff_stat(self) -> None:
        text = findings.digest(self.merge(), " a.py | 4 ++--\n 1 file changed")
        self.assertTrue(text.startswith("Findings so far: 1 CRITICAL, 2 HIGH, 3 MEDIUM, 0 LOW"))
        self.assertIn("- CRITICAL [src/a.py:10]", text)
        self.assertIn("lower finding(s) in src/c.py", text)
        self.assertIn("git diff --stat:\n a.py | 4 ++--", text)


class PartitionTests(unittest.TestCase):
    def stats(self, spec: dict[str, int]) -> list[tuple[str, int]]:
        return list(spec.items())

    def test_numstat_parses_binary_and_renames(self) -> None:
        text = "10\t2\tsrc/a.py\n-\t-\timg/logo.png\n3\t1\tsrc/{old => new}.py\n2\t0\told.py => moved.py\nbad line\n"
        self.assertEqual(review_split.parse_numstat(text), [("src/a.py", 12), ("img/logo.png", 0), ("src/new.py", 4), ("moved.py", 2)])

    def test_a_small_diff_is_not_split(self) -> None:
        plan = review_split.plan_review(self.stats({"src/a/x.py": 100, "docs/y.md": 50}))
        self.assertFalse(plan["split"])
        self.assertEqual(plan["slices"], [])

    def test_a_large_single_group_is_not_split(self) -> None:
        self.assertFalse(review_split.plan_review(self.stats({"src/a/x.py": 5000, "src/a/y.py": 10}))["split"])

    def test_a_large_diff_is_packed_by_path_group(self) -> None:
        plan = review_split.plan_review(self.stats({"src/a/x.py": 600, "src/a/y.py": 100, "src/b/z.py": 500, "docs/g.md": 40, "README.md": 5}),
                                        threshold=800, max_reviewers=2)
        self.assertTrue(plan["split"])
        self.assertEqual(len(plan["slices"]), 2)
        self.assertEqual(sum(s["lines"] for s in plan["slices"]), 1245)
        every = sorted(f for s in plan["slices"] for f in s["files"])
        self.assertEqual(every, sorted(["src/a/x.py", "src/a/y.py", "src/b/z.py", "docs/g.md", "README.md"]))
        self.assertEqual(plan["slices"][0]["groups"], ["src/a"])

    def test_never_more_slices_than_the_cap_or_groups(self) -> None:
        plan = review_split.plan_review(self.stats({"a/x/1.py": 900, "b/y/2.py": 900}), threshold=800, max_reviewers=5)
        self.assertEqual(len(plan["slices"]), 2)

    def test_cli_reads_git(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-split-"))
        run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)  # noqa: E731
        run("init", "-q")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        (repo / "a").mkdir()
        (repo / "a" / "f.py").write_text("x\n", encoding="utf-8")
        run("add", ".")
        run("commit", "-qm", "base")
        base = run("rev-parse", "HEAD").stdout.strip()
        (repo / "a" / "f.py").write_text("x\n" * 50, encoding="utf-8")
        (repo / "b").mkdir()
        (repo / "b" / "g.py").write_text("y\n" * 60, encoding="utf-8")
        run("add", ".")
        run("commit", "-qm", "work")
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "review_split.py"), "plan", "--repo", str(repo), "--base", base,
                               "--threshold", "50", "--max-reviewers", "2"], capture_output=True, text=True, check=False)
        plan = json.loads(done.stdout)
        self.assertTrue(plan["split"], plan)
        self.assertEqual(plan["total_lines"], 109)
        digest = subprocess.run([sys.executable, "-I", str(SCRIPTS / "findings.py"), "digest", "--repo", str(repo), "--base", base, str(repo / "none.md")],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(digest.returncode, 0)  # a missing report file is an error, not an empty digest


if __name__ == "__main__":
    unittest.main()
