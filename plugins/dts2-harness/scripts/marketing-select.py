#!/usr/bin/env python3
"""Pick the ordered subset of marketing-skills a repo needs for the GTM pass."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Final

# Canonical pipeline order; mirrors the pinned order in skills/gtm/SKILL.md.
MARKETING_ORDER: Final[tuple[str, ...]] = (
    "product-marketing-context", "competitor-profiling", "seo-audit", "page-cro",
    "copywriting", "copy-editing", "launch-strategy", "analytics-tracking",
)
ALWAYS_ON: Final[frozenset[str]] = frozenset(
    {"product-marketing-context", "competitor-profiling", "launch-strategy"})
WEB_FACTS: Final[tuple[str, ...]] = ("has_web", "has_landing")
WEB_SKILLS: Final[frozenset[str]] = frozenset({"seo-audit", "page-cro"})
COPY_FACTS: Final[tuple[str, ...]] = ("has_marketing_surface", "has_web")
COPY_SKILLS: Final[frozenset[str]] = frozenset({"copywriting", "copy-editing"})
ANALYTICS_FACT: Final[str] = "analytics"
ANALYTICS_SKILL: Final[str] = "analytics-tracking"


def any_fact(facts: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(bool(facts.get(key)) for key in keys)


def wanted_skills(facts: dict[str, Any]) -> set[str]:
    wanted: set[str] = set(ALWAYS_ON)
    if any_fact(facts, WEB_FACTS):
        wanted |= WEB_SKILLS
    if any_fact(facts, COPY_FACTS):
        wanted |= COPY_SKILLS
    if facts.get(ANALYTICS_FACT):
        wanted.add(ANALYTICS_SKILL)
    return wanted


def select_marketing(facts: dict[str, Any]) -> list[str]:
    """Ordered subset of MARKETING_ORDER, no duplicates."""
    wanted: set[str] = wanted_skills(facts)
    return [name for name in MARKETING_ORDER if name in wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", default="{}", help="JSON object of GTM facts")
    args = parser.parse_args()
    try:
        facts: Any = json.loads(args.facts)
    except json.JSONDecodeError as error:
        print(f"marketing-select error: --facts is not JSON ({error})", file=sys.stderr)
        return 1
    if not isinstance(facts, dict):
        print("marketing-select error: --facts must be a JSON object", file=sys.stderr)
        return 1
    print(json.dumps(select_marketing(facts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
