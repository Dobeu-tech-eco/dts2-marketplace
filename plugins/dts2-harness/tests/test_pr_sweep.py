"""pr_sweep.py: inventory with a stubbed gh, bucket classification, merge order, ledger and report. No network."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import pr_sweep  # noqa: E402

NOW: Final[str] = "2026-11-06T12:00:00Z"
FRESH: Final[str] = "2026-11-06T10:00:00Z"
OLD: Final[str] = "2026-10-20T10:00:00Z"
OK: Final[dict[str, Any]] = {"name": "test", "status": "completed", "conclusion": "success"}
LINT_OK: Final[dict[str, Any]] = {"name": "lint", "status": "completed", "conclusion": "success"}


def pr(number: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"number": number, "title": f"PR {number}", "head": f"feat/{number}", "head_sha": f"sha{number}",
                            "base": "main", "draft": False, "author": "dev", "created_at": FRESH, "updated_at": FRESH,
                            "mergeable": True, "mergeable_state": "clean", "files": [f"src/f{number}.py"],
                            "checks": [OK, LINT_OK]}
    base.update(over)
    return base


def inventory(prs: list[dict[str, Any]], required: dict[str, Any] | None = None, stale_days: int = 3) -> dict[str, Any]:
    return {"repo": "o/r", "generated_at": NOW, "stale_days": stale_days, "open_total": len(prs),
            "open_heads": [p["head"] for p in prs], "prs": prs, "required": required if required is not None else {"main": ["test", "lint"]}}


def buckets(inv: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {r["number"]: r for r in pr_sweep.classify(inv, pr_sweep.parse_time(NOW))["prs"]}


def run_cli(*argv: str) -> dict[str, Any]:
    out = io.StringIO()
    with unittest.mock.patch.object(sys, "argv", ["pr_sweep.py", *argv]), redirect_stdout(out):
        code: int = pr_sweep.main()
    data: dict[str, Any] = json.loads(out.getvalue())
    data["_code"] = code
    return data


class ClassifyTests(unittest.TestCase):
    def test_every_bucket(self) -> None:
        red = pr(2, checks=[{"name": "test", "status": "completed", "conclusion": "failure"}, LINT_OK])
        cancelled = pr(3, checks=[{"name": "test", "status": "completed", "conclusion": "cancelled"}, LINT_OK])
        pending = pr(4, checks=[{"name": "test", "status": "in_progress", "conclusion": None}, LINT_OK], mergeable_state="blocked")
        inv = inventory([
            pr(1),
            red,
            cancelled,
            pending,
            pr(5, mergeable=False, mergeable_state="dirty"),
            pr(6, mergeable_state="behind"),
            pr(7, draft=True),
            pr(8, head="feat/8"),
            pr(9, base="feat/8"),
        ])
        got = buckets(inv)
        self.assertEqual(got[1]["bucket"], pr_sweep.GREEN)
        self.assertEqual(got[2]["bucket"], pr_sweep.CI_RED)
        self.assertEqual(got[2]["failing_required"], ["test"])
        self.assertEqual(got[3]["bucket"], pr_sweep.CI_RED)
        self.assertEqual(got[4]["bucket"], pr_sweep.PENDING)
        self.assertEqual(got[5]["bucket"], pr_sweep.NEEDS_REBASE)
        self.assertEqual(got[6]["bucket"], pr_sweep.NEEDS_REBASE)
        self.assertEqual(got[7]["bucket"], pr_sweep.DRAFT)
        self.assertEqual(got[8]["bucket"], pr_sweep.GREEN)
        self.assertEqual(got[9]["bucket"], pr_sweep.STACKED)

    def test_non_required_failure_is_green_when_required_known(self) -> None:
        preview = {"name": "preview", "status": "completed", "conclusion": "cancelled"}
        inv = inventory([pr(1, checks=[OK, LINT_OK, preview], mergeable_state="unstable")])
        row = buckets(inv)[1]
        self.assertEqual(row["bucket"], pr_sweep.GREEN)
        self.assertEqual(row["failing"], ["preview"])
        self.assertEqual(row["failing_required"], [])

    def test_unknown_required_makes_every_failure_required(self) -> None:
        preview = {"name": "preview", "status": "completed", "conclusion": "failure"}
        inv = inventory([pr(1, checks=[OK, preview], mergeable_state="unstable")], required={"main": None})
        row = buckets(inv)[1]
        self.assertEqual(row["bucket"], pr_sweep.CI_RED)
        self.assertEqual(row["failing_required"], ["preview"])

    def test_missing_required_check_is_pending(self) -> None:
        inv = inventory([pr(1, checks=[OK])])
        self.assertEqual(buckets(inv)[1]["bucket"], pr_sweep.PENDING)

    def test_no_checks_reported_is_pending_not_green(self) -> None:
        row = buckets(inventory([pr(1, checks=[])], required={"main": None}))[1]
        self.assertEqual(row["bucket"], pr_sweep.PENDING)
        self.assertIn("no checks reported", row["evidence"])

    def test_commit_statuses_become_check_rows(self) -> None:
        rows = pr_sweep.status_rows({"statuses": [{"context": "ci/a", "state": "success"}, {"context": "ci/b", "state": "error"},
                                                  {"context": "ci/c", "state": "pending"}]})
        self.assertEqual([(r["name"], r["status"], r["conclusion"]) for r in rows],
                         [("ci/a", "completed", "success"), ("ci/b", "completed", "failure"), ("ci/c", "in_progress", None)])
        self.assertEqual(buckets(inventory([pr(1, checks=[OK, LINT_OK, rows[1]])], required={"main": None}))[1]["bucket"],
                         pr_sweep.CI_RED)
        self.assertEqual(buckets(inventory([pr(1, checks=[OK, LINT_OK, rows[2]])], required={"main": None}))[1]["bucket"],
                         pr_sweep.PENDING)

    def test_stale_flag_coexists_with_primary_bucket(self) -> None:
        inv = inventory([pr(1, updated_at=OLD), pr(2), pr(3, updated_at=OLD, mergeable=False, mergeable_state="dirty")])
        got = buckets(inv)
        self.assertTrue(got[1]["stale"])
        self.assertEqual(got[1]["bucket"], pr_sweep.GREEN)
        self.assertFalse(got[2]["stale"])
        self.assertTrue(got[3]["stale"])
        self.assertEqual(got[3]["bucket"], pr_sweep.NEEDS_REBASE)

    def test_base_of_another_open_pr_is_not_stale(self) -> None:
        inv = inventory([pr(1, head="feat/base", updated_at=OLD), pr(2, base="feat/base")])
        got = buckets(inv)
        self.assertFalse(got[1]["stale"])
        self.assertEqual(got[2]["bucket"], pr_sweep.STACKED)

    def test_stale_days_comes_from_inventory(self) -> None:
        recent = "2026-11-04T12:00:00Z"
        self.assertFalse(buckets(inventory([pr(1, updated_at=recent)], stale_days=3))[1]["stale"] or False)
        self.assertTrue(buckets(inventory([pr(1, updated_at=recent)], stale_days=1))[1]["stale"])

    def test_candidates(self) -> None:
        inv = inventory([
            pr(1, files=[]),
            pr(2, files=[".github/workflows/ci.yml"]),
            pr(3, files=["config/.env.production"]),
            pr(4, files=["scripts/release.sh"]),
            pr(5),
        ])
        got = buckets(inv)
        self.assertEqual(got[1]["candidates"]["superseded"], ["empty diff"])
        self.assertEqual(got[2]["candidates"]["needs_me"], [".github/workflows/ci.yml"])
        self.assertEqual(got[3]["candidates"]["needs_me"], ["config/.env.production"])
        self.assertEqual(got[4]["candidates"]["needs_me"], ["scripts/release.sh"])
        self.assertEqual(got[5]["candidates"], {"superseded": [], "needs_me": []})

    def test_overlaps_and_shared_files(self) -> None:
        inv = inventory([
            pr(1, files=["a.py", "CHANGELOG.md"]),
            pr(2, files=["b.py", "CHANGELOG.md", "changelog.d/batch-1.md"]),
            pr(3, files=["pkg/.claude-plugin/plugin.json", "uv.lock", "docs/INVENTORY.md"]),
            pr(4, files=["c.py"]),
        ])
        result = pr_sweep.classify(inv, pr_sweep.parse_time(NOW))
        self.assertEqual(result["overlaps"], [{"prs": [1, 2], "files": ["CHANGELOG.md"]}])
        got = {r["number"]: r for r in result["prs"]}
        self.assertEqual(got[1]["shared_files"], ["CHANGELOG.md"])
        self.assertEqual(got[2]["shared_files"], ["CHANGELOG.md", "changelog.d/batch-1.md"])
        self.assertEqual(len(got[3]["shared_files"]), 3)
        self.assertEqual(got[4]["shared_files"], [])
        self.assertEqual(result["counts"][pr_sweep.GREEN], 4)


class OrderTests(unittest.TestCase):
    def waves(self, inv: dict[str, Any]) -> list[list[int]]:
        return pr_sweep.merge_waves(inv, pr_sweep.parse_time(NOW))["waves"]

    def test_plain_prs_share_one_wave(self) -> None:
        self.assertEqual(self.waves(inventory([pr(3), pr(1), pr(2)])), [[1, 2, 3]])

    def test_stack_base_before_child(self) -> None:
        inv = inventory([pr(2, head="feat/two", base="feat/one"), pr(1, head="feat/one"), pr(3, head="feat/three", base="feat/two"), pr(4)])
        self.assertEqual(self.waves(inv), [[1], [2], [3, 4]])

    def test_shared_file_prs_are_serialized(self) -> None:
        inv = inventory([pr(1, files=["CHANGELOG.md"]), pr(2, files=["CHANGELOG.md"]), pr(3), pr(4, files=["plugin.json"])])
        self.assertEqual(self.waves(inv), [[1], [2], [4], [3]])

    def test_drafts_are_skipped(self) -> None:
        result = pr_sweep.merge_waves(inventory([pr(1), pr(2, draft=True)]), pr_sweep.parse_time(NOW))
        self.assertEqual(result["waves"], [[1]])
        self.assertEqual(result["skipped_drafts"], [2])

    def test_cycle_does_not_loop(self) -> None:
        inv = inventory([pr(1, head="a", base="b"), pr(2, head="b", base="a")])
        self.assertEqual(self.waves(inv), [[1, 2]])

    def test_order_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            path.write_text(json.dumps(inventory([pr(2), pr(1)])), encoding="utf-8")
            out = run_cli("order", "--inventory", str(path), "--now", NOW)
        self.assertEqual(out["waves"], [[1, 2]])
        self.assertEqual(out["_code"], 0)


def fake_gh(protection: Any) -> Any:
    listing = [
        {"number": 7, "title": "Add thing", "head": {"ref": "dts2/s1/a", "sha": "aaa"}, "base": {"ref": "main"}, "draft": False,
         "user": {"login": "dev"}, "created_at": FRESH, "updated_at": FRESH},
        {"number": 8, "title": "Other", "head": {"ref": "feat/b", "sha": "bbb"}, "base": {"ref": "main"}, "draft": True,
         "user": {"login": "someone"}, "created_at": FRESH, "updated_at": OLD},
    ]
    calls: list[str] = []

    def gh(path: str, paginate: bool = False) -> Any:
        calls.append(path)
        if path.startswith("repos/o/r/pulls?state=open"):
            return listing
        if path == "repos/o/r/pulls/7":
            return {"mergeable": True, "mergeable_state": "clean"}
        if path.startswith("repos/o/r/pulls/7/files"):
            return [{"filename": "src/a.py"}]
        if path.startswith("repos/o/r/commits/aaa/check-runs"):
            return {"total_count": 1, "check_runs": [{"name": "test", "status": "completed", "conclusion": "success"}]}
        if path.startswith("repos/o/r/commits/aaa/status"):
            return {"state": "success", "statuses": [{"context": "lint", "state": "success"}]}
        if path.endswith("/branches/main/protection"):
            if isinstance(protection, Exception):
                raise protection
            return protection
        raise AssertionError(f"unexpected gh call {path}")

    gh.calls = calls  # type: ignore[attr-defined]
    return gh


class InventoryTests(unittest.TestCase):
    def test_inventory_with_stubbed_gh(self) -> None:
        stub = fake_gh({"required_status_checks": {"contexts": ["test"], "checks": [{"context": "lint"}]}})
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(pr_sweep, "gh_api", stub):
            out = run_cli("inventory", "--repo", "o/r", "--head-prefix", "dts2/s1/", "--out", tmp)
            data = json.loads((Path(tmp) / "inventory.json").read_text(encoding="utf-8"))
            markdown = (Path(tmp) / "inventory.md").read_text(encoding="utf-8")
        self.assertEqual((out["_code"], out["open_total"], out["in_scope"]), (0, 2, 1))
        self.assertEqual([p["number"] for p in data["prs"]], [7])
        self.assertEqual(data["prs"][0]["files"], ["src/a.py"])
        self.assertEqual([(c["name"], c["conclusion"]) for c in data["prs"][0]["checks"]], [("test", "success"), ("lint", "success")])
        self.assertEqual(data["required"], {"main": ["lint", "test"]})
        self.assertEqual(data["open_heads"], ["dts2/s1/a", "feat/b"])
        self.assertIn("#7", markdown)
        self.assertNotIn("PR 8", markdown)

    def test_author_filter_and_unreadable_protection(self) -> None:
        stub = fake_gh(pr_sweep.GhError("403"))
        with unittest.mock.patch.object(pr_sweep, "gh_api", stub):
            inv = pr_sweep.build_inventory("o/r", 3, None, "dev")
            self.assertEqual([p["number"] for p in inv["prs"]], [7])
            self.assertEqual(inv["required"], {"main": None})
            self.assertEqual(pr_sweep.build_inventory("o/r", 3, None, "nobody")["prs"], [])

    def test_gh_failure_is_reported_as_json(self) -> None:
        def boom(path: str, paginate: bool = False) -> Any:
            raise pr_sweep.GhError("HTTP 401")

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(pr_sweep, "gh_api", boom):
            out = run_cli("inventory", "--repo", "o/r", "--out", tmp)
        self.assertEqual((out["ok"], out["_code"]), (False, 2))
        self.assertIn("401", out["error"])

    def test_bad_repo_name_is_refused(self) -> None:
        self.assertEqual(run_cli("inventory", "--repo", "nope", "--out", "x")["_code"], 2)

    def test_split_json_reads_concatenated_pages(self) -> None:
        self.assertEqual(pr_sweep.split_json('[{"a":1}]\n[{"a":2}]'), [[{"a": 1}], [{"a": 2}]])

    def test_gh_api_merges_pages(self) -> None:
        pages = '{"check_runs":[1]}\n{"check_runs":[2]}'
        with unittest.mock.patch.object(pr_sweep, "run_gh", return_value=pages):
            self.assertEqual(pr_sweep.gh_api("x", paginate=True), {"check_runs": [1, 2]})
        with unittest.mock.patch.object(pr_sweep, "run_gh", return_value="[1]\n[2]"):
            self.assertEqual(pr_sweep.gh_api("x", paginate=True), [1, 2])


class LedgerTests(unittest.TestCase):
    def test_record_and_report_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "run"
            directory.mkdir()
            (directory / "inventory.json").write_text(json.dumps(inventory([pr(1), pr(2), pr(3), pr(4)])), encoding="utf-8")
            run_cli("record", "--dir", str(directory), "--pr", "1", "--bucket", "GREEN", "--action", "merged", "--sha", "abc123",
                    "--ci", "retried", "--worker", "sonnet", "--verified-by", "lead")
            run_cli("record", "--dir", str(directory), "--pr", "2", "--bucket", "STALE", "--action", "closed",
                    "--reason", "superseded by #1")
            run_cli("record", "--dir", str(directory), "--pr", "3", "--bucket", "H", "--action", "waiting",
                    "--reason", "touches a workflow file: approve?")
            run_cli("record", "--dir", str(directory), "--pr", "1", "--bucket", "", "--action", "branch-kept",
                    "--reason", "deletion denied: feat/1")
            out = run_cli("report", "--dir", str(directory))
            text = (directory / "report.md").read_text(encoding="utf-8")
        self.assertEqual((out["before"], out["after"], out["merged"], out["closed"], out["waiting"]), (4, 2, 1, 1, 1))
        self.assertEqual(out["branches_not_deleted"], 1)
        self.assertTrue(text.startswith("# PR sweep report"))
        self.assertIn("Open PRs 4 -> 2. Merged 1, closed 1, waiting on you 1.", text)
        self.assertIn("| #1 | GREEN | merged | abc123 | retried | sonnet | lead |", text)
        self.assertIn("- #3: touches a workflow file: approve?", text)
        self.assertIn("- PR #1: deletion denied: feat/1", text)

    def test_repeat_sweep_counts_only_current_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_cli("record", "--dir", tmp, "--pr", "1", "--bucket", "GREEN", "--action", "merged")
            run_cli("record", "--dir", tmp, "--pr", "2", "--bucket", "GREEN", "--action", "merged")
            (directory / "inventory.json").write_text(json.dumps(inventory([pr(3), pr(4)])), encoding="utf-8")
            run_cli("record", "--dir", tmp, "--pr", "3", "--bucket", "GREEN", "--action", "merged")
            out = run_cli("report", "--dir", tmp)
        self.assertEqual((out["before"], out["after"], out["merged"]), (2, 1, 1))

    def test_report_without_inventory_or_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = run_cli("report", "--dir", tmp)
            self.assertTrue((Path(tmp) / "report.md").is_file())
        self.assertEqual((out["before"], out["after"], out["merged"]), (0, 0, 0))

    def test_record_appends_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("record", "--dir", tmp, "--pr", "5", "--bucket", "A", "--action", "merged")
            run_cli("record", "--dir", tmp, "--pr", "6", "--bucket", "A", "--action", "merged")
            lines = (Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["pr"] for line in lines], [5, 6])

    def test_reason_file_is_stored_literally(self) -> None:
        hostile = "error: $(touch pwned) `id` ; rm -rf x"
        with tempfile.TemporaryDirectory() as tmp:
            reason = Path(tmp) / "reason-7.txt"
            reason.write_text(hostile + "\n", encoding="utf-8")
            out = run_cli("record", "--dir", tmp, "--pr", "7", "--bucket", "C", "--action", "escalate",
                          "--reason", "ignored", "--reason-file", str(reason))
            self.assertFalse((Path(tmp) / "pwned").exists())
        self.assertEqual(out["row"]["reason"], hostile)

    def test_ci_triage_docs_route_untrusted_text_through_a_file(self) -> None:
        skill = Path(__file__).resolve().parents[1] / "skills" / "pr-sweep"
        triage = (skill / "phase-2-ci-triage.md").read_text(encoding="utf-8")
        execute = (skill / "phase-3-execute.md").read_text(encoding="utf-8")
        self.assertIn("--reason-file", triage)
        self.assertNotIn('--reason "<log line>"', triage)
        self.assertIn("git check-ref-format --branch", execute)


if __name__ == "__main__":
    unittest.main()
