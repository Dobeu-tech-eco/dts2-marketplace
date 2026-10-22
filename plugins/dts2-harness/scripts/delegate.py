#!/usr/bin/env python3
"""Resolve model, tier and effort for a dispatch seat. Frontier is for advice and sign-off only; builders never get it."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "profiles" / "agents"
EFFORT_LEVELS: Final[tuple[str, ...]] = ("low", "medium", "high", "max")
SEATS: Final[tuple[str, ...]] = ("execution", "advisory", "signoff")
BUDGETS: Final[tuple[str, ...]] = ("ok", "low", "exhausted")
EXECUTION_EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
ADVISORY_EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
SIGNOFF_EFFORT: Final[dict[str, str]] = {"mechanical": "medium", "normal": "high", "design": "max"}
ADVISORY_TIER: Final[dict[str, str]] = {"mechanical": "standard", "normal": "standard", "design": "frontier"}
FRONTIER: Final[str] = "frontier"
STANDARD: Final[str] = "standard"
ECONOMY: Final[str] = "economy"
DEFAULT_EFFORT: Final[str] = "medium"
LOW_BUDGET_EFFORT_CAP: Final[str] = "medium"
EXHAUSTED_EFFORT: Final[str] = "low"
DEFAULT_LEAD: Final[str] = "claude"
# Roles that make a provider able to give advice: a reviewer, or an independent second opinion.
ADVISORY_ROLES: Final[tuple[str, ...]] = ("reviewer", "second-opinion")
SEAT_EFFORT: Final[dict[str, dict[str, str]]] = {
    "execution": EXECUTION_EFFORT, "advisory": ADVISORY_EFFORT, "signoff": SIGNOFF_EFFORT,
}


class DelegationError(Exception):
    """Raised on an unknown seat, complexity or agent, or when a builder would run a frontier model."""


def execution_tier(complexity: str) -> str:
    """Cheapest capable tier for a builder: economy for mechanical work, standard otherwise. Never frontier."""
    return ECONOMY if complexity == "mechanical" else STANDARD


def assert_execution_not_frontier(tier: str) -> None:
    if tier == FRONTIER:
        raise DelegationError("execution seats never run a frontier model")


def violates_execution_policy(seat: str, tier: str) -> bool:
    return seat == "execution" and tier == FRONTIER


def level_index(level: str) -> int:
    return EFFORT_LEVELS.index(level)


def clamp_effort(desired: str, available: list[str]) -> str:
    """The desired level if supported, else the highest supported level at or below it, else the highest supported."""
    if not available:
        return DEFAULT_EFFORT
    if desired in available:
        return desired
    ranked: list[str] = sorted((a for a in available if a in EFFORT_LEVELS), key=level_index)
    if not ranked:
        return DEFAULT_EFFORT
    below: list[str] = [a for a in ranked if level_index(a) <= level_index(desired)]
    return below[-1] if below else ranked[-1]


def lead_eligible(profiles: dict[str, dict[str, Any]]) -> list[str]:
    """Names of profiles that can fill advisory and sign-off seats, sorted by name."""
    return sorted(
        name for name, profile in profiles.items()
        if any(role in profile.get("roles", []) for role in ADVISORY_ROLES)
    )


def signoff_agent(profiles: dict[str, dict[str, Any]], lead_provider: str) -> str:
    return lead_provider if lead_provider in lead_eligible(profiles) else DEFAULT_LEAD


def check_inputs(seat: str, complexity: str, budget: str) -> None:
    if seat not in SEATS:
        raise DelegationError(f"unknown seat '{seat}'")
    if complexity not in EXECUTION_EFFORT:
        raise DelegationError(f"unknown complexity '{complexity}'")
    if budget not in BUDGETS:
        raise DelegationError(f"unknown budget '{budget}'")


def execution_plan(profile: dict[str, Any], complexity: str, budget: str) -> tuple[str, str]:
    levels: list[str] = profile.get("effortLevels", [DEFAULT_EFFORT])
    if budget == "exhausted":
        assert_execution_not_frontier(ECONOMY)
        return ECONOMY, EXHAUSTED_EFFORT
    tier: str = execution_tier(complexity)
    desired: str = EXECUTION_EFFORT[complexity]
    if budget == "low" and level_index(desired) > level_index(LOW_BUDGET_EFFORT_CAP):
        desired = LOW_BUDGET_EFFORT_CAP
    assert_execution_not_frontier(tier)
    return tier, clamp_effort(desired, levels)


def seat_plan(profile: dict[str, Any], seat: str, complexity: str, budget: str) -> tuple[str, str]:
    if seat == "execution":
        return execution_plan(profile, complexity, budget)
    levels: list[str] = profile.get("effortLevels", [DEFAULT_EFFORT])
    tier: str = ADVISORY_TIER[complexity] if seat == "advisory" else FRONTIER
    return tier, clamp_effort(SEAT_EFFORT[seat][complexity], levels)


def pick_profile(
    profile: dict[str, Any], seat: str, lead_provider: str | None,
    profiles: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Advisory and sign-off seats follow the chosen lead provider; execution never does."""
    if seat == "execution" or lead_provider is None:
        return profile
    pool: dict[str, dict[str, Any]] = profiles if profiles is not None else load_profiles(PROFILE_DIR)
    chosen: str = signoff_agent(pool, lead_provider)
    return pool.get(chosen, profile)


def delegate(
    profile: dict[str, Any], seat: str, complexity: str, budget: str = "ok",
    lead_provider: str | None = None, profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    check_inputs(seat, complexity, budget)
    chosen: dict[str, Any] = pick_profile(profile, seat, lead_provider, profiles)
    tier, effort = seat_plan(chosen, seat, complexity, budget)
    return {
        "agent": chosen["name"], "seat": seat, "model": chosen["models"][tier], "tier": tier,
        "effort": effort, "tokenBurn": chosen.get("tokenBurn", {}).get(tier),
    }


def load_profiles(profile_dir: Path) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(profile_dir.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        profiles[data["name"]] = data
    return profiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR))
    parser.add_argument("--agent", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--complexity", required=True)
    parser.add_argument("--budget", default="ok")
    parser.add_argument("--lead-provider", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profiles: dict[str, dict[str, Any]] = load_profiles(Path(args.profile_dir))
    if args.agent not in profiles:
        print(f"delegate error: unknown agent '{args.agent}'", file=sys.stderr)
        return 1
    try:
        result: dict[str, Any] = delegate(
            profiles[args.agent], args.seat, args.complexity, args.budget, args.lead_provider, profiles,
        )
    except DelegationError as error:
        print(f"delegate error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
