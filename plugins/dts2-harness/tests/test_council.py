"""council.py: full-history dossier, five-seat tally with dissent briefs, and head-of-council decision checks."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home, run_script
from test_text_contracts import TextContractMixin

SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "autopilot" / "SKILL.md"
BRIEF: Final[str] = "\n## Dissent brief\nRound 2 showed the race in queue.ts; add a lock.\n"


def write(folder: Path, name: str, text: str) -> Path:
    path: Path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ballots(votes: dict[str, str], briefs: set[str]) -> list[Path]:
    folder: Path = make_tmp_home()
    return [write(folder, f"{seat}.md", f"VOTE: {vote}\n- HIGH a.ts:1 — x — y\n" + (BRIEF if seat in briefs else ""))
            for seat, vote in votes.items()]


def tally(votes: dict[str, str], briefs: set[str]) -> dict[str, Any]:
    return run_script("council.py", "tally", *[str(p) for p in ballots(votes, briefs)])


FIVE_SPLIT: Final[dict[str, str]] = {
    "claude-opus": "APPROVE", "codex": "APPROVE", "gemini": "APPROVE", "grok": "REJECT", "opus-security": "REJECT",
}


class DossierTest(unittest.TestCase):
    def test_every_entry_from_every_round_is_kept_in_order(self) -> None:
        votes: Path = make_tmp_home() / "votes" / "s3"
        write(votes, "01-plan-r1-claude-opus.md", "VOTE: REJECT\nplan note one")
        write(votes, "02-plan-r1-codex-gpt-6-astra.md", "VOTE: APPROVE\nnote two")
        write(votes, "03-fix-r1-lead.md", "fixed the schema")
        write(votes, "10-build-r3-gemini.md", "VOTE: REJECT\nlast word")
        write(votes, "stray.md", "unlabelled observation")
        out: Path = votes.parent / "dossier.md"
        result = run_script("council.py", "dossier", "--votes-dir", str(votes), "--out", str(out))
        text: str = out.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], 5)
        self.assertEqual(result["byKind"], {"plan": 2, "fix": 1, "build": 1})
        self.assertEqual(result["unrecognized"], ["stray.md"])
        for needle in ("plan note one", "note two", "fixed the schema", "last word", "unlabelled observation"):
            self.assertIn(needle, text)
        self.assertLess(text.find("plan note one"), text.find("fixed the schema"))
        self.assertLess(text.find("fixed the schema"), text.find("last word"))

    def test_empty_history_is_not_ok(self) -> None:
        folder: Path = make_tmp_home() / "votes" / "s9"
        folder.mkdir(parents=True)
        result = run_script("council.py", "dossier", "--votes-dir", str(folder), "--out", str(folder / "d.md"))
        self.assertFalse(result["ok"])


class TallyTest(unittest.TestCase):
    def test_split_names_dissenters_with_briefs(self) -> None:
        result = tally(FIVE_SPLIT, {"grok", "opus-security"})
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual((result["approve"], result["reject"], result["majority"]), (3, 2, "APPROVE"))
        self.assertEqual(sorted(result["dissenters"]), ["grok", "opus-security"])

    def test_dissenter_without_brief_fails(self) -> None:
        result = tally(FIVE_SPLIT, {"grok"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["missingBrief"], ["opus-security"])

    def test_approvers_dissent_from_reject_majority(self) -> None:
        votes = {seat: ("REJECT" if vote == "APPROVE" else "APPROVE") for seat, vote in FIVE_SPLIT.items()}
        result = tally(votes, {"grok", "opus-security"})
        self.assertEqual(result["majority"], "REJECT")
        self.assertEqual(sorted(result["dissenters"]), ["grok", "opus-security"])

    def test_unanimous_needs_no_brief(self) -> None:
        result = tally({seat: "APPROVE" for seat in FIVE_SPLIT}, set())
        self.assertTrue(result["ok"])
        self.assertTrue(result["unanimous"])

    def test_needs_five_valid_ballots(self) -> None:
        folder: Path = make_tmp_home()
        paths = [str(p) for p in ballots(dict(list(FIVE_SPLIT.items())[:4]), {"grok"})]
        paths.append(str(write(folder, "muse.md", "I think it is fine")))
        result = run_script("council.py", "tally", *paths)
        self.assertFalse(result["ok"])
        self.assertEqual(result["invalid"], ["muse"])


RESPONSES: Final[str] = (
    "## Dissent responses\n### grok\nAgreed on the race.\nUpdate: lock added in queue.ts\n"
    "### opus-security\nOverruled: token is server-only.\nUpdate: comment and test proving it stays server-side\n"
)


def decision(text: str, dissenters: list[str], entries: int = 12) -> dict[str, Any]:
    folder: Path = make_tmp_home()
    record: Path = write(folder, "council.md", text)
    tally_file: Path = write(folder, "tally.json", json.dumps({"dissenters": dissenters}))
    return run_script("council.py", "check-decision", str(record), "--tally", str(tally_file), "--entries", str(entries))


def record(head: str, extra: str = "", responses: str = RESPONSES, entries: int = 12) -> str:
    return (f"DECISION: {head}\n\n## Head of council brief\nRounds 1-3 split on one race; approved once the lock landed.\n\n"
            f"## History considered\nEntries reviewed: {entries}\n\n{responses}\n{extra}")


class DecisionTest(unittest.TestCase):
    DISSENTERS: Final[list[str]] = ["grok", "opus-security"]

    def test_approve_answering_every_dissent_passes(self) -> None:
        result = decision(record("APPROVE"), self.DISSENTERS)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["decision"], "APPROVE")

    def test_missing_dissent_response_fails(self) -> None:
        only_one = "## Dissent responses\n### grok\nUpdate: lock added\n"
        result = decision(record("APPROVE", responses=only_one), self.DISSENTERS)
        self.assertFalse(result["ok"])
        self.assertIn("no response to dissenter opus-security", result["problems"])

    def test_response_without_update_fails(self) -> None:
        vague = RESPONSES.replace("Update: comment and test proving it stays server-side\n", "Noted.\n")
        result = decision(record("APPROVE", responses=vague), self.DISSENTERS)
        self.assertIn("response to opus-security has no 'Update:' line", result["problems"])

    def test_must_review_the_whole_history(self) -> None:
        result = decision(record("APPROVE", entries=7), self.DISSENTERS, entries=12)
        self.assertFalse(result["ok"])

    def test_fix_and_strike_need_their_lists(self) -> None:
        self.assertFalse(decision(record("FIX"), self.DISSENTERS)["ok"])
        self.assertTrue(decision(record("FIX", "## Fixes\n- builder-2: add lock\n"), self.DISSENTERS)["ok"])
        self.assertFalse(decision(record("STRIKE"), self.DISSENTERS)["ok"])
        self.assertTrue(decision(record("STRIKE", "## Struck\n- plan item 4: CSV export\n"), self.DISSENTERS)["ok"])

    def test_missing_head_brief_fails(self) -> None:
        text = record("APPROVE").replace("## Head of council brief", "## Notes")
        self.assertIn("no '## Head of council brief'", decision(text, self.DISSENTERS)["problems"])

    def test_no_decision_line_never_passes(self) -> None:
        result = decision(record("APPROVE").replace("DECISION: APPROVE", "Looks good to me"), self.DISSENTERS)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["decision"])


class LedgerTest(unittest.TestCase):
    def run_ledger(self, out: Path, step: str) -> dict[str, Any]:
        folder: Path = make_tmp_home()
        seats: Path = folder / "council" / step
        for seat, vote in FIVE_SPLIT.items():
            write(seats, f"{seat}.md", f"VOTE: {vote}\n- HIGH a.ts:1 — {seat} finding\n" + (BRIEF if vote == "REJECT" else ""))
        tally_file: Path = write(folder, "tally.json", json.dumps(
            {"approve": 3, "reject": 2, "majority": "APPROVE", "dissenters": ["grok", "opus-security"]}))
        rec: Path = write(folder, "council-x.md", record("FIX", "## Fixes\n- builder-2: add lock\n"))
        return run_script("council.py", "ledger", "--ballots-dir", str(seats), "--tally", str(tally_file),
                          "--decision", str(rec), "--step", step, "--stamp", "20261104-1200", "--out", str(out))

    def test_ledger_records_vote_reasons_decision_and_brief(self) -> None:
        out: Path = make_tmp_home() / ".harness" / "council.md"
        result = self.run_ledger(out, "s3")
        text: str = out.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertEqual((result["decision"], result["seats"]), ("FIX", 5))
        for needle in ("# Council decisions", "## Council 20261104-1200 — step s3", "3 approve, 2 reject",
                       "dissenters: grok, opus-security", "- Decision: FIX", "#### grok: REJECT",
                       "grok finding", "Dissent brief:", "race in queue.ts", "### Head of council brief",
                       "approved once the lock landed", "### Dissent responses", "Update: lock added",
                       "### Fixes", "builder-2: add lock", "Entries reviewed: 12"):
            self.assertIn(needle, text)

    def test_ledger_appends_never_rewrites(self) -> None:
        out: Path = make_tmp_home() / ".harness" / "council.md"
        self.run_ledger(out, "s3")
        self.run_ledger(out, "s5")
        text: str = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("# Council decisions"), 1)
        self.assertLess(text.find("step s3"), text.find("step s5"))


def seats(usable: str, config: str | None = None, failed: str = "") -> dict[str, Any]:
    folder: Path = make_tmp_home()
    path: Path = write(folder, "config.yaml", config) if config is not None else folder / "none.yaml"
    return run_script("council.py", "seats", "--usable", usable, "--config", str(path), "--failed", failed)


class SeatsTest(unittest.TestCase):
    def pairs(self, result: dict[str, Any]) -> list[tuple[str, str]]:
        return [(s["provider"], s["model"]) for s in result["seats"]]

    def test_five_providers_get_one_seat_each(self) -> None:
        result = seats("claude,codex,gemini,grok,muse,cursor")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual([s["provider"] for s in result["seats"]], ["claude", "codex", "gemini", "grok", "muse"])
        self.assertEqual(result["doubled"], [])

    def test_too_few_providers_double_with_different_models(self) -> None:
        result = seats("claude,codex,gemini")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(set(self.pairs(result))), 5)
        self.assertEqual(result["doubled"], ["claude"])
        self.assertIn(("claude", "claude-fable-5-0"), self.pairs(result))
        self.assertEqual(result["providers"], ["claude", "codex", "gemini"])

    def test_head_model_never_seated(self) -> None:
        result = seats("claude,codex,gemini", "council:\n  models: [claude:claude-fable-5-1, claude:fable]\n")
        self.assertNotIn("fable", [m for _, m in self.pairs(result)])
        self.assertNotIn("claude-fable-5-1", [m for _, m in self.pairs(result)])

    def test_config_order_exclude_and_extra_models(self) -> None:
        config = "council:\n  order: [gemini, codex, claude]\n  exclude: [grok]\n  models: [cursor:cursor-frontier-1]\n"
        result = seats("claude,codex,gemini,grok,cursor", config)
        self.assertTrue(result["ok"], result["problems"])
        providers = [s["provider"] for s in result["seats"]]
        self.assertEqual(providers[:4], ["gemini", "codex", "claude", "cursor"])
        self.assertNotIn("grok", providers)

    def test_failed_seat_falls_back_and_bench_holds_spares(self) -> None:
        full = seats("claude,codex,gemini,grok,muse")
        self.assertTrue(full["bench"])
        result = seats("claude,codex,gemini,grok,muse", failed="grok:grok-4.7")
        self.assertTrue(result["ok"], result["problems"])
        self.assertNotIn("grok", [s["provider"] for s in result["seats"]])
        self.assertIn(("claude", "claude-fable-5-0"), self.pairs(result))

    def test_not_enough_distinct_models_is_not_ok(self) -> None:
        result = seats("claude,codex")
        self.assertFalse(result["ok"])
        self.assertEqual(len(set(self.pairs(result))), len(result["seats"]))

    def test_dispatch_route_per_seat(self) -> None:
        routes = {s["model"]: s["via"] for s in seats("claude,codex,gemini")["seats"]}
        self.assertEqual(routes["opus"], "agent-tool")
        self.assertEqual(routes["claude-fable-5-0"], "claude-cli")
        self.assertEqual(routes["gpt-6-astra"], "roster-command")

    def test_roster_command_takes_an_exact_model(self) -> None:
        result = run_script("roster.py", "command", "--agent", "codex", "--role", "second-opinion",
                            "--tier", "frontier", "--model", "gpt-6.1-sol")
        self.assertEqual(result["model"], "gpt-6.1-sol")
        self.assertIn("gpt-6.1-sol", result["argv"])


class CouncilSkillContract(TextContractMixin):
    def test_autopilot_escalates_to_council(self) -> None:
        self.assert_contains(SKILL, [
            "## 1b. The council", "council.py\" dossier", "council.py\" tally", "council.py\" check-decision",
            "five seats spread across as many different frontier providers", "council.py\" seats",
            "always with a different model", "Claude Opus 5.5 and Claude Fable 5.0", "`council:` block",
            "bench", "head of council", "Claude Fable 5.1", "never holds a council seat",
            "council.py\" ledger", ".harness/council.md", "## Council decisions", ".harness/lessons.md",
            "## Head of council brief", "## Dissent brief",
            "DECISION: FIX", "DECISION: STRIKE", "DECISION: APPROVE", "## Dissent responses", "Update:",
            "Entries reviewed:", "Keep every note", "never a summary", "beginning to end",
            "convene the **council** (section 1b) instead of parking", "council does not reconvene",
            "never overrides a hard stop",
        ])

    def test_check_in_and_pr_show_council(self) -> None:
        self.assert_contains(PLUGIN_ROOT / "skills" / "check-in" / "SKILL.md", ["council", "council-<stamp>-<step>.md"])
        self.assert_contains(PLUGIN_ROOT / "templates" / "pr-template.md", ["head of council", "each dissent"])


if __name__ == "__main__":
    unittest.main()
