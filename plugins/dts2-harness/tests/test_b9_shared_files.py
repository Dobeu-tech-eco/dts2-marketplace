"""G-25: `lanes.shared_files` in .harness/config.yaml routes those paths to the integration lane (same code as the B6 routing)."""
from __future__ import annotations

import unittest

from test_b9_merge_flow import Base, lane


class SharedFilesTests(Base):
    def test_shared_files_config_routes_to_integration_lane(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "config/app.json", "docs/a.md"]), lane("b", ["src/b/y.py", "config/app.json"])]
        blocked = self.run_cmd("check", self.manifest(lanes))
        self.assertFalse(blocked["ok"])
        self.config("lanes:\n  shared_files: config/app.json, docs/*.md   # owned by the integration lane\n")
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertTrue(result["ok"], result)
        self.assertEqual(sorted(result["integration"]["files"]), ["config/app.json", "docs/a.md"])
        self.assertEqual(result["integration"]["routed"]["a"][0]["kind"], "shared")

    def test_shared_files_pattern_does_not_widen_to_other_paths(self) -> None:
        self.config("lanes:\n  shared_files: config/app.json\n")
        lanes = [lane("a", ["src/a/x.py", "other/config/app.json"]), lane("b", ["src/b/y.py", "other/config/app.json"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertFalse(result["ok"])



if __name__ == "__main__":
    unittest.main()
