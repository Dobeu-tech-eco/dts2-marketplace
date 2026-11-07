"""Review fixes: plan-ballot ledger scoping, blind stems, config comments, `**/` scope globs, action-item redaction, head pinning."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT
from skill_text import read_rel
from test_deterministic_gates import FAKE_KEY, GREEN, SCRIPTS, call, fake_git, repo

SETUP_DEFAULTS: Final[str] = "do_not_touch:\n  - .env\n  - .env.*\n  - secrets/**\n  - \"**/credentials*\"\n"
NAMES: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "secret-scan", "scope-check")


def load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ledger_with(head: str | None, status: str = "pass") -> Path:
    path: Path = Path(tempfile.mkdtemp(prefix="dts2-head-")) / "ledger.jsonl"
    rows = []
    for n in NAMES:
        row: dict[str, Any] = {"kind": "check", "name": n, "status": status, "duration_ms": 1, "log_path": "x"}
        if head:
            row["head"] = head
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def scope_status(config_extra: str, files: str) -> str:
    root = repo(GREEN, config_extra)
    env = fake_git(root, files)
    call("checks.py", "run", "--stamp", "s", "--cwd", str(root), "--base", "main", env=env)
    ledger = [json.loads(line) for line in (root / ".harness/runs/s/ledger.jsonl").read_text().splitlines()]
    return next(r["status"] for r in ledger if r["name"] == "scope-check")


class PlanBallotLedgerText(unittest.TestCase):
    def test_autopilot_scopes_ledger_to_build_ballot(self) -> None:
        text = read_rel("skills/autopilot/SKILL.md")
        step = next(line for line in text.splitlines() if line.startswith("5. **Check the record.**"))
        self.assertIn("only when the council sits on the build ballot", step)
        self.assertIn("plan-ballot council omits", step)

    def test_phase3_and_dpp_make_the_same_split(self) -> None:
        for rel in ("skills/dpp/SKILL.md", "skills/run/phase-3-review.md"):
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("plan-ballot council", text, rel)

    def test_fix_round_rechecks_are_described(self) -> None:
        for rel in ("skills/autopilot/SKILL.md", "skills/run/phase-3-review.md", "skills/dpp/SKILL.md"):
            text = read_rel(rel)
            self.assertIn("council.py", text, rel)
            self.assertRegex(text, r"(?s)fix round.{0,400}(checks\.py\W+run|re-run the checks)", rel)
            self.assertIn("route --ledger", text, rel)

    def test_check_decision_without_ledger_accepts_approve(self) -> None:
        d = Path(tempfile.mkdtemp(prefix="dts2-plan-"))
        decision = d / "d.md"
        decision.write_text("DECISION: APPROVE\n\n## Head of council brief\nok\n\n## History considered\nEntries reviewed: 4\n", encoding="utf-8")
        tally = d / "t.json"
        tally.write_text(json.dumps({"dissenters": []}), encoding="utf-8")
        code, out = call("council.py", "check-decision", str(decision), "--tally", str(tally), "--entries", "4")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])


class BlindStemTests(unittest.TestCase):
    def blind(self, stems: tuple[str, str], bodies: tuple[str, str]) -> str:
        d = Path(tempfile.mkdtemp(prefix="dts2-blind-"))
        for stem, body in zip(stems, bodies):
            (d / f"{stem}.md").write_text(body, encoding="utf-8")
        code, out = call("council.py", "blind", "--proposals", str(d), "--out", str(d / "out"), "--voters", "v1", "--seed", "s")
        self.assertEqual(code, 0, out)
        return (d / "out" / "ballot-v1.md").read_text(encoding="utf-8")

    def test_numeric_stems_keep_body_text(self) -> None:
        text = self.blind(("1", "2"), ("Do layer 1 first, then step 2 then 1.\n", "Another take on layer 1.\n"))
        self.assertIn("layer 1", text)
        self.assertIn("step 2 then 1", text)
        self.assertNotIn("the author", text)

    def test_word_stems_keep_body_text(self) -> None:
        text = self.blind(("plan", "test"), ("Skip the plan and the test.\n", "Run the test then the plan.\n"))
        self.assertIn("Skip the plan and the test.", text)
        self.assertNotIn("the author", text)

    def test_listed_author_stem_is_still_stripped(self) -> None:
        d = Path(tempfile.mkdtemp(prefix="dts2-blind-"))
        (d / "zed.md").write_text("zed proposes this.\n", encoding="utf-8")
        (d / "other.md").write_text("plain\n", encoding="utf-8")
        code, out = call("council.py", "blind", "--proposals", str(d), "--out", str(d / "o"), "--voters", "v1", "--seed", "s", "--authors", "zed")
        self.assertEqual(code, 0, out)
        self.assertNotIn("zed", (d / "o" / "ballot-v1.md").read_text(encoding="utf-8"))

    def test_author_line_only_in_header_block(self) -> None:
        body = "# Data model\nModel: gpt-x\n\n**Model:** User has many Posts\n\nThe gpt-x design is fine.\n"
        text = self.blind(("claude-a", "claude-b"), (body, "# Other\nplain\n"))
        self.assertIn("**Model:** User has many Posts", text)
        self.assertNotIn("Model: gpt-x", text)
        self.assertNotIn("gpt-x", text)


class ScopeFixTests(unittest.TestCase):
    def test_column_zero_comment_keeps_list(self) -> None:
        config = load("checks_x", "checks.py").parse_config("do_not_touch:\n# c\n  - .env\n")
        self.assertEqual(config["do_not_touch"], [".env"])
        self.assertEqual(scope_status("do_not_touch:\n# note\n  - .env\n", ".env"), "fail")

    def test_top_level_credentials_json_is_caught(self) -> None:
        self.assertEqual(scope_status(SETUP_DEFAULTS, "credentials.json"), "fail")
        self.assertEqual(scope_status(SETUP_DEFAULTS, "deep/dir/credentials.json"), "fail")
        self.assertEqual(scope_status(SETUP_DEFAULTS, "src/app.py"), "pass")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], check=True, capture_output=True)


def rename_scope_status(commit_rename: bool) -> str:
    root = repo(GREEN, "do_not_touch:\n  - .env\n")
    git(root, "init", "-q", "-b", "main")
    (root / ".env").write_text("A=1\n", encoding="utf-8")
    (root / "ok.txt").write_text("x\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "work")
    git(root, "mv", ".env", "moved.txt")
    if commit_rename:
        git(root, "commit", "-q", "-m", "rename")
    call("checks.py", "run", "--stamp", "s", "--cwd", str(root), "--base", "main", env={"DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""})
    ledger = [json.loads(line) for line in (root / ".harness/runs/s/ledger.jsonl").read_text().splitlines()]
    return next(r["status"] for r in ledger if r["name"] == "scope-check")


class RenameScopeTests(unittest.TestCase):
    def test_committed_rename_of_protected_file_is_red(self) -> None:
        self.assertEqual(rename_scope_status(True), "fail")

    def test_staged_rename_of_protected_file_is_red(self) -> None:
        self.assertEqual(rename_scope_status(False), "fail")


class ActionItemRedaction(unittest.TestCase):
    def test_key_shapes_are_redacted(self) -> None:
        module = load("action_items_y", "action-items.py")
        raws = [FAKE_KEY, "sk-" + "ant-api03-abcdefghijklmnop1234", "AKIA" + "ABCDEFGHIJKLMNOP", "Bearer " + "tok123abcdef", "x"]
        cleaned: str = module.clean_text(f'rotate {raws[0]} and {raws[1]} and {raws[2]} and {raws[3]} and {{"password": "{raws[4]}"}}')
        for raw in raws[:4]:
            self.assertNotIn(raw, cleaned)
        self.assertNotIn('"x"', cleaned)
        self.assertNotIn("|", module.clean_text("a | b"))


class HeadPinning(unittest.TestCase):
    def test_gate_ignores_checks_from_another_head(self) -> None:
        checks = load("checks_z", "checks.py")
        records = checks.read_ledger(ledger_with("aaa"))
        self.assertTrue(checks.gate(records)["ok"])
        self.assertTrue(checks.gate(records, "aaa")["ok"])
        stale = checks.gate(records, "bbb")
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["action"], "run-checks")
        self.assertFalse(checks.gate(checks.read_ledger(ledger_with(None)), "aaa")["ok"])

    def test_cli_head_flag_on_route_and_check_decision(self) -> None:
        path = ledger_with("aaa")
        code, out = call("council.py", "route", "--ledger", str(path), "--head", "bbb")
        self.assertEqual(out["action"], "run-checks")
        code, out = call("council.py", "route", "--ledger", str(path), "--head", "aaa")
        self.assertEqual(out["action"], "vote")
        d = path.parent
        (d / "d.md").write_text("DECISION: APPROVE\n\n## Head of council brief\nok\n\n## History considered\nEntries reviewed: 1\n", encoding="utf-8")
        (d / "t.json").write_text(json.dumps({"dissenters": []}), encoding="utf-8")
        args = ("check-decision", str(d / "d.md"), "--tally", str(d / "t.json"), "--entries", "1", "--ledger", str(path))
        self.assertTrue(call("council.py", *args, "--head", "aaa")[1]["ok"])
        self.assertFalse(call("council.py", *args, "--head", "bbb")[1]["ok"])

    def test_run_records_head(self) -> None:
        root = repo(GREEN)
        env = fake_git(root, "abc123")
        call("checks.py", "run", "--stamp", "s", "--cwd", str(root), "--base", "main", env=env)
        rows = [json.loads(line) for line in (root / ".harness/runs/s/ledger.jsonl").read_text().splitlines()]
        self.assertTrue(all(r.get("head") == "abc123" for r in rows))
        code, out = call("checks.py", "gate", "--stamp", "s", "--cwd", str(root), "--head", "abc123")
        self.assertEqual(code, 0, out)
        code, out = call("checks.py", "gate", "--stamp", "s", "--cwd", str(root), "--head", "other")
        self.assertEqual(code, 1, out)


if __name__ == "__main__":
    unittest.main()
