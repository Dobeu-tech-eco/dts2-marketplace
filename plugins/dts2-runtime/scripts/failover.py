#!/usr/bin/env python3
"""Pick the next lead provider when the current one stalls on a usage or token limit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profiles import PROFILE_DIR, Profiles  # noqa: E402

LIST_SEPARATOR: Final[str] = ","


def lead_eligible(profiles: dict[str, dict[str, Any]]) -> list[str]:
    return Profiles(profiles).lead_eligible()


def rotation(eligible: list[str], current: str) -> list[str]:
    """Providers starting just after current, wrapping round.

    Keeps the order it is given (see verified_first for the failover order).
    """
    if current not in eligible:
        return list(eligible)
    start: int = eligible.index(current) + 1
    return eligible[start:] + eligible[:start]


def verified_first(profiles: dict[str, dict[str, Any]]) -> list[str]:
    """Lead-eligible names: verified providers first, then unverified, each alphabetical."""
    eligible: list[str] = lead_eligible(profiles)
    verified: list[str] = [n for n in eligible if profiles[n].get("verified") is True]
    unverified: list[str] = [n for n in eligible if n not in verified]
    return verified + unverified


def cooling_now() -> list[str]:
    """Names with an active cooldown; empty when the cooldown store cannot be read."""
    try:
        import cooldowns
        return list(cooldowns.cooling_names())
    except Exception:
        return []


def next_lead(
    profiles: dict[str, dict[str, Any]], current: str, exclude: Iterable[str] = (),
    cooling: Iterable[str] | None = None,
) -> str | None:
    paused: Iterable[str] = cooling_now() if cooling is None else cooling
    skipped: set[str] = {current, *exclude, *paused}
    for name in rotation(verified_first(profiles), current):
        if name not in skipped:
            return name
    return None


def parse_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(LIST_SEPARATOR) if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR))
    parser.add_argument("--current", required=True)
    parser.add_argument("--exclude", default="")
    args = parser.parse_args()
    profiles: dict[str, dict[str, Any]] = Profiles.load(Path(args.profile_dir)).as_dict()
    chosen: str | None = next_lead(profiles, args.current, parse_list(args.exclude))
    print(json.dumps({"current": args.current, "next": chosen}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
