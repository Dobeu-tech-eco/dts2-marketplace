"""B1 (son): son mode has its own brief of about 4 KB, built from a template by scripts/briefs.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import briefs  # noqa: E402

TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "son-brief.md"
BRIEFS: Final[Path] = PLUGIN_ROOT / "scripts" / "briefs.py"
MANIFEST: Final[dict[str, Any]] = {
    "stamp": "20261105-1", "base": "abc1234", "scope": "single",
    "lanes": [{"id": "a", "item": "S1", "files": ["src/b.py", "src/a.py"], "ids": {}, "depends_on": ["z"], "tier": "standard"}],
}


class SonBriefTests(unittest.TestCase):
    def test_template_is_about_four_kilobytes(self) -> None:
        size: int = len(TEMPLATE.read_bytes())
        self.assertTrue(3000 <= size <= 4600, size)

    def test_brief_carries_the_lane_fields(self) -> None:
        text: str = briefs.son_brief(MANIFEST, "a", 3)
        self.assertNotIn("{{", text)
        for needle in ("20261105-1", "lane-a", "dts2/20261105-1/lane-a", "epoch: 3", "src/a.py", "src/b.py", "MAX_BUNDLE: 5",
                       "S1", "abc1234", "pr-open", "questions/", "report.md"):
            self.assertIn(needle, text)
        self.assertLessEqual(text.index("src/a.py"), text.index("src/b.py"))

    def test_brief_stays_near_four_kilobytes(self) -> None:
        self.assertLessEqual(len(briefs.son_brief(MANIFEST, "a", 3).encode()), 4800)

    def test_unknown_lane_is_an_error(self) -> None:
        with self.assertRaises(briefs.BriefError):
            briefs.son_brief(MANIFEST, "zz", 1)

    def test_cli_writes_brief_md(self) -> None:
        root: Path = Path(tempfile.mkdtemp(prefix="dts2-brief-"))
        manifest: Path = root / "lanes.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        out: Path = root / "brief.md"
        done = subprocess.run([sys.executable, "-I", str(BRIEFS), "son-brief", str(manifest), "--lane", "a", "--epoch", "2",
                               "--out", str(out)], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["bytes"], len(out.read_bytes()))
        self.assertIn("epoch: 2", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
