"""Behavioral gates and schema checks for the Cursor dt package."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

REPO: Final[Path] = PLUGIN_ROOT.parent.parent
GATE: Final[Path] = REPO / "plugins" / "dt-cursor" / "scripts" / "dt_gate.py"
PACKAGE: Final[Path] = REPO / "plugins" / "dt-cursor"
FIXTURES: Final[Path] = PLUGIN_ROOT / "tests" / "fixtures"
MISSING: Final[str] = "No end state yet; /dt-setup interviews to one."


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(GATE), *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        check=False,
    )


def _end_state(root: Path, status: str = "approved") -> None:
    harness = root / ".harness"
    harness.mkdir(parents=True)
    (harness / "end-state.md").write_text(f"- status: {status}\n\n## Goal\n\nShip.\n", encoding="utf-8")


def _validate(instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> None:
    root = schema if root is None else root
    if "$ref" in schema:
        target: Any = root
        for part in schema["$ref"][2:].split("/"):
            target = target[part]
        _validate(instance, target, root)
        return
    if "oneOf" in schema:
        errors: list[str] = []
        for option in schema["oneOf"]:
            try:
                _validate(instance, option, root)
                return
            except AssertionError as exc:
                errors.append(str(exc))
        raise AssertionError(errors)
    if "const" in schema:
        assert instance == schema["const"]
        return
    kind = schema.get("type")
    if kind == "object":
        assert isinstance(instance, dict), instance
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            assert not extra, extra
        for key in schema.get("required", []):
            assert key in instance
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], root)
        return
    if kind == "string":
        assert isinstance(instance, str)
        if "minLength" in schema:
            assert len(instance) >= schema["minLength"]
        if "pattern" in schema:
            assert re.search(schema["pattern"], instance), instance
        return
    if kind == "array":
        assert isinstance(instance, list)
        if "items" in schema:
            for item in instance:
                _validate(item, schema["items"], root)


class TestGate:
    def test_check_in_names_dt_setup_and_writes_nothing(self, tmp_path: Path) -> None:
        before = list(REPO.rglob(".harness"))
        result = _run("check-in", str(tmp_path))
        assert result.returncode == 0
        assert result.stdout.strip() == MISSING
        assert before == list(REPO.rglob(".harness"))
        assert not (tmp_path / ".harness").exists()

    def test_kind_without_digest_does_not_scaffold(self, tmp_path: Path) -> None:
        _end_state(tmp_path)
        (tmp_path / ".harness" / "approvals.jsonl").write_text(
            json.dumps({"kind": "end-state", "decision": "approve"}) + "\n",
            encoding="utf-8",
        )
        agents = tmp_path / "AGENTS.md"
        agents.write_text("keep this\n", encoding="utf-8")
        result = _run("scaffold", str(tmp_path))
        assert result.returncode == 2
        assert "kind alone is not authorization" in result.stderr
        assert not (tmp_path / ".harness" / "config.yaml").exists()
        assert agents.read_text(encoding="utf-8") == "keep this\n"

    def test_scaffold_requires_matching_approval_and_is_idempotent(self, tmp_path: Path) -> None:
        _end_state(tmp_path)
        denied = _run("approve", "--repo", str(tmp_path), "--kind", "end-state", "--decision", "approve", "--yes")
        assert denied.returncode == 2
        assert not (tmp_path / ".harness" / "approvals.jsonl").exists()
        recorded = _run("approve", "--repo", str(tmp_path), "--kind", "end-state", "--decision", "approve")
        assert recorded.returncode == 0, recorded.stderr
        first = _run("scaffold", str(tmp_path))
        assert first.returncode == 0, first.stderr
        config = (tmp_path / ".harness" / "config.yaml").read_bytes()
        assert b"name: cursor" in config
        assert (tmp_path / ".harness" / "discipline.md").is_file()
        assert not (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / "CLAUDE.md").exists()
        second = _run("scaffold", str(tmp_path))
        assert second.returncode == 0, second.stderr
        assert (tmp_path / ".harness" / "config.yaml").read_bytes() == config

    def test_run_phases_stop_until_each_digest_matches(self, tmp_path: Path) -> None:
        _end_state(tmp_path)
        assert _run("preflight", str(tmp_path)).returncode == 2
        assert _run("approve", "--repo", str(tmp_path), "--kind", "end-state", "--decision", "approve").returncode == 0
        assert _run("preflight", str(tmp_path), "--phase", "ready").returncode == 0
        assert _run("preflight", str(tmp_path), "--phase", "build").returncode == 2
        (tmp_path / ".harness" / "plan.md").write_text("plan v1\n", encoding="utf-8")
        assert _run("approve", "--repo", str(tmp_path), "--kind", "plan", "--decision", "approve").returncode == 0
        assert _run("preflight", str(tmp_path), "--phase", "build").returncode == 0
        (tmp_path / ".harness" / "plan.md").write_text("plan v2\n", encoding="utf-8")
        assert _run("preflight", str(tmp_path), "--phase", "build").returncode == 2
        assert _run("preflight", str(tmp_path), "--phase", "ship").returncode == 2

    def test_stop_file_blocks_scaffold(self, tmp_path: Path) -> None:
        _end_state(tmp_path)
        assert _run("approve", "--repo", str(tmp_path), "--kind", "end-state", "--decision", "approve").returncode == 0
        (tmp_path / ".harness" / "STOP").write_text("stop\n", encoding="utf-8")
        result = _run("scaffold", str(tmp_path))
        assert result.returncode == 2
        assert "STOP" in result.stderr
        assert not (tmp_path / ".harness" / "config.yaml").exists()

    def test_blocked_actions_do_not_run(self, tmp_path: Path) -> None:
        missing = _run("blocked", "--repo", str(tmp_path), "--action", "merge")
        assert missing.returncode == 2
        bad = _run("permit", "--repo", str(tmp_path), "--action", "merge", "--phrase", "approve")
        assert bad.returncode == 2
        good = _run("permit", "--repo", str(tmp_path), "--action", "merge", "--phrase", "I approve merge")
        assert good.returncode == 0, good.stderr
        refused = _run("blocked", "--repo", str(tmp_path), "--action", "merge")
        assert refused.returncode == 3
        assert "CURSOR_UNSUPPORTED" in refused.stdout
        assert "gh pr merge" not in refused.stdout

    def test_companion_bridge_does_not_install(self, tmp_path: Path) -> None:
        result = _run("bridge", "skills-check.py", str(tmp_path), "--fix")
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["installs"] == []
        assert payload["fix_ignored"] is True
        blocked = _run("bridge", "roster.py", "detect")
        assert blocked.returncode == 2
        assert "BLOCKED unsupported-runtime-script roster.py" in blocked.stdout


class TestPackage:
    def test_schema_and_twenty_seven_procedures(self) -> None:
        plugin_schema = json.loads((FIXTURES / "cursor-plugin.schema.json").read_text(encoding="utf-8"))
        market_schema = json.loads((FIXTURES / "cursor-marketplace.schema.json").read_text(encoding="utf-8"))
        plugin = json.loads((PACKAGE / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((REPO / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        _validate(plugin, plugin_schema)
        _validate(market, market_schema)
        assert plugin["displayName"] == "DT: Init to Ship Auto Agent Orchestrator"
        skills = sorted(path.parent.name for path in (PACKAGE / "skills").glob("*/SKILL.md"))
        commands = sorted(path.stem for path in (PACKAGE / "commands").glob("*.md"))
        assert "dt" in skills
        assert commands == [name for name in skills if name != "dt"]
        assert len(commands) == 27
        assert not (PACKAGE / "commands" / "dt-respond.md").exists()
        for stem in commands:
            text = (PACKAGE / "commands" / f"{stem}.md").read_text(encoding="utf-8")
            skill = (PACKAGE / "skills" / stem / "SKILL.md").read_text(encoding="utf-8")
            assert f"name: {stem}" in text
            assert f"name: {stem}" in skill
            assert "scripts/dt_gate.py" in text
            assert "CLAUDE_PLUGIN_ROOT" not in text
            assert "does not run the harness" not in text
            assert "gh pr merge" not in text
            assert (REPO / ".cursor" / "skills" / stem / "SKILL.md").read_text(encoding="utf-8") == skill
        setup = (PACKAGE / "commands" / "dt-setup.md").read_text(encoding="utf-8")
        assert "Part 1" in setup
        assert "dt_gate.py approve" in setup
        assert "The gate rejects `--scaffold-only`." in setup
        run = (PACKAGE / "skills" / "dt-run" / "SKILL.md").read_text(encoding="utf-8")
        assert "phase-1-plan.md" in run
        assert "BLOCKED unsupported-runtime-script" in run or "dt_gate.py" in run
        rule = (PACKAGE / "rules" / "instruction-edition.mdc").read_text(encoding="utf-8")
        assert "alwaysApply: false" in rule
        assert "does not attach this rule to every chat" in rule

    def test_generator_check(self) -> None:
        result = subprocess.run(
            ["python3", str(PLUGIN_ROOT / "scripts" / "cursor_surface.py"), "--check"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
