"""Rules for the name of a user-chosen agent such as `grok-api`: shape, reserved words, uniqueness and suggestions.
Pure functions; `profiles` is anything with `names()` and `layer_of()` (a `profiles.Profiles`)."""
from __future__ import annotations

import re
from typing import Any, Final, Iterable

NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
RESERVED: Final[frozenset[str]] = frozenset({
    "lead", "builder", "reviewer", "verifier", "scout", "auditor", "fixer",
    "all", "none", "frontier", "standard", "economy",
})
API_SUFFIX: Final[str] = "-api"


def validate_name(name: str) -> str | None:
    """None when `name` is usable, else the reason it is not."""
    if not NAME_PATTERN.match(name):
        return "use lowercase kebab-case, 2-32 characters, starting with a letter (a-z, 0-9, single dashes)"
    if "--" in name:
        return "no double dashes"
    if name in RESERVED:
        return f"'{name}' is a reserved word"
    return None


def suggest_name(base: str, taken: Iterable[str]) -> str:
    """`base` when free, else `<base>-api`, else `<base>-api-2`, `-3`, ..."""
    used: set[str] = set(taken)
    if base not in used:
        return base
    candidate: str = base + API_SUFFIX
    counter: int = 2
    while candidate in used:
        candidate = f"{base}{API_SUFFIX}-{counter}"
        counter += 1
    return candidate


def next_free(name: str, taken: Iterable[str]) -> str:
    """`<name>-2`, `<name>-3`, ... : the first that is not taken."""
    used: set[str] = set(taken)
    counter: int = 2
    while f"{name}-{counter}" in used:
        counter += 1
    return f"{name}-{counter}"


def collision(name: str, profiles: Any) -> str | None:
    """The layer ("bundled", "user" or "project") that already has `name`, or None."""
    return profiles.layer_of(name) if name in profiles.names() else None
