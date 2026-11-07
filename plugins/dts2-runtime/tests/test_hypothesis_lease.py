"""Property tests for lease epochs in lanes.py, driven as a subprocess against a model of the epoch rules.

Skipped unless hypothesis is importable (pip install -r requirements-dev.txt)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_HYPOTHESIS = False

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
STAMP: Final[str] = "20261104-2"
MAX_EXAMPLES: Final[int] = 25


def make_repo() -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="dts2-hyp-lease-"))
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "m.json"
    manifest.write_text(json.dumps({"stamp": STAMP, "base": "abc", "scope": "single", "lanes": [
        {"id": "a", "item": "Sa", "files": ["src/a.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}),
        encoding="utf-8")
    return repo, manifest, repo / ".harness" / "runs" / STAMP / "a" / "lease.json"


def call(repo: Path, *args: str) -> dict[str, Any]:
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(repo), "--no-prs", *args],
                          capture_output=True, text=True, check=False)
    parsed: dict[str, Any] = json.loads(done.stdout)
    return parsed


if HAVE_HYPOTHESIS:
    # ("lease" | "release", epoch argument or None)
    OPS = st.lists(st.tuples(st.sampled_from(["lease", "release"]), st.one_of(st.none(), st.integers(0, 6))),
                   min_size=1, max_size=8)


if HAVE_HYPOTHESIS:
    class LeaseEpochProperties(unittest.TestCase):
        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(OPS)
        def test_epoch_follows_the_model_and_never_regresses(self, ops: list[tuple[str, int | None]]) -> None:
            repo, manifest, lease_file = make_repo()
            stored = 0
            for kind, given_epoch in ops:
                before = lease_file.read_bytes() if lease_file.exists() else None
                extra = [] if given_epoch is None else ["--epoch", str(given_epoch)]
                if kind == "lease":
                    result = call(repo, "lease", str(manifest), "--lane", "a", *extra)
                elif stored == 0:
                    continue  # releasing a lane that was never leased is an error path, not an epoch rule
                else:
                    result = call(repo, "release", STAMP, "--lane", "a", *extra)
                stale = given_epoch is not None and given_epoch < stored
                self.assertEqual(result["ok"], not stale, (kind, given_epoch, stored, result))
                if stale:
                    self.assertEqual(lease_file.read_bytes(), before)
                elif kind == "lease":
                    stored += 1
                    self.assertEqual(result["epoch"], stored)
                record = json.loads(lease_file.read_text(encoding="utf-8"))
                self.assertEqual(record["epoch"], stored)

        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(st.integers(1, 5))
        def test_n_plain_leases_end_at_epoch_n(self, count: int) -> None:
            repo, manifest, lease_file = make_repo()
            epochs = [call(repo, "lease", str(manifest), "--lane", "a")["epoch"] for _ in range(count)]
            self.assertEqual(epochs, list(range(1, count + 1)))
            self.assertEqual(json.loads(lease_file.read_text(encoding="utf-8"))["epoch"], count)

else:

    @unittest.skip("hypothesis is not installed; see requirements-dev.txt")
    class LeaseEpochProperties(unittest.TestCase):
        def test_requires_hypothesis(self) -> None:
            pass


if __name__ == "__main__":
    unittest.main()
