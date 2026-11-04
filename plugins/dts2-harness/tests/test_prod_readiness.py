"""Tests for app-type detection, the production-readiness table and the verifier's readiness step."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, _write, run_script

SCRIPT: Final[str] = "app-type-detect.py"
REPORT_ROWS: Final[set[str]] = {"coverage", "a11y-axe", "lighthouse", "sast-semgrep", "license-check", "sbom", "stride"}


def detect(files: dict[str, str], *extra: str) -> dict[str, Any]:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-apptype-"))
    for rel, text in files.items():
        _write(repo / rel, text)
    return run_script(SCRIPT, str(repo), *extra)


def pkg(**fields: Any) -> dict[str, str]:
    return {"package.json": json.dumps(fields)}


class AppTypeDetectTests(unittest.TestCase):
    def test_node_types(self) -> None:
        cases: dict[str, dict[str, str]] = {
            "web-app": pkg(dependencies={"next": "1", "react": "1"}),
            "api": pkg(dependencies={"express": "4"}),
            "cli": pkg(bin={"tool": "cli.js"}),
            "library": pkg(main="index.js"),
            "static-site": pkg(devDependencies={"vitepress": "1"}),
        }
        for expected, files in cases.items():
            self.assertEqual(detect(files)["appType"], expected, expected)

    def test_web_framework_beats_bin(self) -> None:
        self.assertEqual(detect(pkg(dependencies={"react": "1"}, bin="x.js"))["appType"], "web-app")

    def test_python_rust_go(self) -> None:
        self.assertEqual(detect({"pyproject.toml": 'dependencies = ["fastapi"]'})["appType"], "api")
        self.assertEqual(detect({"pyproject.toml": "[project.scripts]\ntool = 'x:main'"})["appType"], "cli")
        self.assertEqual(detect({"pyproject.toml": "[project]\nname = 'x'"})["appType"], "library")
        self.assertEqual(detect({"Cargo.toml": "[package]\n", "src/main.rs": "fn main(){}"})["appType"], "cli")
        self.assertEqual(detect({"Cargo.toml": "[package]\n", "src/lib.rs": ""})["appType"], "library")
        self.assertEqual(detect({"go.mod": "module x", "main.go": 'import "net/http"'})["appType"], "api")

    def test_static_and_unknown(self) -> None:
        self.assertEqual(detect({"index.html": "<html>"})["appType"], "static-site")
        self.assertEqual(detect({"README.md": "x"})["appType"], "unknown")

    def test_broken_manifest_is_unknown(self) -> None:
        self.assertEqual(detect({"package.json": "{not json"})["appType"], "unknown")

    def test_cli_has_no_service_gates(self) -> None:
        out: dict[str, Any] = detect(pkg(bin="x.js"))
        for row in ("uptime-check", "runbook", "backups", "rollback", "alert-route", "error-tracking"):
            self.assertNotIn(row, out["gates"], row)
        self.assertIn("ci", out["gates"])
        self.assertIn("install-docs", out["gates"])
        self.assertNotIn("lighthouse", out["reportOnly"])

    def test_web_app_has_service_gates_and_report_rows(self) -> None:
        out: dict[str, Any] = detect(pkg(dependencies={"next": "1"}))
        for row in ("runbook", "uptime-check", "backups", "restore-test", "rollback", "post-deploy-watch", "promotion"):
            self.assertIn(row, out["gates"], row)
        self.assertIn("lighthouse", out["reportOnly"])
        self.assertNotIn("install-docs", out["gates"])

    def test_report_rows_never_gates(self) -> None:
        out: dict[str, Any] = detect({"README.md": "x"}, "--type", "web-app")
        self.assertTrue(REPORT_ROWS.isdisjoint(out["gates"]))
        for row in out["rows"]:
            self.assertEqual(row["kind"] == "report", row["row"] in REPORT_ROWS)

    def test_unknown_marks_everything_todo(self) -> None:
        out: dict[str, Any] = detect({"README.md": "x"})
        self.assertTrue(all(r["status"] == "todo" for r in out["rows"]))

    def test_type_override(self) -> None:
        self.assertEqual(detect({"README.md": "x"}, "--type", "cli")["appType"], "cli")

    def test_table_output_matches_rows(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-apptype-"))
        _write(repo / "index.html", "<html>")
        proc = subprocess.run(
            [sys.executable, "-I", str(PLUGIN_ROOT / "scripts" / SCRIPT), str(repo), "--table"],
            capture_output=True, text=True, check=True,
        )
        self.assertTrue(proc.stdout.startswith("| row | kind | evidence | status |"))
        self.assertIn("| lighthouse | report |", proc.stdout)
        self.assertIn("| backups | gate | ops/backups.md schedule | n/a |", proc.stdout)


class ReadinessTextTests(unittest.TestCase):
    def test_end_state_has_readiness_section(self) -> None:
        text: str = (PLUGIN_ROOT / "templates" / "end-state.md").read_text(encoding="utf-8")
        self.assertIn("## Production readiness", text)
        self.assertIn("appType: unset", text)
        self.assertIn("| row | kind | evidence | status |", text)

    def test_end_state_readiness_adds_no_checkboxes(self) -> None:
        text: str = (PLUGIN_ROOT / "templates" / "end-state.md").read_text(encoding="utf-8")
        section: str = text.split("## Production readiness", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("- [", section)

    def test_verifier_checks_only_applicable_rows(self) -> None:
        text: str = (PLUGIN_ROOT / "agents" / "verifier.md").read_text(encoding="utf-8")
        self.assertIn("Production readiness", text)
        self.assertIn("not `n/a`", text)
        self.assertIn("Always `INFO`, never a blocker", text)
        self.assertIn("Readiness <row>", text)


class SetupSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text: str = (PLUGIN_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

    def test_setup_detects_type_and_fills_table(self) -> None:
        self.assertIn("app-type-detect.py", self.text)
        self.assertIn("--table", self.text)

    def test_setup_scaffolds_ci_and_ops(self) -> None:
        for needle in ("prod-scaffold.py", ".github/workflows/ci.yml", "merge_group", "ops/credential-handoff.md", "RUNBOOK.md"):
            self.assertIn(needle, self.text)

    def test_setup_never_changes_protection_or_overwrites(self) -> None:
        self.assertIn("never change branch protection", self.text)
        self.assertIn("Never overwrite an existing `ci.yml`", self.text)


if __name__ == "__main__":
    unittest.main()
