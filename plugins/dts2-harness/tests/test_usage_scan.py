from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from helpers import make_tmp_home, run_script


def record(name: str, inp: dict[str, Any], days_ago: int = 1) -> str:
    ts: str = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    block = {"type": "tool_use", "name": name, "input": inp}
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [block]}})


def write_session(home: Path, lines: list[str]) -> None:
    proj: Path = home / "projects" / "p1"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n")


class UsageScanTest(unittest.TestCase):
    def test_counts_skill_agent_mcp(self) -> None:
        home = make_tmp_home()
        write_session(home, [
            record("Skill", {"skill": "dts2-harness:run"}),
            record("Skill", {"skill": "dts2-harness:run"}),
            record("Agent", {"subagent_type": "dts2-harness:lead"}),
            record("mcp__Linear__x", {}),
        ])
        out = run_script("usage-scan.py", "--claude-home", str(home))
        self.assertEqual(out["plugins"], {"dts2-harness": 3, "Linear": 1})
        self.assertEqual(out["skills"], {"dts2-harness:run": 2})
        self.assertEqual(out["agents"], {"dts2-harness:lead": 1})
        self.assertEqual(out["mcp"], {"Linear": 1})

    def test_skips_malformed_and_old(self) -> None:
        home = make_tmp_home()
        write_session(home, ["not json {", record("Skill", {"skill": "old:x"}, days_ago=90)])
        out = run_script("usage-scan.py", "--claude-home", str(home))
        self.assertEqual(out["linesSkipped"], 1)
        self.assertEqual(out["skills"], {})


if __name__ == "__main__":
    unittest.main()
