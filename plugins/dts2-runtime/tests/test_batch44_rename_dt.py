"""The 5.0 rename dts2 -> dt: a pre-5.0 plugin id in a keep list or a settings file is still handled sensibly."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final


from helpers import PLUGIN_ROOT
from test_skills_check import Fixture

OLD_IDS: Final[tuple[str, ...]] = ("dts2@dts2", "dts2-harness@dts2")


def load_script(name: str) -> ModuleType:
    import importlib.util
    import sys
    scripts = str(PLUGIN_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_b44", PLUGIN_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LegacyPluginIdTests(unittest.TestCase):
    def test_plugin_manifests_use_the_new_name_and_keep_the_marketplace(self) -> None:
        import json
        plugin = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((PLUGIN_ROOT.parents[1] / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "dt")
        self.assertEqual(market["name"], "dts2")
        self.assertEqual([p["name"] for p in market["plugins"]], ["dt"])

    def test_keep_list_with_old_id_is_not_updated_as_an_extra_plugin(self) -> None:
        fx = Fixture("plugins:\n  - dts2@dts2\n  - dts2-harness@dts2\n  - impeccable@impeccable\n")
        out = fx.run("--fix", "--no-upstream")
        log = fx.log("claude")
        for old in OLD_IDS:
            self.assertNotIn(f"plugin update {old}", log)
        self.assertIn("plugin update impeccable@impeccable", log)
        self.assertEqual(out["harness"]["plugins_updated"], ["impeccable@impeccable"])

    def test_old_keep_entries_do_not_protect_the_old_install_from_machine_prep(self) -> None:
        mod = load_script("machine-prep")
        project = Path(tempfile.mkdtemp(prefix="dts2-legacy-keep-"))
        (project / ".harness").mkdir()
        (project / ".harness" / "keep.yaml").write_text(
            "plugins:\n  - dts2@dts2\n  - dt@dts2\n  - dts2-harness@dts2\n", encoding="utf-8")
        merged = mod.with_keep_list({"requiredByHarness": []}, project)
        self.assertEqual(merged["requiredByHarness"], ["dt@dts2"])

    def test_composio_never_offers_to_disable_the_harness_under_any_of_its_names(self) -> None:
        mod = load_script("composio-setup")
        for item in ("dt@dts2", "dts2@dts2", "dts2-harness@dts2"):
            self.assertEqual(mod.exclusion_reason(item, [], []), "dts2", item)
        self.assertIsNone(mod.exclusion_reason("other@dts2", [], []))


if __name__ == "__main__":
    unittest.main()


class ResumePointerMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_script("agent-memory")
        self.tmp = tempfile.TemporaryDirectory()
        self.path: Path = Path(self.tmp.name) / "CLAUDE.md"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_4x_block_resume_pointer_is_rewritten_and_user_text_kept(self) -> None:
        old_block: str = self.mod.managed_block("demo").replace("/dt:run resume", "/dts2:run resume")
        user_text: str = "# Mine\n\nRun /dts2:run resume by hand if you like.\n\n"
        self.path.write_text(user_text + old_block, encoding="utf-8")
        self.assertEqual(self.mod.sync_file(self.path, "demo"), "migrated")
        text: str = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(user_text))
        self.assertIn("(resume with /dt:run resume)", text)
        self.assertEqual(text.count(self.mod.START_MARKER), 1)
        self.assertEqual(self.mod.sync_file(self.path, "demo"), "unchanged")

    def test_current_block_is_left_alone(self) -> None:
        self.path.write_text(self.mod.managed_block("demo"), encoding="utf-8")
        self.assertEqual(self.mod.sync_file(self.path, "demo"), "unchanged")
