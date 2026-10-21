"""Tests for scripts/deploy-detect.py."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT, _write, run_script

SCRIPT: Final[str] = "deploy-detect.py"
PROVIDERS: Final[tuple[str, ...]] = ("vercel", "cloudflare", "netlify", "fly", "render", "firebase")


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_detect", PLUGIN_ROOT / "scripts" / SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detect(files: dict[str, str]) -> dict[str, Any]:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-deploy-"))
    for rel, text in files.items():
        _write(repo / rel, text)
    return run_script(SCRIPT, str(repo))


class DeployDetectTests(unittest.TestCase):
    def test_vercel_json(self) -> None:
        out: dict[str, Any] = detect({"vercel.json": "{}"})
        self.assertEqual(out["provider"], "vercel")
        self.assertEqual(out["checkCommand"], "vercel ls --prod")
        self.assertIn("vercel.json", out["evidence"])
        self.assertIsNone(out["productionUrl"])

    def test_vercel_project_dir(self) -> None:
        out: dict[str, Any] = detect({".vercel/project.json": "{}"})
        self.assertEqual(out["provider"], "vercel")

    def test_cloudflare_variants(self) -> None:
        for name in ("wrangler.toml", "wrangler.jsonc"):
            out: dict[str, Any] = detect({name: ""})
            self.assertEqual(out["provider"], "cloudflare")
            self.assertEqual(out["checkCommand"], "wrangler deployments list")

    def test_other_providers(self) -> None:
        cases: dict[str, tuple[str, str | None]] = {
            "netlify.toml": ("netlify", "netlify status"),
            "fly.toml": ("fly", "fly status"),
            "render.yaml": ("render", None),
            "firebase.json": ("firebase", "firebase hosting:channel:list"),
        }
        for name, (provider, command) in cases.items():
            out: dict[str, Any] = detect({name: ""})
            self.assertEqual(out["provider"], provider)
            self.assertEqual(out["checkCommand"], command)

    def test_workflow_with_deploy(self) -> None:
        out: dict[str, Any] = detect({".github/workflows/ship.yml": "name: x\njobs:\n  deploy:\n    runs-on: x\n"})
        self.assertEqual(out["provider"], "github-workflow")
        self.assertEqual(out["checkCommand"], "gh run list --workflow ship.yml --limit 1")
        self.assertIn(".github/workflows/ship.yml", out["evidence"])

    def test_yaml_extension_workflow(self) -> None:
        out: dict[str, Any] = detect({".github/workflows/release.yaml": "jobs:\n  deploy:\n    runs-on: x\n"})
        self.assertEqual(out["provider"], "github-workflow")
        self.assertIn(".github/workflows/release.yaml", out["evidence"])

    def test_wrangler_json(self) -> None:
        self.assertEqual(detect({"wrangler.json": "{}"})["provider"], "cloudflare")

    def test_workflow_without_deploy_is_none(self) -> None:
        out: dict[str, Any] = detect({".github/workflows/ci.yml": "name: ci\njobs:\n  test: {}\n"})
        self.assertEqual(out["provider"], "none")

    def test_empty_is_none(self) -> None:
        out: dict[str, Any] = detect({})
        self.assertEqual(out, {"provider": "none", "evidence": [], "productionUrl": None, "checkCommand": None})

    def test_provider_file_beats_workflow(self) -> None:
        out: dict[str, Any] = detect({"fly.toml": "", ".github/workflows/d.yml": "deploy"})
        self.assertEqual(out["provider"], "fly")

    def test_production_url_from_end_state(self) -> None:
        text: str = "# End state\n\ndeploy:\n  provider: vercel\n  productionUrl: https://app.example.com\n  checkCommand: null\n"
        out: dict[str, Any] = detect({"vercel.json": "{}", ".harness/end-state.md": text})
        self.assertEqual(out["productionUrl"], "https://app.example.com")

    def test_null_production_url_is_none(self) -> None:
        text: str = "deploy:\n  provider: none\n  productionUrl: null\n"
        out: dict[str, Any] = detect({".harness/end-state.md": text})
        self.assertIsNone(out["productionUrl"])

    def test_missing_repo_exits_zero(self) -> None:
        out: dict[str, Any] = run_script(SCRIPT, "/nonexistent/dts2-repo")
        self.assertEqual(out["provider"], "none")

    def test_constants(self) -> None:
        module: ModuleType = load_module()
        self.assertEqual(set(module.DEPLOY_COMMANDS), {"vercel", "cloudflare", "netlify", "fly", "github-workflow"})
        self.assertEqual(module.DEPLOY_COMMANDS["fly"], "fly deploy")
        self.assertEqual(module.DEPLOY_COMMANDS["vercel"], "vercel --prod")
        signals: set[str] = {"nextjs", "react", "static", "node-api", "python-api", "docker", "supabase", "workers"}
        self.assertEqual(set(module.PRODUCTION_PLANS), signals)
        self.assertEqual(module.PRODUCTION_PLANS["nextjs"], ["vercel", "cloudflare-pages"])
        self.assertEqual(module.PRODUCTION_PLANS["docker"], ["fly", "render"])
        self.assertEqual(module.PRODUCTION_PLANS["supabase"], ["vercel"])
        self.assertEqual(module.PRODUCTION_PLANS["workers"], ["cloudflare"])


if __name__ == "__main__":
    unittest.main()
