"""Batch 11 (round 2): report sections, OTEL passthrough, PR decisions, doctor rows, plugin options, signed journal."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import doctor  # noqa: E402
import plugin_options  # noqa: E402
import pr_payload  # noqa: E402
import receipts_sign  # noqa: E402
import son_launch  # noqa: E402
from lanes.common import LANE_SECTIONS, RUN_SECTIONS  # noqa: E402
from lanes.runend import run_report_view  # noqa: E402
from lanes.runstate import report_check  # noqa: E402

STAMP = "20260101-000000"


def make_run(root: Path) -> Path:
    runs = root / "runs"
    lane = runs / STAMP / "a"
    (lane / "requests").mkdir(parents=True)
    (lane / "status.json").write_text(json.dumps({"v": 1, "lane": "a", "status": "done", "pr": 7, "ci": "green"}), encoding="utf-8")
    (lane / "requests" / "r1.json").write_text(json.dumps({"id": "r1", "outcome": "granted"}), encoding="utf-8")
    (runs / STAMP / "budget.json").write_text(json.dumps({"spent_usd": 1.5, "unknown_calls": 1, "lanes": {}}), encoding="utf-8")
    (runs / STAMP / "model-ledger.jsonl").write_text(json.dumps({"lane": "a", "event": "merge-refused", "reason": "red"}) + "\n", encoding="utf-8")
    return runs


class ReportSections(unittest.TestCase):
    def test_run_wide_sections_and_son_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_report_view(make_run(Path(tmp)), STAMP)
        md = result["markdown"]
        for heading in ("Refusals", "Overrides", "Merge order and rebases", "Total spend", "Check-in delta", "Per-son results"):
            self.assertIn(f"### {heading}", md)
        self.assertIn("a: merge-refused red", md)
        self.assertIn("total: $1.50", md)
        self.assertIn("ci green", md)
        self.assertIn("r1=granted", md)

    def test_report_check_cross_checks_son_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = make_run(Path(tmp))
            report = Path(tmp) / "r.md"
            body = "## Lane a\n" + "".join(f"### {s}\nx\n" for s in LANE_SECTIONS) + "".join(f"## {s}\nx\n" for s in RUN_SECTIONS)
            report.write_text(body, encoding="utf-8")
            self.assertTrue(report_check(report, ["a"])["ok"])
            bad = report_check(report, ["a"], runs, STAMP)
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["unreferenced_prs"], [{"lane": "a", "pr": 7}])
            report.write_text(body + "PR #7\n", encoding="utf-8")
            self.assertTrue(report_check(report, ["a"], runs, STAMP)["ok"])
            self.assertEqual(report_check(report, ["b"], runs, STAMP)["unlisted"], ["a"])


class OtelEnv(unittest.TestCase):
    def test_otel_passes_and_secrets_do_not(self) -> None:
        env = son_launch.allowed_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "x", "GH_TOKEN": "t", "PATH": "/bin"})
        self.assertIn("OTEL_EXPORTER_OTLP_ENDPOINT", env)
        self.assertNotIn("GH_TOKEN", env)


class Decisions(unittest.TestCase):
    def test_section_from_ledger(self) -> None:
        records = [{"kind": "finding", "status": "declined", "summary": "rename x", "reason": "churn"},
                   {"kind": "check", "status": "declined", "summary": "ignored"}]
        text = pr_payload.decisions_section(records)
        self.assertIn("- declined: rename x (churn)", text)
        self.assertNotIn("ignored", text)
        self.assertIn("none", pr_payload.decisions_section([]))

    def test_template_and_evolve_text(self) -> None:
        self.assertIn(pr_payload.DECISIONS_HEADING, (PLUGIN_ROOT / "templates" / "pr-template.md").read_text(encoding="utf-8"))
        self.assertIn("hardening ladder", (PLUGIN_ROOT / "skills" / "evolve" / "SKILL.md").read_text(encoding="utf-8"))


class DoctorRows(unittest.TestCase):
    def test_rows_present_and_windows_warns(self) -> None:
        names = {c["name"] for c in doctor.run_checks()}
        self.assertLessEqual({"bwrap", "socat", "auth", "platform"}, names)
        with mock.patch.object(sys, "platform", "win32"):
            row = doctor.check_platform()
        self.assertEqual(row["status"], doctor.WARN)
        self.assertIn(doctor.WINDOWS_PARK_REASON, row["detail"])

    def test_auth_names_method_not_value(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-secret"}):
            self.assertNotIn("sk-secret", doctor.check_auth()["detail"])

    def test_runtime_table_matches_constants(self) -> None:
        text = (PLUGIN_ROOT / "docs" / "RUNTIMES.md").read_text(encoding="utf-8")
        for runtime, codes in doctor.TIMEOUT_MAPPING.items():
            row = re.search(rf"^\| {runtime.upper() if runtime == 'wsl' else runtime.title()} \| (\d+) \| (\d+) \| (\d+) \|", text, re.M)
            self.assertIsNotNone(row, runtime)
            self.assertEqual([int(g) for g in row.groups()], [codes["timeout"], codes["killed"], codes["terminated"]])


class PluginOptions(unittest.TestCase):
    def test_option_and_data_dir(self) -> None:
        env = {"CLAUDE_PLUGIN_OPTION_LEAD": "x", "CLAUDE_PLUGIN_OPTION_FLAG": "true", "CLAUDE_PLUGIN_DATA": "/d"}
        self.assertEqual(plugin_options.option("lead", env=env), "x")
        self.assertTrue(plugin_options.option_bool("flag", env=env))
        self.assertEqual(plugin_options.cache_path("c.json", env), Path("/d/c.json"))
        self.assertIsNone(plugin_options.cache_path("../x", env))
        self.assertIsNone(plugin_options.data_dir({}))


class SignedJournal(unittest.TestCase):
    def test_chain_detects_edit_and_signature_needs_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "j.jsonl"
            for n in range(3):
                receipts_sign.append(path, {"n": n}, b"k")
            self.assertTrue(receipts_sign.verify(path, b"k")["ok"])
            self.assertFalse(receipts_sign.verify(path, b"other")["ok"])
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace('"n": 1', '"n": 9') if '"n": 1' in lines[1] else lines[1].replace('"n":1', '"n":9')
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(receipts_sign.verify(path)["broken_at"], 1)

    def test_key_file_is_a_denied_son_variable(self) -> None:
        self.assertTrue(receipts_sign.KEY_FILE_VAR.startswith(son_launch.ENV_DENY_PREFIXES))
        self.assertNotIn(receipts_sign.KEY_FILE_VAR, son_launch.allowed_env({receipts_sign.KEY_FILE_VAR: "/k"}))


if __name__ == "__main__":
    unittest.main()
