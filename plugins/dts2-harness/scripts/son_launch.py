"""How a son is launched (A7, A8, SE-4): the environment allowlist, the per-lane port and database names, the settings
JSON handed to `claude --settings` (deny hook, sandbox block), the tool lists, and the CLI version check.
lanes.py calls these; nothing here starts a process."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

from approvals import deny_rules as approval_deny_rules
from briefs import PREFIX_FLAG, cached_prefix
from model_call import read_block
from proc import binary
from state_io import CACHE_REL, CHECKS_SH_REL, RUNS_REL

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
GUARD: Final[Path] = PLUGIN_ROOT / "scripts" / "guard.py"
ENV_ALLOW: Final[frozenset[str]] = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "TZ", "PWD",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})
ENV_ALLOW_PREFIXES: Final[tuple[str, ...]] = ("LC_", "DTS2_", "CLAUDE_CODE_", "XDG_", "OTEL_")  # OTEL_*: telemetry export only, no tagging (Q8)
ENV_DENY_PREFIXES: Final[tuple[str, ...]] = ("DTS2_PR_",)
PASS_VAR: Final[str] = "DTS2_SON_ENV_PASS"  # comma-separated name patterns the owner chooses to hand a son
CACHE_TTL_VAR: Final[str] = "CLAUDE_CODE_PROMPT_CACHE_TTL"
CACHE_TTL: Final[str] = "1h"
MIN_CLI: Final[tuple[int, int, int]] = (2, 1, 242)  # CLAUDE_CODE_PROMPT_CACHE_TTL needs this release
DEFAULT_PORT_BASE: Final[int] = 4000
PORT_STRIDE: Final[int] = 10
CACHE_DIR: Final[str] = CACHE_REL
RUNS_DIR: Final[str] = RUNS_REL
NAME_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
BLOCK_SANDBOX: Final[str] = "sandbox"
BLOCK_MERGE: Final[str] = "merge"
DEFAULT_TARGET: Final[str] = "dev"
ALLOWED_DOMAINS: Final[tuple[str, ...]] = (
    "registry.npmjs.org", "pypi.org", "files.pythonhosted.org", "github.com", "api.github.com",
    "codeload.github.com", "objects.githubusercontent.com", "api.anthropic.com",
)
TOOLS: Final[str] = "Bash,Read,Edit,Write,Glob,Grep,Skill,Agent"  # `--tools`: what exists; `--allowedTools` says what runs unasked
PERMISSION_MODES: Final[tuple[str, ...]] = ("dontAsk", "acceptEdits", "plan", "default")  # never bypassPermissions (G-61)
DEFAULT_MODE: Final[str] = "dontAsk"
BASE_ALLOWED: Final[tuple[str, ...]] = ("Read", "Edit", "Write", "Glob", "Grep", "Skill", "Agent")
GIT_ALLOWED: Final[tuple[str, ...]] = (  # G-64: add and commit, never push; the head publishes
    "Bash(git add *)", "Bash(git commit *)", "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
    "Bash(git rev-parse*)", "Bash(git branch*)", "Bash(git checkout*)", "Bash(git switch*)", "Bash(git merge*)",
    "Bash(git worktree*)", "Bash(git ls-files*)", "Bash(git stash*)",
)
HARNESS_ALLOWED: Final[tuple[str, ...]] = (f"Bash(python3 -I {PLUGIN_ROOT / 'scripts'}/*)", f"Bash(bash {CHECKS_SH_REL}*)")
CHECK_BLOCK: Final[str] = "commands"  # `commands:` in .harness/config.yaml: test, typecheck, lint
RULE_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[()\n]")
HANDOVER_DENY: Final[tuple[str, ...]] = ("Bash(git push*)", "Bash(gh pr*)", "Bash(gh api*)")  # G-64: a son hands over a branch
DISALLOWED: Final[tuple[str, ...]] = (
    *HANDOVER_DENY,
    "Bash(gh pr merge *)", "Bash(*head_publish.py*)", "Bash(*lanes.py merge-go*)", "Bash(*lanes.py merge-target*)", "Bash(*lanes.py publish*)", "Bash(gh repo delete *)", "Bash(git -c *)", "Bash(git push --force *)",
    "Bash(git push -f *)", "Read(~/.ssh/**)", "Read(**/.env)", "Read(**/.env.*)", "Read(~/.aws/**)",
    "Read(~/.config/gcloud/**)", "Edit(.claude/**)", "Write(.claude/**)", "Edit(.mcp.json)", "Write(.mcp.json)",
    "Edit(.git/hooks/**)", "Write(.git/hooks/**)",
)
APPROVAL_FILE: Final[str] = ".claude/settings.local.json"
MERGE_GO_NAME: Final[str] = "merge-go.md"
PROBE_LANE: Final[str] = "preflight"  # the preflight probe is not a lane: it has no builders and no grant file
BUILDERS_VAR: Final[str] = "DTS2_BUILDERS_DIR"
SON_MARKER: Final[str] = "DTS2_SON"  # set in every son's env; lanes.py refuses the merge-granting commands when present
SETTING_SOURCES: Final[str] = "local"  # `--setting-sources` takes user, project, local; local-only drops shared hooks and allow rules
GIT_TIMEOUT_S: Final[int] = 20
GUARDED_TOOLS: Final[str] = "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"


def allowed_env(source: dict[str, str]) -> dict[str, str]:
    """Only allowlisted variables survive, so GH_TOKEN, GITHUB_TOKEN, SSH_AUTH_SOCK and cloud credentials are absent."""
    extra: list[str] = [p.strip() for p in source.get(PASS_VAR, "").split(",") if p.strip()]
    return {k: v for k, v in source.items()
            if (k in ENV_ALLOW or k.startswith(ENV_ALLOW_PREFIXES) or any(fnmatch.fnmatchcase(k, p) for p in extra))
            and not k.startswith(ENV_DENY_PREFIXES)}


def safe_permission_mode(mode: str | None) -> str:
    """`mode` when it is on the allowlist, else `dontAsk`. `bypassPermissions` is never accepted (G-61)."""
    return mode if mode in PERMISSION_MODES else DEFAULT_MODE


def mode_problem(mode: str | None) -> str | None:
    """Why `son_permission_mode` is refused, or None."""
    if mode in PERMISSION_MODES:
        return None
    return f"son_permission_mode {mode!r} is not allowed (use one of {', '.join(PERMISSION_MODES)}); dontAsk is used instead"


def check_rules(cwd: Path) -> list[str]:
    """`Bash(<command>)` rules for the repo's own test, typecheck and lint commands from `commands:` in config.yaml."""
    rules: list[str] = []
    for command in read_block(cwd, CHECK_BLOCK).values():
        text: str = command.strip()
        if text and not RULE_UNSAFE.search(text):
            rules += [f"Bash({text})", f"Bash({text} *)"]
    return rules


def allowed_tools(cwd: Path) -> list[str]:
    """The explicit `--allowedTools` set: file tools, git add and commit (no push), the repo's check commands and the
    harness scripts. Everything else is denied under dontAsk."""
    return [*BASE_ALLOWED, *GIT_ALLOWED, *HARNESS_ALLOWED, *check_rules(cwd)]


CLAUDE_CREDENTIALS: Final[frozenset[str]] = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"})


def provider_env(source: dict[str, str], key_env: str | None = None, claude: bool = False) -> dict[str, str]:
    """The environment for a non-Claude agent CLI (codex, gemini, muse, agy, grok): the son allowlist, minus the Anthropic
    credentials unless the agent is Claude, plus the one API-key variable that agent's own profile names (G-67)."""
    env: dict[str, str] = allowed_env(source)
    if not claude:
        env = {k: v for k, v in env.items() if k not in CLAUDE_CREDENTIALS and not k.startswith("CLAUDE_CODE_")}
    if key_env and source.get(key_env):
        env[key_env] = source[key_env]
    return env


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
        SON_MARKER: "1", "DTS2_SON_BRANCH_PREFIX": f"dts2/{stamp}/lane-{lane_id}",
        BUILDERS_VAR: str(builders_dir(cwd, lane_id)),
        "npm_config_cache": f"{cache}/npm", "PIP_CACHE_DIR": f"{cache}/pip", "UV_CACHE_DIR": f"{cache}/uv",
        "YARN_CACHE_FOLDER": f"{cache}/yarn", "PNPM_HOME": f"{cache}/pnpm",
        # pnpm's content store, its operation lock and its state dir default to the home dir, outside the sandbox's
        # writable paths, so install and the pre-commit hook failed in every son (D74); keep them in the run cache.
        "npm_config_store_dir": f"{cache}/pnpm-store", "pnpm_config_store_dir": f"{cache}/pnpm-store",
        "npm_config_state_dir": f"{cache}/pnpm-state", "pnpm_config_state_dir": f"{cache}/pnpm-state",
        # skills and hooks address harness scripts as "${CLAUDE_PLUGIN_ROOT}/scripts/..."; the allowlisted env dropped it (D74)
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
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


def git_common_dir(cwd: Path) -> Path:
    """Absolute `git rev-parse --git-common-dir` of the root (a linked worktree commits into it); `<root>/.git` when git
    cannot say."""
    value: str = os.environ.get("DTS2_GIT_BIN", "git")
    cmd: list[str] = [sys.executable, value] if value.endswith(".py") else [value]
    try:
        done = subprocess.run([*cmd, "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd, capture_output=True,
                              text=True, timeout=GIT_TIMEOUT_S, check=False)
        out: str = done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        out = ""
    path: Path = Path(out) if out else cwd / ".git"
    return (path if path.is_absolute() else cwd / path).resolve()


def builders_dir(cwd: Path, lane_id: str) -> Path:
    """The one directory a lane's builder worktrees live in: `<repo parent>/<repo>-dts2-<lane>-builders`. Sandbox write paths take
    no mid-path wildcard on Linux, so the son gets this exact path and `lanes.py spawn` creates it."""
    root: Path = cwd.resolve()
    return root.parent / f"{root.name}-dts2-{slug(lane_id)}-builders"


def lane_grant_file(cwd: Path, stamp: str, lane_id: str) -> Path:
    return cwd.resolve() / RUNS_DIR / stamp / lane_id / MERGE_GO_NAME


def prepare_lane(cwd: Path, stamp: str, lane_id: str) -> None:
    """What the sandbox paths need to exist: the builders directory, and a placeholder merge-go.md (denied for writing, so a
    son cannot create it; the head replaces it when it grants). A real grant is never overwritten."""
    builders_dir(cwd, lane_id).mkdir(parents=True, exist_ok=True)
    grant: Path = lane_grant_file(cwd, stamp, lane_id)
    if not grant.exists():
        grant.parent.mkdir(parents=True, exist_ok=True)
        grant.write_text("# No merge grant for this lane yet.\n", encoding="utf-8")


def existing(paths: list[Path]) -> list[str]:
    return [str(p) for p in paths if p.exists()]


def approval_files(root: Path, worktree: Path) -> list[str]:
    """`.claude/settings.local.json` holds the human-only approval key (Q11): no son may write it, in the repo or its worktree."""
    return [str(base / APPROVAL_FILE) for base in (root, worktree.resolve())]


def write_scope(manifest: dict[str, Any], lane_id: str, cwd: Path, worktree: Path) -> tuple[list[str], list[str]]:
    """(allowWrite, denyWrite) for one son. Sandbox protected paths cover `.git/hooks` and `.git/config` only inside the
    working directory, and a linked worktree commits into the main repo's git dir, so the deny entries are explicit (a
    trailing `/**` is the only wildcard these lists honour on Linux). The lane's run dir is writable except its merge-go.md,
    and builder worktrees go under the lane's builders directory."""
    root: Path = cwd.resolve()
    common: Path = git_common_dir(root)
    stamp: str = str(manifest["stamp"])
    lane_dir: Path = root / RUNS_DIR / stamp / lane_id
    allow: list[str] = [str(root / CACHE_DIR), str(common), str(lane_dir), str(worktree.resolve())]
    deny: list[str] = [str(common / "hooks"), str(common / "config"), *approval_files(root, worktree),
                       *existing([common / "modules", *sorted((common / "worktrees").glob("*/config.worktree"))])]
    if lane_id != PROBE_LANE:
        allow.append(str(builders_dir(root, lane_id)))
        deny.append(str(lane_grant_file(root, stamp, lane_id)))
    return allow, deny


def son_settings(cwd: Path, manifest: dict[str, Any], lane_id: str, worktree: Path) -> dict[str, Any]:
    """The settings a son runs with: the deny hook, and the sandbox with default-deny egress when it is on."""
    hook: dict[str, Any] = {"type": "command", "timeout": 10,
                            "command": f'python3 -I "{GUARD}" --mode son'}
    settings: dict[str, Any] = {"hooks": {"PreToolUse": [{"matcher": GUARDED_TOOLS, "hooks": [hook]}]},
                                "permissions": {"deny": deny_list()}}
    box: dict[str, Any] = sandbox_config(cwd)
    if box["enabled"]:
        allow, deny = write_scope(manifest, lane_id, cwd, worktree)
        settings["sandbox"] = {
            "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": box["domains"], "strictAllowlist": True},
            "filesystem": {"allowWrite": allow, "denyWrite": deny},
        }
    return settings


def deny_list() -> list[str]:
    """`permissions.deny` of the son settings, the primary control: the deny list plus the human-approval file (G-63)."""
    return [*DISALLOWED, *approval_deny_rules()]


def launch_flags(cwd: Path, mode: str, manifest: dict[str, Any], lane_id: str, worktree: Path) -> list[str]:
    """Permission mode, tool allowlist, deny list and explicit settings for one son. No `--bare`: bare mode ignores hooks
    passed with `--settings` and in a loaded plugin, and drops OAuth and keychain auth. `--setting-sources local` isolates
    the son from user and project settings instead. `--append-system-prompt` carries the shared prefix (discipline, roster,
    probe) so its bytes are the same for every dispatch of the run and can be served from the prompt cache."""
    return [PREFIX_FLAG, cached_prefix(cwd, str(manifest["stamp"])), "--setting-sources", SETTING_SOURCES,
            "--permission-mode", safe_permission_mode(mode), "--tools", TOOLS, "--allowedTools", ",".join(allowed_tools(cwd)),
            "--disallowedTools", ",".join(deny_list()),
            "--settings", json.dumps(son_settings(cwd, manifest, lane_id, worktree), separators=(",", ":")),
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


AUTH_TIMEOUT_S: Final[int] = 20
INIT_SUBTYPE: Final[str] = "init"


def auth_problem(cwd: Path, env: dict[str, str] | None = None) -> str | None:
    """Why `claude auth status` says no son can run (not logged in, or the CLI cannot say), or None (G-60). Fails closed."""
    try:
        done = subprocess.run([*binary("DTS2_CLAUDE_BIN", "claude"), "auth", "status"], cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=AUTH_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"`claude auth status` could not run: {exc}"
    return None if done.returncode == 0 else "`claude auth status` reports no login; run `claude auth login` as the owner"


def init_plugin_errors(stream: str) -> list[str]:
    """`plugin_errors` of every `system`/`init` event in a stream-json transcript. A plugin that failed to load means the
    guard hook may not run, so a non-empty answer fails the preflight (G-60)."""
    found: list[str] = []
    for line in stream.splitlines():
        try:
            event: Any = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "system" or event.get("subtype") != INIT_SUBTYPE:
            continue
        errors: Any = event.get("plugin_errors")
        if isinstance(errors, list):
            found += [str(e if isinstance(e, str) else json.dumps(e, sort_keys=True)) for e in errors]
    return found


def hooks_enabled(settings: dict[str, Any], flags: list[str]) -> bool:
    """True when the son keeps its hooks: not bare, hooks not disabled, and a PreToolUse guard is present."""
    return ("--bare" not in flags and not settings.get("disableAllHooks") and bool(settings.get("hooks", {}).get("PreToolUse")))
