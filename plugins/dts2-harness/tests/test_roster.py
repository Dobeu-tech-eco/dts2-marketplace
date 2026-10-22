"""Tests for agent profiles and scripts/roster.py."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, run_script

PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
PROFILE_NAMES: Final[tuple[str, ...]] = (
    "claude", "codex", "gemini", "opencode", "copilot", "cursor", "antigravity", "grok", "muse",
)
SCHEMA_KEYS: Final[frozenset[str]] = frozenset({
    "name", "displayName", "form", "rulesFile", "invocation", "command",
    "headlessFlag", "roles", "specialty", "verified",
    "costTier", "statusCommand", "loginCommand", "models", "modelsVerified",
    "subscriptionName", "apiKeyEnv", "searchPaths",
})
OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"roleCommands", "notes", "stdin", "fallback", "env"})
VERIFIED: Final[frozenset[str]] = frozenset({"claude", "codex", "opencode"})
COST_TIERS: Final[dict[str, int]] = {
    "claude": 3, "codex": 2, "gemini": 1, "opencode": 1,
    "copilot": 2, "cursor": 2, "antigravity": 2, "grok": 2, "muse": 2,
}
MODEL_TIERS: Final[tuple[str, ...]] = ("frontier", "standard", "economy")
LIVE_AGENTS: Final[frozenset[str]] = frozenset({
    "claude", "codex", "gemini", "opencode", "copilot", "grok", "muse",
})
ROSTER: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"
FIXTURES: Final[Path] = PLUGIN_ROOT / "tests" / "fixtures" / "classify"


def recorded(name: str) -> str:
    """Recorded CLI output (see fixtures/classify/README.txt); never hand-written."""
    return (FIXTURES / name).read_text(encoding="utf-8")


BILLING_402: Final[str] = recorded("muse-402.txt")
QUOTA_429: Final[str] = recorded("muse-429.txt")
RESET: Final[str] = "2026-10-22T12:54:03Z"
GROK_PROTECTED_DIRS: Final[tuple[str, ...]] = (".git", ".grok", ".claude", ".cursor")
GROK_BUILDER_PATH_DENIES: Final[tuple[str, ...]] = (
    "Edit(**/.git/**)", "Edit(**/.git)", "Write(**/.git/**)", "Write(**/.git)",
    "Edit(**/.grok/**)", "Write(**/.grok/**)", "Edit(**/.claude/**)", "Write(**/.claude/**)",
    "Edit(**/.cursor/**)", "Write(**/.cursor/**)",
)
QUOTE_MARKERS: Final[tuple[str, ...]] = ("- ", "* ", "> ", "| ", "1. ", "  - ", 'muse.json:48: "')


def write_config(text: str) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-roster-"))
    path: Path = folder / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def isolated_env(path: str) -> dict[str, str]:
    """PATH-only env with HOME and the Windows app dirs pointed at an empty folder, so profile
    searchPaths such as ~/.local/bin never find binaries installed on the host."""
    home: str = tempfile.mkdtemp(prefix="dts2-home-")
    return {"PATH": path, "HOME": home, "LOCALAPPDATA": home, "APPDATA": home}


def raw_run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(ROSTER), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env=env,
    )


class ProfileTests(unittest.TestCase):
    def test_every_profile_has_schema(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertTrue(SCHEMA_KEYS <= set(data), name)
            self.assertTrue(set(data) <= SCHEMA_KEYS | OPTIONAL_KEYS, name)
            self.assertEqual(data["name"], name)
            self.assertEqual(data["verified"], name in VERIFIED, name)

    def test_claude_roles(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "claude.json").read_text())
        self.assertIn("lead", data["roles"])
        self.assertIn("verifier", data["roles"])

    def test_ide_profiles_are_handoff(self) -> None:
        for name in ("cursor", "antigravity"):
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["invocation"], "handoff")
            self.assertIsNone(data["command"])


class ProfileExtensionTests(unittest.TestCase):
    def test_cost_tiers_and_model_keys(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["costTier"], COST_TIERS[name], name)
            self.assertEqual(set(data["models"]), set(MODEL_TIERS), name)
            self.assertIsInstance(data["modelsVerified"], bool)
            self.assertEqual(data["modelsVerified"], name == "claude", name)

    def test_status_commands(self) -> None:
        expected: dict[str, Any] = {
            "claude": ["claude", "auth", "status"], "codex": ["codex", "login", "status"],
            "gemini": ["agy", "--version"], "opencode": ["opencode", "--version"],
            "copilot": ["gh", "auth", "status"], "grok": ["grok", "version"],
            "muse": ["muse", "--version"], "cursor": None, "antigravity": None,
        }
        for name, command in expected.items():
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["statusCommand"], command, name)

    def test_login_commands(self) -> None:
        expected: dict[str, Any] = {
            "claude": ["claude", "auth", "status"], "codex": ["codex", "login", "status"],
            "copilot": ["gh", "auth", "status"], "gemini": None, "grok": None,
            "opencode": None, "cursor": None, "antigravity": None, "muse": None,
        }
        for name, command in expected.items():
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["loginCommand"], command, name)

    def test_grok_profile(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "grok.json").read_text())
        self.assertEqual(data["form"], "cli")
        self.assertEqual(data["rulesFile"], "AGENTS.md")
        self.assertEqual(data["invocation"], "live")
        self.assertEqual(data["command"], ["grok", "-p"])
        self.assertIsNone(data["headlessFlag"])
        self.assertEqual(data["roles"], ["builder", "reviewer", "second-opinion"])
        self.assertFalse(data["verified"])
        self.assertEqual(data["models"], {
            "frontier": "grok-4.7", "standard": "grok-4.7", "economy": "grok-4.7-build-fast",
        })
        self.assertEqual(data["roleCommands"]["reviewer"], [
            "grok", "--prompt-file", "{promptFile}", "-m", "{model}", "--permission-mode", "plan",
            "--deny", "Bash", "--deny", "Edit", "--deny", "Write", "--deny", "MCPTool",
            "--no-subagents", "--disable-web-search",
        ])
        self.assertEqual(data["roleCommands"]["builder"], [
            "grok", "--prompt-file", "{promptFile}", "-m", "{model}", "--permission-mode", "acceptEdits",
            "--allow", "Edit(./**)", "--allow", "Write(./**)", "--deny", "Bash",
            *[part for rule in GROK_BUILDER_PATH_DENIES for part in ("--deny", rule)],
            "--deny", "MCPTool", "--no-subagents", "--disable-web-search",
        ])
        self.assertEqual(data["env"], {"GROK_WORKFLOWS": "0"})
        notes: str = " ".join(data["notes"])
        self.assertIn("GROK_WORKFLOWS=0", notes)
        for phrase in ("subagents", "~/.claude/settings.json", ".claude/settings.json", "~/.grok/config.toml"):
            self.assertIn(phrase, notes)
        self.assertTrue(any("auto-denied" in note for note in data["notes"]))

    def test_notes_and_role_commands_shape(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            for note in data.get("notes", []):
                self.assertIsInstance(note, str, name)
            for role, argv in data.get("roleCommands", {}).items():
                self.assertIn(role.split(":")[0], {r.split(":")[0] for r in data["roles"]}, name)
                self.assertTrue({"{prompt}", "{promptFile}"} & set(argv), f"{name} {role}")

    def test_gemini_profile_roles(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "gemini.json").read_text())
        self.assertEqual(data["roles"], ["builder", "reviewer", "second-opinion"])

    def test_gemini_profile_runs_agy_headless(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "gemini.json").read_text())
        self.assertEqual(data["statusCommand"], ["agy", "--version"])
        self.assertEqual(data["models"], {
            "frontier": "gemini-3.8-flash-high", "standard": "gemini-3.8-flash-medium",
            "economy": "gemini-3.8-flash-low",
        })
        for role in ("reviewer", "builder"):
            argv: list[str] = data["roleCommands"][role]
            self.assertEqual(argv[:3], ["agy", "-p", "{prompt}"], role)
            self.assertEqual(argv[argv.index("--mode") + 1], "plan", role)
            self.assertEqual(argv[argv.index("--model") + 1], "{model}", role)
            self.assertRegex(argv[argv.index("--print-timeout") + 1], r"^\d+m$", role)
            self.assertEqual(argv[argv.index("--add-dir") + 1], "{addDir}", role)
        notes: str = " ".join(data["notes"])
        for phrase in ("--add-dir", "run it from the target repo", "never ask it to run commands"):
            self.assertIn(phrase, notes)

    def test_codex_profile(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "codex.json").read_text())
        self.assertEqual(data["models"], {"frontier": None, "standard": None, "economy": None})
        self.assertNotIn("gpt-5-codex", json.dumps(data["models"]) + json.dumps(data["roleCommands"]))
        self.assertEqual(data["stdin"], "/dev/null")
        self.assertEqual(data["roleCommands"]["builder"], ["codex", "exec", "-m", "{model}", "--", "{prompt}"])
        self.assertEqual(data["roleCommands"]["second-opinion"], [
            "codex", "exec", "-m", "{model}", "--sandbox", "read-only", "--", "{prompt}",
        ])
        notes: str = " ".join(data["notes"])
        self.assertIn("do not commit", notes)
        self.assertIn("lead commits", notes)
        self.assertIn("< /dev/null", notes)

    def test_muse_profile(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "muse.json").read_text())
        self.assertEqual(data["form"], "cli")
        self.assertEqual(data["invocation"], "live")
        self.assertEqual(data["command"], ["muse", "exec"])
        self.assertEqual(data["roles"], ["builder", "second-opinion"])
        self.assertEqual(data["roleCommands"]["second-opinion"], [
            "muse", "exec", "--model", "{model}", "--workspace", "{workspace}", "--prompt-file", "{promptFile}",
            "--disable-write", "--disable-shell", "--disable-web-tools",
        ])
        self.assertNotIn("reviewer", data["roleCommands"])
        self.assertEqual(data["models"], {
            "frontier": "muse-wonder-1.0", "standard": "muse-spark-1.3", "economy": "muse-spark-1.3",
        })
        self.assertEqual(data["searchPaths"], [])
        self.assertEqual(data["roleCommands"]["builder"], [
            "muse", "exec", "--model", "{model}", "--workspace", "{workspace}", "--prompt-file", "{promptFile}",
        ])
        notes: str = " ".join(data["notes"])
        for phrase in ("muse login", "402", "429", "unavailable (billing/quota)",
                       "no read-only permission profile", "second-opinion only"):
            self.assertIn(phrase, notes)

    def test_only_gemini_owns_agy(self) -> None:
        owners: list[str] = []
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            commands: list[list[str]] = [data["command"] or [], data["statusCommand"] or []]
            commands += list((data.get("roleCommands") or {}).values())
            if any(c and c[0] == "agy" for c in commands):
                owners.append(name)
        self.assertEqual(owners, ["gemini"])
        antigravity: dict[str, Any] = json.loads((PROFILE_DIR / "antigravity.json").read_text())
        self.assertIn("gemini profile", " ".join(antigravity["notes"]))


class ModelTests(unittest.TestCase):
    def model(self, agent: str, tier: str) -> str:
        return raw_run("model", "--agent", agent, "--tier", tier).stdout.strip()

    def test_claude_models(self) -> None:
        self.assertEqual(self.model("claude", "frontier"), "opus")
        self.assertEqual(self.model("claude", "standard"), "sonnet")
        self.assertEqual(self.model("claude", "economy"), "haiku")

    def test_null_model(self) -> None:
        self.assertEqual(self.model("cursor", "frontier"), "null")

    def test_grok_model(self) -> None:
        self.assertEqual(self.model("grok", "economy"), "grok-4.7-build-fast")


def command(agent: str, role: str, tier: str = "standard") -> subprocess.CompletedProcess[str]:
    return raw_run("command", "--agent", agent, "--role", role, "--tier", tier)


class CommandTests(unittest.TestCase):
    def resolved(self, agent: str, role: str, tier: str = "standard") -> dict[str, Any]:
        result = command(agent, role, tier)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @staticmethod
    def rules(argv: list[str], flag: str) -> list[str]:
        return [argv[i + 1] for i, part in enumerate(argv) if part == flag]

    def test_grok_reviewer_is_plan_mode(self) -> None:
        data: dict[str, Any] = self.resolved("grok", "reviewer", "frontier")
        argv: list[str] = data["argv"]
        self.assertEqual(data["model"], "grok-4.7")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertEqual(argv[argv.index("-m") + 1], "grok-4.7")
        self.assertEqual(self.rules(argv, "--allow"), [])

    def test_grok_reviewer_cannot_write_spawn_or_use_mcp(self) -> None:
        argv: list[str] = self.resolved("grok", "reviewer")["argv"]
        self.assertEqual(sorted(self.rules(argv, "--deny")), ["Bash", "Edit", "MCPTool", "Write"])
        self.assertIn("--no-subagents", argv)
        self.assertIn("--disable-web-search", argv)

    def test_grok_builder_allows_edits_not_shell(self) -> None:
        argv: list[str] = self.resolved("grok", "builder", "economy")["argv"]
        self.assertIn("grok-4.7-build-fast", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(self.rules(argv, "--allow"), ["Edit(./**)", "Write(./**)"])
        self.assertEqual(sorted(self.rules(argv, "--deny")), sorted([
            "Bash", "MCPTool", *GROK_BUILDER_PATH_DENIES,
        ]))
        self.assertIn("--no-subagents", argv)
        self.assertIn("--disable-web-search", argv)

    def test_grok_builder_denies_every_hook_folder_unrooted(self) -> None:
        denies: list[str] = self.rules(self.resolved("grok", "builder")["argv"], "--deny")
        for folder in GROK_PROTECTED_DIRS:
            for tool in ("Edit", "Write"):
                self.assertIn(f"{tool}(**/{folder}/**)", denies)
        for tool in ("Edit", "Write"):
            self.assertIn(f"{tool}(**/.git)", denies)
        self.assertFalse([r for r in denies if "(." in r], "path denies must be unrooted (**/...)")

    def test_second_opinion_uses_reviewer_command(self) -> None:
        self.assertIn("plan", self.resolved("grok", "second-opinion")["argv"])

    def test_role_suffix_uses_base_role_command(self) -> None:
        self.assertIn("plan", self.resolved("grok", "reviewer:security")["argv"])

    def test_fallback_to_profile_command(self) -> None:
        self.assertEqual(self.resolved("opencode", "builder")["argv"], ["opencode", "run", "{prompt}"])

    def test_gemini_reviewer_resolves_model(self) -> None:
        argv: list[str] = self.resolved("gemini", "reviewer", "frontier")["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-3.8-flash-high")

    def test_null_model_drops_model_flag(self) -> None:
        self.assertEqual(self.resolved("claude", "builder")["model"], "sonnet")
        self.assertIsNone(self.resolved("opencode", "builder")["model"])
        data: dict[str, Any] = self.resolved("codex", "builder", "frontier")
        self.assertIsNone(data["model"])
        self.assertEqual(data["argv"], ["codex", "exec", "--", "{prompt}"])

    def test_codex_stdin_is_dev_null(self) -> None:
        self.assertEqual(self.resolved("codex", "builder")["stdin"], "/dev/null")
        self.assertIsNone(self.resolved("grok", "builder")["stdin"])

    def filled(self, agent: str, role: str) -> tuple[dict[str, Any], Path]:
        folder: Path = Path(tempfile.mkdtemp(prefix="dts2-prompt-"))
        brief: Path = (folder / "brief.md").resolve()
        brief.write_text("SECRET-BRIEF-TEXT $(rm -rf /) `id`\n", encoding="utf-8")
        workspace: str = tempfile.mkdtemp(prefix="dts2-ws-")
        result = raw_run("command", "--agent", agent, "--role", role, "--prompt-file", str(brief),
                         "--workspace", workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout), brief

    def test_prompt_file_fills_every_token(self) -> None:
        for agent, role in (("grok", "reviewer"), ("grok", "builder"), ("gemini", "reviewer"),
                            ("codex", "builder"), ("codex", "second-opinion"), ("muse", "builder"),
                            ("opencode", "builder"), ("claude", "reviewer")):
            data, brief = self.filled(agent, role)
            self.assertFalse([p for p in data["argv"] if "{" in p], f"{agent} {role}")
            self.assertNotIn("SECRET-BRIEF-TEXT", data["shell"], f"{agent} {role}")
            self.assertNotIn("SECRET-BRIEF-TEXT", json.dumps(data["argv"]), f"{agent} {role}")

    def test_grok_shell_line_disables_workflows(self) -> None:
        for role in ("reviewer", "builder"):
            data, _ = self.filled("grok", role)
            self.assertEqual(data["env"], {"GROK_WORKFLOWS": "0"})
            self.assertEqual(data["shell"], shlex.join(["env", "GROK_WORKFLOWS=0", *data["argv"]]))

    def test_env_is_empty_for_other_agents(self) -> None:
        data, _ = self.filled("codex", "builder")
        self.assertEqual(data["env"], {})
        self.assertFalse(data["shell"].startswith("env "))

    def test_env_without_prompt_file(self) -> None:
        self.assertEqual(self.resolved("grok", "reviewer")["env"], {"GROK_WORKFLOWS": "0"})

    def test_grok_reads_the_prompt_file(self) -> None:
        data, brief = self.filled("grok", "reviewer")
        self.assertEqual(data["argv"][data["argv"].index("--prompt-file") + 1], str(brief))

    def test_gemini_points_at_the_file_and_adds_its_folder(self) -> None:
        data, brief = self.filled("gemini", "reviewer")
        argv: list[str] = data["argv"]
        self.assertIn(str(brief), argv[2])
        self.assertEqual(argv[argv.index("--add-dir") + 1], str(brief.parent))

    def test_codex_shell_line_is_quoted_with_dev_null(self) -> None:
        data, brief = self.filled("codex", "builder")
        self.assertEqual(data["argv"][-2], "--")
        self.assertIn(str(brief), data["argv"][-1])
        self.assertEqual(data["shell"], shlex.join(data["argv"]) + " < /dev/null")

    def test_binary_found_through_search_paths(self) -> None:
        env: dict[str, str] = isolated_env(tempfile.mkdtemp(prefix="dts2-path-"))
        local: Path = Path(env["HOME"]) / ".local" / "bin"
        local.mkdir(parents=True)
        (local / "agy").write_text("#!/bin/sh\n")
        (local / "agy").chmod(0o755)
        result = raw_run("command", "--agent", "gemini", "--role", "reviewer", env=env)
        self.assertEqual(json.loads(result.stdout)["binary"], str(local / "agy"))

    def test_binary_null_when_missing(self) -> None:
        env: dict[str, str] = isolated_env(tempfile.mkdtemp(prefix="dts2-path-"))
        result = raw_run("command", "--agent", "gemini", "--role", "reviewer", env=env)
        self.assertIsNone(json.loads(result.stdout)["binary"])

    def test_muse_reviewer_seat_rejected(self) -> None:
        self.assertEqual(command("muse", "reviewer").returncode, 1)

    def test_muse_workspace_is_filled(self) -> None:
        data, _ = self.filled("muse", "builder")
        self.assertTrue(Path(data["argv"][data["argv"].index("--workspace") + 1]).is_dir())

    def test_unsupported_role_rejected(self) -> None:
        result = command("grok", "lead")
        self.assertEqual(result.returncode, 1)
        self.assertIn("lead", result.stderr)

    def test_handoff_agent_has_no_command(self) -> None:
        self.assertEqual(command("cursor", "builder").returncode, 1)


def fake_bin(names: list[str]) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-fake-"))
    for name in names:
        script: Path = folder / name
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
    return str(folder)


def probe(config_text: str, path: str) -> dict[str, Any]:
    env: dict[str, str] = {**isolated_env(path), "DTS2_PROBE_PATH": path}
    cfg: str = write_config(config_text)
    result = raw_run("probe", "--config", cfg, env=env)
    return json.loads(result.stdout)


ALL_LIVE_ROSTER: Final[str] = (
    "roster:\n" + "".join(f"  - name: {n}\n" for n in sorted(LIVE_AGENTS))
)


class ProbeTests(unittest.TestCase):
    def test_empty_path_drops_everything(self) -> None:
        data: dict[str, Any] = probe(ALL_LIVE_ROSTER, tempfile.mkdtemp(prefix="dts2-path-"))
        self.assertEqual(data["usable"], [])
        self.assertEqual({d["name"] for d in data["dropped"]}, set(LIVE_AGENTS))
        for dropped in data["dropped"]:
            self.assertEqual(dropped["reason"], "not installed")

    def test_fake_codex_available(self) -> None:
        data: dict[str, Any] = probe("roster:\n  - name: codex\n", fake_bin(["codex"]))
        entry: dict[str, Any] = data["agents"]["codex"]
        self.assertTrue(entry["available"])
        self.assertEqual(entry["budget"], "unknown")
        self.assertEqual(entry["costTier"], 2)
        self.assertEqual(data["usable"], ["codex"])
        self.assertEqual(entry["roles"], ["builder", "second-opinion"])

    def test_low_budget_second_opinion_only(self) -> None:
        cfg: str = "roster:\n  - name: codex\nbudget:\n  codex:\n    status: low\n"
        data: dict[str, Any] = probe(cfg, fake_bin(["codex"]))
        entry: dict[str, Any] = data["agents"]["codex"]
        self.assertEqual(entry["budget"], "low")
        self.assertEqual(entry["roles"], ["second-opinion"])
        self.assertIn("codex", data["usable"])

    def test_exhausted_budget_dropped(self) -> None:
        cfg: str = "roster:\n  - name: codex\nbudget:\n  codex:\n    status: exhausted\n"
        data: dict[str, Any] = probe(cfg, fake_bin(["codex"]))
        self.assertEqual(data["usable"], [])
        self.assertEqual(data["dropped"], [{"name": "codex", "reason": "budget exhausted"}])

    def test_ide_agent_available_without_command(self) -> None:
        data: dict[str, Any] = probe("roster:\n  - name: cursor\n", tempfile.mkdtemp())
        self.assertEqual(data["usable"], ["cursor"])

    def test_failing_status_command_dropped(self) -> None:
        folder: str = fake_bin([])
        script: Path = Path(folder) / "codex"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        data: dict[str, Any] = probe("roster:\n  - name: codex\n", folder)
        self.assertEqual(data["dropped"][0]["reason"], "status check failed")


    def test_quota_status_drops_with_reset_time(self) -> None:
        folder: str = fake_bin([])
        script: Path = Path(folder) / "muse"
        script.write_text(f"#!/bin/sh\necho '{QUOTA_429}' >&2\nexit 1\n")
        script.chmod(0o755)
        data: dict[str, Any] = probe("roster:\n  - name: muse\n", folder)
        self.assertEqual(data["usable"], [])
        reason: str = data["dropped"][0]["reason"]
        self.assertTrue(reason.startswith("unavailable (billing/quota)"), reason)
        self.assertIn(RESET, reason)
        self.assertEqual(data["agents"]["muse"]["resetAt"], RESET)

    def test_quoted_quota_text_with_ok_status_stays_available(self) -> None:
        folder: str = fake_bin([])
        script: Path = Path(folder) / "muse"
        script.write_text(f"#!/bin/sh\necho '> {QUOTA_429.strip()}'\nexit 0\n")
        script.chmod(0o755)
        self.assertEqual(probe("roster:\n  - name: muse\n", folder)["usable"], ["muse"])

    def test_fake_muse_available(self) -> None:
        data: dict[str, Any] = probe("roster:\n  - name: muse\n", fake_bin(["muse"]))
        self.assertEqual(data["usable"], ["muse"])
        self.assertEqual(data["agents"]["muse"]["roles"], ["builder", "second-opinion"])


def classify(agent: str, role: str, output: str, *extra: str, exit_code: int = 1) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-I", str(ROSTER), "classify", "--agent", agent, "--role", role,
         "--exit-code", str(exit_code), *extra],
        input=output, capture_output=True, text=True, cwd=str(PLUGIN_ROOT),
    )
    return json.loads(result.stdout)


class ClassifyTests(unittest.TestCase):
    """Every error fixture is recorded output (fixtures/classify/README.txt). Negative cases quote
    those recorded lines; they never invent new error text."""

    def test_recorded_402_is_unavailable_for_run(self) -> None:
        data: dict[str, Any] = classify("muse", "builder", BILLING_402)
        self.assertEqual(data["outcome"], "unavailable")
        self.assertEqual(data["reason"], "unavailable (billing/quota)")
        self.assertIsNone(data["resetAt"])
        self.assertTrue(data["dropForRun"])
        self.assertFalse(data["seatFailed"])

    def test_recorded_429_reports_reset_time(self) -> None:
        data: dict[str, Any] = classify("muse", "builder", QUOTA_429)
        self.assertEqual(data["outcome"], "unavailable")
        self.assertEqual(data["resetAt"], RESET)
        self.assertIn(f"resets at {RESET}", data["reason"])
        self.assertTrue(data["dropForRun"])
        self.assertFalse(data["seatFailed"])

    def test_recorded_preamble_then_402(self) -> None:
        for code in (0, 1):
            self.assertEqual(classify("muse", "builder", recorded("muse-402-preamble.txt"), exit_code=code)["outcome"],
                             "unavailable", code)

    def test_recorded_forms_are_decisive_at_exit_zero(self) -> None:
        self.assertEqual(classify("muse", "builder", BILLING_402, exit_code=0)["outcome"], "unavailable")
        data: dict[str, Any] = classify("muse", "builder", QUOTA_429, exit_code=0)
        self.assertEqual(data["outcome"], "unavailable")
        self.assertEqual(data["resetAt"], RESET)

    def test_marker_form_needs_a_non_zero_exit(self) -> None:
        line: str = "Error: " + QUOTA_429.strip()
        self.assertEqual(classify("muse", "builder", line, exit_code=0)["outcome"], "ok")
        self.assertEqual(classify("muse", "builder", line, exit_code=1)["outcome"], "unavailable")

    def test_recorded_successful_run_is_ok(self) -> None:
        data: dict[str, Any] = classify("muse", "builder", recorded("muse-ok-reply.txt"), exit_code=0)
        self.assertEqual(data["outcome"], "ok")
        self.assertFalse(data["dropForRun"])

    def test_quoted_recorded_lines_never_match(self) -> None:
        for line in (BILLING_402.strip(), QUOTA_429.strip()):
            for marker in QUOTE_MARKERS:
                for code in (0, 1):
                    data: dict[str, Any] = classify("muse", "reviewer", f"Review done.\n{marker}{line}\nLOW: none\n", exit_code=code)
                    self.assertEqual(data["outcome"], "ok", f"{marker!r} exit {code}")

    def test_ordinary_output_is_ok(self) -> None:
        data: dict[str, Any] = classify("muse", "builder", "Edited src/app.ts; 3 tests pass. HTTP 4290 rows.")
        self.assertEqual(data["outcome"], "ok")
        self.assertFalse(data["dropForRun"])

    def test_unit_classifier(self) -> None:
        sys.path.insert(0, str(ROSTER.parent))
        try:
            import roster as module
        finally:
            sys.path.pop(0)
        self.assertIsNone(module.classify_output("all good", 1))
        self.assertIsNone(module.classify_output("> " + QUOTA_429, 1))
        self.assertEqual(module.classify_output(QUOTA_429, 0)["resetAt"], RESET)

    def test_only_the_tail_is_read(self) -> None:
        output: str = QUOTA_429 + "\n".join(f"line {n}" for n in range(30))
        self.assertEqual(classify("muse", "builder", output)["outcome"], "ok")


CONTEXT_BUDGET: Final[str] = recorded("copilot-context-budget.txt")


class CopilotFallbackTests(unittest.TestCase):
    def test_profile_names_grok_for_security_seat(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "copilot.json").read_text())
        self.assertEqual(data["fallback"], {"reviewer:security": "grok"})
        self.assertIn("context budget", " ".join(data["notes"]))

    def test_context_budget_falls_back_to_grok(self) -> None:
        data: dict[str, Any] = classify("copilot", "reviewer:security", CONTEXT_BUDGET, "--usable", "claude,grok")
        self.assertEqual(data["outcome"], "context-budget")
        self.assertEqual(data["fallback"], "grok")
        self.assertFalse(data["dropForRun"])
        self.assertFalse(data["seatFailed"])

    def test_no_fallback_when_grok_not_usable(self) -> None:
        data: dict[str, Any] = classify("copilot", "reviewer:security", CONTEXT_BUDGET, "--usable", "claude")
        self.assertEqual(data["outcome"], "context-budget")
        self.assertIsNone(data["fallback"])

    def test_fallback_without_usable_list(self) -> None:
        self.assertEqual(classify("copilot", "reviewer:security", CONTEXT_BUDGET)["fallback"], "grok")

    def test_recorded_copilot_error_falls_back_to_grok(self) -> None:
        data: dict[str, Any] = classify(
            "copilot", "reviewer:security", recorded("copilot-context-budget.txt"), "--usable", "claude,grok",
        )
        self.assertEqual(data["outcome"], "context-budget")
        self.assertEqual(data["fallback"], "grok")

    def test_status_markers_are_allowed(self) -> None:
        line: str = recorded("copilot-context-budget.txt").splitlines()[2]
        message: str = line[2:]
        for marker in ("! ", "✗ ", "× ", "Error: ", "error: ", "fatal: ", ""):
            data: dict[str, Any] = classify("copilot", "reviewer:security", marker + message)
            self.assertEqual(data["outcome"], "context-budget", repr(marker))

    def test_quoted_recorded_error_never_matches(self) -> None:
        message: str = recorded("copilot-context-budget.txt").splitlines()[2][2:]
        for marker in QUOTE_MARKERS:
            data: dict[str, Any] = classify("copilot", "reviewer:security", marker + message)
            self.assertEqual(data["outcome"], "ok", repr(marker))

    def test_bare_reviewer_role_is_copilots_security_seat(self) -> None:
        data: dict[str, Any] = classify("copilot", "reviewer", CONTEXT_BUDGET, "--usable", "grok")
        self.assertEqual(data["seat"], "reviewer:security")
        self.assertEqual(data["fallback"], "grok")

    def test_axis_names_the_seat(self) -> None:
        data: dict[str, Any] = classify("copilot", "reviewer", CONTEXT_BUDGET, "--axis", "security")
        self.assertEqual(data["seat"], "reviewer:security")
        self.assertEqual(data["fallback"], "grok")

    def test_other_axis_has_no_fallback(self) -> None:
        data: dict[str, Any] = classify("copilot", "reviewer", CONTEXT_BUDGET, "--axis", "correctness")
        self.assertEqual(data["seat"], "reviewer:correctness")
        self.assertIsNone(data["fallback"])

    def test_other_copilot_seats_have_no_fallback(self) -> None:
        self.assertIsNone(classify("copilot", "builder", CONTEXT_BUDGET)["fallback"])

    def test_ok_output_has_no_fallback(self) -> None:
        self.assertIsNone(classify("copilot", "reviewer:security", "No findings.")["fallback"])

    def test_grok_can_take_the_security_seat(self) -> None:
        result = command("grok", "reviewer:security")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plan", json.loads(result.stdout)["argv"])


class CostOrderTests(unittest.TestCase):
    def test_cost_order_ascending(self) -> None:
        cfg: str = write_config("roster:\n  - name: claude\n  - name: gemini\n  - name: codex\n")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["costOrder"], ["gemini", "codex", "claude"])


class DetectTests(unittest.TestCase):
    def test_empty_path_is_claude_only(self) -> None:
        empty: str = tempfile.mkdtemp(prefix="dts2-path-")
        project: str = tempfile.mkdtemp(prefix="dts2-proj-")
        result = raw_run("detect", "--project", project, env=isolated_env(empty))
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude"])
        self.assertTrue(data["claudeOnly"])

    def test_fake_binary_and_ide_marker(self) -> None:
        bindir: Path = Path(tempfile.mkdtemp(prefix="dts2-bin-"))
        fake: Path = bindir / "codex"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        project: Path = Path(tempfile.mkdtemp(prefix="dts2-proj-"))
        (project / ".cursor").mkdir()
        result = raw_run("detect", "--project", str(project), env=isolated_env(str(bindir)))
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude", "codex", "cursor"])
        self.assertFalse(data["claudeOnly"])


class ResolveTests(unittest.TestCase):
    def test_no_roster_is_claude_on_all_roles(self) -> None:
        missing: str = str(Path(tempfile.mkdtemp()) / "nope.yaml")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", missing)
        self.assertEqual(data["enabled"], ["claude"])
        for role in ("lead", "verifier", "builder", "reviewer"):
            self.assertEqual(data["assignments"][role], ["claude"])
        self.assertEqual(data["handoff"], [])
        self.assertEqual(data["live"], ["claude"])

    def test_cursor_builder_is_handoff(self) -> None:
        cfg: str = write_config(
            "roster:\n  - name: claude\n  - name: cursor\n    roles: [builder]\n"
        )
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["handoff"], ["cursor"])
        self.assertEqual(data["live"], ["claude"])
        self.assertIn("cursor", data["assignments"]["builder"])

    def test_cursor_lead_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: cursor\n    roles: [lead]\n")
        result = raw_run("resolve", "--config", cfg)
        self.assertEqual(result.returncode, 1)
        self.assertIn("lead", result.stderr + result.stdout)

    def test_unknown_agent_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: nonesuch\n")
        self.assertEqual(raw_run("resolve", "--config", cfg).returncode, 1)

    def test_config_without_roster_block(self) -> None:
        cfg: str = write_config("other: 1\n")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["enabled"], ["claude"])


if __name__ == "__main__":
    unittest.main()
