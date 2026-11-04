"""Pins for quoted command parsing and Go / Node detection fixes."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, _write, run_script

SCAFFOLD: Final[Path] = PLUGIN_ROOT / "scripts" / "prod-scaffold.py"


def scaffold(commands: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-quote-"))
    _write(repo / ".harness/config.yaml", "commands:\n" + commands)
    proc = subprocess.run([sys.executable, "-I", str(SCAFFOLD), str(repo), "--app-type", "cli"],
                          capture_output=True, text=True, check=True)
    out: dict[str, Any] = json.loads(proc.stdout)
    ci: str = (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    runs: dict[str, str] = {}
    for name, value in re.findall(r"- name: (\w[\w ]*)\n\s+run: (\".*\")$", ci, re.MULTILINE):
        runs[name] = json.loads(value)
    return runs, out["dropped"]


class QuotedCommandTests(unittest.TestCase):
    def test_inner_quotes_kept(self) -> None:
        runs, _ = scaffold('  test: pytest -k "not slow"\n')
        self.assertEqual(runs["test"], 'pytest -k "not slow"')

    def test_single_quoted(self) -> None:
        runs, _ = scaffold("  lint: 'ruff check .'\n")
        self.assertEqual(runs["lint"], "ruff check .")

    def test_double_quoted_escapes(self) -> None:
        runs, _ = scaffold('  typecheck: "echo \\"hi\\""\n')
        self.assertEqual(runs["typecheck"], 'echo "hi"')

    def test_plain_comment_stripped(self) -> None:
        runs, _ = scaffold("  build: npm run build # comment\n")
        self.assertEqual(runs["build"], "npm run build")

    def test_unterminated_dropped(self) -> None:
        runs, dropped = scaffold('  test: "unterminated\n')
        self.assertNotIn("test", runs)
        self.assertEqual([d["key"] for d in dropped], ["test"])
        self.assertIn("could not parse quoted value", dropped[0]["reason"])


class DetectTests(unittest.TestCase):
    def test_go_server_with_mux_is_api(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-go-"))
        _write(repo / "go.mod", "module x\nrequire github.com/gorilla/mux v1.8.0\n")
        _write(repo / "main.go", 'package main\nfunc main(){ srv := &http.Server{Addr: ":8080", Handler: r}; srv.ListenAndServe() }\n')
        self.assertEqual(run_script("app-type-detect.py", str(repo))["appType"], "api")

    def test_go_server_in_second_file(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-go-"))
        _write(repo / "go.mod", "module x\n")
        _write(repo / "main.go", "package main\nfunc main(){ run() }\n")
        _write(repo / "server.go", "package main\nfunc run(){ srv := &http.Server{}; _ = srv }\n")
        self.assertEqual(run_script("app-type-detect.py", str(repo))["appType"], "api")

    def test_react_component_library(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-lib-"))
        _write(repo / "package.json", json.dumps({"main": "dist/index.js", "peerDependencies": {"react": "^18"}, "devDependencies": {"react": "^18"}}))
        self.assertEqual(run_script("app-type-detect.py", str(repo))["appType"], "library")

    def test_next_dependency_stays_web_app(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-next-"))
        _write(repo / "package.json", json.dumps({"main": "x.js", "dependencies": {"next": "^14"}}))
        self.assertEqual(run_script("app-type-detect.py", str(repo))["appType"], "web-app")


class VerifierWordingTests(unittest.TestCase):
    def test_last_section_needs_real_row(self) -> None:
        text: str = (PLUGIN_ROOT / "agents" / "verifier.md").read_text(encoding="utf-8")
        self.assertIn("at least one real (non-placeholder) row", text)


if __name__ == "__main__":
    unittest.main()
