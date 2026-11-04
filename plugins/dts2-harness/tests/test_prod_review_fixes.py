"""Pins for the C1-C7 review fixes: gate-row conditions, dropped CI commands, Go client detection."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, _write, run_script

SCAFFOLD: Final[Path] = PLUGIN_ROOT / "scripts" / "prod-scaffold.py"


def step7() -> str:
    text: str = (PLUGIN_ROOT / "agents" / "verifier.md").read_text(encoding="utf-8")
    return text.split("7. **Production readiness**", 1)[1].split("## Output", 1)[0]


class VerifierGateTests(unittest.TestCase):
    def test_step7_names_blocking_condition(self) -> None:
        body: str = step7()
        self.assertIn("Mode: readiness", body)
        self.assertIn("last section", body)
        self.assertIn("pending (<status>)", body)
        self.assertIn("never FAIL", body)

    def test_legend_and_template_match(self) -> None:
        text: str = (PLUGIN_ROOT / "agents" / "verifier.md").read_text(encoding="utf-8")
        self.assertIn("only under `Mode: readiness`", text)
        end_state: str = (PLUGIN_ROOT / "templates" / "end-state.md").read_text(encoding="utf-8")
        self.assertIn("before the project reports done", end_state)
        self.assertNotIn("before a run reports done", end_state)


class DroppedCommandTests(unittest.TestCase):
    def test_dropped_reported(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-drop-"))
        _write(repo / ".harness/config.yaml", "commands:\n  build: echo ${{ secrets.X }}\n  lint: make lint\n")
        proc = subprocess.run([sys.executable, "-I", str(SCAFFOLD), str(repo), "--app-type", "cli"],
                              capture_output=True, text=True, check=True)
        out: dict[str, Any] = json.loads(proc.stdout)
        self.assertEqual([d["key"] for d in out["dropped"]], ["build"])
        self.assertTrue(out["dropped"][0]["reason"])

    def test_setup_reports_dropped(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`dropped`", text)


class GoClientTests(unittest.TestCase):
    def test_go_cli_with_http_client_is_cli(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-go-"))
        _write(repo / "go.mod", "module x\n")
        _write(repo / "main.go", 'package main\nimport "net/http"\nfunc main(){ http.Get("https://example.com") }\n')
        self.assertEqual(run_script("app-type-detect.py", str(repo))["appType"], "cli")


if __name__ == "__main__":
    unittest.main()
