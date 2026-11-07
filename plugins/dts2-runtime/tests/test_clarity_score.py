from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from helpers import make_tmp_home, run_script


def score(mode: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    path: Path = make_tmp_home() / "ratings.json"
    path.write_text(json.dumps({"mode": mode, "components": components}))
    return run_script("clarity-score.py", str(path))


def comp(name: str, goal: int, constraints: int, success: int, context: int = 0) -> dict[str, Any]:
    return {"name": name, "goal": goal, "constraints": constraints, "success": success, "context": context}


class ClarityScoreTest(unittest.TestCase):
    def test_greenfield_weights(self) -> None:
        self.assertEqual(score("greenfield", [comp("a", 100, 50, 0)])["clarity"], 55)

    def test_weakest_component_bounds_score(self) -> None:
        result = score("greenfield", [comp("a", 100, 100, 100), comp("b", 40, 40, 40)])
        self.assertEqual(result["clarity"], 40)
        self.assertEqual(result["weakest"]["component"], "b")

    def test_weakest_dimension_named(self) -> None:
        result = score("greenfield", [comp("a", 90, 90, 10)])
        self.assertEqual(result["weakest"]["dimension"], "success")

    def test_brownfield_uses_context(self) -> None:
        self.assertEqual(score("brownfield", [comp("a", 100, 100, 100, 0)])["clarity"], 85)


if __name__ == "__main__":
    unittest.main()
