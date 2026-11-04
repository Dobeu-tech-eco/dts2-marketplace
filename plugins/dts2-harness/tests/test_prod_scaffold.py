"""Tests for scripts/prod-scaffold.py and the production templates it copies."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, _write

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "prod-scaffold.py"
TEMPLATES: Final[Path] = PLUGIN_ROOT / "templates"
CONFIG: Final[str] = "project: x\ncommands:\n  test: npm test\n  typecheck: \"\"\n  lint: npm run lint\n  build: null\nnext: y\n"


def run(repo: Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, "-I", str(SCRIPT), str(repo), *args], capture_output=True, text=True, check=True)
    out: dict[str, Any] = json.loads(proc.stdout)
    return out


def make_repo(files: dict[str, str]) -> Path:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-scaffold-"))
    for rel, text in files.items():
        _write(repo / rel, text)
    return repo


class CiTests(unittest.TestCase):
    def test_ci_triggers_and_steps(self) -> None:
        repo: Path = make_repo({"package.json": "{}", "package-lock.json": "{}", ".harness/config.yaml": CONFIG})
        out: dict[str, Any] = run(repo, "--app-type", "web-app")
        self.assertIn(".github/workflows/ci.yml", out["written"])
        text: str = (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("merge_group:", text)
        self.assertIn('run: "npm test"', text)
        self.assertIn('run: "npm run lint"', text)
        self.assertNotIn("typecheck", text)
        self.assertNotIn("build", text.split("steps:", 1)[1])
        self.assertIn(".harness/checks.sh", text)
        self.assertIn('"npm ci"', text)
        self.assertIn("contents: read", text)
        self.assertNotIn("{{SETUP}}", text)
        self.assertNotIn("{{STEPS}}", text)

    def test_unsafe_command_is_dropped(self) -> None:
        cfg: str = "commands:\n  test: echo ${{ secrets.X }}\n  lint: make lint\n"
        repo: Path = make_repo({".harness/config.yaml": cfg})
        run(repo, "--app-type", "cli")
        text: str = (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("secrets.X", text)
        self.assertIn('"make lint"', text)

    def test_stack_setup_variants(self) -> None:
        cases: dict[str, tuple[dict[str, str], str]] = {
            "python": ({"pyproject.toml": ""}, "actions/setup-python@v5"),
            "go": ({"go.mod": "module x"}, "actions/setup-go@v5"),
            "rust": ({"Cargo.toml": ""}, "dtolnay/rust-toolchain@stable"),
            "pnpm": ({"package.json": "{}", "pnpm-lock.yaml": ""}, "pnpm install --frozen-lockfile"),
        }
        for name, (files, needle) in cases.items():
            repo: Path = make_repo(files)
            run(repo, "--app-type", "library")
            self.assertIn(needle, (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8"), name)

    def test_no_config_still_runs_checks_script(self) -> None:
        repo: Path = make_repo({})
        run(repo, "--app-type", "library")
        text: str = (repo / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("bash .harness/checks.sh", text)

    def test_never_overwrites(self) -> None:
        repo: Path = make_repo({".github/workflows/ci.yml": "mine", "RUNBOOK.md": "mine"})
        out: dict[str, Any] = run(repo, "--app-type", "api")
        self.assertIn(".github/workflows/ci.yml", out["skipped"])
        self.assertIn("RUNBOOK.md", out["skipped"])
        self.assertEqual((repo / "RUNBOOK.md").read_text(encoding="utf-8"), "mine")
        self.assertEqual(run(repo, "--app-type", "api")["written"], [])

    def test_no_ci_flag(self) -> None:
        repo: Path = make_repo({})
        out: dict[str, Any] = run(repo, "--app-type", "api", "--no-ci")
        self.assertNotIn(".github/workflows/ci.yml", out["written"])


class OpsFilesTests(unittest.TestCase):
    def test_files_by_app_type(self) -> None:
        expected: dict[str, set[str]] = {
            "web-app": {"RUNBOOK.md", "ops/monitoring.md", "ops/backups.md", "ops/credential-handoff.md", "ops/rollback.md", "ops/release.md"},
            "api": {"RUNBOOK.md", "ops/monitoring.md", "ops/backups.md", "ops/credential-handoff.md", "ops/rollback.md", "ops/release.md"},
            "static-site": {"ops/monitoring.md", "ops/rollback.md", "ops/release.md"},
            "cli": {"ops/release.md"},
            "library": {"ops/release.md"},
        }
        for app_type, files in expected.items():
            out: dict[str, Any] = run(make_repo({}), "--app-type", app_type, "--no-ci")
            self.assertEqual(set(out["written"]), files, app_type)

    def test_bad_repo_path(self) -> None:
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), "/nonexistent-x", "--app-type", "cli"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


class TemplateContentTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (TEMPLATES / name).read_text(encoding="utf-8")

    def test_rollback_first_option_and_watch(self) -> None:
        text: str = self.read("ops/rollback.md")
        self.assertLess(text.index("Provider instant rollback"), text.index("Feature flag off"))
        self.assertIn("15 to 30 minutes", text)
        self.assertIn("recommend a rollback", text)
        self.assertIn("action-items.py <repo> add Deploy", text)

    def test_migration_and_backup_rules(self) -> None:
        text: str = self.read("ops/backups.md")
        for needle in ("Expand", "Contract", "fresh backup", "Restore test"):
            self.assertIn(needle, text)

    def test_credential_handoff_is_scoped_and_short_lived(self) -> None:
        text: str = self.read("ops/credential-handoff.md")
        self.assertIn("never hold standing production credentials", text)
        self.assertIn("lifetime", text)
        self.assertIn("revokes", text)

    def test_release_template(self) -> None:
        text: str = self.read("ops/release.md")
        for needle in ("semver", "preview", "staging", "production", "Feature flags"):
            self.assertIn(needle, text)

    def test_monitoring_template(self) -> None:
        text: str = self.read("ops/monitoring.md")
        for needle in ("Error tracking", "Uptime check", "Alert route"):
            self.assertIn(needle, text)

    def test_runbook_template(self) -> None:
        self.assertIn("First five minutes", self.read("RUNBOOK.md"))


if __name__ == "__main__":
    unittest.main()
