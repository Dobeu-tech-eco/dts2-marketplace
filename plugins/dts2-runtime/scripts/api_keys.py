"""API-key agents (batch E): where a profile's key comes from and where its private home lives.

`resolve_key(profile)` reads the key a profile's `apiKeyRef` points at (`env:NAME`, `keyring:service/user`,
`op://vault/item/field`, `doppler:PROJECT/CONFIG/NAME`) or, with no ref, the profile's `apiKeyEnv` variable in the parent
environment. It returns `(value or None, source label)`; the label (`env:XAI_API_KEY`, `keyring`, `op`, `doppler`) is safe
to print and record, the value is not: it goes only into the one child's environment (`child_env`) and nowhere else, never
to a file, a receipt, a ledger or a log. The password-manager binaries can be pointed elsewhere with DTS2_OP_BIN,
DTS2_DOPPLER_BIN, DTS2_SECRET_TOOL_BIN and DTS2_SECURITY_BIN, which is how tests use fake ones.

A profile with `homeEnv` (such as `CLAUDE_CONFIG_DIR` or `CODEX_HOME`) gets its own folder under the harness user dir
(`agents-home/<name>`, next to the user agents folder), so it never reads another login. `homeFiles` are written there on first
launch when missing (mode 0600, folder 0700)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profiles import user_agents_dir  # noqa: E402
from proc import binary  # noqa: E402

OP_BIN: Final[str] = "DTS2_OP_BIN"
DOPPLER_BIN: Final[str] = "DTS2_DOPPLER_BIN"
SECRET_TOOL_BIN: Final[str] = "DTS2_SECRET_TOOL_BIN"
SECURITY_BIN: Final[str] = "DTS2_SECURITY_BIN"
LOOKUP_TIMEOUT_S: Final[int] = 20
HOME_PARENT: Final[str] = "agents-home"
DIR_MODE: Final[int] = 0o700
FILE_MODE: Final[int] = 0o600
SCHEME_KEYRING: Final[str] = "keyring"
SCHEME_OP: Final[str] = "op"
SCHEME_DOPPLER: Final[str] = "doppler"
SCHEME_ENV: Final[str] = "env"
SETUP_HINT: Final[str] = (
    "set apiKeyRef on the profile (keyring:service/user, op://vault/item/field, doppler:PROJECT/CONFIG/NAME or env:NAME) "
    "or export {env}; see docs/API-AGENTS.md"
)
NAME_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")


class KeyMissing(Exception):
    """A key agent was asked to launch and no key was found."""


def ref_of(profile: Mapping[str, Any]) -> str | None:
    ref: Any = profile.get("apiKeyRef")
    return ref if isinstance(ref, str) and ref else None


def key_env_of(profile: Mapping[str, Any]) -> str | None:
    name: Any = profile.get("apiKeyEnv")
    return name if isinstance(name, str) and name else None


def scheme_of(ref: str) -> str:
    """`keyring`, `op`, `doppler` or `env`; an empty string for anything else."""
    if ref.startswith("op://"):
        return SCHEME_OP
    head: str = ref.split(":", 1)[0]
    return head if head in (SCHEME_KEYRING, SCHEME_DOPPLER, SCHEME_ENV) and ":" in ref else ""


def source_label(profile: Mapping[str, Any]) -> str:
    """Where the profile's key comes from, as a label with no secret in it: `keyring`, `op`, `doppler`, `env:NAME`, or `none`."""
    ref: str | None = ref_of(profile)
    if ref:
        scheme: str = scheme_of(ref)
        return f"env:{ref.split(':', 1)[1]}" if scheme == SCHEME_ENV else scheme or "none"
    key_env: str | None = key_env_of(profile)
    return f"env:{key_env}" if key_env else "none"


def run_lookup(argv: list[str], env: Mapping[str, str]) -> str | None:
    """Run one password-manager command and return its stdout minus the final newline; None on any failure or empty answer.
    Its stderr is dropped, so nothing it says can reach a log."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(env),
                              timeout=LOOKUP_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    value: str = done.stdout.rstrip("\r\n") if done.returncode == 0 else ""
    return value or None


def from_env(name: str, env: Mapping[str, str]) -> str | None:
    return env.get(name) or None


def from_python_keyring(service: str, user: str) -> str | None:
    try:
        import keyring  # noqa: PLC0415 - optional; the CLI fallbacks below cover its absence
        value: Any = keyring.get_password(service, user)
    except Exception:  # noqa: BLE001 - no module, no backend or a locked store all mean "not found here"
        return None
    return value if isinstance(value, str) and value else None


def from_keyring(spec: str, env: Mapping[str, str]) -> str | None:
    """`service/user` from the python keyring when it imports, else `secret-tool` (Linux) or `security` (macOS)."""
    service, _, user = spec.partition("/")
    if not service or not user:
        return None
    found: str | None = from_python_keyring(service, user)
    if found:
        return found
    if sys.platform == "darwin" and not os.environ.get(SECRET_TOOL_BIN):
        return run_lookup([*binary(SECURITY_BIN, "security"), "find-generic-password", "-s", service, "-a", user, "-w"], env)
    return run_lookup([*binary(SECRET_TOOL_BIN, "secret-tool"), "lookup", "service", service, "username", user], env)


def from_op(ref: str, env: Mapping[str, str]) -> str | None:
    return run_lookup([*binary(OP_BIN, "op"), "read", ref], env)


def from_doppler(spec: str, env: Mapping[str, str]) -> str | None:
    """`PROJECT/CONFIG/NAME`."""
    parts: list[str] = spec.split("/")
    if len(parts) != 3 or not all(parts):
        return None
    project, config, name = parts
    return run_lookup([*binary(DOPPLER_BIN, "doppler"), "secrets", "get", name, "--plain", "--project", project, "--config", config], env)


def resolve_key(profile: Mapping[str, Any], env: Mapping[str, str] | None = None) -> tuple[str | None, str]:
    """(key or None, source label). With an `apiKeyRef` only that ref is tried; with none, the profile's `apiKeyEnv` variable in
    `env` (default: this process's environment). The label never holds the key."""
    source: Mapping[str, str] = os.environ if env is None else env
    label: str = source_label(profile)
    ref: str | None = ref_of(profile)
    if ref is None:
        key_env: str | None = key_env_of(profile)
        return (from_env(key_env, source) if key_env else None), label
    scheme: str = scheme_of(ref)
    rest: str = ref.split(":", 1)[1] if ":" in ref else ""
    if scheme == SCHEME_ENV:
        return from_env(rest, source), label
    if scheme == SCHEME_KEYRING:
        return from_keyring(rest, source), label
    if scheme == SCHEME_OP:
        return from_op(ref, source), label
    if scheme == SCHEME_DOPPLER:
        return from_doppler(rest, source), label
    return None, label


def has_key(profile: Mapping[str, Any], env: Mapping[str, str] | None = None) -> bool:
    return resolve_key(profile, env)[0] is not None


def missing_message(profile: Mapping[str, Any]) -> str:
    """The refusal text for a key agent with no key: names the ref or variable and how to set it. No secret."""
    name: str = str(profile.get("name") or "agent")
    ref: str | None = ref_of(profile)
    key_env: str = key_env_of(profile) or "its key variable"
    where: str = f"apiKeyRef '{ref}' returned no key" if ref else f"{key_env} is not set"
    return f"agent '{name}' has no API key: {where}; " + SETUP_HINT.format(env=key_env)


def home_dir(profile: Mapping[str, Any]) -> Path | None:
    """The agent's own home folder (`agents-home/<name>` beside the user agents folder), or None when its profile has no `homeEnv`."""
    if not isinstance(profile.get("homeEnv"), str) or not profile["homeEnv"]:
        return None
    name: str = NAME_UNSAFE.sub("-", str(profile.get("name") or "agent")).strip(".-") or "agent"
    return user_agents_dir().parent / HOME_PARENT / name


def home_env(profile: Mapping[str, Any]) -> dict[str, str]:
    """`{CLAUDE_CONFIG_DIR: <path>}` for a profile with a private home; nothing is created. `{}` otherwise."""
    folder: Path | None = home_dir(profile)
    return {str(profile["homeEnv"]): str(folder)} if folder is not None else {}


def prepare_home(profile: Mapping[str, Any]) -> dict[str, str]:
    """Create the private home (0700) and write each of the profile's `homeFiles` that is missing (0600); the env it adds."""
    folder: Path | None = home_dir(profile)
    if folder is None:
        return {}
    folder.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    folder.chmod(DIR_MODE)
    files: Any = profile.get("homeFiles")
    for name, text in (files.items() if isinstance(files, dict) else []):
        target: Path = folder / str(name)
        if target.exists() or Path(str(name)).name != str(name):
            continue
        fd: int = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(text))
    return home_env(profile)


def child_env(profile: Mapping[str, Any], base: Mapping[str, str], source: Mapping[str, str] | None = None) -> tuple[dict[str, str], str]:
    """(the launch environment, source label): `base` (already scrubbed) plus the profile's private home and, only here, its
    key under its own variable. KeyMissing when no key is found, before anything is created."""
    value, label = resolve_key(profile, source)
    key_env: str | None = key_env_of(profile)
    if value is None or key_env is None:
        raise KeyMissing(missing_message(profile))
    env: dict[str, str] = {**base, **prepare_home(profile)}
    env[key_env] = value
    return env, label
