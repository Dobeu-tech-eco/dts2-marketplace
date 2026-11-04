"""How a son is launched (A7, A8, SE-4): the environment allowlist, the per-lane port and database names, the settings
JSON handed to `claude --settings` (deny hook, sandbox block), the tool lists, and the CLI version check.
lanes.py calls these; nothing here starts a process."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any, Final

from model_call import read_block

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
GUARD: Final[Path] = PLUGIN_ROOT / "scripts" / "guard.py"
ENV_ALLOW: Final[frozenset[str]] = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "TZ", "PWD",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})
ENV_ALLOW_PREFIXES: Final[tuple[str, ...]] = ("LC_", "DTS2_", "CLAUDE_CODE_", "XDG_")
ENV_DENY_PREFIXES: Final[tuple[str, ...]] = ("DTS2_PR_",)
PASS_VAR: Final[str] = "DTS2_SON_ENV_PASS"  # comma-separated name patterns the owner chooses to hand a son
CACHE_TTL_VAR: Final[str] = "CLAUDE_CODE_PROMPT_CACHE_TTL"
CACHE_TTL: Final[str] = "1h"
MIN_CLI: Final[tuple[int, int, int]] = (2, 1, 242)  # CLAUDE_CODE_PROMPT_CACHE_TTL needs this release
DEFAULT_PORT_BASE: Final[int] = 4000
PORT_STRIDE: Final[int] = 10
CACHE_DIR: Final[str] = ".harness/cache"
NAME_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
BLOCK_SANDBOX: Final[str] = "sandbox"
BLOCK_MERGE: Final[str] = "merge"
DEFAULT_TARGET: Final[str] = "dev"
ALLOWED_DOMAINS: Final[tuple[str, ...]] = (
    "registry.npmjs.org", "pypi.org", "files.pythonhosted.org", "github.com", "api.github.com",
    "codeload.github.com", "objects.githubusercontent.com", "api.anthropic.com",
)
TOOLS: Final[str] = "Bash,Read,Edit,Write,Glob,Grep,Skill,Agent"
DISALLOWED: Final[tuple[str, ...]] = (
    "Bash(gh pr merge *)", "Bash(gh repo delete *)", "Bash(git -c *)", "Bash(git push --force *)",
    "Bash(git push -f *)", "Read(~/.ssh/**)", "Read(**/.env)", "Read(**/.env.*)", "Read(~/.aws/**)",
    "Read(~/.config/gcloud/**)", "Edit(.claude/**)", "Write(.claude/**)", "Edit(.mcp.json)", "Write(.mcp.json)",
    "Edit(.git/hooks/**)", "Write(.git/hooks/**)",
)
GUARDED_TOOLS: Final[str] = "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"


def allowed_env(source: dict[str, str]) -> dict[str, str]:
    """Only allowlisted variables survive, so GH_TOKEN, GITHUB_TOKEN, SSH_AUTH_SOCK and cloud credentials are absent."""
    extra: list[str] = [p.strip() for p in source.get(PASS_VAR, "").split(",") if p.strip()]
    return {k: v for k, v in source.items()
            if (k in ENV_ALLOW or k.startswith(ENV_ALLOW_PREFIXES) or any(fnmatch.fnmatchcase(k, p) for p in extra))
            and not k.startswith(ENV_DENY_PREFIXES)}


def slug(text: str) -> str:
    return NAME_UNSAFE.sub("-", text.lower()).strip("-") or "x"


def lane_index(manifest: dict[str, Any], lane_id: str) -> int:
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    return ids.index(lane_id) if lane_id in ids else 0


def port_base(cwd: Path) -> int:
    raw: str | None = read_block(cwd, "lanes").get("port_base")
    return int(raw) if raw and raw.isdigit() and 1024 <= int(raw) <= 60000 else DEFAULT_PORT_BASE


def lane_env(manifest: dict[str, Any], lane_id: str, cwd: Path) -> dict[str, str]:
    """Per-lane PORT and database/Compose names, the shared package caches, and the lane's own branch prefix."""
    stamp: str = str(manifest["stamp"])
    key: str = f"{slug(stamp)}-{slug(lane_id)}"
    cache: str = str(cwd.resolve() / CACHE_DIR)
    return {
        "PORT": str(port_base(cwd) + PORT_STRIDE * lane_index(manifest, lane_id)),
        "COMPOSE_PROJECT_NAME": f"dts2-{key}",
        "DTS2_DB_NAME": f"dts2_{key.replace('-', '_')}",
        "DTS2_SON_BRANCH_PREFIX": f"dts2/{stamp}/lane-{lane_id}",
        "npm_config_cache": f"{cache}/npm", "PIP_CACHE_DIR": f"{cache}/pip", "UV_CACHE_DIR": f"{cache}/uv",
        "YARN_CACHE_FOLDER": f"{cache}/yarn", "PNPM_HOME": f"{cache}/pnpm",
        CACHE_TTL_VAR: CACHE_TTL,
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
    }


def son_env(manifest: dict[str, Any], lane_id: str, cwd: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    return {**allowed_env(dict(os.environ) if source is None else source), **lane_env(manifest, lane_id, cwd)}


def sandbox_config(cwd: Path) -> dict[str, Any]:
    """The `sandbox:` block of .harness/config.yaml: enabled (default true) and extra allowed domains."""
    raw: dict[str, str] = read_block(cwd, BLOCK_SANDBOX)
    extra: list[str] = [d.strip() for d in raw.get("extra_domains", "").split(",") if re.match(r"^[A-Za-z0-9.*-]+$", d.strip())]
    return {"enabled": raw.get("enabled", "true").lower() != "false", "domains": [*ALLOWED_DOMAINS, *extra]}


def merge_config(cwd: Path) -> dict[str, str]:
    """`merge:` block: target (default dev) and default_branch (default main)."""
    raw: dict[str, str] = read_block(cwd, BLOCK_MERGE)
    return {"target": raw.get("target") or DEFAULT_TARGET, "default_branch": raw.get("default_branch") or "main"}


def son_settings(cwd: Path) -> dict[str, Any]:
    """The settings a son runs with: the deny hook, and the sandbox with default-deny egress when it is on."""
    hook: dict[str, Any] = {"type": "command", "timeout": 10,
                            "command": f'python3 -I "{GUARD}" --mode son'}
    settings: dict[str, Any] = {"hooks": {"PreToolUse": [{"matcher": GUARDED_TOOLS, "hooks": [hook]}]}}
    box: dict[str, Any] = sandbox_config(cwd)
    if box["enabled"]:
        settings["sandbox"] = {
            "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": box["domains"], "strictAllowlist": True},
            "filesystem": {"allowWrite": [str(cwd.resolve() / CACHE_DIR)]},
        }
    return settings


def launch_flags(cwd: Path, mode: str) -> list[str]:
    """Permission mode, tool allowlist, deny list, minimal startup and explicit settings for one son."""
    return ["--bare", "--permission-mode", mode, "--tools", TOOLS, "--allowedTools", TOOLS,
            "--disallowedTools", ",".join(DISALLOWED), "--settings", json.dumps(son_settings(cwd), separators=(",", ":")),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']


def version_tuple(text: str | None) -> tuple[int, ...] | None:
    parts: list[str] = (text or "").split(".")
    return tuple(int(p) for p in parts) if len(parts) == 3 and all(p.isdigit() for p in parts) else None


def cli_too_old(version: str | None) -> str | None:
    """Why a son must not start on this CLI (it ignores the cache-TTL variable), or None. Fails closed on unreadable."""
    parsed = version_tuple(version)
    need: str = ".".join(str(n) for n in MIN_CLI)
    if parsed is None:
        return f"cannot read `claude --version`; the son launch needs {need} or newer"
    return None if parsed >= MIN_CLI else f"claude {version} is older than {need}, which the son launch needs"
