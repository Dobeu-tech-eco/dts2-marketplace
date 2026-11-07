"""Speed defaults: agent models and cache frontmatter, fix-round tiers, son_model default, CI workflow shape."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import delegate  # noqa: E402
from lanes import supervisor  # noqa: E402
from lanes.common import SON_MODEL, son_model  # noqa: E402

WORKFLOW: Final[Path] = PLUGIN_ROOT.parent.parent / ".github" / "workflows" / "test.yml"
CACHED: Final[tuple[str, ...]] = ("builder", "verifier", "reviewer", "fixer", "scout", "auditor")
OMIT_CLAUDE_MD: Final[tuple[str, ...]] = ("scout", "auditor", "verifier")


def front(name: str) -> str:
    text: str = (PLUGIN_ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
    return text.split("---", 2)[1]


class AgentFrontmatterTests(unittest.TestCase):
    def test_verifier_and_fixer_run_on_sonnet(self) -> None:
        for name in ("verifier", "fixer"):
            self.assertIn("\nmodel: sonnet\n", front(name), name)

    def test_cache_ttl_on_the_listed_agents(self) -> None:
        for name in CACHED:
            self.assertIn("\nexperimental:\n  cacheTtl: 1h\n", front(name), name)

    def test_omit_claude_md_on_the_listed_agents(self) -> None:
        for name in OMIT_CLAUDE_MD:
            self.assertIn("\nomitClaudeMd: true\n", front(name), name)
        self.assertNotIn("omitClaudeMd", front("builder"))


class FixRoundTests(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual([delegate.fix_round_model(n) for n in range(1, 6)], ["sonnet"] * 3 + ["opus"] * 2)
        self.assertEqual((delegate.FIX_SONNET_ROUNDS, delegate.FIX_MAX_ROUNDS), (3, 5))

    def test_out_of_range_is_refused(self) -> None:
        for bad in (0, 6, -1):
            with self.assertRaises(delegate.DelegationError):
                delegate.fix_round_model(bad)


class SonModelTests(unittest.TestCase):
    def test_default_is_sonnet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual((SON_MODEL, son_model(Path(tmp))), ("sonnet", "sonnet"))
        self.assertIn("son_model: sonnet", (PLUGIN_ROOT / "templates" / "dts2-harness.local.md").read_text(encoding="utf-8"))

    def test_resume_keeps_the_start_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root: Path = Path(tmp)
            (root / ".claude").mkdir()
            status: Path = root / "status.json"
            self.assertEqual(supervisor.session_model(status, root, resume=False), "sonnet")
            (root / ".claude" / "dts2-harness.local.md").write_text("---\nson_model: opus\n---\n", encoding="utf-8")
            self.assertEqual(supervisor.session_model(status, root, resume=True), "sonnet")
            self.assertEqual(json.loads(status.read_text(encoding="utf-8"))[supervisor.START_MODEL_KEY], "sonnet")
            self.assertEqual(supervisor.session_model(status, root, resume=False), "opus")


class PreUpgradeLaneTests(unittest.TestCase):
    """A lane made before `start_model` existed keeps the model its recorded son argv ran on."""

    def lane(self, root: Path, argv: list[str] | None) -> Path:
        (root / ".claude").mkdir()
        status: Path = root / "status.json"
        if argv is not None:
            (root / "son.json").write_text(json.dumps({"argv": argv, "session_id": "s1"}), encoding="utf-8")
        return status

    def test_resume_recovers_model_from_son_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root: Path = Path(tmp)
            status: Path = self.lane(root, ["claude", "--model", "opus", "--resume", "s1"])
            self.assertEqual(supervisor.session_model(status, root, resume=True), "opus")
            self.assertEqual(json.loads(status.read_text(encoding="utf-8"))[supervisor.START_MODEL_KEY], "opus")

    def test_resume_without_any_record_uses_the_default(self) -> None:
        for argv in (None, ["claude", "--resume", "s1"]):
            with tempfile.TemporaryDirectory() as tmp:
                root: Path = Path(tmp)
                self.assertEqual(supervisor.session_model(self.lane(root, argv), root, resume=True), "sonnet")

    def test_fresh_start_ignores_the_old_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root: Path = Path(tmp)
            status: Path = self.lane(root, ["claude", "--model", "opus"])
            self.assertEqual(supervisor.session_model(status, root, resume=False), "sonnet")


class FixLadderContractTests(unittest.TestCase):
    def test_dispatch_and_fixer_use_the_round_model(self) -> None:
        build: str = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        self.assertIn("--fix-round 2", build)
        self.assertIn("`fixModel`", build)
        self.assertIn("round-5 cap", build)
        self.assertNotIn("Round 3 and the cap are unchanged", build)
        self.assertIn("fixModel", (PLUGIN_ROOT / "agents" / "fixer.md").read_text(encoding="utf-8"))


class WorkflowTests(unittest.TestCase):
    def test_matrix_cache_and_pytest(self) -> None:
        text: str = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("fromJSON('[\"3.12\"]')", text)
        self.assertIn("fromJSON('[\"3.10\",\"3.11\",\"3.12\",\"3.13\"]')", text)
        self.assertIn("github.event_name == 'pull_request'", text)
        self.assertIn("cache: 'pip'", text)
        self.assertIn("cache-dependency-path: plugins/dts2-runtime/requirements-dev.txt", text)
        self.assertIn("python3 -m pytest -n auto -q tests", text)
        self.assertIn("\n  test:\n", text)


if __name__ == "__main__":
    unittest.main()
