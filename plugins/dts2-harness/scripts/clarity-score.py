#!/usr/bin/env python3
"""Score requirement clarity from per-component ratings. The weakest component bounds the score."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Final

GREENFIELD_WEIGHTS: Final[dict[str, float]] = {"goal": 0.40, "constraints": 0.30, "success": 0.30}
BROWNFIELD_WEIGHTS: Final[dict[str, float]] = {
    "goal": 0.35, "constraints": 0.25, "success": 0.25, "context": 0.15,
}
ROUND_DIGITS: Final[int] = 6


def weights_for(mode: str) -> dict[str, float]:
    return BROWNFIELD_WEIGHTS if mode == "brownfield" else GREENFIELD_WEIGHTS


def component_score(component: dict[str, Any], weights: dict[str, float]) -> float:
    total: float = sum(float(component.get(dim, 0)) * w for dim, w in weights.items())
    return round(total, ROUND_DIGITS)


def weakest_dimension(component: dict[str, Any], weights: dict[str, float]) -> str:
    return min(weights, key=lambda dim: float(component.get(dim, 0)))


def score_ratings(ratings: dict[str, Any]) -> dict[str, Any]:
    weights: dict[str, float] = weights_for(str(ratings.get("mode", "greenfield")))
    components: list[dict[str, Any]] = ratings.get("components", [])
    if not components:
        return {"clarity": 0, "weakest": {"component": "", "dimension": ""}, "perComponent": {}}
    scores: dict[str, float] = {str(c["name"]): component_score(c, weights) for c in components}
    weakest: dict[str, Any] = min(components, key=lambda c: scores[str(c["name"])])
    return {
        "clarity": math.floor(scores[str(weakest["name"])]),
        "weakest": {"component": str(weakest["name"]), "dimension": weakest_dimension(weakest, weights)},
        "perComponent": {name: math.floor(s) for name, s in scores.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ratings")
    args = parser.parse_args()
    ratings: dict[str, Any] = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
    print(json.dumps(score_ratings(ratings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
