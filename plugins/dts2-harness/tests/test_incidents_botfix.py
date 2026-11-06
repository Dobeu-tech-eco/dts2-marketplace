"""PR #73 review fixes: capture flag on the hook path, namespaced knowledge keys, K- verdict ids, knowledge search semantics."""
from __future__ import annotations

import os
import re
import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_events  # noqa: E402
import incidents  # noqa: E402
import incidents_detect as detect  # noqa: E402
import incidents_lessons as learn  # noqa: E402
import state_io  # noqa: E402

NOW: Final[int] = 1_800_000_000


def make_repo(name: str | None = None) -> Path:
    base: Path = make_tmp_home()
    repo: Path = base / name if name else base
    (repo / ".harness").mkdir(parents=True)
    return repo


def incident_rows(repo: Path) -> list[dict[str, Any]]:
    return [r for r in incidents.state_of(repo).read_rows(state_io.AGENTS_REL) if r.get("kind") == incidents.KIND_INCIDENT]


class CaptureFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = make_repo()

    def test_disabled_capture_writes_nothing_and_skips_cooldown(self) -> None:
        payload = {"session_id": "s1", "error": "rate_limit", "error_details": "usage limit reached, try again later"}
        with unittest.mock.patch.object(incidents, "settings", return_value={"incident_capture": False}), \
                unittest.mock.patch("cooldowns.record_detection") as record:
            agent_events.record_incident(self.repo, "stop-failure", payload)
            agent_events.record_incident(self.repo, "permission-denied", {"session_id": "s1", "tool_name": "Bash", "reason": "no"})
        self.assertEqual(incident_rows(self.repo), [])
        record.assert_not_called()

    def test_enabled_capture_still_writes(self) -> None:
        with unittest.mock.patch.object(incidents, "settings", return_value={"incident_capture": True}):
            agent_events.record_incident(self.repo, "permission-denied", {"session_id": "s1", "tool_name": "Bash", "reason": "no"})
        self.assertEqual([r["category"] for r in incident_rows(self.repo)], ["permission-denied"])


class KnowledgeKeyTests(unittest.TestCase):
    def promote(self, repo: Path, home: Path) -> str:
        (repo / ".harness" / "lessons.md").write_text("# Lessons\n\n- [L-001] Rule one.\n", encoding="utf-8")
        log = home / "args.txt"
        fake = home / "knowledge.py"
        fake.write_text(f"import sys\nopen({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf", "DTS2_HOME": str(home)}):
            got = learn.promote_knowledge(repo, "L-001", None)
        self.assertTrue(got["ok"])
        return str(got["key"])

    def test_project_lesson_ids_do_not_collide_across_projects(self) -> None:
        home = make_tmp_home()
        first = self.promote(make_repo("alpha-app"), home)
        second = self.promote(make_repo("beta-app"), home)
        self.assertNotEqual(first, second)
        self.assertEqual(first, "incident-alpha-app-l-001")
        self.assertRegex(second, r"^incident-beta-app-l-001$")

    def test_home_tier_ids_stay_unnamespaced(self) -> None:
        home = make_tmp_home()
        repo = make_repo("alpha-app")
        (home / "lessons.md").write_text("# Lessons\n- [H-004] Harness rule.\n", encoding="utf-8")
        fake = home / "knowledge.py"
        fake.write_text("pass\n", encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf", "DTS2_HOME": str(home)}):
            got = learn.promote_knowledge(repo, "H-004", None)
        self.assertEqual(got["key"], "incident-h-004")


class KnowledgeIdVerdictTests(unittest.TestCase):
    def test_k_ids_keep_case_and_parse(self) -> None:
        text = "Lessons: L-012 helpful, K-incidentl001 not-helpful, K-abc unused\n"
        self.assertEqual(detect.parse_lessons_line(text),
                         {"L-012": "helpful", "K-incidentl001": "not-helpful", "K-abc": "unused"})

    def test_feed_back_scores_injected_k_id(self) -> None:
        repo = make_repo()
        seen: list[tuple[str, str]] = []
        row = {"kind": incidents.KIND_INJECTION, "agent_id": "a1", "lesson_id": "K-incidentl001", "tier": 4}
        with unittest.mock.patch.object(incidents, "state_of") as state, unittest.mock.patch.object(incidents.learn, "sidecar_for") as sidecar:
            state.return_value.events.return_value = [row]
            sidecar.return_value.update.side_effect = lambda fn: seen.append(
                (fn.keywords["lesson_id"], fn.keywords["verdict"]))
            incidents.feed_back(repo, "a1", "Lessons: K-incidentl001 helpful", NOW)
        self.assertEqual(seen, [("K-incidentl001", "helpful")])


class KnowledgeSearchTests(unittest.TestCase):
    FAKE: Final[str] = (
        "import json, sys\n"
        "rows = [{'key': 'a1', 'value': 'Retry on 429 {paths: src/api/**}', 'kind': 'learning', 'tags': ['incident']},\n"
        "        {'key': 'b2', 'value': 'Docs only {paths: docs/**}', 'kind': 'learning', 'tags': ['incident']},\n"
        "        {'key': 'c3', 'value': 'Reviewer only {agents: reviewer}', 'kind': 'learning', 'tags': []},\n"
        "        {'key': 'd4', 'value': 'Global rule', 'kind': 'learning', 'tags': []}]\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'find':\n"
        "    needle = args[1].lower()\n"
        "    rows = [r for r in rows if needle in (r['key'] + r['value'] + ' '.join(r['tags'])).lower()]\n"
        "print(json.dumps(rows))\n")

    def test_multi_token_query_is_not_a_literal_substring(self) -> None:
        home = make_tmp_home()
        fake = home / "knowledge.py"
        fake.write_text(self.FAKE, encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf"}):
            lines = learn.knowledge_lines("builder src/api/client.py")
        ids = [re.match(r"- \[(K-\w+)\]", line).group(1) for line in lines]  # type: ignore[union-attr]
        self.assertEqual(ids, ["K-a1", "K-d4"])

    def test_cap_of_three(self) -> None:
        home = make_tmp_home()
        fake = home / "knowledge.py"
        rows = [{"key": f"k{i}", "value": f"Rule {i}", "kind": "learning", "tags": []} for i in range(6)]
        fake.write_text(f"import json\nprint(json.dumps({rows!r}))\n", encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_SCRIPT": str(fake), "DTS2_KNOWLEDGE": "cf"}):
            self.assertEqual(len(learn.knowledge_lines("builder src/x.py")), 3)


if __name__ == "__main__":
    unittest.main()
