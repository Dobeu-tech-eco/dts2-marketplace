"""AC-1: one Profiles class loads agent profiles; roster, delegate, council, agent-memory and failover use it."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _load  # noqa: E402
import profiles as profiles_mod  # noqa: E402
from profiles import Profiles  # noqa: E402

FAKE: Final[dict[str, dict[str, Any]]] = {
    "alpha": {"name": "alpha", "roles": ["lead", "reviewer"], "models": {"frontier": "a-big", "standard": "a-mid", "economy": None},
              "tokenBurn": {"frontier": 9, "standard": 3}},
    "beta": {"name": "beta", "roles": ["builder"], "models": {"standard": "b-mid"}},
    "gamma": {"name": "gamma", "roles": ["second-opinion"], "models": {}},
}


class ProfilesTests(unittest.TestCase):
    def test_load_reads_the_shipped_profiles(self) -> None:
        p = Profiles.load()
        self.assertIn("claude", p.names())
        self.assertEqual(p.get("claude")["name"], "claude")
        self.assertEqual(p.as_dict().keys(), {f.stem for f in (PLUGIN_ROOT / "profiles" / "agents").glob("*.json")})

    def test_load_from_a_folder_skips_unreadable_files(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="b12-"))
        (folder / "a.json").write_text(json.dumps(FAKE["alpha"]))
        (folder / "bad.json").write_text("{nope")
        (folder / "noname.json").write_text("{}")
        self.assertEqual(Profiles.load(folder).names(), ["alpha"])

    def test_injected_dict_drives_accessors(self) -> None:
        p = Profiles(FAKE)
        self.assertEqual(p.model("alpha", "frontier"), "a-big")
        self.assertIsNone(p.model("alpha", "economy"))
        self.assertIsNone(p.model("nobody", "standard"))
        self.assertEqual(p.token_burn("alpha", "frontier"), 9)
        self.assertEqual(p.token_burn("alpha", "economy"), 1)  # absent: default
        self.assertEqual(p.token_burn("nobody", "standard", default=5), 5)
        self.assertEqual(p.lead_eligible(), ["alpha", "gamma"])
        self.assertIsNone(p.get("nobody"))
        self.assertIn("beta", p)

    def test_token_burn_ignores_bad_values(self) -> None:
        p = Profiles({"x": {"name": "x", "tokenBurn": {"standard": "lots", "economy": True, "frontier": -2}}})
        self.assertEqual([p.token_burn("x", t) for t in ("standard", "economy", "frontier")], [1, 1, 1])


class ConsumersUseProfilesTests(unittest.TestCase):
    def test_delegate_and_roster_load_the_same_data(self) -> None:
        delegate = _load.load("delegate")
        roster = _load.load("roster")
        expected = Profiles.load().as_dict()
        self.assertEqual(delegate.load_profiles(delegate.PROFILE_DIR), expected)
        self.assertEqual(roster.load_profiles(), expected)

    def test_delegate_lead_eligible_matches_profiles(self) -> None:
        delegate = _load.load("delegate")
        self.assertEqual(delegate.lead_eligible(FAKE), Profiles(FAKE).lead_eligible())

    def test_failover_and_agent_memory_share_the_profile_dir(self) -> None:
        self.assertEqual(_load.load("failover").PROFILE_DIR, profiles_mod.PROFILE_DIR)
        self.assertEqual(_load.load("agent-memory").PROFILE_DIR, profiles_mod.PROFILE_DIR)

    def test_council_reads_profiles_through_the_class(self) -> None:
        council = _load.load("council")
        self.assertEqual(council.frontier_model("claude"), Profiles.load().model("claude", "frontier"))
        self.assertEqual(council.read_profile("no-such"), {})

    def test_no_script_but_profiles_globs_the_profile_folder(self) -> None:
        for path in SCRIPTS.glob("*.py"):
            if path.name == "profiles.py":
                continue
            self.assertNotIn('glob("*.json")', path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
