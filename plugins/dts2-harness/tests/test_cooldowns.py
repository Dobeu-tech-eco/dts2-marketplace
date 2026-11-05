"""Tests for scripts/cooldowns.py: the shared agent cooldown registry."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import cooldowns  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "cooldowns.py"
NOW: Final[datetime] = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
HOUR: Final[timedelta] = timedelta(hours=1)
DAY: Final[timedelta] = timedelta(days=1)
STATUS_ENV: Final[str] = "DTS2_AGENT_STATUS"


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TempStatus(unittest.TestCase):
    """Each test gets its own status file inside a temp dir; nothing touches ~/.dts2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path: Path = Path(self.tmp.name) / "sub" / "agent-status.json"
        saved: str | None = os.environ.get(STATUS_ENV)
        os.environ[STATUS_ENV] = str(self.path)
        self.addCleanup(lambda: os.environ.__setitem__(STATUS_ENV, saved) if saved else os.environ.pop(STATUS_ENV, None))

    def put(self, name: str, reset: datetime, source: str = "error", **kw: Any) -> dict[str, Any]:
        return cooldowns.record(name, reset, source, "test", "limit", path=self.path, now=NOW, **kw)


class RegistryTests(TempStatus):
    def test_status_path_prefers_explicit_env(self) -> None:
        self.assertEqual(cooldowns.status_path(), self.path)

    def test_status_path_uses_dts2_home(self) -> None:
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop(STATUS_ENV)
        os.environ["DTS2_HOME"] = "/x/home"
        self.assertEqual(cooldowns.status_path(), Path("/x/home/agent-status.json"))

    def test_status_path_default_is_user_dir(self) -> None:
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop(STATUS_ENV)
        os.environ.pop("DTS2_HOME", None)
        self.assertEqual(cooldowns.status_path(), Path.home() / ".dts2" / "agent-status.json")

    def test_round_trip(self) -> None:
        entry = self.put("codex", NOW + DAY, provider="openai")
        self.assertEqual(entry["reset_at"], "2026-11-06T12:00:00Z")
        self.assertEqual(entry["state"], "cooldown")
        found = cooldowns.is_cooling("codex", self.path, NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found["provider"], "openai")  # type: ignore[index]
        self.assertEqual(cooldowns.cooling_names(self.path, NOW), ["codex"])
        self.assertTrue(cooldowns.clear("codex", self.path))
        self.assertIsNone(cooldowns.is_cooling("codex", self.path, NOW))

    def test_entry_has_all_schema_fields(self) -> None:
        entry = self.put("codex", NOW + HOUR)
        self.assertEqual(
            set(entry),
            {"state", "reset_at", "source", "set_by", "reason", "set_at", "provider", "needs_date"},
        )
        self.assertEqual(entry["set_at"], "2026-11-05T12:00:00Z")
        self.assertFalse(entry["needs_date"])

    def test_document_has_version_one(self) -> None:
        self.put("codex", NOW + HOUR)
        self.assertEqual(json.loads(self.path.read_text())["version"], 1)

    def test_not_cooling_after_reset(self) -> None:
        self.put("codex", NOW + HOUR)
        self.assertIsNone(cooldowns.is_cooling("codex", self.path, NOW + HOUR))
        self.assertIsNone(cooldowns.is_cooling("codex", self.path, NOW + 2 * HOUR))

    def test_is_cooling_does_not_write(self) -> None:
        self.assertIsNone(cooldowns.is_cooling("codex", self.path, NOW))
        self.assertFalse(self.path.exists())
        self.put("codex", NOW + HOUR)
        before = self.path.read_text()
        cooldowns.is_cooling("codex", self.path, NOW + DAY)
        self.assertEqual(self.path.read_text(), before)

    def test_clear_missing_returns_false(self) -> None:
        self.assertFalse(cooldowns.clear("ghost", self.path))

    def test_expire_removes_only_due_entries(self) -> None:
        self.put("a", NOW + HOUR)
        self.put("b", NOW + DAY)
        self.assertEqual(cooldowns.expire(self.path, NOW + 2 * HOUR), ["a"])
        self.assertEqual(cooldowns.cooling_names(self.path, NOW + 2 * HOUR), ["b"])

    def test_expire_nothing_due_does_not_write(self) -> None:
        self.put("a", NOW + DAY)
        before = self.path.stat().st_mtime_ns
        self.assertEqual(cooldowns.expire(self.path, NOW), [])
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_provisional_when_no_date(self) -> None:
        entry = cooldowns.record("grok", None, "error", "test", "limit", path=self.path, now=NOW)
        self.assertEqual(entry["reset_at"], "2026-11-05T17:00:00Z")
        self.assertEqual(entry["source"], "assumed")
        self.assertTrue(entry["needs_date"])

    def test_never_shorten_active_cooldown(self) -> None:
        self.put("codex", NOW + DAY)
        kept = self.put("codex", NOW + 2 * HOUR)
        self.assertEqual(kept["reset_at"], "2026-11-06T12:00:00Z")
        self.assertEqual(cooldowns.load(self.path)["agents"]["codex"]["reset_at"], "2026-11-06T12:00:00Z")

    def test_later_date_extends(self) -> None:
        self.put("codex", NOW + HOUR)
        self.assertEqual(self.put("codex", NOW + DAY)["reset_at"], "2026-11-06T12:00:00Z")

    def test_user_may_shorten(self) -> None:
        self.put("codex", NOW + DAY)
        self.assertEqual(self.put("codex", NOW + HOUR, source="user")["reset_at"], "2026-11-05T13:00:00Z")

    def test_manual_may_shorten(self) -> None:
        self.put("codex", NOW + DAY)
        self.assertEqual(self.put("codex", NOW + HOUR, source="manual")["source"], "manual")

    def test_expired_entry_can_be_replaced_by_shorter(self) -> None:
        self.put("codex", NOW + HOUR)
        later = NOW + 2 * HOUR
        entry = cooldowns.record("codex", later + HOUR, "error", "t", "r", path=self.path, now=later)
        self.assertEqual(entry["reset_at"], to_iso(later + HOUR))

    def test_real_date_replaces_provisional_guess(self) -> None:
        cooldowns.record("grok", None, "error", "t", "r", path=self.path, now=NOW)
        entry = self.put("grok", NOW + 2 * HOUR)
        self.assertEqual(entry["reset_at"], "2026-11-05T14:00:00Z")
        self.assertFalse(entry["needs_date"])

    def test_name_is_lowercased(self) -> None:
        self.put("Claude-API", NOW + HOUR)
        self.assertEqual(cooldowns.cooling_names(self.path, NOW), ["claude-api"])
        self.assertIsNotNone(cooldowns.is_cooling("CLAUDE-API", self.path, NOW))

    def test_custom_agent_names_work(self) -> None:
        for name in ("claude-api", "grok-review", "my.agent_2", "a"):
            self.put(name, NOW + HOUR)
        self.assertEqual(len(cooldowns.cooling_names(self.path, NOW)), 4)

    def test_invalid_names_rejected(self) -> None:
        for name in ("", "-lead", "has space", "a/b", "x" * 65, "..", "ünï"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.put(name, NOW + HOUR)

    def test_invalid_source_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cooldowns.record("codex", NOW + HOUR, "bogus", "t", "r", path=self.path, now=NOW)

    def test_atomic_write_leaves_valid_json_and_no_temp_files(self) -> None:
        for index in range(5):
            self.put(f"agent-{index}", NOW + HOUR)
        parsed = json.loads(self.path.read_text())
        self.assertEqual(len(parsed["agents"]), 5)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_parent_dir_is_created(self) -> None:
        self.assertFalse(self.path.parent.exists())
        self.put("codex", NOW + HOUR)
        self.assertTrue(self.path.is_file())

    def test_corrupt_file_reads_empty(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(cooldowns.load(self.path), {"version": 1, "agents": {}})
        self.assertIsNone(cooldowns.is_cooling("codex", self.path, NOW))
        self.assertEqual(self.put("codex", NOW + HOUR)["state"], "cooldown")

    def test_wrong_shapes_read_empty(self) -> None:
        self.path.parent.mkdir(parents=True)
        for text in ("[]", '{"agents": []}', '{"agents": {"a": 5, "b": {"reset_at": "junk"}}}', ""):
            self.path.write_text(text)
            with self.subTest(text=text):
                self.assertEqual(cooldowns.load(self.path)["agents"], {})

    def test_missing_file_reads_empty(self) -> None:
        self.assertEqual(cooldowns.load(self.path), {"version": 1, "agents": {}})


def to_iso(moment: datetime) -> str:
    return cooldowns.to_iso(moment)


class ParseResetTests(unittest.TestCase):
    def parse(self, text: str, now: datetime = NOW) -> datetime | None:
        return cooldowns.parse_reset(text, now)

    def test_claude_epoch(self) -> None:
        self.assertEqual(self.parse("Claude AI usage limit reached|1763700000"), datetime.fromtimestamp(1763700000, timezone.utc))

    def test_iso_z(self) -> None:
        self.assertEqual(self.parse("until 2026-11-21T09:00:00Z"), utc(2026, 11, 21, 9))

    def test_iso_offset(self) -> None:
        self.assertEqual(self.parse("2026-11-21T09:00:00+02:00"), utc(2026, 11, 21, 7))
        self.assertEqual(self.parse("2026-11-21T09:00:00-0500"), utc(2026, 11, 21, 14))
        self.assertEqual(self.parse("2026-11-21T09:00:00+00:00"), utc(2026, 11, 21, 9))

    def test_iso_naive_is_utc(self) -> None:
        self.assertEqual(self.parse("2026-11-21T09:30:00"), utc(2026, 11, 21, 9, 30))

    def test_iso_date_only(self) -> None:
        self.assertEqual(self.parse("2026-11-21"), utc(2026, 11, 21))

    def test_resets_at_iso(self) -> None:
        self.assertEqual(self.parse("quota; resets at 2026-12-01T00:00:00Z"), utc(2026, 12, 1))
        self.assertEqual(self.parse("reset at 2026-12-01T00:00:00Z"), utc(2026, 12, 1))

    def test_relative_days_hours_minutes(self) -> None:
        self.assertEqual(self.parse("Try again in 2 days 3 hours 4 minutes."), NOW + timedelta(days=2, hours=3, minutes=4))

    def test_relative_short_forms(self) -> None:
        self.assertEqual(self.parse("in 3h 20m"), NOW + timedelta(hours=3, minutes=20))
        self.assertEqual(self.parse("try again in 45s"), NOW + timedelta(seconds=45))

    def test_retry_after_seconds(self) -> None:
        self.assertEqual(self.parse("retry after 120 seconds"), NOW + timedelta(seconds=120))

    def test_try_again_at_full_date(self) -> None:
        self.assertEqual(self.parse("try again at Nov 21st, 2026 9:00 AM"), utc(2026, 11, 21, 9))

    def test_pm_conversion(self) -> None:
        self.assertEqual(self.parse("try again at Nov 21st, 2026 9:00 PM"), utc(2026, 11, 21, 21))
        self.assertEqual(self.parse("try again at Nov 21, 2026 12:00 AM"), utc(2026, 11, 21, 0))
        self.assertEqual(self.parse("try again at Nov 21, 2026 12:00 PM"), utc(2026, 11, 21, 12))

    def test_resets_on_month_name_this_year(self) -> None:
        self.assertEqual(self.parse("resets on November 21"), utc(2026, 11, 21))
        self.assertEqual(self.parse("resets Nov 21"), utc(2026, 11, 21))

    def test_month_without_year_rolls_to_next_year_when_past(self) -> None:
        self.assertEqual(self.parse("resets Nov 2"), utc(2027, 11, 2))
        self.assertEqual(self.parse("resets Jan 3", utc(2026, 12, 30)), utc(2027, 1, 3))

    def test_invalid_calendar_date_is_none(self) -> None:
        self.assertIsNone(self.parse("resets Feb 30"))

    def test_time_only_later_today(self) -> None:
        self.assertEqual(self.parse("resets 3pm"), utc(2026, 11, 5, 15))
        self.assertEqual(self.parse("resets at 3:30 pm"), utc(2026, 11, 5, 15, 30))

    def test_time_only_next_occurrence(self) -> None:
        self.assertEqual(self.parse("resets 9am"), utc(2026, 11, 6, 9))
        self.assertEqual(self.parse("resets at 12:00 pm"), utc(2026, 11, 6, 12))  # equals now, so the next one

    def test_you_hit_your_limit_message(self) -> None:
        self.assertEqual(self.parse("You've hit your limit · resets 3pm (UTC)"), utc(2026, 11, 5, 15))

    def test_epoch_beats_other_patterns(self) -> None:
        self.assertEqual(
            self.parse("limit reached|1763700000 resets 3pm"), datetime.fromtimestamp(1763700000, timezone.utc),
        )

    def test_unparseable_is_none(self) -> None:
        for text in ("", "nothing here", "resets soon", "try again later", "resets 25pm"):
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_result_is_utc_aware(self) -> None:
        local = datetime(2026, 11, 5, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
        result = cooldowns.parse_reset("try again in 1h", local)
        self.assertEqual(result, utc(2026, 11, 5, 13))
        self.assertEqual(result.utcoffset(), timedelta(0))  # type: ignore[union-attr]


class DetectTests(unittest.TestCase):
    def det(self, text: str, code: int | None = 1, **kw: Any) -> dict[str, Any] | None:
        return cooldowns.detect(text, code, "agent-x", now=NOW, **kw)

    def test_provider_samples(self) -> None:
        samples: dict[str, str | None] = {
            "Claude AI usage limit reached|1763700000": "claude",
            "5-hour limit reached": "claude",
            "You've reached your weekly limit": "claude",
            "You've hit your limit - resets 3pm": "claude",
            "Your limit will reset at 3pm": "claude",
            "usage limit reached": "claude",
            '{"type":"rate_limit_error"}': "anthropic-api",
            "Your credit balance is too low to access the Anthropic API": "anthropic-api",
            "You exceeded your current quota, please check your plan": "openai",
            "code: insufficient_quota": "openai",
            "You've hit your usage limit. Try again in 2 days 3 hours": "openai",
            "Error: 429 rate limit exceeded": "xai",
            "You have reached your monthly spending limit": "xai",
            "credits exhausted": "xai",
            "429 RESOURCE_EXHAUSTED": "gemini",
            "Quota exceeded for metric": None,
            "usage limit": None,
            "out of credits": None,
            "HTTP 429 Too Many Requests": None,
            "status: 429": None,
        }
        for text, provider in samples.items():
            with self.subTest(text=text):
                result = self.det(text)
                self.assertIsNotNone(result)
                self.assertEqual(result["provider"], provider)  # type: ignore[index]
                self.assertEqual(result["agent"], "agent-x")  # type: ignore[index]

    def test_provider_argument_overrides(self) -> None:
        self.assertEqual(self.det("insufficient_quota", provider="custom")["provider"], "custom")  # type: ignore[index]

    def test_negative_normal_output(self) -> None:
        for text in ("All tests passed.", "", "build finished in 3m", "Review complete: 2 findings"):
            with self.subTest(text=text):
                self.assertIsNone(self.det(text, 0))

    def test_negative_unrelated_limit_word(self) -> None:
        for text in ("the speed limit is 55", "raise the line-length limit to 120", "limit: 10 items per page", "port 4290 is open"):
            with self.subTest(text=text):
                self.assertIsNone(self.det(text))

    def test_clean_exit_judges_tail_only(self) -> None:
        discussion = "We discuss the usage limit handling in cooldowns.py.\n" + "x" * 2000
        self.assertIsNone(self.det(discussion, 0))
        self.assertIsNotNone(self.det(discussion, 1))

    def test_reset_known_is_iso(self) -> None:
        result = self.det("Try again in 2 days 3 hours. You exceeded your current quota")
        self.assertEqual(result["reset_at"], "2026-11-07T15:00:00Z")  # type: ignore[index]
        self.assertFalse(result["transient"])  # type: ignore[index]

    def test_reset_unknown_is_none(self) -> None:
        result = self.det("insufficient_quota")
        self.assertIsNone(result["reset_at"])  # type: ignore[index]
        self.assertFalse(result["transient"])  # type: ignore[index]

    def test_short_reset_is_transient(self) -> None:
        result = self.det("429 rate limit exceeded, retry after 60 seconds")
        self.assertTrue(result["transient"])  # type: ignore[index]

    def test_boundary_is_not_transient(self) -> None:
        self.assertFalse(self.det("usage limit, try again in 15 minutes")["transient"])  # type: ignore[index]
        self.assertTrue(self.det("usage limit, try again in 14 minutes")["transient"])  # type: ignore[index]

    def test_reason_is_short(self) -> None:
        self.assertLessEqual(len(self.det("usage limit")["reason"]), cooldowns.REASON_MAX)  # type: ignore[index]

    def test_epoch_in_claude_message_is_parsed(self) -> None:
        result = self.det("Claude AI usage limit reached|1793880000")
        self.assertEqual(result["reset_at"], cooldowns.to_iso(datetime.fromtimestamp(1793880000, timezone.utc)))  # type: ignore[index]


class RecordDetectionTests(TempStatus):
    def test_known_reset_recorded_as_error(self) -> None:
        det = cooldowns.detect("You exceeded your current quota. Try again in 2 days", 1, "codex", now=NOW)
        entry = cooldowns.record_detection(det, "tester", self.path, NOW)  # type: ignore[arg-type]
        self.assertEqual(entry["source"], "error")  # type: ignore[index]
        self.assertEqual(entry["reset_at"], "2026-11-07T12:00:00Z")  # type: ignore[index]
        self.assertEqual(entry["provider"], "openai")  # type: ignore[index]
        self.assertEqual(entry["set_by"], "tester")  # type: ignore[index]

    def test_unknown_reset_is_provisional(self) -> None:
        det = cooldowns.detect("insufficient_quota", 1, "codex", now=NOW)
        entry = cooldowns.record_detection(det, "tester", self.path, NOW)  # type: ignore[arg-type]
        self.assertTrue(entry["needs_date"])  # type: ignore[index]
        self.assertEqual(entry["source"], "assumed")  # type: ignore[index]

    def test_transient_is_not_recorded(self) -> None:
        det = cooldowns.detect("rate limit exceeded, retry after 30 seconds", 1, "grok", now=NOW)
        self.assertIsNone(cooldowns.record_detection(det, "tester", self.path, NOW))  # type: ignore[arg-type]
        self.assertFalse(self.path.exists())


class CliTests(TempStatus):
    def run_cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        env = {**os.environ, STATUS_ENV: str(self.path)}
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
            env=env, cwd=str(PLUGIN_ROOT),
        )

    def seed(self, name: str, reset: datetime, reason: str = "limit", needs_date: bool = False) -> None:
        cooldowns.record(name, None if needs_date else reset, "error", "seed", reason, path=self.path, now=NOW)

    def future(self, delta: timedelta) -> datetime:
        return datetime.now(timezone.utc) + delta

    def test_set_until_iso_and_check(self) -> None:
        until = cooldowns.to_iso(self.future(2 * DAY))
        result = self.run_cli("set", "codex", "--until", until, "--reason", "weekly")
        self.assertEqual(result.returncode, 0, result.stderr)
        printed = json.loads(result.stdout)
        self.assertEqual(printed["reset_at"], until)
        self.assertEqual(printed["source"], "manual")
        self.assertEqual(printed["reason"], "weekly")
        checked = self.run_cli("check", "codex")
        self.assertEqual(checked.returncode, 3)
        self.assertTrue(json.loads(checked.stdout)["cooling"])

    def test_set_in_duration(self) -> None:
        result = self.run_cli("set", "codex", "--in", "2d 3h", "--source", "user", "--by", "me")
        self.assertEqual(result.returncode, 0, result.stderr)
        printed = json.loads(result.stdout)
        self.assertEqual(printed["source"], "user")
        self.assertEqual(printed["set_by"], "me")
        reset = cooldowns.parse_iso(printed["reset_at"])
        gap = reset - datetime.now(timezone.utc)  # type: ignore[operator]
        self.assertLess(abs(gap - timedelta(days=2, hours=3)), timedelta(minutes=1))

    def test_set_until_natural_date(self) -> None:
        result = self.run_cli("set", "codex", "--until", "Nov 21, 2099 9:00 AM")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["reset_at"], "2099-11-21T09:00:00Z")

    def test_set_bad_date_exits_2(self) -> None:
        result = self.run_cli("set", "codex", "--until", "whenever")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.path.exists())

    def test_set_bad_name_exits_2(self) -> None:
        self.assertEqual(self.run_cli("set", "Bad Name", "--in", "1d").returncode, 2)

    def test_check_free_agent(self) -> None:
        result = self.run_cli("check", "codex")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"agent": "codex", "cooling": False})

    def test_check_cooling_reports_reset(self) -> None:
        reset = self.future(DAY).replace(microsecond=0)
        self.seed("codex", reset)
        result = self.run_cli("check", "codex")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["reset_at"], cooldowns.to_iso(reset))

    def test_clear(self) -> None:
        self.seed("codex", self.future(DAY))
        self.assertEqual(json.loads(self.run_cli("clear", "codex").stdout), {"cleared": True})
        self.assertEqual(json.loads(self.run_cli("clear", "codex").stdout), {"cleared": False})
        self.assertEqual(self.run_cli("check", "codex").returncode, 0)

    def test_list_hides_expired_unless_all(self) -> None:
        self.seed("live", self.future(DAY))
        cooldowns.record("old", NOW, "error", "seed", "x", path=self.path, now=NOW - DAY)
        shown = json.loads(self.run_cli("list").stdout)
        self.assertEqual([row["name"] for row in shown["cooling"]], ["live"])
        self.assertIn("now", shown)
        everything = json.loads(self.run_cli("list", "--all").stdout)
        self.assertEqual([row["name"] for row in everything["cooling"]], ["live", "old"])

    def test_detect_prints_detection(self) -> None:
        result = self.run_cli("detect", "--agent", "codex", "--exit-code", "1", stdin="You exceeded your current quota")
        printed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(printed["limited"])
        self.assertTrue(printed["needs_date"])
        self.assertEqual(printed["provider"], "openai")
        self.assertFalse(self.path.exists())

    def test_detect_negative(self) -> None:
        result = self.run_cli("detect", "--agent", "codex", stdin="all good")
        self.assertEqual(json.loads(result.stdout), {"limited": False})

    def test_detect_record_known_date(self) -> None:
        result = self.run_cli(
            "detect", "--agent", "codex", "--record", "--by", "hook", stdin="insufficient_quota. Try again in 3 days",
        )
        printed = json.loads(result.stdout)
        self.assertFalse(printed["needs_date"])
        self.assertTrue(printed["recorded"])
        stored = cooldowns.load(self.path)["agents"]["codex"]
        self.assertEqual(stored["set_by"], "hook")
        self.assertEqual(stored["source"], "error")

    def test_detect_record_unknown_date_is_provisional(self) -> None:
        printed = json.loads(self.run_cli("detect", "--agent", "grok", "--record", stdin="credits exhausted").stdout)
        self.assertTrue(printed["needs_date"])
        self.assertTrue(cooldowns.load(self.path)["agents"]["grok"]["needs_date"])

    def test_detect_record_skips_transient(self) -> None:
        printed = json.loads(
            self.run_cli("detect", "--agent", "grok", "--record", stdin="429 rate limit exceeded retry after 20 seconds").stdout,
        )
        self.assertTrue(printed["transient"])
        self.assertFalse(printed["recorded"])
        self.assertFalse(self.path.exists())

    def test_expire_command(self) -> None:
        cooldowns.record("old", NOW, "error", "seed", "x", path=self.path, now=NOW - DAY)
        self.seed("live", self.future(DAY))
        self.assertEqual(json.loads(self.run_cli("expire").stdout), {"expired": ["old"]})

    def test_session_note_silent_when_nothing(self) -> None:
        result = self.run_cli("session-note")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_session_note_lists_active_cooldowns(self) -> None:
        self.seed("codex", self.future(DAY), reason="weekly quota")
        out = self.run_cli("session-note").stdout
        self.assertIn("dts2: cooling down, do not call: codex until ", out)
        self.assertIn("UTC", out)
        self.assertIn("(weekly quota)", out)
        self.assertNotIn("date unconfirmed", out)

    def test_session_note_flags_unconfirmed_date(self) -> None:
        self.seed("grok", NOW, needs_date=True)
        cooldowns.record("grok", None, "error", "seed", "credits", path=self.path, now=datetime.now(timezone.utc))
        self.assertIn("; date unconfirmed, ask the user", self.run_cli("session-note").stdout)

    def test_session_note_reenabled_line_after_expiry(self) -> None:
        cooldowns.record("codex", NOW, "error", "seed", "x", path=self.path, now=NOW - DAY)
        self.seed("grok", self.future(DAY))
        lines = self.run_cli("session-note").stdout.splitlines()
        self.assertEqual(lines[0], "dts2: re-enabled codex (cooldown ended).")
        self.assertIn("grok", lines[1])
        self.assertEqual(self.run_cli("session-note").stdout.splitlines()[0][:23], "dts2: cooling down, do ")

    def test_session_note_never_raises_on_corrupt_file(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("garbage")
        result = self.run_cli("session-note")
        self.assertEqual((result.returncode, result.stdout), (0, ""))


class ContractTests(unittest.TestCase):
    def test_script_has_no_harness_dir_literal(self) -> None:
        self.assertNotIn("." + "harness", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
