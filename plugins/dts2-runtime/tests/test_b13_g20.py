"""G-20: `lease` and `plan` fail closed when gh is missing or cannot answer; gh is retried a bounded number of times."""
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

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.gitrefs import GH_TRIES, gh_json  # noqa: E402

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-3"
# Counts its calls in $FAKE_COUNT; fails (exit 1) until the call number reaches $FAKE_OK_AT, then prints $FAKE_PRS.
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os, sys
path = os.environ["FAKE_COUNT"]
n = int(open(path).read() or "0") + 1 if os.path.exists(path) else 1
open(path, "w").write(str(n))
if n < int(os.environ.get("FAKE_OK_AT", "1")):
    sys.exit(1)
print(os.environ.get("FAKE_PRS", "[]"))
"""


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-g20-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.gh = self.root / "gh.py"
        self.gh.write_text(FAKE_GH, encoding="utf-8")
        self.count = self.root / "count"
        manifest = {"stamp": STAMP, "base": "abc", "scope": "single",
                    "lanes": [{"id": "a", "item": "Sa", "files": ["src/a/x.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}
        self.manifest = self.root / "m.json"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        self.draft = self.root / "draft.json"
        self.draft.write_text(json.dumps(manifest), encoding="utf-8")
        self.checkin = self.root / "checkin.json"
        self.checkin.write_text(json.dumps({"outstanding_items": ["Sa"]}), encoding="utf-8")

    def cli(self, *args: str, gh: str | None = None, ok_at: int = 1) -> tuple[int, dict[str, Any], str]:
        env = {**os.environ, "DTS2_GH_BIN": gh or str(self.gh), "FAKE_COUNT": str(self.count), "FAKE_OK_AT": str(ok_at)}
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, env=env, check=False)
        return done.returncode, json.loads(done.stdout), done.stderr

    def calls(self) -> int:
        return int(self.count.read_text(encoding="utf-8")) if self.count.exists() else 0


class GhJsonTests(Base):
    def env(self, ok_at: int) -> None:
        for key, value in (("DTS2_GH_BIN", str(self.gh)), ("FAKE_COUNT", str(self.count)), ("FAKE_OK_AT", str(ok_at))):
            self.addCleanup(os.environ.pop, key, None)
            os.environ[key] = value

    def test_a_flaky_gh_gets_a_second_chance(self) -> None:
        self.env(ok_at=2)
        waits: list[float] = []
        data, why = gh_json(["pr", "list"], self.repo, sleep=waits.append)
        self.assertEqual((data, why, self.calls(), len(waits)), ([], None, 2, 1))

    def test_retries_are_bounded(self) -> None:
        self.env(ok_at=99)
        data, why = gh_json(["pr", "list"], self.repo, sleep=lambda _s: None)
        self.assertIsNone(data)
        self.assertEqual(self.calls(), GH_TRIES)
        self.assertIn("exited 1", why or "")

    def test_a_missing_gh_is_not_retried(self) -> None:
        for key, value in (("DTS2_GH_BIN", str(self.root / "no-such-gh")), ("FAKE_COUNT", str(self.count))):
            self.addCleanup(os.environ.pop, key, None)
            os.environ[key] = value
        data, why = gh_json(["pr", "list"], self.repo, sleep=lambda _s: self.fail("slept"))
        self.assertIsNone(data)
        self.assertIn("not installed", why or "")

    def test_output_that_is_not_json_is_a_failure(self) -> None:
        self.env(ok_at=1)
        os.environ["FAKE_PRS"] = "not json"
        self.addCleanup(os.environ.pop, "FAKE_PRS", None)
        data, why = gh_json(["pr", "list"], self.repo, sleep=lambda _s: None)
        self.assertEqual((data, why, self.calls()), (None, "gh printed output that is not JSON", GH_TRIES))


class FailClosedTests(Base):
    def test_lease_refuses_without_gh_and_writes_nothing(self) -> None:
        code, out, _err = self.cli("lease", str(self.manifest), "--lane", "a", gh=str(self.root / "no-such-gh"))
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertIn("fails closed", out["detail"])
        self.assertFalse((self.repo / ".harness" / "runs" / STAMP / "a" / "lease.json").exists())

    def test_lease_refuses_when_gh_keeps_failing_after_its_retries(self) -> None:
        code, out, _err = self.cli("lease", str(self.manifest), "--lane", "a", ok_at=99)
        self.assertEqual((code, out["ok"]), (2, False))
        self.assertEqual(self.calls(), GH_TRIES)

    def test_lease_succeeds_when_gh_answers_on_a_retry(self) -> None:
        code, out, _err = self.cli("lease", str(self.manifest), "--lane", "a", ok_at=2)
        self.assertEqual((code, out["ok"], self.calls()), (0, True, 2))

    def test_no_prs_flag_skips_the_check_on_purpose(self) -> None:
        code, out, _err = self.cli("--no-prs", "lease", str(self.manifest), "--lane", "a", gh=str(self.root / "no-such-gh"))
        self.assertEqual((code, out["ok"]), (0, True))

    def test_plan_fails_closed_without_gh(self) -> None:
        code, out, _err = self.cli("plan", "--from-checkin", str(self.checkin), "--draft", str(self.draft),
                                   gh=str(self.root / "no-such-gh"))
        self.assertEqual((code, out["ok"]), (2, False))
        self.assertIn("plan fails closed", out["detail"])
        self.assertFalse(out["feasibility"]["prs_checked"])

    def test_plan_passes_with_gh(self) -> None:
        code, out, _err = self.cli("plan", "--from-checkin", str(self.checkin), "--draft", str(self.draft))
        self.assertEqual((code, out["ok"]), (0, True))

    def test_check_stays_advisory_without_gh(self) -> None:
        code, out, _err = self.cli("check", str(self.manifest), gh=str(self.root / "no-such-gh"))
        self.assertEqual((code, out["ok"], out["prs_checked"]), (0, True, False))


if __name__ == "__main__":
    unittest.main()
