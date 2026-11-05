"""Batch 17 (G-43..G-51): the head/son mailbox, status schema v1, the son contract, scope policy and a son lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes import mailbox, policy  # noqa: E402
from lanes.leases import write_lease  # noqa: E402
from lanes.phases import transition  # noqa: E402
from lanes.records import read_json_object  # noqa: E402
from lanes.runstate import fold, read_status_files, sendback, stop_check  # noqa: E402
from lanes.supervisor import loop  # noqa: E402
from son_launch import SON_MARKER  # noqa: E402
from state_io import RUNS_REL  # noqa: E402

LANES: Final[Path] = SCRIPTS / "lanes.py"
AUTOPILOT: Final[Path] = PLUGIN_ROOT / "skills" / "autopilot" / "son-contract.md"
STAMP: Final[str] = "20261105-1"
OTHER_STAMP: Final[str] = "20261105-2"
GIT_ENV: Final[dict[str, str]] = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                                  "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
FAKE_SON: Final[str] = '''#!/usr/bin/env python3
"""A fake `claude -p` son: does what a real son does through lanes.py, step by step."""
import json, os, subprocess, sys
e = os.environ
def lanes(*a):
    done = subprocess.run([sys.executable, "-I", e["FAKE_LANES"], "--cwd", e["FAKE_CWD"], *a], capture_output=True, text=True)
    return json.loads(done.stdout)
def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
stamp, lane, epoch, step = e["FAKE_STAMP"], e["FAKE_LANE"], e["FAKE_EPOCH"], e["FAKE_STEP"]
out = {}
if step == "start":
    out["rules"] = lanes("mailbox", "rules", stamp, "--lane", lane, "--point", "start")
    os.makedirs("src", exist_ok=True)
    open(f"src/{lane}.py", "w").write("x = 1\\n")
    git("add", "."); git("commit", "-q", "-m", f"lane {lane}")
    out["ask"] = lanes("mailbox", "ask", stamp, "--lane", lane, "--text", "which database?", "--epoch", epoch)
    out["beat"] = lanes("heartbeat", stamp, "--lane", lane, "--status", "pr-open", "--epoch", epoch)
    out["self_grant"] = lanes("merge-go-step", stamp, "--step", "1", "--head", git("rev-parse", "HEAD"), "--base", "abcdef1")
elif step == "answer":
    out["answer"] = lanes("mailbox", "check", stamp, "--lane", lane, "--id", "q1")
elif step == "merge":
    out["check"] = lanes("mailbox", "merge-go-check", stamp, "--lane", lane)
elif step == "late-commit":
    open(f"src/{lane}.py", "a").write("y = 2\\n")
    git("add", "."); git("commit", "-q", "-m", "after the grant")
    out["check"] = lanes("mailbox", "merge-go-check", stamp, "--lane", lane)
print(json.dumps(out))
'''


def lane_entry(lane_id: str, files: list[str], depends_on: list[str] | None = None) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {"D": []}, "depends_on": depends_on or [], "tier": "standard"}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **GIT_ENV}, check=True)
    return done.stdout.strip()


class MailboxCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-b17-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.runs = self.repo / RUNS_REL
        (self.runs / STAMP).mkdir(parents=True)

    def lane_dir(self, lane_id: str, stamp: str = STAMP) -> Path:
        folder = self.runs / stamp / lane_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def lease(self, lane_id: str, epoch_bumps: int = 1, item: str | None = None) -> None:
        path = self.lane_dir(lane_id) / "lease.json"
        for _ in range(epoch_bumps):
            write_lease({"stamp": STAMP, "base": "abc"}, {"id": lane_id, "item": item or f"S{lane_id}", "files": []}, path, None, 3600)

    def write_status(self, lane_id: str, **fields: Any) -> Path:
        path = self.lane_dir(lane_id) / "status.json"
        path.write_text(json.dumps({"lane": lane_id, **fields}), encoding="utf-8")
        return path

    def settings(self, **keys: str) -> None:
        path = self.repo / ".claude" / "dts2-harness.local.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in keys.items()) + "---\n", encoding="utf-8")


class StatusSchemaTests(MailboxCase):
    def test_transition_stamps_version_and_epoch(self) -> None:
        self.lease("a", epoch_bumps=2)
        done = transition(self.runs, STAMP, "a", "pr-open", actor="son")
        self.assertTrue(done["ok"], done)
        saved = read_json_object(self.runs / STAMP / "a" / "status.json")
        self.assertEqual((saved["v"], saved["epoch"], saved["status"]), (1, 2, "pr-open"))

    def test_stale_epoch_write_is_ignored(self) -> None:
        self.lease("a", epoch_bumps=3)
        transition(self.runs, STAMP, "a", "pr-open", actor="son", epoch=3)
        stale = transition(self.runs, STAMP, "a", "blocked", actor="son", epoch=1)
        self.assertFalse(stale["ok"])
        self.assertTrue(stale["stale"])
        self.assertEqual(read_json_object(self.runs / STAMP / "a" / "status.json")["status"], "pr-open")

    def test_truncated_status_reports_incomplete_status_unreadable(self) -> None:
        path = self.lane_dir("a") / "status.json"
        path.write_text('{"lane": "a", "status": "pr-o', encoding="utf-8")
        rows = dict((p.parent.name, d) for p, d in read_status_files(self.runs, STAMP))
        self.assertEqual((rows["a"]["status"], rows["a"]["reason"]), ("incomplete", "status-unreadable"))

    def test_parked_and_stopped_map_to_incomplete_with_reason(self) -> None:
        self.write_status("a", status="parked")
        self.write_status("b", status="stopped", reason="user")
        self.write_status("c", status="done", v=9)
        rows = dict((p.parent.name, d) for p, d in read_status_files(self.runs, STAMP))
        self.assertEqual((rows["a"]["status"], rows["a"]["reason"]), ("incomplete", "parked"))
        self.assertEqual((rows["b"]["status"], rows["b"]["reason"]), ("incomplete", "user"))
        self.assertEqual((rows["c"]["status"], rows["c"]["reason"]), ("incomplete", "status-version"))

    def test_fold_reads_lease_files_and_rebuilds_checkpoints_from_git(self) -> None:
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "f.txt").write_text("1", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "base")
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "g.txt").write_text("2", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "checkpoint 1/2")
        for lane_id, owned in (("a", ["src/x.py"]), ("b", ["src/x.py"])):
            write_lease({"stamp": STAMP, "base": base}, {"id": lane_id, "files": owned}, self.lane_dir(lane_id) / "lease.json", None, 3600)
            self.write_status(lane_id, status="blocked", pr=int(ord(lane_id)), files=[f"other/{lane_id}.py"], worktree=str(self.repo))
        result = fold(self.runs, STAMP)
        self.assertEqual([g["lanes"] for g in result["groups"]], [["a"], ["b"]])  # the lease files overlap; status.json's do not
        self.assertEqual(result["groups"][0]["checkpoints"]["a"], [f"{git(self.repo, 'rev-parse', '--short', 'HEAD')} checkpoint 1/2"])


class MailboxMessageTests(MailboxCase):
    def test_question_answer_roundtrip_carries_ids_and_epoch(self) -> None:
        self.lease("a", epoch_bumps=2)
        asked = mailbox.ask(self.runs, STAMP, "a", "which database?", self.repo)
        self.assertEqual(asked["id"], "q1")
        message = json.loads(Path(asked["path"]).read_text(encoding="utf-8"))
        self.assertEqual((message["v"], message["epoch"], message["lane"]), (1, 2, "a"))
        self.assertEqual(mailbox.check(self.runs, STAMP, "a", "q1")["state"], "waiting")
        self.assertTrue(mailbox.answer(self.runs, STAMP, "a", "q1", "postgres")["ok"])
        reply = mailbox.check(self.runs, STAMP, "a", "q1")
        self.assertEqual((reply["state"], reply["text"]), ("answered", "postgres"))
        self.assertEqual(mailbox.ask(self.runs, STAMP, "a", "again", self.repo)["id"], "q2")
        self.assertEqual(mailbox.ask(self.runs, STAMP, "a", "which?", self.repo, kind="need-human")["id"], "h1")

    def test_answer_for_an_older_epoch_is_ignored(self) -> None:
        self.lease("a")
        mailbox.ask(self.runs, STAMP, "a", "q", self.repo)
        mailbox.answer(self.runs, STAMP, "a", "q1", "late")
        self.lease("a", epoch_bumps=1)  # the lane was re-leased: epoch 2 now
        self.assertEqual(mailbox.check(self.runs, STAMP, "a", "q1")["state"], "waiting")

    def test_wait_expiry_parks_the_lane_incomplete(self) -> None:
        self.settings(mailbox_wait_min="2")
        self.lease("a")
        asked = mailbox.ask(self.runs, STAMP, "a", "q", self.repo, now=1000)
        self.assertEqual(asked["deadline"], 1000 + 2 * 60)
        self.assertEqual(mailbox.check(self.runs, STAMP, "a", "q1", now=1100)["state"], "waiting")
        expired = mailbox.check(self.runs, STAMP, "a", "q1", now=1121)
        self.assertEqual((expired["state"], expired["parked"]), ("expired", True))
        saved = read_json_object(self.runs / STAMP / "a" / "status.json")
        self.assertEqual((saved["status"], saved["reason"], saved["waiting_on"]), ("incomplete", "mailbox-timeout", "q1"))

    def test_default_wait_is_a_constant_and_a_bad_setting_falls_back(self) -> None:
        self.assertEqual(mailbox.wait_seconds(self.repo), 30 * 60)
        self.settings(mailbox_wait_min="soon")
        self.assertEqual(mailbox.wait_seconds(self.repo), 30 * 60)

    def test_a_son_cannot_answer_its_own_question(self) -> None:
        self.lease("a")
        mailbox.ask(self.runs, STAMP, "a", "q", self.repo)
        with mock.patch.dict(os.environ, {SON_MARKER: "1"}):
            self.assertFalse(mailbox.answer(self.runs, STAMP, "a", "q1", "yes")["ok"])

    def test_sendback_carries_number_and_epoch(self) -> None:
        self.lease("a", epoch_bumps=2)
        first = sendback(self.runs, STAMP, "a", "fix the test")
        second = sendback(self.runs, STAMP, "a", "again")
        self.assertEqual((first["n"], first["epoch"], second["n"]), (1, 2, 2))
        body = json.loads((self.runs / STAMP / "a" / "send-back-2.json").read_text(encoding="utf-8"))
        self.assertEqual((body["kind"], body["n"], body["epoch"]), ("send-back", 2, 2))
        self.assertFalse(sendback(self.runs, STAMP, "a", "third")["ok"])

    def test_park_reasons_include_seat_pool_context_guard_and_no_browser(self) -> None:
        self.lease("a")
        parked = mailbox.park(self.runs, STAMP, "a", "context-guard", "sess-9")
        self.assertTrue(parked["ok"], parked)
        saved = read_json_object(self.runs / STAMP / "a" / "status.json")
        self.assertEqual((saved["status"], saved["reason"], saved["session_id"]), ("incomplete", "context-guard", "sess-9"))
        self.assertIn("seat-pool-collapse", mailbox.PARK_REASONS)
        self.assertIn("no-browser", mailbox.PARK_REASONS)
        with self.assertRaises(Exception):
            mailbox.park(self.runs, STAMP, "a", "whim")

    def test_out_of_lane_request_climbs_one_rung_at_a_time(self) -> None:
        self.lease("a")
        made = mailbox.request_out_of_lane(self.runs, STAMP, "a", ["shared/x.py"], "needs the helper")
        stages = [made["stage"]]
        for _ in range(3):
            stages.append(mailbox.advance_request(self.runs, STAMP, "a", "r1", "escalate").get("stage"))
        self.assertEqual(stages, ["head", "vote", "council", "user"])
        self.assertFalse(mailbox.advance_request(self.runs, STAMP, "a", "r1", "escalate")["ok"])  # the user is the last rung
        self.assertTrue(mailbox.advance_request(self.runs, STAMP, "a", "r1", "granted")["ok"])
        self.assertFalse(mailbox.advance_request(self.runs, STAMP, "a", "r1", "denied")["ok"])

    def test_rules_reread_reports_a_mid_run_change(self) -> None:
        plugin = self.root / "plugin"
        for rel in ("templates/discipline.md", "skills/run/a.md", "skills/ship/SKILL.md", "agents/verifier.md"):
            (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
            (plugin / rel).write_text("rule one\n", encoding="utf-8")
        started = mailbox.check_rules(self.runs, STAMP, "a", "start", plugin)
        self.assertEqual(len(started["changed"]), 4)
        self.assertEqual(mailbox.check_rules(self.runs, STAMP, "a", "vote", plugin)["changed"], [])
        (plugin / "agents" / "verifier.md").write_text("rule two\n", encoding="utf-8")
        (plugin / "skills" / "run" / "a.md").write_text("rule two\n", encoding="utf-8")
        before_ship = mailbox.check_rules(self.runs, STAMP, "a", "ship", plugin)
        self.assertEqual(before_ship["changed"], ["agents/verifier.md", "skills/run/a.md"])
        self.assertEqual(mailbox.check_rules(self.runs, STAMP, "a", "merge", plugin)["changed"], [])

    def test_agents_are_rule_sources(self) -> None:
        self.assertIn("agents/*.md", mailbox.RULE_SOURCES)
        names = mailbox.rules_digest()
        self.assertTrue(any(n.startswith("agents/") for n in names), names)
        self.assertIn("templates/discipline.md", names)


class StopCheckTests(MailboxCase):
    def ledger(self, prs: list[int]) -> None:
        rows = "".join(f"| {pr} | dts2/x/b | B1 | S1 x |\n" for pr in prs)
        (self.runs / STAMP / "task-ledger.md").write_text(f"# Task ledger\n\n| PR | branch | tasks | blocked by |\n| --- | --- | --- | --- |\n{rows}", encoding="utf-8")

    def checkin(self, outstanding: list[str]) -> Path:
        path = self.root / "ci.json"
        path.write_text(json.dumps({"outstanding_items": outstanding, "complete_items": []}), encoding="utf-8")
        return path

    def test_items_tied_to_a_ledgered_blocked_pr_do_not_keep_the_run_going(self) -> None:
        self.write_status("a", status="done", pr=1)
        self.write_status("b", status="blocked", pr=12, item="S1", tasks=["B1"], blocked_by=["A4"])
        self.ledger([12])
        waiting = ["A4 Secrets: STRIPE_KEY", "B1", "S1"]
        done = stop_check(self.runs, STAMP, self.checkin(waiting))
        self.assertTrue(done["stop"], done)
        self.assertEqual(done["excluded"], sorted(waiting))
        other = stop_check(self.runs, STAMP, self.checkin([*waiting, "section 3: ui shell"]))
        self.assertFalse(other["stop"])
        self.assertEqual(other["outstanding"], ["section 3: ui shell"])

    def test_a_blocked_pr_missing_from_the_ledger_ties_nothing(self) -> None:
        self.write_status("b", status="blocked", pr=12, item="S1", blocked_by=["A4"])
        self.ledger([99])
        done = stop_check(self.runs, STAMP, self.checkin(["A4 Secrets: STRIPE_KEY"]))
        self.assertFalse(done["stop"])
        self.assertEqual(done["blocked_without_ledger"], ["b"])

    def test_check_in_reads_the_end_state_from_the_fetched_base(self) -> None:
        origin = self.root / "origin.git"
        git(self.root, "init", "-q", "--bare", "-b", "dev", str(origin))
        git(self.repo, "init", "-q", "-b", "dev")
        git(self.repo, "remote", "add", "origin", str(origin))
        end_state = self.repo / ".harness" / "end-state.md"
        end_state.parent.mkdir(parents=True, exist_ok=True)
        end_state.write_text("# End state\n\n## Sections\n| # | section | serves component | files / area | depends on | complexity | status |\n"
                             "|---|---|---|---|---|---|---|\n| 1 | data model | api | db/ | - | normal | done |\n"
                             "| 2 | ui shell | web | web/ | 1 | normal | todo |\n", encoding="utf-8")
        git(self.repo, "add", "-f", ".harness/end-state.md")
        git(self.repo, "commit", "-q", "-m", "end state")
        git(self.repo, "push", "-q", "origin", "dev")
        end_state.write_text(end_state.read_text(encoding="utf-8").replace("| todo |", "| done |"), encoding="utf-8")  # a stale working copy
        env = {**os.environ, **GIT_ENV}
        with mock.patch.dict(os.environ, env):
            items, why = policy.base_outstanding(self.repo, "dev", {"A1 Secrets: KEY"})
        self.assertIsNone(why)
        self.assertEqual(items, {"section 2: ui shell", "A1 Secrets: KEY"})
        with mock.patch.dict(os.environ, env):
            missing, why = policy.base_outstanding(self.repo, "nope", set())
        self.assertEqual(missing, set())
        self.assertIn("cannot read", why or "")

    def test_fullauto_loop_parks_resumably_past_three(self) -> None:
        results = [loop(self.runs, STAMP, self.repo) for _ in range(4)]
        self.assertEqual([r["stop"] for r in results], [False, False, False, True])
        self.assertEqual((results[-1]["status"], results[-1]["reason"], results[-1]["max"]), ("incomplete", "loops", 3))
        self.assertTrue((self.runs / STAMP / "budget.json").is_file())  # the counter is kept: a later run resumes from it


class PolicyTests(MailboxCase):
    def plan_result(self, items: list[str]) -> dict[str, Any]:
        lanes = [lane_entry(i[1:], [f"src/{i}.py"]) for i in items]
        return {"ok": True, "stamp": STAMP, "manifest": {"stamp": STAMP, "lanes": lanes}}

    def test_ask_each_lane_applies_outside_autopilot_only(self) -> None:
        self.settings(dpp_full_ask_each_lane="true")
        asked = policy.apply_policy(self.plan_result(["Sa", "Sb"]), self.runs, self.repo, full=True, fullauto=False, autopilot=False)
        self.assertEqual(asked["needs_approval"], ["a", "b"])
        under = policy.apply_policy(self.plan_result(["Sa"]), self.runs, self.repo, full=True, fullauto=False, autopilot=True)
        self.assertNotIn("needs_approval", under)

    def test_freeze_scope_keeps_the_first_item_set_and_pends_the_rest(self) -> None:
        self.settings(fullauto_freeze_scope="true")
        first = policy.apply_policy(self.plan_result(["Sa", "Sb"]), self.runs, self.repo, full=True, fullauto=True, autopilot=True)
        self.assertEqual(first["pending"], [])
        again = policy.apply_policy(self.plan_result(["Sa", "Sc"]), self.runs, self.repo, full=True, fullauto=True, autopilot=True)
        self.assertEqual([lane["item"] for lane in again["manifest"]["lanes"]], ["Sa"])
        self.assertEqual(again["pending"], ["Sc"])
        self.assertEqual(again["scope_hash"], first["scope_hash"])
        self.assertEqual(policy.scope_hash(["Sb", "Sa"]), first["scope_hash"])
        off = policy.apply_policy(self.plan_result(["Sz"]), self.runs, self.root, full=True, fullauto=True, autopilot=True)
        self.assertNotIn("pending", off)

    def test_override_needs_the_human_channel_and_is_logged(self) -> None:
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Owner Name")
        with mock.patch.object(policy, "human_approved", return_value=False):
            self.assertFalse(policy.override("a", "needed", self.repo)["ok"])
        with mock.patch.object(policy, "human_approved", return_value=True) as approved:
            done = policy.override("a", "needed for the hotfix", self.repo)
        approved.assert_called_once_with("override", "a")
        self.assertTrue(done["ok"], done)
        log = (self.repo / ".harness" / "state.md").read_text(encoding="utf-8")
        self.assertIn("override lane a by Owner Name: needed for the hotfix", log)

    def test_override_is_never_open_to_a_vote_a_council_or_a_son(self) -> None:
        with mock.patch.object(policy, "human_approved", return_value=True):
            for env in ({"DTS2_ROLE": "vote"}, {"DTS2_ROLE": "council"}, {SON_MARKER: "1"}):
                with mock.patch.dict(os.environ, env):
                    self.assertFalse(policy.override("a", "why", self.repo)["ok"], env)
        self.assertFalse((self.repo / ".harness" / "state.md").exists())

    def test_without_the_approvals_module_nothing_is_approved(self) -> None:
        with mock.patch.dict(sys.modules, {"approvals": None}):
            self.assertFalse(policy.human_approved("override", "a"))


class LeaseHoldTests(MailboxCase):
    def test_lease_records_the_item_and_a_second_run_cannot_take_it(self) -> None:
        self.lease("a", item="Sa")
        record = json.loads((self.runs / STAMP / "a" / "lease.json").read_text(encoding="utf-8"))
        self.assertEqual(record["item"], "Sa")
        from lanes.leases import admission_refusal, held_items
        self.assertEqual(held_items(self.runs), {"Sa": f"{STAMP}/a"})
        self.assertIsNone(admission_refusal(self.runs, STAMP, "a", "Sa"))
        self.assertIn("held by the live lease", admission_refusal(self.runs, OTHER_STAMP, "z", "Sa") or "")


class SonContractTextTests(unittest.TestCase):
    RULES: Final[tuple[str, ...]] = (
        "No own stamp", "Protected records", ".harness/end-state.md", ".harness/council.md", ".harness/state.md",
        ".harness/lessons.md", ".harness/autopilot/latest.md", "need-human", "seat-pool-collapse", "context-guard",
        "--session-id", "mailbox-timeout", "verified_head_sha", "mailbox rules", "mailbox request", "no-browser",
    )

    def test_the_son_contract_exists_and_names_each_rule(self) -> None:
        text = AUTOPILOT.read_text(encoding="utf-8")
        self.assertIn("## Son contract", text)
        section = text[text.index("## Son contract"):]
        for rule in self.RULES:
            self.assertIn(rule, section, rule)

    def test_the_contract_cites_sections_instead_of_copying_them(self) -> None:
        text = AUTOPILOT.read_text(encoding="utf-8")
        section = text[text.index("## Son contract"):]
        for cite in ("section 0", "section 1", "section 4", "dpp section 7"):
            self.assertIn(cite, section)

    def test_dpp_and_fullauto_texts_carry_the_new_settings(self) -> None:
        dpp = (PLUGIN_ROOT / "skills" / "dpp" / "SKILL.md").read_text(encoding="utf-8")
        full = (PLUGIN_ROOT / "skills" / "fullauto" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("dpp_full_ask_each_lane", "approve-lane", "fullauto_freeze_scope", "pending-items.json", "lanes.py override"):
            self.assertIn(phrase, dpp, phrase)
        for phrase in ("fullauto_freeze_scope", "--fullauto", "--base"):
            self.assertIn(phrase, full, phrase)
        template = (PLUGIN_ROOT / "templates" / "dts2-harness.local.md").read_text(encoding="utf-8")
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        for key in ("mailbox_wait_min", "dpp_full_ask_each_lane", "fullauto_freeze_scope"):
            self.assertIn(f"{key}:", template)
            self.assertIn(f"`{key}`", readme)


class SonLifecycleTests(MailboxCase):
    """G-51: a fake son (the command `son-command` builds, run in a real git worktree) against the real head commands."""

    def setUp(self) -> None:
        super().setUp()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.invalid")
        (self.repo / "README.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.fake = self.root / "claude.py"
        self.fake.write_text(FAKE_SON, encoding="utf-8")
        self.settings(dpp_full_ask_each_lane="true", mailbox_wait_min="1")
        self.draft = {"stamp": STAMP, "base": self.base, "scope": "single",
                      "lanes": [lane_entry("a", ["src/a.py"]), lane_entry("b", ["src/b.py"], ["a"])]}
        self.manifest = self.root / "lanes.json"  # lease and son-command: no depends_on, which blocks a lease while its provider is unmerged
        self.manifest.write_text(json.dumps({**self.draft, "lanes": [lane_entry("a", ["src/a.py"]), lane_entry("b", ["src/b.py"])]}),
                                 encoding="utf-8")
        self.ordered = self.root / "ordered.json"  # merge commands: b depends on a
        self.ordered.write_text(json.dumps(self.draft), encoding="utf-8")
        self.env = {**os.environ, **GIT_ENV, "DTS2_CLAUDE_BIN": str(self.fake)}

    def head(self, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, env=env or self.env, check=False)
        return {**json.loads(done.stdout), "_code": done.returncode}

    def run_son(self, lane_id: str, step: str, epoch: int) -> dict[str, Any]:
        worktree = self.root / f"wt-{lane_id}"
        if not worktree.exists():
            git(self.repo, "worktree", "add", "-q", "-b", f"dts2/{STAMP}/lane-{lane_id}", str(worktree), self.base)
        command = self.head("son-command", str(self.manifest), "--lane", lane_id, "--worktree", str(worktree))
        self.assertTrue(command["ok"], command)
        env = {**self.env, **command["env"], "FAKE_LANES": str(LANES), "FAKE_CWD": str(self.repo), "FAKE_STAMP": STAMP,
               "FAKE_LANE": lane_id, "FAKE_EPOCH": str(epoch), "FAKE_STEP": step}
        done = subprocess.run(command["argv"], cwd=command["cwd"], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def lane_head(self, lane_id: str) -> str:
        return git(self.root / f"wt-{lane_id}", "rev-parse", "HEAD")

    def test_son_lifecycle_through_the_mailbox(self) -> None:
        checkin = self.root / "ci.json"
        checkin.write_text(json.dumps({"outstanding_items": ["Sa", "Sb"], "complete_items": []}), encoding="utf-8")
        first = self.root / "first.json"  # --full admits only independent lanes per pass; b waits for a's output
        first.write_text(json.dumps({**self.draft, "lanes": [self.draft["lanes"][0]]}), encoding="utf-8")
        planned = self.head("plan", "--from-checkin", str(checkin), "--draft", str(first), "--full", "--stamp", STAMP)
        self.assertEqual(planned["needs_approval"], ["a"])  # approval gate: dpp-full outside autopilot asks first
        refused = self.head("lease", str(self.manifest), "--lane", "a")
        self.assertFalse(refused["ok"])
        self.assertIn("needs the user's yes", refused.get("detail", json.dumps(refused)))
        for lane_id in ("a", "b"):
            self.assertTrue(self.head("approve-lane", STAMP, "--lane", lane_id)["ok"])
            self.assertEqual(self.head("lease", str(self.manifest), "--lane", lane_id)["epoch"], 1)
        # a second run cannot plan the item a live lease holds (G-47)
        rival = self.root / "rival.json"
        rival.write_text(json.dumps({**self.draft, "stamp": OTHER_STAMP, "lanes": [lane_entry("a", ["src/a.py"])]}), encoding="utf-8")
        self.assertIn("held by the live lease", json.dumps(self.head("plan", "--from-checkin", str(checkin), "--draft", str(rival),
                                                                   "--stamp", OTHER_STAMP)["refused"]))
        # the sons start: rules, a commit, a question, pr-open; a son's own merge grant is refused
        for lane_id in ("a", "b"):
            started = self.run_son(lane_id, "start", 1)
            self.assertEqual(started["ask"]["id"], "q1")
            self.assertTrue(started["beat"]["ok"], started["beat"])
            self.assertFalse(started["self_grant"]["ok"])
            self.assertTrue(started["rules"]["reread"])
        status = {row["lane"]: row["phase"] for row in self.head("status", STAMP)["lanes"]}
        self.assertEqual(status, {"a": "pr-open", "b": "pr-open"})
        saved = json.loads((self.runs / STAMP / "a" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["v"], saved["epoch"]), (1, 1))
        # question -> answer, and a send-back with n and epoch
        question = json.loads((self.runs / STAMP / "a" / "questions" / "q1.json").read_text(encoding="utf-8"))
        self.assertEqual(question["text"], "which database?")
        self.assertEqual(self.run_son("a", "answer", 1)["answer"]["state"], "waiting")
        self.assertTrue(self.head("mailbox", "answer", STAMP, "--lane", "a", "--id", "q1", "--text", "postgres")["ok"])
        self.assertEqual(self.run_son("a", "answer", 1)["answer"]["text"], "postgres")
        back = self.head("sendback", STAMP, "--lane", "a", "--reason", "add a test")
        self.assertEqual((back["n"], back["epoch"]), (1, 1))
        # merge order: b depends on a, so b is refused until a has merged
        head_a, head_b = self.lane_head("a"), self.lane_head("b")
        early = self.head("merge-go", str(self.ordered), "--lane", "b", "--head", head_b, "--base", self.base)
        self.assertFalse(early["ok"])
        self.assertEqual(early["waiting_on"], ["a"])
        self.assertEqual(self.run_son("a", "merge", 1)["check"]["ok"], False)  # no grant yet
        granted = self.head("merge-go", str(self.ordered), "--lane", "a", "--head", head_a, "--base", self.base)
        self.assertTrue(granted["ok"], granted)
        payload = json.loads((self.runs / STAMP / "a" / "merge-go.json").read_text(encoding="utf-8"))
        self.assertEqual((payload["lane"], payload["epoch"], payload["verified_head_sha"], payload["base_sha"]),
                         ("a", 1, head_a, self.base))
        self.assertTrue(self.run_son("a", "merge", 1)["check"]["ok"])
        # a commit after the grant voids it on the son side
        voided = self.run_son("a", "late-commit", 1)["check"]
        self.assertFalse(voided["ok"])
        self.assertIn("HEAD differs from verified_head_sha", voided["detail"])
        self.assertTrue(self.head("merge-done", str(self.ordered), "--lane", "a")["ok"])
        self.assertTrue(self.head("merge-go", str(self.ordered), "--lane", "b", "--head", head_b, "--base", self.base)["ok"])
        # the owner override is refused without the human channel
        no = self.head("override", "b", "--reason", "hotfix")
        self.assertFalse(no["ok"])
        self.assertIn("no human approval", no["detail"])

    def test_a_lane_needing_a_browser_parks_instead_of_skipping(self) -> None:
        self.lease("a")
        parked = self.head("mailbox", "park", STAMP, "--lane", "a", "--reason", "no-browser", "--session-id", "s1")
        self.assertTrue(parked["ok"], parked)
        status = {row["lane"]: row["phase"] for row in self.head("status", STAMP)["lanes"]}
        self.assertEqual(status["a"], "incomplete")
        self.assertEqual(json.loads((self.runs / STAMP / "a" / "status.json").read_text(encoding="utf-8"))["reason"], "no-browser")


if __name__ == "__main__":
    unittest.main()
