"""N5, Q-11: a fixed-order cached prefix (discipline, roster, probe) that is byte-identical across dispatches, and a
`dry-run` that prints the exact son command, env allowlist and prompt byte count without starting a session."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import briefs  # noqa: E402
import son_launch  # noqa: E402

BRIEFS: Final[Path] = PLUGIN_ROOT / "scripts" / "briefs.py"
FLAG: Final[str] = "--append-system-prompt"
FAKE_CLAUDE: Final[str] = "#!/usr/bin/env python3\nimport sys, pathlib\npathlib.Path(sys.argv[0]).with_suffix('.ran').write_text('ran')\n"
PROBE: Final[dict[str, Any]] = {"agents": {"claude": {"available": True}}, "usable": ["claude"], "dropped": []}


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-prefix-"))
        (self.root / ".harness" / "runs" / "s1").mkdir(parents=True)
        (self.root / ".harness" / "discipline.md").write_text("# Discipline\nRule 1: test first.\n", encoding="utf-8")
        (self.root / ".harness" / "config.yaml").write_text("roster:\n  - name: claude\n", encoding="utf-8")
        (self.root / ".harness" / "runs" / "s1" / "probe.json").write_text(briefs.canonical(PROBE), encoding="utf-8")
        self.manifest = self.root / "lanes.json"
        self.manifest.write_text(json.dumps({
            "stamp": "s1", "base": "abc", "scope": "single",
            "lanes": [{"id": "a", "item": "S1", "files": ["src/a.py"], "ids": {}, "depends_on": [], "tier": "standard"},
                      {"id": "b", "item": "S2", "files": ["src/b.py"], "ids": {}, "depends_on": [], "tier": "standard"}],
        }), encoding="utf-8")
        self.fake = self.root / "claude.py"
        self.fake.write_text(FAKE_CLAUDE, encoding="utf-8")

    def dry_run(self, lane: str, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        wt: Path = self.root / "wt" / lane
        wt.mkdir(parents=True, exist_ok=True)
        env: dict[str, str] = {**os.environ, "DTS2_CLAUDE_BIN": str(self.fake), **(extra_env or {})}
        done = subprocess.run([sys.executable, "-I", str(BRIEFS), "dry-run", str(self.manifest), "--lane", lane,
                               "--worktree", str(wt), "--cwd", str(self.root)],
                              capture_output=True, text=True, env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed


class PrefixTests(Fixture):
    def test_fixed_order_discipline_roster_probe(self) -> None:
        text: str = briefs.cached_prefix(self.root, "s1")
        self.assertLess(text.index("## 1. Discipline"), text.index("## 2. Roster"))
        self.assertLess(text.index("## 2. Roster"), text.index("## 3. Probe"))
        self.assertLess(text.index("Rule 1: test first."), text.index("## 2. Roster"))
        self.assertIn('"usable"', text[text.index("## 3. Probe"):])

    def test_prefix_is_deterministic(self) -> None:
        self.assertEqual(briefs.cached_prefix(self.root, "s1").encode(), briefs.cached_prefix(self.root, "s1").encode())

    def test_missing_files_fall_back_without_error(self) -> None:
        empty: Path = Path(tempfile.mkdtemp(prefix="dts2-empty-"))
        text: str = briefs.cached_prefix(empty, "s9")
        self.assertIn("## 1. Discipline", text)
        self.assertIn("no probe recorded", text)

    def test_launch_flags_carry_the_prefix(self) -> None:
        manifest: dict[str, Any] = json.loads(self.manifest.read_text(encoding="utf-8"))
        flags: list[str] = son_launch.launch_flags(self.root, "dontAsk", manifest, "a", self.root / "wt")
        self.assertEqual(flags[flags.index(FLAG) + 1], briefs.cached_prefix(self.root, "s1"))


class DryRunTests(Fixture):
    def prefix_of(self, result: dict[str, Any]) -> bytes:
        argv: list[str] = result["argv"]
        return argv[argv.index(FLAG) + 1].encode()

    def test_prefix_is_byte_identical_across_two_dispatches(self) -> None:
        first, second = self.dry_run("a"), self.dry_run("b")
        self.assertEqual(self.prefix_of(first), self.prefix_of(second))
        self.assertEqual(first["prefix_sha256"], second["prefix_sha256"])
        self.assertEqual(first["prefix_bytes"], len(self.prefix_of(first)))
        self.assertNotEqual(first["argv"], second["argv"])  # the lane part differs, the prefix does not

    def test_prefix_ignores_the_caller_environment(self) -> None:
        plain, noisy = self.dry_run("a"), self.dry_run("a", {"GH_TOKEN": "secret", "SOMETHING_ELSE": "x"})
        self.assertEqual(self.prefix_of(plain), self.prefix_of(noisy))

    def test_report_has_command_env_allowlist_and_prompt_bytes(self) -> None:
        result: dict[str, Any] = self.dry_run("a", {"GH_TOKEN": "secret"})
        self.assertFalse(result["started"])
        self.assertIn(str(self.fake), result["command"])
        self.assertIn("--append-system-prompt", result["command"])
        self.assertEqual(result["prompt"], "/dts2-harness:autopilot --son s1/a")
        self.assertEqual(result["prompt_bytes"], len(result["prompt"].encode()))
        self.assertIn("PATH", result["env_allowlist"])
        self.assertIn("DTS2_SON", result["env_allowlist"])
        self.assertNotIn("GH_TOKEN", result["env_allowlist"])
        self.assertNotIn("secret", json.dumps(result))

    def test_no_session_is_started(self) -> None:
        self.dry_run("a")
        self.assertFalse(self.fake.with_suffix(".ran").exists())

    def test_unknown_lane_fails(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(BRIEFS), "dry-run", str(self.manifest), "--lane", "zz",
                               "--worktree", str(self.root), "--cwd", str(self.root)], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 1)
        self.assertFalse(json.loads(done.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
