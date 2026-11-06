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
