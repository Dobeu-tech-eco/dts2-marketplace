"""ask_expert.py: clarity rubric, goal record, memo check, sweep ledger, archive/backup/delete guards."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ask_expert.py"
CLEAR_TEXT: Final[str] = "Whether the billing service is worth maintaining alongside my other projects"
FULL_ANSWERS: Final[dict[str, Any]] = {
    "goal": "money", "unsure": CLEAR_TEXT, "outcome": "A first paying customer within three months",
    "budget": "Five hours a week and no money to spend", "fold_targets": ["acme-api"], "audience": "just me",
    "restatement_confirmed": True}
FAKE_GH: Final[str] = '#!/bin/sh\necho "gh $*" >> "$FAKE_LOG"\nexit "${FAKE_GH_RC:-0}"\n'
FAKE_GIT: Final[str] = """#!/bin/sh
echo "git $*" >> "$FAKE_LOG"
case "$1 $2" in
  "clone --mirror") for last; do :; done; mkdir -p "$last" ;;
  "bundle create") echo bundle > "$3" ;;
  "bundle verify") exit "${FAKE_VERIFY_RC:-0}" ;;
esac
exit 0
"""
GOOD_REPORT: Final[str] = """VERDICT: TEMPLATE
CONFIDENCE: moderate

## Why
- The code is clean and small.
- Nobody uses it as a product.
- Starter kits like it sell.

## What your goal means
You want income, so the template route fits.

## Numbers that mattered
| Number | Value | Label | Source |
|---|---|---|---|
| Template price | $29 | sourced | https://example.com/listing |
| Monthly sales | 10 | estimated | comparable listings |
| Prep hours | 6 | assumed | my guess |

## Template path
Sell on a marketplace for $29-$49 after a day of cleanup.

## Salvage list
- auth module

## What would change the answer
A paying customer appears.

## Next step
Archive nothing yet; write the listing.

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 8 | OpenSSF Scorecard | sourced |
| code_health | 7 | tests and recency | sourced |
| product_viability | 6 | end to end run | estimated |
| market_size | 5 | bottom-up TAM | estimated |
| revenue_potential | 5 | pricing benchmarks | estimated |
| time_to_profit | 4 | break-even months | assumed |
| projections | 4 | 3-year cases | assumed |
| moat | 3 | competitor review | assumed |
| upkeep_cost | 8 | hours per month | estimated |

Overall: 55/100
"""
SCORES: Final[list[int]] = [8, 7, 6, 5, 5, 4, 4, 3, 8]


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False,
                          cwd=str(cwd or PLUGIN_ROOT), env={**os.environ, **(env or {})})


def write(path: Path, text: str, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def answers_file(folder: Path, **changes: Any) -> Path:
    merged: dict[str, Any] = {**FULL_ANSWERS, **changes}
    return write(folder / "answers.json", json.dumps({k: v for k, v in merged.items() if v is not None}))


class ClarityCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()

    def clarity(self, *extra: str, **changes: Any) -> tuple[int, dict[str, Any]]:
        done = run("clarity", "--answers", str(answers_file(self.dir, **changes)), *extra, cwd=self.dir)
        return done.returncode, json.loads(done.stdout)

    def test_full_answers_pass(self) -> None:
        code, out = self.clarity()
        self.assertEqual((code, out["score"], out["passed"], out["next_slot"]), (0, 100, True, None))
        self.assertEqual({s["status"] for s in out["slots"].values()}, {"full"})

    def test_weights(self) -> None:
        _, out = self.clarity()
        self.assertEqual({k: v["max"] for k, v in out["slots"].items()},
                         {"goal": 25, "unsure": 15, "outcome": 15, "budget": 10, "fold_targets": 10, "audience": 10,
                          "restatement_confirmed": 15})

    def test_goal_unsure_and_missing_score_zero(self) -> None:
        for goal in ("unsure", None):
            code, out = self.clarity(goal=goal)
            self.assertEqual((code, out["slots"]["goal"]["earned"], out["slots"]["goal"]["status"]), (3, 0, "missing"))
            self.assertEqual(out["next_slot"], "goal")

    def test_free_text_partial_is_half_rounded_down(self) -> None:
        _, out = self.clarity(unsure="fix it", budget="ok")
        self.assertEqual(out["slots"]["unsure"], {"earned": 7, "max": 15, "status": "partial"})
        self.assertEqual(out["slots"]["budget"], {"earned": 5, "max": 10, "status": "partial"})

    def test_free_text_missing(self) -> None:
        _, out = self.clarity(outcome="  ")
        self.assertEqual(out["slots"]["outcome"], {"earned": 0, "max": 15, "status": "missing"})

    def test_fold_targets_variants(self) -> None:
        for value, status in (("none", "full"), (["a", "b"], "full"), ([], "missing"), (None, "missing")):
            _, out = self.clarity(fold_targets=value)
            self.assertEqual(out["slots"]["fold_targets"]["status"], status, value)

    def test_audience_just_me_is_full_and_text_is_scored(self) -> None:
        self.assertEqual(self.clarity(audience="Just Me")[1]["slots"]["audience"]["status"], "full")
        self.assertEqual(self.clarity(audience="hobbyists who like small tools for their desks")[1]["slots"]["audience"]["status"], "full")
        self.assertEqual(self.clarity(audience="devs")[1]["slots"]["audience"]["status"], "partial")

    def test_restatement_unconfirmed(self) -> None:
        code, out = self.clarity(restatement_confirmed=False)
        self.assertEqual((code, out["score"], out["next_slot"]), (3, 85, "restatement_confirmed"))

    def test_next_slot_lowest_ratio_then_listed_order(self) -> None:
        _, out = self.clarity(unsure="fix it", budget=None, audience=None)
        self.assertEqual(out["next_slot"], "budget")  # ratio 0 ties budget/audience; listed order picks budget
        _, out = self.clarity(unsure="fix it")
        self.assertEqual(out["next_slot"], "unsure")

    def test_threshold_from_flag_config_default(self) -> None:
        _, out = self.clarity()
        self.assertEqual(out["threshold"], 95)
        write(self.dir / ".harness" / "config.yaml", "ask_expert:\n  clarity_threshold: 80\n")
        _, out = self.clarity(restatement_confirmed=False)
        self.assertEqual((out["threshold"], out["passed"]), (80, True))
        code, out = self.clarity("--threshold", "90", restatement_confirmed=False)
        self.assertEqual((out["threshold"], out["passed"], code), (90, False, 3))

    def test_budget_exhausted(self) -> None:
        self.assertFalse(self.clarity("--asked", "7")[1]["budget_exhausted"])
        self.assertTrue(self.clarity("--asked", "8")[1]["budget_exhausted"])


class GoalRecordCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()

    def test_refuses_until_clarity_passes(self) -> None:
        done = run("goal", "record", "--repo", "demo", "--answers", str(answers_file(self.dir, goal="unsure")),
                   "--root", str(self.dir))
        self.assertEqual(done.returncode, 3)
        self.assertFalse(json.loads(done.stdout)["ok"])
        self.assertFalse((self.dir / ".harness" / "ask-expert" / "demo" / "goal.json").exists())

    def test_records_answers_score_and_time(self) -> None:
        done = run("goal", "record", "--repo", "demo", "--answers", str(answers_file(self.dir)), "--root", str(self.dir))
        self.assertEqual(done.returncode, 0, done.stdout)
        record: dict[str, Any] = json.loads((self.dir / ".harness" / "ask-expert" / "demo" / "goal.json").read_text())
        self.assertEqual((record["answers"]["goal"], record["score"], record["repo"]), ("money", 100, "demo"))
        self.assertIn("recorded_at", record)

    def test_rejects_path_like_repo(self) -> None:
        done = run("goal", "record", "--repo", "../x", "--answers", str(answers_file(self.dir)), "--root", str(self.dir))
        self.assertEqual(done.returncode, 2)


class CheckReportCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()

    def check(self, text: str) -> tuple[int, dict[str, Any]]:
        done = run("check-report", str(write(self.dir / "r.md", text)))
        return done.returncode, json.loads(done.stdout)

    def errors(self, text: str) -> str:
        code, out = self.check(text)
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        return " | ".join(out["errors"])

    def test_happy_path(self) -> None:
        self.assertEqual(self.check(GOOD_REPORT), (0, {"ok": True, "errors": []}))
        self.assertEqual(sum(s * w for s, w in zip(SCORES, (10, 10, 15, 15, 15, 15, 10, 5, 5))), 545)  # rounds to 55

    def test_fold_with_target_ok(self) -> None:
        text = GOOD_REPORT.replace("VERDICT: TEMPLATE", "VERDICT: FOLD\nFOLD_TARGET: acme-api")
        self.assertEqual(self.check(text)[0], 0)

    def test_fold_without_target(self) -> None:
        self.assertIn("FOLD_TARGET", self.errors(GOOD_REPORT.replace("TEMPLATE", "FOLD", 1)))

    def test_bad_verdict(self) -> None:
        self.assertIn("VERDICT", self.errors(GOOD_REPORT.replace("VERDICT: TEMPLATE", "VERDICT: MAYBE")))

    def test_bad_or_missing_confidence(self) -> None:
        self.assertIn("CONFIDENCE", self.errors(GOOD_REPORT.replace("CONFIDENCE: moderate\n", "")))
        self.assertIn("CONFIDENCE", self.errors(GOOD_REPORT.replace("moderate", "certain")))

    def test_each_missing_section(self) -> None:
        for heading in ("## Why", "## What your goal means", "## Numbers that mattered", "## Template path", "## Salvage list",
                        "## What would change the answer", "## Next step"):
            self.assertIn(heading, self.errors(GOOD_REPORT.replace(heading, "## Other")), heading)

    def test_why_needs_exactly_three_bullets(self) -> None:
        self.assertIn("exactly 3", self.errors(GOOD_REPORT.replace("- Starter kits like it sell.\n", "")))
        self.assertIn("exactly 3", self.errors(GOOD_REPORT.replace("- Starter kits like it sell.\n", "- a\n- b\n")))

    def test_unsourced_url_row(self) -> None:
        self.assertIn("no http(s) URL", self.errors(GOOD_REPORT.replace("https://example.com/listing", "a listing page")))

    def test_row_without_label(self) -> None:
        self.assertIn("label", self.errors(GOOD_REPORT.replace("| assumed |", "| guessed |")))

    def test_numbers_table_needs_rows(self) -> None:
        text = GOOD_REPORT.split("| Template price")[0] + "\n## Template path" + GOOD_REPORT.split("## Template path")[1]
        self.assertIn("data row", self.errors(text))

    def test_template_path_needs_price_or_not_sellable(self) -> None:
        self.assertIn("price range", self.errors(GOOD_REPORT.replace("$29-$49", "something")))
        text = GOOD_REPORT.replace("Sell on a marketplace for $29-$49 after a day of cleanup.", "Not sellable: it is a one-off script.")
        self.assertEqual(self.check(text)[0], 0)


class ScorecardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()

    def card(self, text: str, *extra: str) -> tuple[int, dict[str, Any]]:
        done = run("scorecard", "--report", str(write(self.dir / "r.md", text)), *extra, cwd=self.dir)
        return done.returncode, json.loads(done.stdout)

    def test_weights_sum_to_100_for_every_goal(self) -> None:
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        import ask_expert
        for goal, weights in ask_expert.GOAL_WEIGHTS.items():
            self.assertEqual(sum(weights.values()), 100, goal)
            self.assertEqual(list(weights), list(ask_expert.FACTORS))
        self.assertEqual(ask_expert.GOAL_WEIGHTS["template"], ask_expert.GOAL_WEIGHTS["money"])

    def test_computes_overall_default_money(self) -> None:
        code, out = self.card(GOOD_REPORT)
        self.assertEqual((code, out["ok"], out["overall"], out["stated"], out["goal"]), (0, True, 55, 55, "money"))
        self.assertEqual(out["factors"]["security"], {"score": 8, "evidence": "sourced"})
        self.assertEqual(out["weights"]["market_size"], 15)

    def test_goal_flag_changes_weighting(self) -> None:
        code, out = self.card(GOOD_REPORT, "--goal", "passion")
        self.assertEqual((code, out["overall"]), (1, 65))  # weighted 645 -> 65; the memo states 55
    def test_goal_from_goal_json(self) -> None:
        run("goal", "record", "--repo", "demo", "--answers", str(answers_file(self.dir, goal="portfolio")), "--root", str(self.dir))
        _, out = self.card(GOOD_REPORT, "--repo", "demo", "--root", str(self.dir))
        self.assertEqual(out["goal"], "portfolio")

    def test_tolerance_of_one(self) -> None:
        self.assertTrue(self.card(GOOD_REPORT.replace("55/100", "56/100"))[1]["ok"])
        code, out = self.card(GOOD_REPORT.replace("55/100", "57/100"))
        self.assertEqual(code, 1)
        self.assertIn("does not match", out["errors"][0])

    def test_malformed(self) -> None:
        bad: dict[str, str] = {
            "header": GOOD_REPORT.replace("| Factor | Score |", "| Thing | Score |"),
            "missing row": GOOD_REPORT.replace("| moat | 3 | competitor review | assumed |\n", ""),
            "order": GOOD_REPORT.replace("| security |", "| zzz |"),
            "score": GOOD_REPORT.replace("| 8 | OpenSSF", "| 11 | OpenSSF"),
            "evidence": GOOD_REPORT.replace("| 8 | hours per month | estimated", "| 8 | hours per month | guess"),
            "overall": GOOD_REPORT.replace("Overall: 55/100", ""),
        }
        for name, text in bad.items():
            self.assertEqual(self.card(text)[0], 1, name)

    def test_unknown_goal(self) -> None:
        self.assertEqual(self.card(GOOD_REPORT, "--goal", "fame")[0], 2)

    def test_check_report_fails_on_mismatch_and_missing_scorecard(self) -> None:
        path = write(self.dir / "m.md", GOOD_REPORT.replace("55/100", "90/100"))
        done = run("check-report", str(path))
        self.assertEqual(done.returncode, 1)
        self.assertIn("does not match", done.stdout)
        no_card = write(self.dir / "n.md", GOOD_REPORT.split("## Scorecard")[0])
        self.assertIn("Scorecard", run("check-report", str(no_card)).stdout)


class SweepCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()

    def add(self, repo: str, *extra: str, score: str = "40") -> subprocess.CompletedProcess[str]:
        return run("sweep", "add", "--repo", repo, "--verdict", "ARCHIVE", "--confidence", "high", "--score", score, "--reason", "idle | stale",
                   "--salvage", "none", *extra, "--root", str(self.dir))

    def test_add_default_ledger_and_show(self) -> None:
        first = json.loads(self.add("old-one").stdout)
        ledger: Path = Path(first["ledger"])
        self.assertTrue(ledger.is_file())
        self.assertEqual(ledger.parent, self.dir / ".harness" / "ask-expert")
        self.assertTrue(ledger.name.startswith("sweep-") and ledger.suffix == ".jsonl")
        self.assertEqual(self.add("two", "--ledger", str(ledger), "--report", "r.md", score="75").returncode, 0)
        shown = json.loads(run("sweep", "show", "--ledger", str(ledger)).stdout)
        self.assertEqual([r["repo"] for r in shown["rows"]], ["two", "old-one"])  # best score first
        self.assertEqual(shown["rows"][0]["report"], "r.md")
        self.assertIn("| Repo | Verdict | Confidence | Score | Reason | Salvage |", shown["table"])
        self.assertIn("| old-one | ARCHIVE | high | 40 | idle \\| stale | none |", shown["table"])

    def test_score_required_and_bounded(self) -> None:
        self.assertEqual(self.add("x", score="101").returncode, 2)
        done = run("sweep", "add", "--ledger", str(self.dir / "l.jsonl"), "--repo", "x", "--verdict", "KEEP", "--confidence", "high",
                   "--reason", "r", "--salvage", "s")
        self.assertNotEqual(done.returncode, 0)

    def test_rejects_bad_verdict(self) -> None:
        done = run("sweep", "add", "--ledger", str(self.dir / "l.jsonl"), "--repo", "x", "--verdict", "NUKE", "--confidence", "high",
                   "--score", "5", "--reason", "r", "--salvage", "s")
        self.assertEqual(done.returncode, 2)

    def test_show_empty_ledger(self) -> None:
        shown = json.loads(run("sweep", "show", "--ledger", str(self.dir / "missing.jsonl")).stdout)
        self.assertEqual(shown["rows"], [])


class CleanupCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        self.log: Path = self.dir / "calls.log"
        self.env: dict[str, str] = {
            "DTS2_GH_BIN": str(write(self.dir / "bin" / "gh", FAKE_GH, True)),
            "DTS2_GIT_BIN": str(write(self.dir / "bin" / "git", FAKE_GIT, True)),
            "FAKE_LOG": str(self.log), "DTS2_HOME": str(self.dir / "home")}

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def make_bundle(self, name: str = "me__demo-20260101T000000Z.bundle") -> Path:
        return write(self.dir / name, "bundle")

    def delete(self, **changes: str) -> subprocess.CompletedProcess[str]:
        args: dict[str, str] = {"repo": "me/demo", "confirm": "demo", "bundle": str(self.make_bundle()), **changes}
        env: dict[str, str] = {**self.env, **{k: v for k, v in changes.items() if k.startswith("FAKE_")}}
        return run("delete", "--repo", args["repo"], "--confirm", args["confirm"], "--bundle", args["bundle"], env=env)

    def test_archive_argv(self) -> None:
        done = run("archive", "--repo", "me/demo", env=self.env)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.calls(), ["gh repo archive me/demo --yes"])

    def test_archive_rejects_bad_repo_and_reports_gh_failure(self) -> None:
        self.assertEqual(run("archive", "--repo", "demo", env=self.env).returncode, 2)
        self.assertEqual(self.calls(), [])
        failed = run("archive", "--repo", "me/demo", env={**self.env, "FAKE_GH_RC": "1"})
        self.assertEqual(failed.returncode, 1)

    def test_backup_creates_and_verifies_bundle(self) -> None:
        dest: Path = self.dir / "out"
        done = run("backup", "--repo", "me/demo", "--dest", str(dest), env=self.env)
        self.assertEqual(done.returncode, 0, done.stdout)
        out: dict[str, Any] = json.loads(done.stdout)
        bundle: Path = Path(out["bundle"])
        self.assertTrue(bundle.is_file() and bundle.parent == dest)
        self.assertRegex(bundle.name, r"^me__demo-\d{8}T\d{6}Z\.bundle$")
        self.assertTrue(out["verified"])
        calls: list[str] = self.calls()
        self.assertTrue(calls[0].startswith("git clone --mirror https://github.com/me/demo.git "))
        self.assertEqual(calls[1], f"git bundle create {bundle} --all")
        self.assertEqual(calls[2], f"git bundle verify {bundle}")

    def test_backup_default_dest_is_dts2_home(self) -> None:
        out = json.loads(run("backup", "--repo", "me/demo", env=self.env).stdout)
        self.assertEqual(Path(out["bundle"]).parent, self.dir / "home" / "repo-backups")

    def test_backup_fails_when_verify_fails(self) -> None:
        done = run("backup", "--repo", "me/demo", "--dest", str(self.dir / "o"), env={**self.env, "FAKE_VERIFY_RC": "1"})
        self.assertEqual(done.returncode, 1)
        self.assertFalse(json.loads(done.stdout)["verified"])

    def test_delete_refuses_wrong_confirm(self) -> None:
        for confirm in ("Demo", "me/demo", ""):
            done = self.delete(confirm=confirm)
            self.assertEqual(done.returncode, 2, confirm)
        self.assertFalse(any(c.startswith("gh ") for c in self.calls()))

    def test_delete_refuses_missing_bundle(self) -> None:
        done = self.delete(bundle=str(self.dir / "me__demo-nothing.bundle"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("not found", json.loads(done.stdout)["error"])
        self.assertEqual(self.calls(), [])

    def test_delete_refuses_mismatched_bundle_name(self) -> None:
        for name in ("other__demo-1.bundle", "me__demo.bundle", "me__demo2-1.bundle"):
            done = self.delete(bundle=str(self.make_bundle(name)))
            self.assertEqual(done.returncode, 2, name)
        self.assertEqual(self.calls(), [])

    def test_delete_refuses_when_verify_fails(self) -> None:
        done = self.delete(FAKE_VERIFY_RC="1")
        self.assertEqual(done.returncode, 2)
        self.assertFalse(any(c.startswith("gh ") for c in self.calls()))

    def test_delete_succeeds_when_all_hold(self) -> None:
        bundle: Path = self.make_bundle()
        done = self.delete(bundle=str(bundle))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.calls(), [f"git bundle verify {bundle}", "gh repo delete me/demo --yes"])

    def test_no_batch_form(self) -> None:
        self.assertNotEqual(run("delete", "--repo", "me/a", "--repo", "me/b", "--confirm", "a", env=self.env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
