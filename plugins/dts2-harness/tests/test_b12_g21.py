"""G-21: contract parsers return a dataclass or Invalid, all on one Markdown tokenizer (mdparse)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import contracts  # noqa: E402
import mdparse  # noqa: E402
from contracts import Ballot, Decision, Invalid, Report, VoteEntry  # noqa: E402

DOC: Final[str] = """\
# Title

intro text

## Alpha
- one
- two

```
## Not a heading
- not a bullet
```

### Alpha sub
text under sub

## Beta
| n | name |
|---|------|
| 1 | first |
| 2 | second |

- [x] done thing
- [ ] open thing
"""


class TokenizerTests(unittest.TestCase):
    def test_tokens(self) -> None:
        tokens = mdparse.tokenize(DOC)
        self.assertEqual([t.text for t in tokens if isinstance(t, mdparse.Heading)], ["Title", "Alpha", "Alpha sub", "Beta"])
        self.assertEqual([t.cells for t in tokens if isinstance(t, mdparse.Row)], [("n", "name"), ("1", "first"), ("2", "second")])
        self.assertEqual([(b.text, b.checked) for b in tokens if isinstance(b, mdparse.Bullet)],
                         [("one", None), ("two", None), ("done thing", True), ("open thing", False)])

    def test_fenced_code_hides_headings_and_bullets(self) -> None:
        self.assertNotIn("Not a heading", [h.text for h in mdparse.headings(DOC)])
        self.assertNotIn("not a bullet", [b.text for b in mdparse.bullets(DOC)])

    def test_section_runs_to_the_next_heading_of_the_same_level(self) -> None:
        body = mdparse.section(DOC, "## Alpha")
        self.assertIn("### Alpha sub", body)
        self.assertIn("## Not a heading", body)  # raw text of the section keeps its code block
        self.assertNotIn("Beta", body)
        self.assertEqual(mdparse.section(DOC, "## Missing"), "")

    def test_stop_at_ends_the_section_at_a_deeper_heading_too(self) -> None:
        self.assertNotIn("Alpha sub", mdparse.section(DOC, "## Alpha", stop_at=3))

    def test_prefix_match_and_has_section(self) -> None:
        self.assertEqual(mdparse.section("## Sections (1)\nx\n", "## Sections", prefix=True), "x")
        self.assertTrue(mdparse.has_section(DOC, "## Beta"))
        self.assertFalse(mdparse.has_section(DOC, "## Gamma"))

    def test_subsections_and_first_line(self) -> None:
        body = "### a\none\n### b\ntwo\nmore\n"
        self.assertEqual(mdparse.subsections(body, 3), {"a": "one", "b": "two\nmore"})
        self.assertEqual(mdparse.first_line("\n\n  hello \nworld"), "hello")


BALLOT: Final[str] = "VOTE: REJECT\nreasons here\n\n## Dissent brief\nwhy not\n"
DECISION: Final[str] = """\
DECISION: FIX

## Head of council brief
Do the fix.

## Dissent responses
### seat-a
- Update: changed the plan

### seat-b
nothing

## Fixes
- patch the thing

## History considered
Entries reviewed: 7
"""


class ContractTests(unittest.TestCase):
    def test_entry_name(self) -> None:
        self.assertEqual(contracts.parse_entry_name("01-plan-r2-claude.md"), VoteEntry(1, "plan", 2, "claude"))
        self.assertIsInstance(contracts.parse_entry_name("notes.md"), Invalid)

    def test_ballot(self) -> None:
        ballot = contracts.parse_ballot(BALLOT, "seat-a")
        self.assertEqual(ballot, Ballot("seat-a", "REJECT", True, "reasons here"))
        bad = contracts.parse_ballot("maybe\n", "seat-b")
        self.assertIsInstance(bad, Invalid)
        self.assertFalse(bad)
        self.assertEqual((bad.partial.vote, bad.partial.has_brief), (None, False))

    def test_decision(self) -> None:
        decision = contracts.parse_decision(DECISION)
        self.assertIsInstance(decision, Decision)
        self.assertEqual((decision.decision, decision.entries_reviewed, decision.fixes), ("FIX", 7, ("patch the thing",)))
        self.assertEqual(sorted(decision.responses), ["seat-a", "seat-b"])
        self.assertTrue(contracts.has_update(decision.responses["seat-a"]))
        self.assertFalse(contracts.has_update(decision.responses["seat-b"]))

    def test_decision_reasons(self) -> None:
        bad = contracts.parse_decision("hello\n")
        self.assertEqual(bad.reasons, ("first line is not 'DECISION: APPROVE|FIX|STRIKE'", "no '## Head of council brief'"))
        self.assertIsNone(bad.partial.decision)

    def test_sections_table(self) -> None:
        text = "# End\n\n## Sections\n\n| # | Section | Status |\n|---|---|---|\n| 1 | Build it (S1) | blocked |\n| 2 | Ship | done |\n\n## Next\n"
        rows = contracts.parse_sections(text)
        self.assertEqual([(r.number, r.name, r.action_id, r.status) for r in rows], [("1", "Build it", "S1", "blocked"), ("2", "Ship", None, "done")])
        self.assertIsInstance(contracts.parse_sections("# nothing"), Invalid)

    def test_acceptance(self) -> None:
        items = contracts.parse_acceptance("## Acceptance criteria\n- [x] a\n- [ ] b\n- plain\n## Other\n- [x] ignored\n")
        self.assertEqual([(i.text, i.done) for i in items], [("a", True), ("b", False)])

    def test_report(self) -> None:
        text = "## Lane a\n### Item\n### Plan (done)\n## Lane b\n### Item\n## Spend\n## Task ledger\n"
        ok = contracts.parse_report(text, ["a"], ("Item", "Plan"), ("Spend", "Task ledger"))
        self.assertIsInstance(ok, Report)
        bad = contracts.parse_report(text, ["a", "b", "c"], ("Item", "Plan"), ("Spend", "Task ledger", "Votes"))
        self.assertIsInstance(bad, Invalid)
        self.assertIn("lane b: missing 'Plan'", bad.reasons)
        self.assertIn("lane c: missing 'Item'", bad.reasons)
        self.assertIn("run: missing 'Votes'", bad.reasons)

    def test_report_sections_ignore_fenced_headings(self) -> None:
        lanes, run = contracts.report_sections("## Lane a\n```\n### Fake\n```\n### Real\n")
        self.assertEqual(lanes, {"a": {"real"}})
        self.assertEqual(run, set())


class OldReadersSitOnTheTokenizer(unittest.TestCase):
    def test_council_handoff_and_check_in_go_through_mdparse_or_contracts(self) -> None:
        for name, needle in (("council.py", "contracts."), ("handoff-write.py", "mdparse."), ("check-in.py", "contracts.")):
            self.assertIn(needle, (SCRIPTS / name).read_text(encoding="utf-8"), name)

    def test_the_old_section_regexes_are_gone(self) -> None:
        for name in ("council.py", "handoff-write.py", "check-in.py"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for old in ("SECTION_END", "ACTION_ID_SUFFIX", "CHECKBOX", "re.MULTILINE | re.DOTALL"):
                self.assertNotIn(old, text, f"{name} still has {old}")


if __name__ == "__main__":
    unittest.main()
