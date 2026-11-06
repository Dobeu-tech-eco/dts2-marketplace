"""Agent profiles in one place. `Profiles.load()` merges three layers: the bundled profiles/agents/*.json, then the user's
(~/.dts2/agents, or $DTS2_USER_AGENTS_DIR), then the project's (.harness/agents); later layers win field by field and a
profile may `extends` another. `Profiles(dict)` wraps any dict, so a test injects its own. roster, delegate, council,
agent-memory and failover go through it instead of globbing the folder."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Final, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_names  # noqa: E402
import state_io  # noqa: E402

PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "agents"
USER_AGENTS_ENV: Final[str] = "DTS2_USER_AGENTS_DIR"
USER_AGENTS_DEFAULT: Final[str] = "~/.dts2/agents"
BUNDLED: Final[str] = "bundled"
USER: Final[str] = "user"
PROJECT: Final[str] = "project"
LAYERS: Final[tuple[str, ...]] = (BUNDLED, USER, PROJECT)
ADVISORY_ROLES: Final[tuple[str, ...]] = ("reviewer", "second-opinion")
DEFAULT_BURN: Final[int] = 1
RAW_KEY: Final[re.Pattern[str]] = re.compile(r"\b(?:sk|xai)-[A-Za-z0-9_-]{20,}")
KEY_REF: Final[re.Pattern[str]] = re.compile(
    r"^(?:keyring:[\w.\-/]+|op://\S+|doppler:[\w.\-/]+|env:[A-Za-z_][A-Za-z0-9_]*)$"
)
REQUIRED_KEYS: Final[tuple[str, ...]] = ("roles", "invocation", "costTier", "statusCommand", "command", "models")
# Profile keys that end up in argv, a subprocess environment or a file path. A project profile (repo-controlled) may not set
# them unless the user trusts the project; see trusted_project().
EXECUTABLE_KEYS: Final[tuple[str, ...]] = (
    "command", "statusCommand", "loginCommand", "roleCommand", "roleCommands", "invocation", "env", "searchPaths",
    "stdin", "headlessFlag", "apiKeyEnv", "rulesFile", "binary", "bin", "path", "cwd",
    "readOnlyCommand", "readOnlyRoles", "budgetFlag", "tierEffort", "apiKeyRef", "homeEnv", "homeFiles",
    "keyRequired", "leadEligible", "auth", "defaultModel",
)


def has_raw_key(value: Any) -> bool:
    """True when any string inside `value` looks like a raw API key (`sk-` or `xai-` plus 20 or more characters)."""
    if isinstance(value, str):
        return RAW_KEY.search(value) is not None
    if isinstance(value, dict):
        return any(has_raw_key(item) for item in value.values())
    if isinstance(value, list):
        return any(has_raw_key(item) for item in value)
    return False


def valid_key_ref(ref: object) -> bool:
    """A pointer such as `keyring:dts2/grok-api`, `op://vault/item/field`, `doppler:NAME` or `env:VAR`; never a key."""
    return isinstance(ref, str) and KEY_REF.match(ref) is not None and not has_raw_key(ref)


def user_agents_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get(USER_AGENTS_ENV) or USER_AGENTS_DEFAULT))


def project_agents_dir(project: Path | str | None = None) -> Path:
    return Path(project or Path.cwd()).joinpath(*state_io.AGENT_PROFILES_REL.split("/"))


def trusted_projects_file() -> Path:
    """The user-owned list of trusted projects, next to the user agents folder (one absolute path per line)."""
    return user_agents_dir().parent / state_io.TRUSTED_PROJECTS_NAME


def trusted_project(project: Path | str | None = None) -> bool:
    try:
        lines: list[str] = trusted_projects_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    root: str = str(Path(project or Path.cwd()).resolve())
    return root in {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def strip_executable(data: dict[str, Any], path: Path, warnings: list[str]) -> dict[str, Any]:
    """`data` without its executable keys; a warning names the agent and the keys dropped."""
    dropped: list[str] = [key for key in EXECUTABLE_KEYS if key in data]
    if not dropped:
        return data
    warnings.append(
        f"project profile '{data['name']}' ({path.name}): dropped executable fields {', '.join(dropped)}"
        f" (list the project in {trusted_projects_file()} to allow them)"
    )
    return {key: value for key, value in data.items() if key not in dropped}


def protected(profile: dict[str, Any] | None) -> bool:
    """A profile the rules depend on: an API-key agent (`keyRequired`) or one that never leads (`leadEligible: false`)."""
    return bool(profile) and (profile.get("keyRequired") is True or profile.get("leadEligible") is False)  # type: ignore[union-attr]


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` on top of `base`: dicts merge recursively, lists and scalars are replaced."""
    merged: dict[str, Any] = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def layer_problem(data: dict[str, Any], layer: str) -> str | None:
    if has_raw_key(data):
        return "it contains something that looks like a raw API key; use apiKeyRef"
    if "apiKeyRef" in data and not valid_key_ref(data["apiKeyRef"]):
        return "apiKeyRef must be keyring:..., op://..., doppler:... or env:VAR"
    if "extends" in data and not (isinstance(data["extends"], str) and data["extends"]):
        return "extends must be a profile name"
    reason: str | None = agent_names.validate_name(data["name"]) if layer != BUNDLED else None
    return f"bad name: {reason}" if reason else None


def layer_files(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    """(path, data) of every readable profile file in one folder that carries a `name`, in file-name order."""
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"]:
            found.append((path, data))
    return found


def read_layer(
    directory: Path, layer: str, warnings: list[str], trusted: bool = True,
) -> dict[str, dict[str, Any]]:
    """Every acceptable profile in one folder, by name. A bad one is skipped with a warning."""
    found: dict[str, dict[str, Any]] = {}
    for path, data in layer_files(directory):
        problem: str | None = layer_problem(data, layer)
        if problem:
            warnings.append(f"{layer} profile '{data['name']}' ({path.name}) dropped: {problem}")
            continue
        found[data["name"]] = data if trusted or layer != PROJECT else strip_executable(data, path, warnings)
    return found


def resolve_extends(
    raw: dict[str, dict[str, Any]], origins: dict[str, list[str]], warnings: list[str],
) -> dict[str, dict[str, Any]]:
    """Merge each profile over its `extends` parent (after every layer is loaded). A cycle, a missing parent or a profile
    that lacks what a roster needs is dropped with a warning; nothing raises."""
    resolved: dict[str, dict[str, Any] | None] = {}

    def build(name: str, stack: tuple[str, ...]) -> dict[str, Any] | None:
        if name in resolved:
            return resolved[name]
        if name in stack:
            return None
        profile: dict[str, Any] = raw[name]
        parent_name: Any = profile.get("extends")
        result: dict[str, Any] | None = profile
        if parent_name is not None:
            parent: dict[str, Any] | None = build(parent_name, (*stack, name)) if parent_name in raw else None
            if parent is None:
                why: str = "cycle" if parent_name in stack or parent_name == name else f"parent '{parent_name}' missing or dropped"
                warnings.append(f"profile '{name}' dropped: extends {why}")
                result = None
            else:
                result = deep_merge(parent, profile)
        if result is not None and origins[name][-1] != BUNDLED:
            missing: list[str] = [key for key in REQUIRED_KEYS if key not in result]
            if missing:
                warnings.append(f"profile '{name}' dropped: missing {', '.join(missing)} (extend a bundled profile)")
                result = None
        resolved[name] = result
        return result

    for name in raw:
        build(name, ())
    return {name: profile for name, profile in resolved.items() if profile is not None}


class Profiles:
    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self._data: dict[str, dict[str, Any]] = dict(data or {})
        self._origins: dict[str, list[str]] = {name: [BUNDLED] for name in self._data}
        self.warnings: list[str] = []

    @classmethod
    def load(
        cls, profile_dir: Path | str | None = None, *, layered: bool | None = None,
        project: Path | str | None = None, user_dir: Path | str | None = None,
    ) -> Profiles:
        """Every readable profile that carries a `name`. With no `profile_dir` (or `layered=True`) the user and project
        layers are merged over the bundled ones; an explicit `profile_dir` alone reads just that folder, in file-name order."""
        use_layers: bool = profile_dir is None if layered is None else layered
        warnings: list[str] = []
        raw: dict[str, dict[str, Any]] = {}
        origins: dict[str, list[str]] = {}
        folders: list[tuple[str, Path]] = [(BUNDLED, Path(profile_dir or PROFILE_DIR))]
        if use_layers:
            folders += [(USER, Path(user_dir) if user_dir else user_agents_dir()), (PROJECT, project_agents_dir(project))]
        trusted: bool = not use_layers or trusted_project(project)
        for layer, folder in folders:
            for name, data in read_layer(folder, layer, warnings, trusted).items():
                if layer == PROJECT and not trusted and protected(raw.get(name)) and set(data) - {"name"}:
                    warnings.append(f"project profile '{name}': ignored, it would change an API-key or non-lead agent "
                                    f"(list the project in {trusted_projects_file()} to allow it)")
                    continue
                raw[name] = deep_merge(raw[name], data) if name in raw else dict(data)
                origins.setdefault(name, []).append(layer)
        profiles: Profiles = cls(resolve_extends(raw, origins, warnings))
        profiles._origins = {name: origins[name] for name in profiles._data}
        profiles.warnings = warnings
        return profiles

    def layer_of(self, name: str) -> str:
        """"bundled", "user" or "project": the highest layer that defines `name` ("" when unknown)."""
        return (self._origins.get(name) or [""])[-1]

    def layers_of(self, name: str) -> list[str]:
        """Every layer that defines `name`, lowest first."""
        return list(self._origins.get(name) or [])

    def base_of(self, name: str) -> str:
        """The root of the `extends` chain (`name` itself when it extends nothing)."""
        seen: set[str] = set()
        current: str = name
        while current not in seen:
            seen.add(current)
            parent: Any = (self._data.get(current) or {}).get("extends")
            if not isinstance(parent, str) or parent not in self._data:
                break
            current = parent
        return current

    def names(self) -> list[str]:
        return list(self._data)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)

    def get(self, name: str) -> dict[str, Any] | None:
        return self._data.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def model(self, name: str, tier: str) -> str | None:
        """The model id a profile pins for `tier`, or None."""
        models: Any = (self._data.get(name) or {}).get("models")
        value: Any = models.get(tier) if isinstance(models, dict) else None
        return value if isinstance(value, str) and value else None

    def token_burn(self, name: str, tier: str, default: int = DEFAULT_BURN) -> int:
        """Relative token cost of a tier; `default` when the profile or tier is missing or the value is not a positive int."""
        burn: Any = (self._data.get(name) or {}).get("tokenBurn")
        value: Any = burn.get(tier) if isinstance(burn, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default

    def lead_eligible(self) -> list[str]:
        """Names that can fill advisory and sign-off seats (a reviewer or an independent second opinion), sorted. A profile with
        `leadEligible: false` (the API-key agents) is never one: it neither leads nor signs off, nor takes over as lead."""
        return sorted(
            name for name, profile in self._data.items()
            if profile.get("leadEligible") is not False and any(role in (profile.get("roles") or []) for role in ADVISORY_ROLES)
        )
