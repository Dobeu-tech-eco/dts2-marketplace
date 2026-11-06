"""User and project agent profiles: layers, extends, name rules, and roster list/add/rename (batch C)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import agent_names  # noqa: E402
import roster  # noqa: E402
from profiles import USER_AGENTS_ENV, Profiles  # noqa: E402

ROSTER_CLI: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"
CONFIG: Final[str] = "project: demo\nroster:\n  - name: claude\n  - name: codex\n    roles: [builder]\nbudget:\n  codex:\n    status: ok\n"
FAKE_KEY: Final[str] = "sk-test-FAKE" + "0123456789abcdefghij"


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dts2-profiles-"))
        self.project = self.tmp / "repo"
        self.home = self.tmp / "home-agents"
        self.project_dir = self.project / ".harness" / "agents"
        self.config = self.project / ".harness" / "config.yaml"
        write(self.config, CONFIG)
        patcher = mock.patch.dict(os.environ, {USER_AGENTS_ENV: str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def load(self) -> Profiles:
        return Profiles.load(project=self.project)

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(ROSTER_CLI), *args], capture_output=True, text=True, check=False,
            cwd=str(self.project), env={**os.environ, USER_AGENTS_ENV: str(self.home)},
        )


class LayerTests(Workspace):
    def test_bundled_only_by_default(self) -> None:
        profiles = self.load()
        self.assertEqual(profiles.layer_of("grok"), "bundled")
        self.assertEqual(profiles.warnings, [])

    def test_later_layers_win_field_by_field(self) -> None:
        write(self.home / "grok.json", {"name": "grok", "models": {"standard": "user-model"}, "costTier": 3})
        write(self.project_dir / "grok.json", {"name": "grok", "costTier": 1})
        profiles = self.load()
        grok = profiles.get("grok") or {}
        self.assertEqual(grok["costTier"], 1)
        self.assertEqual(grok["models"]["standard"], "user-model")
        self.assertEqual(grok["models"]["frontier"], "grok-4.7")
        self.assertEqual(profiles.layer_of("grok"), "project")
        self.assertEqual(profiles.layers_of("grok"), ["bundled", "user", "project"])

    def test_extends_deep_merges_dicts_and_replaces_lists(self) -> None:
        write(self.home / "grok-api.json", {
            "name": "grok-api", "extends": "grok", "roles": ["builder"], "models": {"standard": "grok-build-0.1"},
        })
        child = self.load().get("grok-api") or {}
        self.assertEqual(child["models"], {"frontier": "grok-4.7", "standard": "grok-build-0.1", "economy": "grok-4.7-build-fast"})
        self.assertEqual(child["roles"], ["builder"])
        self.assertEqual(child["apiKeyEnv"], "XAI_API_KEY")
        self.assertEqual(self.load().base_of("grok-api"), "grok")
        self.assertEqual(self.load().layer_of("grok-api"), "user")

    def test_extends_resolves_after_all_layers_load(self) -> None:
        write(self.project_dir / "fast.json", {"name": "fast", "extends": "grok", "costTier": 1})
        write(self.home / "grok.json", {"name": "grok", "costTier": 3})
        self.assertEqual((self.load().get("fast") or {})["costTier"], 1)
        write(self.project_dir / "plain.json", {"name": "plain", "extends": "grok"})
        self.assertEqual((self.load().get("plain") or {})["costTier"], 3)

    def test_cycle_is_dropped_with_a_warning(self) -> None:
        write(self.home / "aa.json", {"name": "aa", "extends": "bb"})
        write(self.home / "bb.json", {"name": "bb", "extends": "aa"})
        profiles = self.load()
        self.assertNotIn("aa", profiles)
        self.assertNotIn("bb", profiles)
        self.assertIn("grok", profiles)
        self.assertTrue(any("cycle" in w for w in profiles.warnings))

    def test_missing_parent_is_dropped_with_a_warning(self) -> None:
        write(self.home / "orphan.json", {"name": "orphan", "extends": "nope"})
        write(self.home / "child.json", {"name": "child", "extends": "orphan"})
        profiles = self.load()
        self.assertNotIn("orphan", profiles)
        self.assertNotIn("child", profiles)
        self.assertTrue(any("'orphan' dropped" in w for w in profiles.warnings))

    def test_profile_without_what_a_roster_needs_is_dropped(self) -> None:
        write(self.home / "bare.json", {"name": "bare"})
        profiles = self.load()
        self.assertNotIn("bare", profiles)
        self.assertTrue(any("missing" in w for w in profiles.warnings))

    def test_raw_key_profile_is_rejected(self) -> None:
        write(self.home / "leaky.json", {"name": "leaky", "extends": "grok", "env": {"XAI_API_KEY": "xai-" + "a" * 24}})
        write(self.home / "leaky-too.json", {"name": "leaky-too", "extends": "grok", "notes": [FAKE_KEY]})
        profiles = self.load()
        self.assertNotIn("leaky", profiles)
        self.assertNotIn("leaky-too", profiles)
        self.assertEqual(len([w for w in profiles.warnings if "raw API key" in w]), 2)

    def test_api_key_ref_must_be_a_pointer(self) -> None:
        for ref in ("keyring:dts2/grok-api", "op://vault/item/field", "doppler:XAI_KEY", "env:XAI_API_KEY"):
            write(self.home / "ok.json", {"name": "okay", "extends": "grok", "apiKeyRef": ref})
            self.assertIn("okay", self.load(), ref)
        write(self.home / "ok.json", {"name": "okay", "extends": "grok", "apiKeyRef": "plain-secret-value"})
        self.assertNotIn("okay", self.load())

    def test_injected_dict_still_works(self) -> None:
        profiles = Profiles({"x": {"name": "x", "roles": ["reviewer"]}})
        self.assertEqual(profiles.lead_eligible(), ["x"])
        self.assertEqual(profiles.layer_of("x"), "bundled")
        self.assertEqual(profiles.layer_of("nope"), "")

    def test_explicit_dir_reads_only_that_folder(self) -> None:
        write(self.home / "grok-api.json", {"name": "grok-api", "extends": "grok"})
        self.assertNotIn("grok-api", Profiles.load(PLUGIN_ROOT / "profiles" / "agents"))


class NameTests(unittest.TestCase):
    def test_valid_names(self) -> None:
        for name in ("grok-api", "ab", "x1", "claude-api-2", "a" + "b" * 30 + "c"):
            self.assertIsNone(agent_names.validate_name(name), name)

    def test_invalid_names(self) -> None:
        for name in ("", "a", "Grok", "grok_api", "grok--api", "-grok", "grok-", "1grok", "a" * 33, "grok api"):
            self.assertIsNotNone(agent_names.validate_name(name), name)

    def test_reserved_names(self) -> None:
        for name in ("lead", "builder", "reviewer", "verifier", "scout", "auditor", "fixer", "all", "none",
                     "frontier", "standard", "economy"):
            self.assertIn("reserved", agent_names.validate_name(name) or "")

    def test_suggest_name_walks_grok_api_then_numbers(self) -> None:
        self.assertEqual(agent_names.suggest_name("grok", {"claude"}), "grok")
        self.assertEqual(agent_names.suggest_name("grok", {"grok"}), "grok-api")
        self.assertEqual(agent_names.suggest_name("grok", {"grok", "grok-api"}), "grok-api-2")
        self.assertEqual(agent_names.suggest_name("grok", {"grok", "grok-api", "grok-api-2"}), "grok-api-3")
        self.assertEqual(agent_names.next_free("grok-api", {"grok-api", "grok-api-2"}), "grok-api-3")

    def test_collision_names_the_layer(self) -> None:
        profiles = Profiles.load()
        self.assertEqual(agent_names.collision("grok", profiles), "bundled")
        self.assertIsNone(agent_names.collision("grok-api", profiles))


class RosterTests(Workspace):
    def test_resolve_accepts_a_user_layer_name(self) -> None:
        write(self.home / "grok-api.json", {"name": "grok-api", "extends": "grok"})
        result = roster.resolve([{"name": "claude"}, {"name": "grok-api", "roles": ["builder"]}], roster.load_profiles(self.project))
        self.assertEqual(result["assignments"]["builder"], ["claude", "grok-api"])
        self.assertEqual(result["live"], ["claude", "grok-api"])

    def test_resolve_still_rejects_unknown_names(self) -> None:
        with self.assertRaises(roster.RosterError):
            roster.resolve([{"name": "nope"}], roster.load_profiles(self.project))

    def test_entry_profile_pointer(self) -> None:
        entries = roster.parse_roster("roster:\n  - name: scout-grok\n    profile: grok\n    roles: [builder]\n")
        self.assertEqual(entries[0]["profile"], "grok")
        result = roster.resolve(entries, roster.load_profiles(self.project))
        self.assertEqual(result["assignments"], {"builder": ["scout-grok"]})
        with self.assertRaises(roster.RosterError):
            roster.resolve([{"name": "x", "profile": "missing"}], roster.load_profiles(self.project))

    def test_parse_roster_tolerates_unknown_keys(self) -> None:
        entries = roster.parse_roster("roster:\n  - name: a\n    rules: {x: 1}\n    profile: grok\n")
        self.assertEqual(entries, [{"name": "a", "profile": "grok"}])

    def test_add_writes_profile_and_roster_entry(self) -> None:
        done = self.cli("add", "--name", "grok-api", "--extends", "grok", "--auth", "api-key",
                        "--api-key-ref", "keyring:dts2/grok-api", "--display-name", "Grok (API key)", "--roles", "builder,reviewer")
        self.assertEqual(done.returncode, 0, done.stderr)
        saved = json.loads((self.project_dir / "grok-api.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, {
            "name": "grok-api", "extends": "grok", "displayName": "Grok (API key)", "auth": "api-key",
            "apiKeyRef": "keyring:dts2/grok-api",
        })
        text = self.config.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("project: demo\nroster:\n  - name: claude\n  - name: codex\n    roles: [builder]\n  - name: grok-api\n"))
        self.assertTrue(text.endswith("budget:\n  codex:\n    status: ok\n"))
        entry = roster.read_roster(self.config)[-1]
        self.assertEqual(entry, {"name": "grok-api", "roles": ["builder", "reviewer"], "auth": "api-key", "included": True})

    def test_add_user_scope_writes_to_the_user_folder(self) -> None:
        done = self.cli("add", "--name", "codex-api", "--extends", "codex", "--scope", "user")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.home / "codex-api.json").exists())
        self.assertFalse(self.project_dir.exists())

    def test_add_collision_exits_2_and_names_the_layer(self) -> None:
        done = self.cli("add", "--name", "grok", "--extends", "grok")
        self.assertEqual(done.returncode, 2)
        self.assertIn("bundled layer", done.stderr)
        self.assertIn("grok-2", done.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), CONFIG)
        write(self.home / "mine.json", {"name": "mine", "extends": "grok"})
        again = self.cli("add", "--name", "mine", "--extends", "codex")
        self.assertEqual(again.returncode, 2)
        self.assertIn("user layer", again.stderr)

    def test_add_edit_existing_overwrites(self) -> None:
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok").returncode, 0)
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok").returncode, 2)
        done = self.cli("add", "--name", "grok-api", "--extends", "grok", "--display-name", "Second", "--edit-existing")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads((self.project_dir / "grok-api.json").read_text(encoding="utf-8"))["displayName"], "Second")
        self.assertEqual([e["name"] for e in roster.read_roster(self.config)].count("grok-api"), 1)

    def test_add_refuses_bad_input(self) -> None:
        cases = (
            ("--name", "Bad_Name", "--extends", "grok"),
            ("--name", "lead", "--extends", "grok"),
            ("--name", "x-api", "--extends", "nope"),
            ("--name", "x-api", "--extends", "grok", "--api-key-ref", FAKE_KEY),
            ("--name", "x-api", "--extends", "grok", "--roles", "lead"),
        )
        for case in cases:
            self.assertEqual(self.cli("add", *case).returncode, 2, case)
        self.assertFalse(self.project_dir.exists())

    def test_add_creates_config_when_missing(self) -> None:
        self.config.unlink()
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok").returncode, 0)
        self.assertEqual([e["name"] for e in roster.read_roster(self.config)], ["claude", "grok-api"])

    def test_rename_rewrites_roster_and_references(self) -> None:
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok", "--roles", "builder").returncode, 0)
        write(self.project_dir / "grok-fast.json", {
            "name": "grok-fast", "extends": "grok-api", "fallback": {"builder": "grok-api", "reviewer": "claude"},
        })
        write(self.config, self.config.read_text(encoding="utf-8").replace(
            "  - name: grok-api\n", "  - name: grok-api\n  - name: twin\n    profile: grok-api\n"))
        done = self.cli("rename", "grok-api", "xai-grok")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.project_dir / "grok-api.json").exists())
        self.assertEqual(json.loads((self.project_dir / "xai-grok.json").read_text(encoding="utf-8"))["name"], "xai-grok")
        fast = json.loads((self.project_dir / "grok-fast.json").read_text(encoding="utf-8"))
        self.assertEqual(fast["extends"], "xai-grok")
        self.assertEqual(fast["fallback"], {"builder": "xai-grok", "reviewer": "claude"})
        entries = roster.read_roster(self.config)
        self.assertEqual([e["name"] for e in entries], ["claude", "codex", "xai-grok", "twin"])
        self.assertEqual(entries[3]["profile"], "xai-grok")
        self.assertEqual(self.load().base_of("grok-fast"), "grok")
        self.assertNotIn("grok-api", self.config.read_text(encoding="utf-8"))

    def test_rename_refuses_bundled_unknown_and_taken(self) -> None:
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok").returncode, 0)
        self.assertEqual(self.cli("rename", "grok", "groky").returncode, 2)
        self.assertEqual(self.cli("rename", "ghost", "spirit").returncode, 2)
        self.assertEqual(self.cli("rename", "grok-api", "codex").returncode, 2)
        self.assertEqual(self.cli("rename", "grok-api", "Bad Name").returncode, 2)
        self.assertTrue((self.project_dir / "grok-api.json").exists())

    def test_list_json_and_table(self) -> None:
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok", "--auth", "api-key").returncode, 0)
        rows = {r["name"]: r for r in json.loads(self.cli("list", "--json").stdout)}
        self.assertEqual(rows["grok-api"]["base"], "grok")
        self.assertEqual(rows["grok-api"]["layer"], "project")
        self.assertEqual(rows["grok-api"]["auth"], "api-key")
        self.assertEqual(rows["grok-api"]["rules"], "-")
        self.assertEqual(rows["grok-api"]["spent_today"], "-")
        self.assertTrue(rows["grok-api"]["inRoster"])
        self.assertFalse(rows["grok"]["inRoster"])
        self.assertEqual(rows["grok"]["layer"], "bundled")
        header = self.cli("list").stdout.splitlines()[0].split()
        self.assertEqual(header, ["name", "base", "layer", "auth", "roles", "rules", "spent_today"])

    def test_suggest_name_cli(self) -> None:
        self.assertEqual(self.cli("suggest-name", "--base", "grok").stdout.strip(), "grok-api")
        self.assertEqual(self.cli("suggest-name", "--base", "newthing").stdout.strip(), "newthing")
        self.assertEqual(self.cli("add", "--name", "grok-api", "--extends", "grok").returncode, 0)
        self.assertEqual(self.cli("suggest-name", "--base", "grok").stdout.strip(), "grok-api-2")


if __name__ == "__main__":
    unittest.main()
