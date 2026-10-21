"""Shared helpers for dts2-harness script tests."""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def run_script(name: str, *args: str) -> dict[str, Any]:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["python3", "-I", str(PLUGIN_ROOT / "scripts" / name), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def make_tmp_home() -> Path:
    return Path(tempfile.mkdtemp(prefix="dts2-test-"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_synced(home: Path, name: str, agents: list[str], skills: list[str], preference: str) -> None:
    folder: Path = home / "plugins" / "synced" / "acct" / f"uuid-{name}"
    _write(folder / ".claude-plugin" / "plugin.json", json.dumps({"name": name}))
    _write(folder.with_suffix(".meta.json"), json.dumps({"installation_preference": preference}))
    for agent in agents:
        _write(folder / "agents" / agent, "# agent\n")
    for skill in skills:
        _write(folder / "skills" / skill / "SKILL.md", "# skill\n")


def _make_market(home: Path, plugin_id: str, agents: list[str]) -> dict[str, list[dict[str, str]]]:
    name, _, market = plugin_id.partition("@")
    for agent in agents:
        _write(home / "plugins" / "cache" / market / name / "1.0.0" / "agents" / agent, "# agent\n")
    return {plugin_id: [{"version": "1.0.0"}]}


def _usage_line(plugin: str) -> str:
    stamp: str = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    block = {"type": "tool_use", "name": "Skill", "input": {"skill": f"{plugin}:x"}}
    return json.dumps({"type": "assistant", "timestamp": stamp, "message": {"content": [block]}})


def make_fake_home(
    synced: dict[str, list[str]],
    marketplace: dict[str, list[str]],
    settings: dict[str, Any],
    usage: dict[str, int] | None = None,
    skills: dict[str, list[str]] | None = None,
    preferences: dict[str, str] | None = None,
) -> Path:
    """Build a fake ~/.claude. synced: plugin name -> agent file names; marketplace: name@market -> agents;
    usage: plugin name -> Skill calls in the last day; skills: plugin name -> skill names."""
    home: Path = make_tmp_home()
    records: dict[str, list[dict[str, str]]] = {}
    for name, agents in synced.items():
        _make_synced(home, name, agents, (skills or {}).get(name, []), (preferences or {}).get(name, "available"))
    for plugin_id, agents in marketplace.items():
        records.update(_make_market(home, plugin_id, agents))
    _write(home / "plugins" / "installed_plugins.json", json.dumps({"plugins": records}))
    _write(home / "settings.json", json.dumps(settings))
    lines: list[str] = [_usage_line(p) for p, n in (usage or {}).items() for _ in range(n)]
    _write(home / "projects" / "p" / "s.jsonl", "\n".join(lines) + "\n")
    return home
