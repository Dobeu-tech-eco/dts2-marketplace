"""AA-9: fixed FLAGS block in the builder report, collected to .harness/runs/<stamp>/flags.md."""
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

REPORT: Final[str] = """status: DONE
commit: abc1234
tests: 12 passed

FLAGS:
- SECRET: STRIPE_KEY — unlocks billing — src/pay.ts
- OUTSIDE_FILE: src/shared/types.ts — needs a new field
- CONCERN: retry loop has no backoff
- bogus: not a fixed kind

Next paragraph is not a flag.
"""


class ParseTests(unittest.TestCase):
    def test_parses_fixed_kinds(self) -> None:
        flags = flags_collect.parse(REPORT)
        self.assertEqual([f["kind"] for f in flags], ["SECRET", "OUTSIDE_FILE", "CONCERN", "CONCERN"])
        self.assertEqual(flags[0]["text"], "STRIPE_KEY — unlocks billing — src/pay.ts")

    def test_unknown_kind_becomes_concern_keeping_its_text(self) -> None:
        self.assertEqual(flags_collect.parse(REPORT)[3]["text"], "bogus: not a fixed kind")

    def test_flags_none_is_empty(self) -> None:
        self.assertEqual(flags_collect.parse("done\nFLAGS: none\n"), [])

    def test_missing_block_is_reported(self) -> None:
        self.assertEqual(flags_collect.parse("status: DONE\n"), [{"kind": "MISSING", "text": "report has no FLAGS block"}])

    def test_kinds_are_fixed(self) -> None:
        self.assertEqual(flags_collect.KINDS, ("SECRET", "OUTSIDE_FILE", "CONCERN", "ASSUMPTION", "SKIPPED"))


class CollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="b14a-flags-"))

    def run_cli(self, builder: str, report: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "-I", str(SCRIPTS / "flags_collect.py"), "--repo", str(self.repo), "--stamp", "s1", "--builder", builder],
            input=report, capture_output=True, text=True,
        )

    def test_appends_per_builder_blocks(self) -> None:
        self.assertEqual(self.run_cli("1", REPORT).returncode, 0)
        self.assertEqual(self.run_cli("2", "x\nFLAGS: none\n").returncode, 0)
        text = (self.repo / ".harness" / "runs" / "s1" / "flags.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Flags\n"))
        self.assertIn("## Builder 1\n- SECRET: STRIPE_KEY", text)
        self.assertIn("## Builder 2\n- none", text)
        self.assertEqual(text.count("# Flags\n"), 1)

    def test_cli_prints_count(self) -> None:
        out = self.run_cli("1", REPORT).stdout
        self.assertIn("4 flags", out)


class ContractTests(unittest.TestCase):
    def test_builder_report_declares_the_flags_block(self) -> None:
        text = (PLUGIN_ROOT / "agents" / "builder.md").read_text(encoding="utf-8")
        self.assertIn("FLAGS:", text)
        for kind in flags_collect.KINDS:
            self.assertIn(kind, text)
        self.assertIn("FLAGS: none", text)

    def test_build_phase_collects_flags(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        self.assertIn("flags_collect.py", text)
        self.assertIn("flags.md", text)


if __name__ == "__main__":
    unittest.main()
