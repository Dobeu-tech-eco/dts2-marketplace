"""Cooldowns are respected by the roster probe, the lead failover and the SessionStart hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, isolate_agent_status

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import failover  # noqa: E402
import roster  # noqa: E402
from profiles import PROFILE_DIR, Profiles  # noqa: E402

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "session-cooldowns.sh"
STATUS_ENV: Final[str] = "DTS2_AGENT_STATUS"
COOLING_AGENT: Final[str] = "codex"
RESET_AT: Final[str] = "2999-01-01T00:00:00Z"
COOL_REASON: Final[str] = "usage limit"
QUOTA_TEXT: Final[str] = "error: API error 429: usage limit reached\n"
RESET_QUOTA_TEXT: Final[str] = "error: API error 429: usage limit reached, resets at 2999-01-01T00:00:00Z\n"


def seed(path: Path, name: str = COOLING_AGENT) -> None:
    entry: dict[str, Any] = {
        "state": "cooldown", "reset_at": RESET_AT, "source": "manual", "set_by": "test",
        "reason": COOL_REASON, "set_at": "2026-01-01T00:00:00Z", "provider": None, "needs_date": False,
    }
    path.write_text(json.dumps({"version": 1, "agents": {name: entry}}), encoding="utf-8")


class CooldownWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.status: Path = isolate_agent_status(self)
        self.profiles: dict[str, dict[str, Any]] = Profiles.load(PROFILE_DIR).as_dict()

    def test_probe_skips_cooling_agent_with_reason(self) -> None:
        seed(self.status)
        result: dict[str, Any] = roster.probe_entry(
            {"name": COOLING_AGENT}, self.profiles[COOLING_AGENT], "", {},
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], f"cooling down until {RESET_AT} ({COOL_REASON})")
        self.assertEqual(result["resetAt"], RESET_AT)
        self.assertEqual(result["roles"], [])

    def test_next_lead_skips_cooling_agent(self) -> None:
        eligible: list[str] = failover.verified_first(self.profiles)
        self.assertIn(COOLING_AGENT, eligible)
        current: str = next(n for n in eligible if n != COOLING_AGENT)
        before: str | None = failover.next_lead(self.profiles, current, cooling=[])
        seed(self.status, before or COOLING_AGENT)
        after: str | None = failover.next_lead(self.profiles, current)
        self.assertNotEqual(after, before)
        self.assertEqual(failover.next_lead(self.profiles, current, cooling=[]), before)

    def test_classify_records_cooldown_and_asks_for_date(self) -> None:
        out: dict[str, Any] = roster.classify_dispatch("muse", "builder", QUOTA_TEXT, 1)
        self.assertEqual(out["outcome"], "unavailable")
        self.assertTrue(out["needsDate"])
        self.assertIsNotNone(out["cooldown"])
        stored: dict[str, Any] = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertIn("muse", stored["agents"])

    def test_classify_with_reset_needs_no_date(self) -> None:
        out: dict[str, Any] = roster.classify_dispatch("muse", "builder", RESET_QUOTA_TEXT, 1)
        self.assertFalse(out["needsDate"])
        self.assertEqual(out["cooldown"]["reset_at"], RESET_AT)

    def test_classify_plain_failure_has_no_cooldown(self) -> None:
        out: dict[str, Any] = roster.classify_dispatch("muse", "builder", "segfault\n", 1)
        self.assertNotIn("cooldown", out)
        self.assertFalse(self.status.exists())


class SessionHookTests(unittest.TestCase):
    def run_hook(self, status: Path) -> subprocess.CompletedProcess[str]:
        home: str = tempfile.mkdtemp(prefix="dts2-home-")
        env: dict[str, str] = {
            **os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "HOME": home, STATUS_ENV: str(status),
        }
        return subprocess.run(
            ["bash", str(HOOK)], capture_output=True, text=True, cwd=home, env=env, input="", check=False,
        )

    def test_hook_prints_cooling_note(self) -> None:
        status: Path = Path(tempfile.mkdtemp(prefix="dts2-status-")) / "agent-status.json"
        seed(status)
        result: subprocess.CompletedProcess[str] = self.run_hook(status)
        self.assertEqual(result.returncode, 0)
        self.assertIn("do not call", result.stdout)
        self.assertIn(COOLING_AGENT, result.stdout)

    def test_hook_is_silent_when_nothing_cooling(self) -> None:
        status: Path = Path(tempfile.mkdtemp(prefix="dts2-status-")) / "agent-status.json"
        result: subprocess.CompletedProcess[str] = self.run_hook(status)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
