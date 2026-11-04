"""B8: the PR-receipt hook resolves its org, and council model ids and freshness come from profile config."""
from __future__ import annotations

import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, run_script
from test_pr_receipt import Fixture

PROFILE: Final[Path] = PLUGIN_ROOT / "profiles" / "agents" / "claude.json"
USABLE: Final[str] = "claude,codex,gemini"


def run_hook(fx: Fixture, owner: str | None = None, org_env: str | None = None) -> str:
    env_before = dict(os.environ)
    try:
        if owner is not None:
            os.environ["FAKE_GH_OWNER"] = owner
        if org_env is not None:
            os.environ["DTS2_PR_ORG"] = org_env
        done = fx.run()
    finally:
        os.environ.clear()
        os.environ.update(env_before)
    assert done.returncode == 0, done.stderr
    return fx.log()


class OrgResolutionTests(unittest.TestCase):
    def test_org_comes_from_gh_repo_view(self) -> None:
        log = run_hook(Fixture("body"), owner="acme-labs")
        self.assertIn("repo view --json owner", log)
        self.assertIn("api repos/acme-labs/.github/contents/.github/pull_request_template.md", log)

    def test_env_org_wins_over_gh(self) -> None:
        log = run_hook(Fixture("body"), owner="from-gh", org_env="from-env")
        self.assertIn("api repos/from-env/.github/", log)
        self.assertNotIn("repo view", log)

    def test_config_org_wins_over_gh(self) -> None:
        fx = Fixture("body")
        (fx.repo / ".harness").mkdir()
        (fx.repo / ".harness" / "config.yaml").write_text("org: from-config  # shared templates\n", encoding="utf-8")
        log = run_hook(fx, owner="from-gh")
        self.assertIn("api repos/from-config/.github/", log)

    def test_unknown_org_skips_the_org_lookup_and_still_adds_the_receipt(self) -> None:
        fx = Fixture("body")
        log = run_hook(fx, owner="")
        self.assertNotIn("api repos", log)
        self.assertIn("## Change receipt", fx.edited())

    def test_unsafe_org_value_is_ignored(self) -> None:
        log = run_hook(Fixture("body"), owner="a/b;rm")
        self.assertNotIn("api repos", log)

    def test_hook_text_names_no_fixed_org(self) -> None:
        text = (PLUGIN_ROOT / "hooks" / "pr-receipt.sh").read_text(encoding="utf-8")
        self.assertNotIn("Dobeu", text)


def seats() -> dict[str, Any]:
    return run_script("council.py", "seats", "--usable", USABLE, "--config", "/nonexistent.yaml")


class CouncilModelConfigTests(unittest.TestCase):
    def test_council_py_holds_no_model_ids(self) -> None:
        text = (PLUGIN_ROOT / "scripts" / "council.py").read_text(encoding="utf-8")
        self.assertNotIn("claude-fable", text)
        self.assertNotIn("claude-opus", text)

    def test_profile_declares_council_models(self) -> None:
        block = json.loads(PROFILE.read_text(encoding="utf-8"))["councilModels"]
        self.assertTrue(block["alternates"] and block["head"])
        date.fromisoformat(block["checked"])

    def test_seats_report_freshness_per_provider(self) -> None:
        result = seats()
        self.assertEqual([f["provider"] for f in result["freshness"]], ["claude"])
        self.assertIn("age_days", result["freshness"][0])

    def test_head_models_are_never_seated(self) -> None:
        head = json.loads(PROFILE.read_text(encoding="utf-8"))["councilModels"]["head"]
        models = [s["model"] for s in seats()["seats"]]
        self.assertFalse(set(head) & set(models))

    def test_freshness_flags_old_and_malformed_dates(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("council", PLUGIN_ROOT / "scripts" / "council.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        checked = date.fromisoformat(json.loads(PROFILE.read_text(encoding="utf-8"))["councilModels"]["checked"])
        max_age = mod.model_freshness("claude", checked)["max_age_days"]
        self.assertFalse(mod.model_freshness("claude", checked + timedelta(days=max_age))["stale"])
        self.assertTrue(mod.model_freshness("claude", checked + timedelta(days=max_age + 1))["stale"])
        self.assertTrue(mod.model_freshness("nosuchprovider", checked)["stale"])

    def test_run_ship_phase_has_no_hard_coded_model(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-4-ship.md").read_text(encoding="utf-8")
        self.assertNotIn("model: opus", text)
        self.assertIn("roster.py model --agent claude --tier frontier", text)


if __name__ == "__main__":
    unittest.main()
