#!/usr/bin/env python3
"""Map detected repo facts to a ranked, deterministic list of candidate skill slugs."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Final

GENERAL: Final[tuple[str, ...]] = ("grill-me", "research")
# (fact, value the fact must have, slugs it adds). Order is the ranking order.
CATALOG: Final[tuple[tuple[str, bool, tuple[str, ...]], ...]] = (
    ("is_brownfield", True, ("improve-codebase-architecture",)),
    ("is_large", True, ("improve-codebase-architecture",)),
    ("has_pr", True, ("pr", "resolving-merge-conflicts")),
    ("has_tests", False, ("test-driven-development",)),
    ("has_tests", True, ("diagnosing-bugs",)),
    ("has_ci", True, ("diagnosing-bugs",)),
    ("has_frontend", True, ("impeccable", "frontend-design")),
    ("has_marketing", True, ("page-cro", "copywriting", "seo-audit")),
    ("has_agent_docs", True, ("writing-for-agents",)),
)
QUESTION_SKILL: Final[str] = "ask-matt"


def matches(facts: dict[str, Any], key: str, wanted: bool) -> bool:
    """A fact matches only when it is present and equal to the wanted boolean (absent never matches)."""
    return key in facts and bool(facts[key]) is wanted


def suggest(facts: dict[str, Any]) -> list[str]:
    ranked: list[str] = list(GENERAL)
    for key, wanted, slugs in CATALOG:
        if matches(facts, key, wanted):
            ranked.extend(slugs)
    ranked.append(QUESTION_SKILL)
    return list(dict.fromkeys(ranked))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", default="{}", help="JSON object of detected repo facts")
    args = parser.parse_args()
    try:
        facts: Any = json.loads(args.facts)
    except json.JSONDecodeError as error:
        print(f"skill-suggest error: --facts is not JSON ({error})", file=sys.stderr)
        return 1
    if not isinstance(facts, dict):
        print("skill-suggest error: --facts must be a JSON object", file=sys.stderr)
        return 1
    print(json.dumps(suggest(facts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
