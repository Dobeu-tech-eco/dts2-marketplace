#!/usr/bin/env python3
"""doctor.py: preflight checks for running the harness on this machine.

Usage: doctor.py [--json]
Checks Python, git, the claude CLI, sandbox tooling and fake-binary env vars. Prints a pass/fail/warn table, or
JSON {ok, checks: [{name, status, detail}]} with --json. Exit 1 when any check fails; warnings never fail.
DTS2_CLAUDE_BIN and DTS2_GIT_BIN override the binaries (a .py value runs under the current interpreter).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

PASS: Final[str] = "pass"
FAIL: Final[str] = "fail"
WARN: Final[str] = "warn"
MIN_PYTHON: Final[tuple[int, int]] = (3, 10)
MIN_GIT: Final[tuple[int, int]] = (2, 38)
TIMEOUT_S: Final[int] = 15
EXIT_FAIL: Final[int] = 1
VERSION_RE: Final[re.Pattern[str]] = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
FAKE_BIN_VARS: Final[tuple[str, ...]] = ("DTS2_CLAUDE_BIN", "DTS2_GH_BIN", "DTS2_NPX_BIN", "DTS2_GIT_BIN",
                                         "DTS2_GITLEAKS_BIN", "DTS2_TRUFFLEHOG_BIN")
SANDBOX_TOOLS: Final[dict[str, str]] = {"linux": "bwrap", "darwin": "sandbox-exec"}
SANDBOX_OVERRIDE: Final[str] = "DTS2_SANDBOX_BIN"
SOCAT_TOOL: Final[str] = "socat"  # the sandbox's network proxy helper on Linux
WINDOWS_PLATFORM: Final[str] = "win32"
WINDOWS_PARK_REASON: Final[str] = "windows-native"  # why dpp parks on native Windows (ruling Q6)
# Exit codes a son or a check can end with, by runtime. Mirrored in docs/RUNTIMES.md; a test keeps the two in step.
EXIT_TIMEOUT: Final[int] = 124  # GNU `timeout` (WSL, Docker)
EXIT_KILLED: Final[int] = 137  # SIGKILL: the OOM killer, `docker stop` after its grace period
EXIT_TERMINATED: Final[int] = 143  # SIGTERM: `docker stop`, a clean shutdown
TIMEOUT_MAPPING: Final[dict[str, dict[str, int]]] = {
    "wsl": {"timeout": EXIT_TIMEOUT, "killed": EXIT_KILLED, "terminated": EXIT_TERMINATED},
    "docker": {"timeout": EXIT_TIMEOUT, "killed": EXIT_KILLED, "terminated": EXIT_TERMINATED},
}
AUTH_ENV: Final[tuple[tuple[str, str], ...]] = (
    ("ANTHROPIC_API_KEY", "api-key"), ("ANTHROPIC_AUTH_TOKEN", "auth-token"), ("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token"))


def check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def binary(env_name: str, default: str) -> list[str] | None:
    """Command for a tool: the env override when set, else the default looked up on PATH; None when not found."""
    value: str = os.environ.get(env_name, default)
    if value.endswith(".py"):
        return [sys.executable, value]
    found: str | None = shutil.which(value)
    return [found] if found else None


def tool_version(cmd: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run([*cmd, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout or done.stderr or "").strip()


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def check_python() -> dict[str, str]:
    current: tuple[int, int] = (sys.version_info.major, sys.version_info.minor)
    label: str = f"{current[0]}.{current[1]}.{sys.version_info.micro}"
    if current >= MIN_PYTHON:
        return check("python", PASS, f"{label} (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
    return check("python", FAIL, f"{label} is older than {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")


def check_git() -> dict[str, str]:
    need: str = f">= {MIN_GIT[0]}.{MIN_GIT[1]}"
    cmd: list[str] | None = binary("DTS2_GIT_BIN", "git")
    if cmd is None:
        return check("git", FAIL, f"git not found (need {need})")
    code, out = tool_version(cmd)
    version = parse_version(out)
    if code != 0 or version is None:
        return check("git", FAIL, f"could not read the git version: {out[:80] or 'no output'}")
    if version[:2] < MIN_GIT:
        return check("git", FAIL, f"{out[:60]} is older than {MIN_GIT[0]}.{MIN_GIT[1]}")
    return check("git", PASS, f"{'.'.join(map(str, version))} (need {need})")


def check_claude() -> dict[str, str]:
    cmd: list[str] | None = binary("DTS2_CLAUDE_BIN", "claude")
    if cmd is None:
        return check("claude", FAIL, "claude CLI not found on PATH (set DTS2_CLAUDE_BIN to override)")
    code, out = tool_version(cmd)
    version = parse_version(out)
    if code != 0 or version is None:
        return check("claude", FAIL, f"`claude --version` failed: {out[:80] or 'no output'}")
    return check("claude", PASS, f"version {'.'.join(map(str, version))}")


def check_sandbox() -> dict[str, str]:
    override: str | None = os.environ.get(SANDBOX_OVERRIDE)
    tool: str | None = override or SANDBOX_TOOLS.get(sys.platform)
    if tool is None:
        return check("sandbox", WARN, f"no sandbox tool known for {sys.platform}")
    found: str | None = shutil.which(tool)
    if found:
        return check("sandbox", PASS, f"{tool} at {found}")
    return check("sandbox", WARN, f"{tool} not found; sandboxed runs are unavailable here")


def check_helper_tools() -> list[dict[str, str]]:
    """bwrap and socat on Linux (the sandbox needs both); other platforms have neither requirement."""
    if sys.platform != "linux":
        return [check("bwrap", PASS, f"not needed on {sys.platform}"), check("socat", PASS, f"not needed on {sys.platform}")]
    rows: list[dict[str, str]] = []
    for tool in ("bwrap", SOCAT_TOOL):
        found: str | None = shutil.which(tool)
        rows.append(check(tool, PASS, found) if found else check(tool, WARN, f"{tool} not found; the sandbox needs it on Linux"))
    return rows


def check_auth() -> dict[str, str]:
    """Which credential the harness would use, named, never its value."""
    for name, label in AUTH_ENV:
        if os.environ.get(name):
            return check("auth", PASS, f"{label} (from {name})")
    return check("auth", PASS, "login (subscription) or none set; run `claude auth status` to confirm")


def check_platform() -> dict[str, str]:
    if sys.platform == WINDOWS_PLATFORM:
        return check("platform", WARN, f"native Windows: dpp parks with reason {WINDOWS_PARK_REASON}; use WSL or Docker (docs/RUNTIMES.md)")
    return check("platform", PASS, sys.platform)


def check_fake_env() -> dict[str, str]:
    active: list[str] = [name for name in FAKE_BIN_VARS if os.environ.get(name)]
    if active:
        return check("fake-binaries", WARN, "set: " + ", ".join(active) + " (test overrides in effect)")
    return check("fake-binaries", PASS, "none set; real binaries are used")


def check_agent_rules() -> dict[str, str]:
    """The roster's per-agent `rules:` blocks in this repo's config: unknown keys or classes, a class in both lists, a bad tier."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import agent_rules  # noqa: PLC0415 - only this check needs them
    import state_io  # noqa: PLC0415
    problems: list[str] = agent_rules.config_problems(Path(state_io.CONFIG_REL))
    return check("agent-rules", FAIL, "; ".join(problems)) if problems else check("agent-rules", PASS, "no invalid rules in the roster")


def run_checks() -> list[dict[str, str]]:
    return [check_python(), check_git(), check_claude(), check_sandbox(), *check_helper_tools(), check_auth(), check_platform(), check_fake_env(),
            check_agent_rules()]


def render_table(checks: list[dict[str, str]]) -> str:
    width: int = max(len(c["name"]) for c in checks)
    lines: list[str] = [f"{'CHECK':<{width}}  STATUS  DETAIL"]
    lines += [f"{c['name']:<{width}}  {c['status'].upper():<6}  {c['detail']}" for c in checks]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="harness preflight doctor")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args()
    checks: list[dict[str, str]] = run_checks()
    ok: bool = all(c["status"] != FAIL for c in checks)
    if args.json:
        result: dict[str, Any] = {"ok": ok, "checks": checks}
        print(json.dumps(result))
    else:
        print(render_table(checks))
        print("ok" if ok else "FAILED")
    return 0 if ok else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
