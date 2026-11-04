"""Review fixes for the deterministic gates: whole-token blinding, ledger order, fail-closed decisions, full gate, scope, redaction."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT
from test_deterministic_gates import FAKE_KEY, GREEN, call, fake_git, ledger_of, repo, run_checks

ALL_FIVE: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "secret-scan", "scope-check")


def write_ledger(names: tuple[str, ...], status: str = "pass") -> Path:
    path: Path = Path(tempfile.mkdtemp(prefix="dts2-fix-")) / "ledger.jsonl"
    path.write_text("".join(json.dumps({"kind": "check", "name": n, "status": status, "duration_ms": 1, "log_path": "x"}) + "\n" for n in names))
    return path


class BlindWholeTokenTests(unittest.TestCase):
    def test_plan_and_planning_survive_while_author_goes(self) -> None:
        root: Path = Path(tempfile.mkdtemp(prefix="dts2-blindfix-"))
        props: Path = root / "props"
        props.mkdir()
        (props / "claude-plan.md").write_text("Plan: use the plan cache. Planning matters. Claude wrote this.\n", encoding="utf-8")
        (props / "codex-plan.md").write_text("Author: Codex Alpha\nUse the plan cache; codex agrees. Alpha mode, planning.\n", encoding="utf-8")
        _, out = call("council.py", "blind", "--proposals", str(props), "--out", str(root / "out"), "--voters", "v1,v2", "--seed", "x")
        self.assertTrue(out["ok"], out)
        for ballot in (root / "out").glob("ballot-*.md"):
            text: str = ballot.read_text()
            self.assertIn("the plan cache", text)
            self.assertIn("Planning matters", text)
            self.assertIn("planning", text)
            self.assertNotIn("the author cache", text)
            self.assertNotIn("authorning", text)
            self.assertNotIn("claude", text.lower())
            self.assertNotIn("codex", text.lower())
            self.assertNotIn("codex alpha", text.lower())

    def test_authors_flag_strips_extra_names(self) -> None:
        root: Path = Path(tempfile.mkdtemp(prefix="dts2-blindfix-"))
        props: Path = root / "props"
        props.mkdir()
        (props / "one.md").write_text("Written with Zorp help; zorpish stays.\n", encoding="utf-8")
        (props / "two.md").write_text("Plain.\n", encoding="utf-8")
        call("council.py", "blind", "--proposals", str(props), "--out", str(root / "out"), "--voters", "v1", "--seed", "x", "--authors", "Zorp")
        text: str = (root / "out" / "ballot-v1.md").read_text()
        self.assertNotIn("Zorp ", text)
        self.assertIn("zorpish", text)


class CheckDecisionFailClosedTests(unittest.TestCase):
    def decision(self, ledger: str | None) -> dict[str, Any]:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-dec-"))
        (folder / "d.md").write_text("DECISION: APPROVE\n\n## Head of council brief\nok\n\n## History considered\nEntries reviewed: 2\n")
        (folder / "t.json").write_text(json.dumps({"dissenters": []}))
        args = ["check-decision", str(folder / "d.md"), "--tally", str(folder / "t.json"), "--entries", "2"]
        return call("council.py", *args, *(["--ledger", ledger] if ledger else []))[1]

    def test_missing_ledger_refuses_approve(self) -> None:
        out = self.decision(str(Path(tempfile.mkdtemp()) / "typo.jsonl"))
        self.assertFalse(out["ok"])
        self.assertTrue(any("no deterministic check results" in p for p in out["problems"]))

    def test_empty_ledger_refuses_approve(self) -> None:
        empty: Path = Path(tempfile.mkdtemp()) / "l.jsonl"
        empty.write_text("")
        self.assertFalse(self.decision(str(empty))["ok"])

    def test_partial_ledger_refuses_approve_and_full_green_allows(self) -> None:
        self.assertFalse(self.decision(str(write_ledger(("lint",))))["ok"])
        self.assertTrue(self.decision(str(write_ledger(ALL_FIVE)))["ok"])


class GateCompletenessTests(unittest.TestCase):
    def test_lint_only_ledger_is_not_enough(self) -> None:
        path: Path = write_ledger(("lint",))
        out = call("council.py", "route", "--ledger", str(path))[1]
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "run-checks")
        self.assertIn("typecheck", out["reason"])

    def test_gate_names_missing_checks(self) -> None:
        root: Path = repo(GREEN)
        ledger_of(root).parent.mkdir(parents=True)
        ledger_of(root).write_text(json.dumps({"kind": "check", "name": "lint", "status": "pass", "duration_ms": 1, "log_path": "x"}) + "\n")
        code, out = call("checks.py", "gate", "--stamp", "s1", "--cwd", str(root))
        self.assertEqual(code, 1)
        self.assertFalse(out["votes_allowed"])
        self.assertEqual(out["action"], "run-checks")
        self.assertEqual(out["missing"], ["test", "typecheck", "secret-scan", "scope-check"])


def stage_git(root: Path, base_diff: str = "", head_diff: str = "", untracked: str = "") -> dict[str, str]:
    script: Path = root / "stage_git.py"
    script.write_text(
        "import sys\n"
        "a = sys.argv[1:]\n"
        f"if a[:2] == ['diff', '--name-only'] and a[2].endswith('...HEAD'): print({base_diff!r})\n"
        f"elif a[:2] == ['diff', '--name-only']: print({head_diff!r})\n"
        f"elif a[:1] == ['ls-files']: print({untracked!r})\n", encoding="utf-8")
    return {"DTS2_GIT_BIN": str(script), "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}


class ScopeTests(unittest.TestCase):
    PROTECTED: Final[str] = "do_not_touch:\n  - .env\n  - secrets/**\n"

    def scope(self, root: Path, env: dict[str, str]) -> dict[str, Any]:
        code, out = call("checks.py", "run", "--stamp", "s1", "--cwd", str(root), "--base", "main", env={**env, "PATH": "/nonexistent-bin"})
        return next(c for c in out["checks"] if c["name"] == "scope-check")

    def test_committed_protected_file_is_red(self) -> None:
        root: Path = repo(GREEN, self.PROTECTED)
        self.assertEqual(self.scope(root, stage_git(root, base_diff="src/a.py\n.env"))["status"], "fail")

    def test_untracked_protected_file_is_red(self) -> None:
        root: Path = repo(GREEN, self.PROTECTED)
        self.assertEqual(self.scope(root, stage_git(root, untracked="secrets/key.txt"))["status"], "fail")

    def test_clean_union_is_green(self) -> None:
        root: Path = repo(GREEN, self.PROTECTED)
        self.assertEqual(self.scope(root, stage_git(root, base_diff="a.py", head_diff="b.py", untracked="c.py"))["status"], "pass")

    def test_unlistable_files_fail_when_protection_is_set(self) -> None:
        root: Path = repo(GREEN, self.PROTECTED)
        broken: Path = root / "broken_git.py"
        broken.write_text("import sys\nsys.exit(128)\n", encoding="utf-8")
        env = {"DTS2_GIT_BIN": str(broken), "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}
        self.assertEqual(self.scope(root, env)["status"], "fail")

    def test_unlistable_files_skip_when_nothing_is_protected(self) -> None:
        root: Path = repo(GREEN)
        broken: Path = root / "broken_git.py"
        broken.write_text("import sys\nsys.exit(128)\n", encoding="utf-8")
        env = {"DTS2_GIT_BIN": str(broken), "DTS2_GITLEAKS_BIN": "", "DTS2_TRUFFLEHOG_BIN": ""}
        self.assertEqual(self.scope(root, env)["status"], "skip")

    def test_inline_flow_list_is_parsed(self) -> None:
        root: Path = repo(GREEN, 'do_not_touch: [".env", "secrets/**"]\n')
        self.assertEqual(self.scope(root, stage_git(root, base_diff=".env"))["status"], "fail")

    def test_unreadable_do_not_touch_fails_closed(self) -> None:
        root: Path = repo(GREEN, "do_not_touch: .env, secrets\n")
        self.assertEqual(self.scope(root, stage_git(root, base_diff="a.py"))["status"], "fail")

    def test_recorded_base_is_used_without_flag(self) -> None:
        root: Path = repo(GREEN, self.PROTECTED)
        (root / ".harness" / "runs" / "s1").mkdir(parents=True)
        (root / ".harness" / "runs" / "s1" / "base").write_text("origin/dev\n")
        _, out = run_checks(root, stage_git(root, base_diff=".env"))
        self.assertEqual(out["red"], ["scope-check"])


class RedactionFixTests(unittest.TestCase):
    def redacted(self, text: str) -> str:
        import sys
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        from checks import redact
        return redact(text)

    def test_bare_names_and_lowercase(self) -> None:
        for text, secret in (("PASSWORD=hunter2", "hunter2"), ("TOKEN=abc123", "abc123"), ("SECRET: s3cr3t", "s3cr3t"),
                             ("password=hunter2", "hunter2")):
            self.assertNotIn(secret, self.redacted(text), text)

    def test_quoted_value_with_spaces_is_removed_whole(self) -> None:
        out: str = self.redacted('API_KEY="two words" next')
        self.assertNotIn("words", out)
        self.assertIn("next", out)

    def test_match_does_not_run_onto_the_next_line(self) -> None:
        out: str = self.redacted("PASSWORD=\nplain line stays\n")
        self.assertIn("plain line stays", out)

    def test_bearer_and_url_userinfo(self) -> None:
        self.assertNotIn("tok_value123", self.redacted("Authorization: Bearer tok_value123"))
        out: str = self.redacted("connect postgres://user:pw0rd@host/db now")
        self.assertNotIn("pw0rd", out)
        self.assertIn("postgres://user:", out)
        self.assertIn("@host/db", out)

    def test_key_shape_still_removed(self) -> None:
        self.assertNotIn(FAKE_KEY, self.redacted(f"seen {FAKE_KEY}"))


class TrufflehogTests(unittest.TestCase):
    def test_raw_secret_never_reaches_the_log(self) -> None:
        root: Path = repo(GREEN)
        env: dict[str, str] = fake_git(root, "a.py")
        tool: Path = root / "trufflehog.py"
        raw: str = "correct horse battery staple"
        finding: dict[str, Any] = {"DetectorName": "Generic", "Raw": raw, "RawV2": raw + " v2",
                                   "SourceMetadata": {"Data": {"Filesystem": {"file": "src/conf.txt", "line": 7}}}}
        tool.write_text(f"import json, sys\nprint(json.dumps({finding!r}))\nprint('stray {raw}')\nsys.exit(183)\n", encoding="utf-8")
        env["DTS2_TRUFFLEHOG_BIN"] = str(tool)
        code, out = run_checks(root, env)
        self.assertEqual(code, 1)
        self.assertEqual(out["red"], ["secret-scan"])
        scan: dict[str, Any] = next(c for c in out["checks"] if c["name"] == "secret-scan")
        log: str = (root / scan["log_path"]).read_text()
        self.assertIn("detector=Generic", log)
        self.assertIn("src/conf.txt", log)
        self.assertIn("line=7", log)
        self.assertNotIn("horse", log)
        self.assertNotIn("horse", ledger_of(root).read_text())


if __name__ == "__main__":
    unittest.main()
