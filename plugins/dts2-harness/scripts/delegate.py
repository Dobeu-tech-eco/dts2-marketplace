#!/usr/bin/env python3
"""Resolve model, tier and effort for a dispatch seat. Frontier is for advice and sign-off only; builders never get it."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_rules  # noqa: E402
import state_io  # noqa: E402
from profiles import PROFILE_DIR, Profiles  # noqa: E402

EFFORT_LEVELS: Final[tuple[str, ...]] = ("low", "medium", "high", "xhigh", "max", "ultra")
HIGH: Final[str] = "high"
COMPLEXITY_ORDER: Final[tuple[str, ...]] = ("mechanical", "normal", "design")
DEFAULT_COMPLEXITY: Final[str] = "normal"
SEATS: Final[tuple[str, ...]] = ("execution", "advisory", "signoff", "escalation")
OWN_PROFILE_SEATS: Final[tuple[str, ...]] = ("execution", "escalation")  # these never follow the lead provider
BUDGETS: Final[tuple[str, ...]] = ("ok", "low", "exhausted")
EXECUTION_EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
ADVISORY_EFFORT: Final[dict[str, str]] = {"mechanical": "low", "normal": "medium", "design": "high"}
ESCALATION_EFFORT: Final[dict[str, str]] = {"mechanical": "high", "normal": "high", "design": "high"}  # the fixer at fix round 2 (AA-4)
SIGNOFF_EFFORT: Final[dict[str, str]] = {"mechanical": "medium", "normal": "high", "design": "max"}
ADVISORY_TIER: Final[dict[str, str]] = {"mechanical": "standard", "normal": "standard", "design": "frontier"}
FRONTIER: Final[str] = "frontier"
STANDARD: Final[str] = "standard"
ECONOMY: Final[str] = "economy"
DEFAULT_EFFORT: Final[str] = "medium"
LOW_BUDGET_EFFORT_CAP: Final[str] = "medium"
EXHAUSTED_EFFORT: Final[str] = "low"
DEFAULT_LEAD: Final[str] = "claude"
FIX_SONNET_ROUNDS: Final[int] = 3  # fix rounds 1-3 run on Sonnet
FIX_MAX_ROUNDS: Final[int] = 5  # rounds 4-5 run on Opus, a fresh worker one tier up
# Roles that make a provider able to give advice: a reviewer, or an independent second opinion.
ADVISORY_ROLES: Final[tuple[str, ...]] = ("reviewer", "second-opinion")
SEAT_EFFORT: Final[dict[str, dict[str, str]]] = {
    "execution": EXECUTION_EFFORT, "advisory": ADVISORY_EFFORT, "signoff": SIGNOFF_EFFORT, "escalation": ESCALATION_EFFORT,
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


def fix_round_model(round_no: int) -> str:
    """Model alias for a fix round: sonnet for rounds 1-3, opus for rounds 4-5. Other rounds are refused."""
    if not 1 <= round_no <= FIX_MAX_ROUNDS:
        raise DelegationError(f"fix round {round_no} is outside 1..{FIX_MAX_ROUNDS}")
    return "sonnet" if round_no <= FIX_SONNET_ROUNDS else "opus"


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
    return Profiles(profiles).lead_eligible()


def signoff_agent(profiles: dict[str, dict[str, Any]], lead_provider: str) -> str:
    return lead_provider if lead_provider in lead_eligible(profiles) else DEFAULT_LEAD


def check_inputs(seat: str, complexity: str, budget: str) -> None:
    if seat not in SEATS:
        raise DelegationError(f"unknown seat '{seat}'")
    if complexity not in EXECUTION_EFFORT:
        raise DelegationError(f"unknown complexity '{complexity}'")
    if budget not in BUDGETS:
        raise DelegationError(f"unknown budget '{budget}'")


def model_for(profile: dict[str, Any], tier: str) -> str | None:
    value: Any = profile["models"].get(tier)
    return value if isinstance(value, str) and value else None


def supported_efforts(profile: dict[str, Any], model: str | None) -> list[str]:
    """Levels the model accepts. A profile without per-model lists uses effortLevels."""
    by_model: dict[str, Any] = profile.get("modelEfforts") or {}
    listed: Any = by_model.get(model) if isinstance(model, str) else None
    if isinstance(listed, list) and listed:
        return [str(level) for level in listed]
    return [str(level) for level in (profile.get("effortLevels") or [DEFAULT_EFFORT])]


def automatic_efforts(profile: dict[str, Any], model: str | None, seat: str) -> list[str]:
    """Levels delegate may choose. explicitOnlyEfforts (max, ultra) stay out unless requested.
    Builders and advisory stay at or below high; sign-off may use the next listed level (xhigh)."""
    levels: list[str] = supported_efforts(profile, model)
    blocked: set[str] = {str(level) for level in (profile.get("explicitOnlyEfforts") or [])}
    auto: list[str] = [level for level in levels if level not in blocked]
    if seat != "signoff":
        capped: list[str] = [
            level for level in auto if level in EFFORT_LEVELS and level_index(level) <= level_index(HIGH)
        ]
        return capped or auto or levels
    return auto or levels


def explicit_effort(profile: dict[str, Any], tier: str, effort: str) -> str:
    """An explicit request may use max or ultra, clamped to what that model accepts."""
    if effort not in EFFORT_LEVELS:
        raise DelegationError(f"unknown effort '{effort}'")
    return clamp_effort(effort, supported_efforts(profile, model_for(profile, tier)))


def execution_plan(profile: dict[str, Any], complexity: str, budget: str) -> tuple[str, str]:
    if budget == "exhausted":
        assert_execution_not_frontier(ECONOMY)
        tier, desired = ECONOMY, EXHAUSTED_EFFORT
    else:
        tier = execution_tier(complexity)
        desired = EXECUTION_EFFORT[complexity]
        if budget == "low" and level_index(desired) > level_index(LOW_BUDGET_EFFORT_CAP):
            desired = LOW_BUDGET_EFFORT_CAP
        assert_execution_not_frontier(tier)
    return tier, clamp_effort(desired, automatic_efforts(profile, model_for(profile, tier), "execution"))


def highest_complexity(found: list[str]) -> str:
    """The hardest known complexity in `found`; unknown words are ignored and an empty list means normal."""
    known: list[str] = [c for c in found if c in COMPLEXITY_ORDER]
    return max(known, key=COMPLEXITY_ORDER.index) if known else DEFAULT_COMPLEXITY


def builder_recommendation(complexity: str, profile: dict[str, Any], budget: str = "ok") -> tuple[str, str]:
    """(tier, effort) a builder gets for this complexity: the same call `delegate` makes for an execution seat."""
    check_inputs("execution", complexity, budget)
    return execution_plan(profile, complexity, budget)


def seat_plan(profile: dict[str, Any], seat: str, complexity: str, budget: str) -> tuple[str, str]:
    if seat == "execution":
        return execution_plan(profile, complexity, budget)
    tier: str = ADVISORY_TIER[complexity] if seat == "advisory" else FRONTIER
    return tier, clamp_effort(
        SEAT_EFFORT[seat][complexity], automatic_efforts(profile, model_for(profile, tier), seat),
    )


def seat_candidates(
    profile: dict[str, Any], seat: str, lead_provider: str | None, profiles: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Profiles that may fill a seat, best first. Execution and escalation seats are the given profile alone; advisory and
    sign-off seats start with the lead provider's profile (Claude when it is not eligible), then the other eligible ones."""
    if seat in OWN_PROFILE_SEATS or lead_provider is None:
        return [profile]
    pool: dict[str, dict[str, Any]] = profiles if profiles is not None else load_profiles(PROFILE_DIR)
    chosen: str = signoff_agent(pool, lead_provider)
    first: dict[str, Any] = pool.get(chosen, profile)
    others: list[str] = [n for n in dict.fromkeys([DEFAULT_LEAD, *lead_eligible(pool)]) if n in pool and n != first["name"]]
    return [first, *[pool[name] for name in others]]


def rules_denial(rules: dict[str, dict[str, Any]], name: str, task_class: str | None, tier: str | None) -> str | None:
    """Why the effective rules of agent `name` refuse the task class or tier, or None (an agent without rules is free)."""
    allowed, why = agent_rules.permits(rules.get(name), task_class, tier)
    return None if allowed else why


def pick_profile(
    profile: dict[str, Any], seat: str, lead_provider: str | None,
    profiles: dict[str, dict[str, Any]] | None,
    task_class: str | None = None, tier: str | None = None, rules: dict[str, dict[str, Any]] | None = None,
    skipped: list[dict[str, str]] | None = None, complexity: str | None = None, budget: str = "ok",
) -> dict[str, Any]:
    """Advisory and sign-off seats follow the chosen lead provider; execution and escalation never do. With `rules` (the
    effective rules by agent name) and a `task_class` or `tier`, a candidate whose rules deny it is skipped (recorded in
    `skipped` as {name, reason}) and the next eligible one is used; none left raises DelegationError naming every reason.
    Without `tier`, the tier the seat would run on (from `complexity`) is checked."""
    options: list[dict[str, Any]] = seat_candidates(profile, seat, lead_provider, profiles)
    if not rules or (task_class is None and tier is None and complexity is None):
        return options[0]
    found: list[dict[str, str]] = []
    for option in options:
        wanted: str | None = tier or (seat_plan(option, seat, complexity, budget)[0] if complexity else None)
        why: str | None = rules_denial(rules, option["name"], task_class, wanted)
        if why is None:
            if skipped is not None:
                skipped.extend(found)
            return option
        found.append({"name": option["name"], "reason": why})
    raise DelegationError(f"no eligible agent for seat '{seat}': " + "; ".join(f"{f['name']}: {f['reason']}" for f in found))


def delegate(
    profile: dict[str, Any], seat: str, complexity: str, budget: str = "ok",
    lead_provider: str | None = None, profiles: dict[str, dict[str, Any]] | None = None,
    effort: str | None = None, task_class: str | None = None, rules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    check_inputs(seat, complexity, budget)
    skipped: list[dict[str, str]] = []
    chosen: dict[str, Any] = pick_profile(profile, seat, lead_provider, profiles, task_class, None, rules, skipped, complexity, budget)
    tier, planned = seat_plan(chosen, seat, complexity, budget)
    resolved: str = explicit_effort(chosen, tier, effort) if effort else planned
    result: dict[str, Any] = {
        "agent": chosen["name"], "seat": seat, "model": chosen["models"][tier], "tier": tier,
        "effort": resolved, "tokenBurn": chosen.get("tokenBurn", {}).get(tier),
    }
    return {**result, "skipped": skipped} if skipped else result


def observed_model(profile: dict[str, Any], model: str | None) -> str | None:
    """The model a run actually used. An empty id is the profile default (codex: gpt-6.1-sol)."""
    if isinstance(model, str) and model:
        return model
    default: Any = profile.get("defaultModel")
    if isinstance(default, str) and default:
        return default
    return model_for(profile, STANDARD)


def tier_of_model(profile: dict[str, Any], model: str | None) -> str | None:
    """Map an observed model id to frontier, standard, or economy. First matching tier wins."""
    observed: str | None = observed_model(profile, model)
    for tier in ("frontier", "standard", "economy"):
        if model_for(profile, tier) == observed and observed is not None:
            return tier
    return None


def receipt_line(profile: dict[str, Any], seat: str, effort: str, model: str | None = None) -> str:
    """One Delegation row: model, tier, and effort. An unpinned codex default reports as standard."""
    shown: str = observed_model(profile, model) or "unpinned"
    tier: str | None = tier_of_model(profile, model)
    tier_bit: str = f" tier={tier}" if tier else ""
    return f"- {profile['name']} {shown}{tier_bit} effort={effort} ({seat})"


def load_profiles(profile_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Layered (bundled, user, project) profiles by default; an explicit folder reads only that folder."""
    return Profiles.load(profile_dir).as_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", default=None, help="read only this folder (default: bundled, user and project layers)")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--complexity", required=True)
    parser.add_argument("--budget", default="ok")
    parser.add_argument("--lead-provider", default=None)
    parser.add_argument("--effort", default=None, help="explicit effort; max and ultra are not chosen otherwise")
    parser.add_argument("--task-class", default=None, choices=agent_rules.TASK_CLASSES,
                        help="skip agents whose per-agent rules deny this class (rules read from --config)")
    parser.add_argument("--config", default=None, help="config.yaml holding the roster rules (default .harness/config.yaml)")
    parser.add_argument("--fix-round", type=int, default=None, help="fix round 1-5; adds fixModel (sonnet rounds 1-3, opus 4-5)")
    return parser


def rules_by_agent(config: Path, profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Effective rules of every roster agent in `config` (a missing file: none)."""
    import roster  # noqa: PLC0415 - only the rules path needs the roster reader
    found: dict[str, dict[str, Any]] = {}
    for entry in roster.read_roster(config) if config.exists() else []:
        profile: dict[str, Any] = profiles.get(entry.get("profile") or entry["name"]) or {}
        found[entry["name"]] = roster.entry_rules(entry, profile)[0]
    return found


def main() -> int:
    args = build_parser().parse_args()
    profiles: dict[str, dict[str, Any]] = load_profiles(Path(args.profile_dir) if args.profile_dir else None)
    if args.agent not in profiles:
        print(f"delegate error: unknown agent '{args.agent}'", file=sys.stderr)
        return 1
    try:
        rules: dict[str, dict[str, Any]] = rules_by_agent(Path(args.config or state_io.CONFIG_REL), profiles)
        result: dict[str, Any] = delegate(
            profiles[args.agent], args.seat, args.complexity, args.budget, args.lead_provider, profiles,
            args.effort, args.task_class, rules,
        )
        if args.fix_round is not None:
            result["fixModel"] = fix_round_model(args.fix_round)
    except DelegationError as error:
        print(f"delegate error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
