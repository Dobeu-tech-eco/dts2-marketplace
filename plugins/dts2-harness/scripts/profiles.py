"""Agent profiles in one place. `Profiles.load()` reads profiles/agents/*.json; `Profiles(dict)` wraps any dict, so a test
injects its own. roster, delegate, council, agent-memory and failover go through it instead of globbing the folder."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Iterator

PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "agents"
ADVISORY_ROLES: Final[tuple[str, ...]] = ("reviewer", "second-opinion")
DEFAULT_BURN: Final[int] = 1


class Profiles:
    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self._data: dict[str, dict[str, Any]] = dict(data or {})

    @classmethod
    def load(cls, profile_dir: Path | str | None = None) -> Profiles:
        """Every readable profile in the folder that carries a `name`, in file-name order."""
        found: dict[str, dict[str, Any]] = {}
        for path in sorted(Path(profile_dir or PROFILE_DIR).glob("*.json")):
            try:
                data: Any = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"]:
                found[data["name"]] = data
        return cls(found)

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
        """Names that can fill advisory and sign-off seats (a reviewer or an independent second opinion), sorted."""
        return sorted(
            name for name, profile in self._data.items()
            if any(role in (profile.get("roles") or []) for role in ADVISORY_ROLES)
        )
