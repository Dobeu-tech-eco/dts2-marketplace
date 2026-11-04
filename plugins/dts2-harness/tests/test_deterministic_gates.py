"""checks.py gate, ledger and redaction; council.py route and blind; scout evidence and verifier split contracts."""
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
FAKE_KEY: Final[str] = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"


def call(script: str, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> tuple[int, dict[str, Any]]:
    done = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], capture_output=True, text=True,
                          cwd=str(cwd or PLUGIN_ROOT), env={**os.environ, **(env or {})}, check=False)
    return done.returncode, json.loads(done.stdout)


def repo(commands: dict[str, str], extra: str = "") -> Path:
    root: Path = Path(tempfile.mkdtemp(prefix="dts2-gate-"))
    (root / ".harness").mkdir()
    body: str = "commands:\n" + "".join(f"  {k}: {v}\n" for k, v in commands.items()) + extra
    (root / ".harness" / "config.yaml").write_text(body, encoding="utf-8")
    return root


def fake_git(root: Path, files: str) -> dict[str, str]:
    script: Path = root / "fake_git.py"
    script.write_text(f"import sys\nprint({files!r})\n", encoding="utf-8")
    return {"DTS2_GIT_BIN": str(script), "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}


GREEN: Final[dict[str, str]] = {"test": "true", "typecheck": "true", "lint": "true"}


def run_checks(root: Path, env: dict[str, str]) -> tuple[int, dict[str, Any]]:
    isolated: dict[str, str] = {**env, "PATH": "/nonexistent-bin"}
    return call("checks.py", "run", "--stamp", "s1", "--cwd", str(root), env=isolated)


def ledger_of(root: Path) -> Path:
    return root / ".harness" / "runs" / "s1" / "ledger.jsonl"


class ChecksTests(unittest.TestCase):
    def test_green_checks_write_machine_readable_lines(self) -> None:
        root: Path = repo(GREEN)
        code, out = run_checks(root, fake_git(root, "a.py"))
        self.assertEqual(code, 0, out)
        self.assertTrue(out["votes_allowed"])
        lines: list[dict[str, Any]] = [json.loads(x) for x in ledger_of(root).read_text().splitlines()]
        self.assertEqual({r["name"] for r in lines}, {"test", "typecheck", "lint", "secret-scan", "scope-check"})
        for record in lines:
            self.assertEqual(set(record), {"kind", "name", "status", "duration_ms", "log_path"})
            self.assertIsInstance(record["duration_ms"], int)
            self.assertTrue((root / record["log_path"]).is_file())

    def test_missing_scanner_is_skipped_with_warning(self) -> None:
        root: Path = repo(GREEN)
        _, out = run_checks(root, fake_git(root, "a.py"))
        scan: dict[str, Any] = next(c for c in out["checks"] if c["name"] == "secret-scan")
        self.assertEqual(scan["status"], "skip")
        self.assertIn("warning", (root / scan["log_path"]).read_text())

    def test_scanner_hit_is_red(self) -> None:
        root: Path = repo(GREEN)
        env: dict[str, str] = fake_git(root, "a.py")
        scanner: Path = root / "gitleaks.py"
        scanner.write_text("import sys\nprint('leak found')\nsys.exit(1)\n", encoding="utf-8")
        env["DTS2_GITLEAKS_BIN"] = str(scanner)
        code, out = run_checks(root, env)
        self.assertEqual(code, 1)
        self.assertEqual(out["red"], ["secret-scan"])

    def test_scope_check_flags_protected_file(self) -> None:
        root: Path = repo(GREEN, "do_not_touch:\n  - .env\n  - secrets/**\n")
        _, out = run_checks(root, fake_git(root, "src/a.py\n.env"))
        self.assertEqual(out["red"], ["scope-check"])

    def test_red_check_blocks_votes_and_names_the_check(self) -> None:
        root: Path = repo({**GREEN, "test": "false"})
        code, out = run_checks(root, fake_git(root, "a.py"))
        self.assertEqual(code, 1)
        self.assertFalse(out["votes_allowed"])
        self.assertEqual(out["action"], "fix")
        self.assertEqual(out["red"], ["test"])

    def test_no_results_means_no_votes(self) -> None:
        root: Path = repo(GREEN)
        code, out = call("checks.py", "gate", "--stamp", "none", "--cwd", str(root))
        self.assertEqual(code, 1)
        self.assertFalse(out["votes_allowed"])

    def test_rerun_after_fix_replaces_red(self) -> None:
        root: Path = repo({**GREEN, "test": "false"})
        env: dict[str, str] = fake_git(root, "a.py")
        run_checks(root, env)
        (root / ".harness" / "config.yaml").write_text("commands:\n  test: true\n  typecheck: true\n  lint: true\n")
        code, out = run_checks(root, env)
        self.assertEqual(code, 0, out)

    def test_summary_is_built_from_ledger_without_rerunning(self) -> None:
        root: Path = repo(GREEN)
        run_checks(root, fake_git(root, "a.py"))
        (root / ".harness" / "config.yaml").write_text("commands:\n  test: false\n")
        _, out = call("checks.py", "summary", "--stamp", "s1", "--cwd", str(root))
        self.assertIn("| test | pass |", out["markdown"])


class RedactionTests(unittest.TestCase):
    def test_log_redacts_key_shaped_output(self) -> None:
        root: Path = repo({**GREEN, "test": f"echo token {FAKE_KEY} API_KEY=hunter2value"})
        _, out = run_checks(root, fake_git(root, "a.py"))
        test: dict[str, Any] = next(c for c in out["checks"] if c["name"] == "test")
        log: str = (root / test["log_path"]).read_text()
        self.assertNotIn(FAKE_KEY, log)
        self.assertNotIn("hunter2value", log)
        self.assertNotIn(FAKE_KEY, ledger_of(root).read_text())

    def test_missing_env_records_names_only(self) -> None:
        root: Path = repo(GREEN)
        _, out = call("checks.py", "env-missing", "--stamp", "s1", "--cwd", str(root),
                      "DATABASE_URL", "STRIPE_KEY=sk_live_abcdefghijklmnopqrstuv", "not a name", FAKE_KEY)
        self.assertEqual(out["missing"], ["DATABASE_URL", "STRIPE_KEY"])
        text: str = ledger_of(root).read_text()
        self.assertNotIn("sk_live", text)
        self.assertNotIn(FAKE_KEY, text)

    def test_action_items_writer_redacts_assignments(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("action_items_x", SCRIPTS / "action-items.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cleaned: str = module.clean_text("add DATABASE_URL=postgres://u:pw@h/db to env")
        self.assertNotIn("postgres://", cleaned)


class RouteTests(unittest.TestCase):
    def ledger(self, status: str) -> Path:
        path: Path = Path(tempfile.mkdtemp(prefix="dts2-route-")) / "ledger.jsonl"
        record = {"kind": "check", "name": "test", "status": status, "duration_ms": 1, "log_path": "x"}
        path.write_text(json.dumps(record) + "\n")
        return path

    def route(self, status: str, *extra: str) -> dict[str, Any]:
        return call("council.py", "route", "--ledger", str(self.ledger(status)), *extra)[1]

    def test_red_check_means_zero_votes_even_with_votes_present(self) -> None:
        out = self.route("fail", "--votes", "APPROVE,APPROVE,APPROVE")
        self.assertEqual((out["action"], out["votes"]), ("fix", 0))

    def test_green_asks_for_the_panel(self) -> None:
        out = self.route("pass")
        self.assertEqual((out["action"], out["votes"]), ("vote", 3))

    def test_unanimous_green_needs_no_council(self) -> None:
        self.assertEqual(self.route("pass", "--votes", "APPROVE,APPROVE,APPROVE")["action"], "pass")

    def test_split_escalates(self) -> None:
        self.assertEqual(self.route("pass", "--votes", "APPROVE,REJECT,APPROVE")["action"], "escalate")

    def test_unanimous_reject_is_a_fix_round_not_council(self) -> None:
        self.assertEqual(self.route("pass", "--votes", "REJECT,REJECT,REJECT")["action"], "fix")

    def test_red_check_with_council_approve_is_rejected(self) -> None:
        out = self.route("fail", "--decision", "APPROVE")
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "fix")

    def test_check_decision_refuses_approve_over_red(self) -> None:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-dec-"))
        decision: Path = folder / "d.md"
        decision.write_text("DECISION: APPROVE\n\n## Head of council brief\nok\n\n## History considered\nEntries reviewed: 2\n")
        tally: Path = folder / "t.json"
        tally.write_text(json.dumps({"dissenters": []}))
        base = ["check-decision", str(decision), "--tally", str(tally), "--entries", "2"]
        self.assertTrue(call("council.py", *base)[1]["ok"])
        out = call("council.py", *base, "--ledger", str(self.ledger("fail")))[1]
        self.assertFalse(out["ok"])
        self.assertTrue(any("red" in p for p in out["problems"]))


class BlindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root: Path = Path(tempfile.mkdtemp(prefix="dts2-blind-"))
        self.props: Path = self.root / "props"
        self.props.mkdir()
        for name in ("claude-opus", "codex", "gemini-pro"):
            (self.props / f"{name}.md").write_text(f"Author: {name}\nPlan from {name}: use a queue.\n", encoding="utf-8")

    def blind(self, seed: str) -> dict[str, Any]:
        out: Path = self.root / f"out-{seed}"
        return call("council.py", "blind", "--proposals", str(self.props), "--out", str(out), "--voters", "v1,v2,v3",
                    "--seed", seed, "--ledger", str(self.root / "ledger.jsonl"))[1]

    def test_no_author_identity_in_ballots(self) -> None:
        result = self.blind("seed1")
        self.assertTrue(result["ok"], result)
        for ballot in Path(result["out"]).glob("ballot-*.md"):
            text: str = ballot.read_text().lower()
            for name in ("claude", "opus", "codex", "gemini"):
                self.assertNotIn(name, text)
            self.assertIn("use a queue", text)

    def test_order_is_seeded_per_voter_and_recorded(self) -> None:
        first = self.blind("seed1")
        again = self.blind("seed1")
        key1 = json.loads(Path(first["key"]).read_text())["key"]
        key2 = json.loads(Path(again["key"]).read_text())["key"]
        self.assertEqual(key1, key2)
        orders = {tuple(k.values()) for k in key1.values()}
        different = [tuple(json.loads(Path(self.blind(f"s{i}")["key"]).read_text())["key"]["v1"].values()) for i in range(6)]
        self.assertGreater(len(set(different)), 1)
        self.assertGreaterEqual(len(orders), 1)
        records = [json.loads(x) for x in (self.root / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(records[0]["kind"], "ballot")
        self.assertEqual(records[0]["seed"], "seed1")


class ScoutTests(unittest.TestCase):
    def check(self, text: str) -> tuple[int, dict[str, Any]]:
        path: Path = Path(tempfile.mkdtemp(prefix="dts2-scout-")) / "evidence.md"
        path.write_text(text, encoding="utf-8")
        return call("checks.py", "scout-check", str(path))

    def test_clean_evidence_passes(self) -> None:
        code, out = self.check("$ npm test\nexit 1\n3 failures in a.test.ts\n")
        self.assertEqual(code, 0, out)

    def test_verdict_tokens_fail(self) -> None:
        for text in ("### Verdict: VERIFIED\n", "all good, BLOCKED\n", "I would APPROVE this\n"):
            code, out = self.check(text)
            self.assertEqual(code, 1, text)
            self.assertTrue(out["tokens"])

    def test_agent_files_describe_the_split(self) -> None:
        scout: str = (PLUGIN_ROOT / "agents" / "scout.md").read_text()
        verifier: str = (PLUGIN_ROOT / "agents" / "verifier.md").read_text()
        self.assertIn("Mode: evidence", scout)
        self.assertIn("Never write a verdict", scout)
        self.assertIn("Evidence: <path>", verifier)
        self.assertIn("\nmodel: opus\n", verifier)
        review: str = (PLUGIN_ROOT / "skills" / "run" / "phase-3-review.md").read_text()
        self.assertLess(review.find("checks.py"), review.find("Verifier walkthrough first"))


if __name__ == "__main__":
    unittest.main()
