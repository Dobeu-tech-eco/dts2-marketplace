"""The dt runtime must work without the optional fleet-ledger plugin (and its Supabase backend)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
SHIPPED_DIRS: tuple[str, ...] = ("scripts", "hooks", "skills", "agents", "commands", "sdk")
DEPENDENCY: re.Pattern[str] = re.compile(r"fleet[-_]ledger", re.IGNORECASE)
SUFFIXES: tuple[str, ...] = (".py", ".sh", ".json")


class FleetLedgerOptionalTests(unittest.TestCase):
    def test_runtime_code_never_references_fleet_ledger(self) -> None:
        offenders: list[str] = []
        for name in SHIPPED_DIRS:
            base: Path = PLUGIN_ROOT / name
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in SUFFIXES and DEPENDENCY.search(path.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(path.relative_to(PLUGIN_ROOT)))
        self.assertEqual(offenders, [], "dt runtime code must not depend on the optional fleet-ledger plugin")

    def test_go_router_has_no_fleet_ledger_dependency(self) -> None:
        router: Path = PLUGIN_ROOT / "scripts" / "next_step.py"
        self.assertTrue(router.is_file())
        self.assertIsNone(DEPENDENCY.search(router.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
