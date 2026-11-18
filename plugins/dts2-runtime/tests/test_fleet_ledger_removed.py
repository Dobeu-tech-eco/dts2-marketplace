"""The fleet-ledger plugin was removed from the marketplace, and the dt runtime must never look for it."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
REPO_ROOT: Path = PLUGIN_ROOT.parent.parent
REMOVED_PLUGIN_DIR: Path = REPO_ROOT / "plugins" / "fleet-ledger"
MARKETPLACE: Path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
EXPECTED_PLUGINS: list[str] = ["dt"]
SHIPPED_DIRS: tuple[str, ...] = ("scripts", "hooks", "skills", "agents", "commands", "sdk")
DEPENDENCY: re.Pattern[str] = re.compile(r"fleet[-_]ledger", re.IGNORECASE)
SUFFIXES: tuple[str, ...] = (".py", ".sh", ".json")
NO_MARKETPLACE: str = "repo-root marketplace.json is absent (the plugin is installed alone)"


class FleetLedgerRemovedTests(unittest.TestCase):
    def test_runtime_code_never_references_fleet_ledger(self) -> None:
        offenders: list[str] = []
        for name in SHIPPED_DIRS:
            base: Path = PLUGIN_ROOT / name
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in SUFFIXES and DEPENDENCY.search(path.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(path.relative_to(PLUGIN_ROOT)))
        self.assertEqual(offenders, [], "the fleet-ledger plugin was removed, so dt runtime code must not look for it")

    def test_go_router_has_no_fleet_ledger_dependency(self) -> None:
        router: Path = PLUGIN_ROOT / "scripts" / "next_step.py"
        self.assertTrue(router.is_file())
        self.assertIsNone(DEPENDENCY.search(router.read_text(encoding="utf-8")))

    def test_plugin_directory_is_gone(self) -> None:
        if not MARKETPLACE.is_file():
            self.skipTest(NO_MARKETPLACE)
        self.assertFalse(REMOVED_PLUGIN_DIR.exists())

    def test_marketplace_lists_only_dt(self) -> None:
        if not MARKETPLACE.is_file():
            self.skipTest(NO_MARKETPLACE)
        market: dict[str, object] = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        names: list[str] = [p["name"] for p in market["plugins"]]  # type: ignore[index]
        self.assertEqual(names, EXPECTED_PLUGINS)


if __name__ == "__main__":
    unittest.main()
