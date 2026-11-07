"""PR #76 review fixes: collision-safe knowledge lesson ids; knowledge cap applied after the status filter."""
from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import incidents_detect as detect  # noqa: E402
import incidents_lessons as learn  # noqa: E402

NOW: Final[int] = 1_800_000_000


def fake_store(keys: list[str]) -> tuple[Path, dict[str, str]]:
    """A home folder with a fake knowledge.py listing one learning per key; returns (home, env)."""
    home: Path = make_tmp_home()
    rows = [{"key": key, "value": f"Rule for {key}", "kind": "learning", "tags": []} for key in keys]
    fake: Path = home / "knowledge.py"
    fake.write_text(f"import json\nprint(json.dumps({rows!r}))\n", encoding="utf-8")
    return home, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf", "DTS2_HOME": str(home)}


def ids_of(lines: list[str]) -> list[str]:
    return [learn.line_id(line) for line in lines]


class KnowledgeIdCollisionTests(unittest.TestCase):
    KEYS: Final[list[str]] = ["incident-alpha-app-l-001", "incident-alpha-app-l-002"]

    def test_long_keys_get_distinct_ids(self) -> None:
        _, env = fake_store(self.KEYS)
        with unittest.mock.patch.dict(os.environ, env):
            ids = ids_of(learn.knowledge_lines("builder src/x.py"))
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_ids_are_stable_and_parse_as_verdicts(self) -> None:
        _, env = fake_store(self.KEYS)
        with unittest.mock.patch.dict(os.environ, env):
            first = ids_of(learn.knowledge_lines("builder src/x.py"))
            second = ids_of(learn.knowledge_lines("builder src/x.py"))
        self.assertEqual(first, second)
        parsed = detect.parse_lessons_line("Lessons: " + ", ".join(f"{i} helpful" for i in first))
        self.assertEqual(set(parsed), set(first))

    def test_both_lessons_are_selected(self) -> None:
        home, env = fake_store(self.KEYS)
        with unittest.mock.patch.dict(os.environ, env):
            chosen = learn.select(home, "builder", ["src/x.py"], 5, NOW, "builder src/x.py")
        self.assertEqual(len(chosen), 2)
        self.assertEqual(len({c["id"] for c in chosen}), 2)

    def test_short_key_is_unchanged(self) -> None:
        _, env = fake_store(["incident-h-004", "abcdefghijklmnop"])
        with unittest.mock.patch.dict(os.environ, env):
            ids = ids_of(learn.knowledge_lines("builder src/x.py"))
        self.assertEqual(ids, ["K-incidenth004", "K-abcdefghijklmnop"])


class KnowledgeCapTests(unittest.TestCase):
    def test_demoted_entries_do_not_block_an_active_one(self) -> None:
        home, env = fake_store(["k1", "k2", "k3", "k4"])
        with unittest.mock.patch.dict(os.environ, env):
            def demote(table: dict) -> None:
                for lid in ("K-k1", "K-k2", "K-k3"):
                    learn.record_verdict(table, lid, "not-helpful", NOW)
                    learn.record_verdict(table, lid, "not-helpful", NOW)
            learn.sidecar_for(learn.TIER_KNOWLEDGE, home).update(demote)
            chosen = learn.select(home, "builder", ["src/x.py"], 5, NOW, "builder src/x.py")
        self.assertEqual([c["id"] for c in chosen], ["K-k4"])

    def test_cap_still_limits_active_knowledge(self) -> None:
        home, env = fake_store([f"k{i}" for i in range(6)])
        with unittest.mock.patch.dict(os.environ, env):
            chosen = learn.select(home, "builder", ["src/x.py"], 10, NOW, "builder src/x.py")
        self.assertEqual(len(chosen), learn.KNOWLEDGE_MAX_LINES)


if __name__ == "__main__":
    unittest.main()
