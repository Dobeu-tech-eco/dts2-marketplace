"""The loop's instructions must retain its frozen comparison and approval boundaries."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LoopSkillTests(unittest.TestCase):
    def test_research_contract(self) -> None:
        text = (ROOT / "skills/loop/SKILL.md").read_text(encoding="utf-8")
        for contract in (
            "name: loop", "one role-instruction file", "past-month receipts",
            "token_cap", "wall_clock_seconds", "strictly improves",
            "ties", "non-finite", "missing usage", "baseline fails",
            "append-only", "started", "invalid", "recovery", "dt:ship",
            "merge_policy", "subscription", "never self-approves",
            "https://github.com/karpathy/autoresearch", "5 minutes", "val_bpb",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)

    def test_example_is_inert_complete_definition(self) -> None:
        example = json.loads((ROOT / "templates/loop-experiment.example.json").read_text(encoding="utf-8"))
        self.assertTrue(example["template_only"])
        self.assertEqual(example["editable_file"], "research/roles/example-reviewer.md")
        self.assertGreater(example["budget"]["token_cap"], 0)
        self.assertEqual(example["budget"]["wall_clock_seconds"], 300)
        self.assertEqual(example["metric"]["direction"], "maximize")
        self.assertEqual(example["metric"]["name"], "receipt_pass_rate")
        self.assertIn("sha256", example["batch"])
        self.assertIn("sha256", example["evaluator"])
        self.assertIn("auth_mode", example["model"])
        self.assertEqual(example["max_experiments"], 3)


if __name__ == "__main__":
    unittest.main()
