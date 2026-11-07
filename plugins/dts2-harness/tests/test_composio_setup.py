"""scripts/composio-setup.py: status, decide, map, overlap and disable against a fake CLI and a temp home."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

from helpers import PLUGIN_ROOT

SCRIPT: Path = PLUGIN_ROOT / "scripts" / "composio-setup.py"
FAKE_CLI: str = """#!/bin/sh
case "$*" in
  "dev toolkits list") cat "$FAKE_TOOLKITS" ;;
  "dev connected-accounts list") cat "$FAKE_CONNECTED" ;;
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
"""
SLOW_CLI: str = "#!/bin/sh\nsleep 5\n"
JSON_TOOLKITS: str = json.dumps({"items": [
    {"slug": "github", "name": "GitHub", "tools": 120}, {"slug": "slack", "name": "Slack"},
    {"slug": "notion", "name": "Notion"}, {"slug": "linear", "name": "Linear"}]})
JSON_CONNECTED: str = json.dumps([{"toolkit": {"slug": "github"}}, {"toolkit_slug": "slack"}, {"app": "github"}])
TEXT_TOOLKITS: str = "SLUG   NAME\n──────────\ngithub  GitHub\n--\nslack  Slack\n\nnotion Notion\n"
TEXT_CONNECTED: str = "toolkit\n=====\ngithub  ok\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ComposioCase(unittest.TestCase):
    def setUp(self) -> None:
        base: Path = Path(tempfile.mkdtemp(prefix="dts2-composio-"))
        self.home: Path = base / "home"
        self.cwd: Path = base / "proj"
        self.state: Path = base / "state"
        self.bin_dir: Path = base / "bin"
        for folder in (self.home, self.cwd, self.bin_dir):
            folder.mkdir(parents=True)
        self.env: dict[str, str] = {k: v for k, v in os.environ.items() if k not in ("DTS2_COMPOSIO_BIN", "COMPOSIO_CACHE_DIR")}
        self.env.update({"DTS2_HOME": str(self.state), "HOME": str(self.home), "PATH": "/usr/bin:/bin"})
        patcher = mock.patch.dict(os.environ, {"DTS2_HOME": str(self.state)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_cli(self, toolkits: str, connected: str, body: str = FAKE_CLI) -> Path:
        binary: Path = write(self.bin_dir / "composio", body)
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        write(self.bin_dir / "toolkits.txt", toolkits)
        write(self.bin_dir / "connected.txt", connected)
        self.env.update({"DTS2_COMPOSIO_BIN": str(binary), "FAKE_TOOLKITS": str(self.bin_dir / "toolkits.txt"),
                         "FAKE_CONNECTED": str(self.bin_dir / "connected.txt")})
        return binary

    def run_cli(self, *args: str, expect: int = 0, scoped: bool = True) -> dict[str, Any]:
        extra: list[str] = ["--home", str(self.home), "--cwd", str(self.cwd)] if scoped else []
        result = subprocess.run(["python3", "-I", str(SCRIPT), *args, *extra], capture_output=True, text=True,
                                env=self.env, cwd=str(PLUGIN_ROOT), check=False)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed

    def settings(self, scope: str, data: dict[str, Any]) -> Path:
        names = {"user": self.home / ".claude" / "settings.json", "project": self.cwd / ".claude" / "settings.json",
                 "local": self.cwd / ".claude" / "settings.local.json"}
        return write(names[scope], json.dumps(data))

    def import_map(self, connected: list[str], toolkits: list[str] | None = None) -> Path:
        source: Path = write(self.bin_dir / "import.json",
                             json.dumps({"toolkits": toolkits or connected, "connected": connected}))
        self.run_cli("map", "--from-json", str(source), scoped=False)
        return source

    def skill(self, name: str) -> Path:
        return write(self.home / ".claude" / "skills" / name / "SKILL.md", "# s\n")


class DecideAndStatusTests(ComposioCase):
    def test_status_empty_machine(self) -> None:
        out = self.run_cli("status")
        self.assertFalse(out["cli"])
        self.assertIsNone(out["cli_path"])
        self.assertFalse(out["logged_in"])
        self.assertFalse(out["plugin_enabled"])
        self.assertEqual(out["mcp_servers"], [])
        self.assertFalse(out["duplicate_connection"])
        self.assertIsNone(out["decision"])
        self.assertFalse(out["tool_map"]["exists"])
        self.assertEqual(out["tool_map"]["toolkits"], 0)

    def test_decide_writes_and_status_reads_it(self) -> None:
        out = self.run_cli("decide", "--account", "yes", "--always-use", "--connection", "plugin", scoped=False)
        self.assertEqual((out["account"], out["always_use"], out["connection"]), ("yes", True, "plugin"))
        self.assertRegex(out["decided_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        on_disk = json.loads((self.state / "composio.json").read_text())
        self.assertEqual(on_disk, out)
        self.assertEqual(self.run_cli("status")["decision"], out)

    def test_decide_defaults_and_rejects_bad_choice(self) -> None:
        out = self.run_cli("decide", "--account", "no", scoped=False)
        self.assertEqual((out["always_use"], out["connection"]), (False, None))
        self.assertEqual(subprocess.run(["python3", "-I", str(SCRIPT), "decide", "--account", "maybe"],
                                        capture_output=True, env=self.env, check=False).returncode, 2)

    def test_status_detects_cli_login_plugin_and_servers(self) -> None:
        binary = self.fake_cli("[]", "[]")
        (self.home / ".composio").mkdir()
        self.settings("user", {"enabledPlugins": {"composio@composio": True}})
        write(self.cwd / ".mcp.json", json.dumps({"mcpServers": {"Composio-Connect": {}, "other": {}}}))
        write(self.home / ".claude.json", json.dumps({
            "mcpServers": {"composio-user": {}},
            "projects": {str(self.cwd): {"mcpServers": {"my-COMPOSIO-local": {}}}}}))
        out = self.run_cli("status")
        self.assertEqual((out["cli"], out["cli_path"], out["logged_in"]), (True, str(binary), True))
        self.assertTrue(out["plugin_enabled"])
        self.assertEqual(out["mcp_servers"], ["Composio-Connect", "composio-user", "my-COMPOSIO-local"])
        self.assertTrue(out["duplicate_connection"])

    def test_plugin_disabled_in_settings_is_not_enabled(self) -> None:
        self.settings("project", {"enabledPlugins": {"composio@composio": False}})
        self.assertFalse(self.run_cli("status")["plugin_enabled"])
        self.settings("local", {"enabledPlugins": {"composio@composio": True}})
        self.assertTrue(self.run_cli("status")["plugin_enabled"])

    def test_cache_dir_override_decides_login(self) -> None:
        cache = self.home / "elsewhere"
        cache.mkdir()
        self.env["COMPOSIO_CACHE_DIR"] = str(cache)
        self.assertTrue(self.run_cli("status")["logged_in"])


class MapTests(ComposioCase):
    def test_map_from_json_cli_output(self) -> None:
        self.fake_cli(JSON_TOOLKITS, JSON_CONNECTED)
        out = self.run_cli("map", scoped=False)
        self.assertEqual((out["source"], out["toolkits"], out["connected"]), ("cli", 4, ["github", "slack"]))
        saved = json.loads((self.state / "composio-tools.json").read_text())
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["source"], "cli")
        by_slug = {t["slug"]: t for t in saved["toolkits"]}
        self.assertEqual(by_slug["github"], {"slug": "github", "name": "GitHub", "connected": True, "tools": 120})
        self.assertEqual(by_slug["notion"], {"slug": "notion", "name": "Notion", "connected": False, "tools": None})
        self.assertEqual(self.run_cli("status")["tool_map"]["connected"], ["github", "slack"])

    def test_map_from_text_output_skips_headers_and_rules(self) -> None:
        self.fake_cli(TEXT_TOOLKITS, TEXT_CONNECTED)
        out = self.run_cli("map", scoped=False)
        self.assertEqual((out["toolkits"], out["connected"]), (3, ["github"]))

    def test_map_accepts_bare_json_list(self) -> None:
        self.fake_cli(json.dumps([{"key": "jira"}, {"name": "asana"}]), json.dumps({"data": [{"appName": "jira"}]}))
        out = self.run_cli("map", scoped=False)
        self.assertEqual((out["toolkits"], out["connected"]), (2, ["jira"]))

    def test_map_from_json_import(self) -> None:
        source = write(self.bin_dir / "meta.json", json.dumps({
            "toolkits": ["github", {"slug": "slack", "name": "Slack", "tools": 7}], "connected": ["slack"]}))
        out = self.run_cli("map", "--from-json", str(source), scoped=False)
        self.assertEqual((out["source"], out["toolkits"], out["connected"]), ("import", 2, ["slack"]))
        saved = json.loads((self.state / "composio-tools.json").read_text())
        self.assertEqual(saved["toolkits"][1]["tools"], 7)
        self.assertEqual([t["connected"] for t in saved["toolkits"]], [False, True])

    def test_map_without_binary_exits_two(self) -> None:
        out = self.run_cli("map", expect=2, scoped=False)
        self.assertEqual(out["error"], "composio CLI not found")
        self.assertIn("hint", out)
        self.assertFalse((self.state / "composio-tools.json").exists())

    def test_map_with_missing_override_binary_exits_two(self) -> None:
        self.env["DTS2_COMPOSIO_BIN"] = str(self.bin_dir / "nope")
        self.run_cli("map", expect=2, scoped=False)

    def test_map_timeout_is_honoured(self) -> None:
        self.fake_cli("[]", "[]", body=SLOW_CLI)
        out = self.run_cli("map", "--timeout", "1", expect=1, scoped=False)
        self.assertIn("error", out)

    def test_map_cli_failure_reports_error(self) -> None:
        self.fake_cli("[]", "[]", body="#!/bin/sh\nexit 3\n")
        self.assertIn("error", self.run_cli("map", expect=1, scoped=False))

    def test_no_secret_fields_are_stored(self) -> None:
        self.fake_cli(json.dumps([{"slug": "github", "api_key": "sk-secret"}]), "[]")
        self.run_cli("map", scoped=False)
        self.assertNotIn("sk-secret", (self.state / "composio-tools.json").read_text())


class OverlapTests(ComposioCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings("user", {"enabledPlugins": {
            "github@claude-plugins-official": True, "slack@mkt": True, "composio@composio": True,
            "dt@dts2": True, "linear@mkt": False, "keepme@mkt": True, "impeccable@x": True}})
        self.settings("project", {"enabledPlugins": {"notion@mkt": True}})
        write(self.cwd / ".mcp.json", json.dumps({"mcpServers": {"github-mcp": {}, "composio-github": {}, "Slack": {}}}))
        write(self.home / ".claude.json", json.dumps({"mcpServers": {"notion-server": {}}}))
        for name in ("github", "slack-helper", "unrelated"):
            self.skill(name)

    def ids(self, out: dict[str, Any]) -> set[tuple[str, str, str]]:
        return {(c["kind"], c["id"], c["scope"]) for c in out["candidates"]}

    def test_overlap_requires_a_map(self) -> None:
        out = self.run_cli("overlap", expect=2)
        self.assertIn("error", out)

    def test_candidates_only_for_connected_toolkits(self) -> None:
        self.import_map(["github", "slack"], ["github", "slack", "notion", "linear"])
        out = self.run_cli("overlap")
        self.assertEqual(self.ids(out), {
            ("plugin", "github@claude-plugins-official", "user"), ("plugin", "slack@mkt", "user"),
            ("mcp", "github-mcp", "project"), ("mcp", "Slack", "project"),
            ("skill", "github", "user"), ("skill", "slack-helper", "user")})
        self.assertTrue(all(c["toolkit"] in ("github", "slack") for c in out["candidates"]))

    def test_all_flag_includes_unconnected_toolkits(self) -> None:
        self.import_map(["github"], ["github", "slack", "notion", "linear"])
        ids = self.ids(self.run_cli("overlap", "--all"))
        self.assertIn(("plugin", "notion@mkt", "project"), ids)
        self.assertIn(("mcp", "notion-server", "user"), ids)
        self.assertNotIn(("plugin", "linear@mkt", "user"), ids)  # disabled plugins are not enabled

    def test_composio_and_harness_never_listed_and_reported_kept(self) -> None:
        self.import_map(["github"])
        out = self.run_cli("overlap")
        listed = {c["id"] for c in out["candidates"]}
        self.assertNotIn("composio-github", listed)
        self.assertNotIn("composio@composio", listed)
        self.assertNotIn("dt@dts2", listed)
        self.assertIn({"id": "composio-github", "reason": "composio"}, out["kept"])

    def test_required_by_harness_and_keep_yaml_are_kept(self) -> None:
        profile = write(self.bin_dir / "profile.json", json.dumps({"requiredByHarness": ["slack@*"]}))
        write(self.cwd / ".harness" / "keep.yaml", "plugins:\n  - github@claude-plugins-official\n")
        self.import_map(["github", "slack"])
        out = self.run_cli("overlap", "--profile", str(profile))
        listed = {c["id"] for c in out["candidates"]}
        self.assertNotIn("slack@mkt", listed)
        self.assertNotIn("github@claude-plugins-official", listed)
        reasons = {k["id"]: k["reason"] for k in out["kept"]}
        self.assertEqual(reasons["slack@mkt"], "requiredByHarness")
        self.assertEqual(reasons["github@claude-plugins-official"], "keep.yaml")
        self.assertIn("github-mcp", listed)

    def test_default_blueprint_profile_protects_required_plugins(self) -> None:
        self.settings("user", {"enabledPlugins": {"impeccable@figma-pack": True, "figma@x": True}})
        self.import_map(["figma"])
        listed = {c["id"] for c in self.run_cli("overlap")["candidates"]}
        self.assertIn("figma@x", listed)
        self.assertNotIn("impeccable@figma-pack", listed)

    def test_servers_already_disabled_in_project_are_not_listed(self) -> None:
        self.settings("local", {"disabledMcpjsonServers": ["github-mcp"]})
        self.import_map(["github"])
        self.assertNotIn("github-mcp", {c["id"] for c in self.run_cli("overlap")["candidates"]})

    def test_profile_covers_required_toolkits(self) -> None:
        data = json.loads((PLUGIN_ROOT / "profiles" / "composio-overlap.json").read_text())
        needed = ("github gitlab slack notion linear gmail googlecalendar googledrive googledocs googlesheets outlook "
                  "microsoft_teams jira confluence asana clickup airtable hubspot stripe supabase vercel sentry posthog "
                  "mixpanel amplitude figma canva webflow apollo semrush firecrawl exa perplexityai mem0").split()
        self.assertEqual(data["version"], 1)
        for slug in needed:
            self.assertEqual(set(data["toolkits"][slug]), {"plugins", "mcp", "skills"}, slug)

    def test_short_slug_does_not_match_unrelated_server(self) -> None:
        write(self.cwd / ".mcp.json", json.dumps({"mcpServers": {"regexalyzer": {}, "exa": {}}}))
        self.import_map(["exa"])
        listed = {c["id"] for c in self.run_cli("overlap")["candidates"]}
        self.assertIn("exa", listed)
        self.assertNotIn("regexalyzer", listed)


class DisableTests(ComposioCase):
    def setUp(self) -> None:
        super().setUp()
        self.user_settings = self.settings("user", {"theme": "dark", "enabledPlugins": {
            "github@official": True, "keep@mkt": True}})
        self.local_settings = self.settings("local", {"permissions": {"allow": []}})
        write(self.cwd / ".mcp.json", json.dumps({"mcpServers": {"github-mcp": {}}}))
        write(self.home / ".claude.json", json.dumps({
            "mcpServers": {"slack-user": {}},
            "projects": {str(self.cwd): {"mcpServers": {"notion-local": {}}}}}))
        self.skill("github-helper")
        self.import_map(["github", "slack", "notion"])

    def snapshot(self) -> dict[str, str]:
        return {str(p): p.read_text() for p in sorted((self.home).rglob("*")) + sorted(self.cwd.rglob("*")) if p.is_file()}

    def test_dry_run_changes_nothing(self) -> None:
        before = self.snapshot()
        out = self.run_cli("disable", "--ids", "github@official,github-mcp,github-helper,slack-user,nope", "--dry-run")
        self.assertTrue(out["dry_run"])
        self.assertEqual({c["kind"] for c in out["changed"]}, {"plugin", "mcp", "skill"})
        self.assertEqual(out["skipped"], ["nope"])
        self.assertEqual(out["backups"], [])
        self.assertEqual(self.snapshot(), before)

    def test_plugin_disable_backs_up_and_sets_false(self) -> None:
        out = self.run_cli("disable", "--ids", "github@official")
        self.assertEqual(out["changed"], [{"kind": "plugin", "id": "github@official", "file": str(self.user_settings)}])
        data = json.loads(self.user_settings.read_text())
        self.assertEqual(data["enabledPlugins"], {"github@official": False, "keep@mkt": True})
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(len(out["backups"]), 1)
        backup = Path(out["backups"][0])
        self.assertRegex(backup.name, r"^settings\.json\.bak-\d{8}T\d{6}Z")
        self.assertTrue(json.loads(backup.read_text())["enabledPlugins"]["github@official"])

    def test_skill_is_archived_not_deleted(self) -> None:
        out = self.run_cli("disable", "--ids", "github-helper")
        archived = self.home / ".claude" / "skills-archive" / "github-helper"
        self.assertEqual(out["changed"][0]["file"], str(archived))
        self.assertTrue((archived / "SKILL.md").is_file())
        self.assertFalse((self.home / ".claude" / "skills" / "github-helper").exists())

    def test_skill_archive_name_collision_gets_a_suffix(self) -> None:
        write(self.home / ".claude" / "skills-archive" / "github-helper" / "old.md", "old")
        out = self.run_cli("disable", "--ids", "github-helper")
        target = Path(out["changed"][0]["file"])
        self.assertTrue(target.name.startswith("github-helper-"))
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((self.home / ".claude" / "skills-archive" / "github-helper" / "old.md").is_file())

    def test_project_mcp_is_listed_in_disabled_servers(self) -> None:
        out = self.run_cli("disable", "--ids", "github-mcp")
        self.assertEqual(out["changed"], [{"kind": "mcp", "id": "github-mcp", "file": str(self.local_settings)}])
        data = json.loads(self.local_settings.read_text())
        self.assertEqual(data["disabledMcpjsonServers"], ["github-mcp"])
        self.assertEqual(data["permissions"], {"allow": []})
        self.assertEqual(len(out["backups"]), 1)
        self.assertIn("github-mcp", (self.cwd / ".mcp.json").read_text())

    def test_project_mcp_creates_local_settings_without_backup(self) -> None:
        self.local_settings.unlink()
        out = self.run_cli("disable", "--ids", "github-mcp")
        self.assertEqual(out["backups"], [])
        self.assertEqual(json.loads(self.local_settings.read_text())["disabledMcpjsonServers"], ["github-mcp"])

    def test_user_and_local_scope_mcp_are_manual_steps(self) -> None:
        before = (self.home / ".claude.json").read_text()
        out = self.run_cli("disable", "--ids", "slack-user,notion-local")
        self.assertEqual(out["changed"], [])
        self.assertEqual(sorted(out["manual"]), ["claude mcp remove notion-local --scope local",
                                                 "claude mcp remove slack-user --scope user"])
        self.assertEqual((self.home / ".claude.json").read_text(), before)

    def test_mcp_in_project_and_user_scope_handles_both(self) -> None:
        write(self.home / ".claude.json", json.dumps({"mcpServers": {"github-mcp": {}, "slack-user": {}}}))
        out = self.run_cli("disable", "--ids", "github-mcp")
        self.assertEqual(out["changed"], [{"kind": "mcp", "id": "github-mcp", "file": str(self.local_settings)}])
        self.assertEqual(json.loads(self.local_settings.read_text())["disabledMcpjsonServers"], ["github-mcp"])
        self.assertEqual(out["manual"], ["claude mcp remove github-mcp --scope user"])

    def test_second_run_is_idempotent(self) -> None:
        ids = "github@official,github-mcp,github-helper"
        first = self.run_cli("disable", "--ids", ids)
        self.assertEqual(len(first["changed"]), 3)
        after_first = self.snapshot()
        second = self.run_cli("disable", "--ids", ids)
        self.assertEqual((second["changed"], second["backups"]), ([], []))
        self.assertEqual(sorted(second["skipped"]), sorted(ids.split(",")))
        self.assertEqual(self.snapshot(), after_first)

    def test_only_overlap_candidates_can_be_disabled(self) -> None:
        out = self.run_cli("disable", "--ids", "keep@mkt")
        self.assertEqual((out["changed"], out["skipped"]), ([], ["keep@mkt"]))
        self.assertTrue(json.loads(self.user_settings.read_text())["enabledPlugins"]["keep@mkt"])

    def test_composio_cannot_be_disabled(self) -> None:
        self.settings("user", {"enabledPlugins": {"composio@composio": True}})
        out = self.run_cli("disable", "--ids", "composio@composio")
        self.assertEqual(out["skipped"], ["composio@composio"])

    def test_disable_without_map_exits_two(self) -> None:
        (self.state / "composio-tools.json").unlink()
        self.run_cli("disable", "--ids", "x", expect=2)


if __name__ == "__main__":
    unittest.main()
