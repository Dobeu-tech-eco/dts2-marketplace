"""AA-5: plan-gate.py PASS/FAIL on ownership, model+effort and token estimate."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "plan-gate.py"

GOOD: Final[str] = """## Plan: demo
Tier: M   Team: 2 builders on separate file sets

## Foundation
wave: 0
- T0 shared types | owns: src/types.ts | done when: compiles

### Builder 1 (claude) — skills: none
complexity: normal
- T1 api | owns: src/api/ | depends: T0 | done when: tests pass
### Builder 2 (claude) — skills: none
complexity: mechanical
- T2 docs | owns: docs/a.md, docs/b.md | depends: none | done when: source
### Integration (Builder 1, after T1 and T2)
- T3 wire | owns: src/index.ts | depends: T1, T2 | done when: tests
## Done
- works — check: tests `make test`
Axes: correctness, style, completeness; reviewer skills: none
"""


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plan_gate_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gate(plan: str, *args: str) -> subprocess.CompletedProcess[str]:
    folder = Path(tempfile.mkdtemp(prefix="b14a-gate-"))
    path = folder / "plan.md"
    path.write_text(plan, encoding="utf-8")
    return subprocess.run(["python3", "-I", str(SCRIPT), str(path), *args], capture_output=True, text=True)


class PlanGateTests(unittest.TestCase):
    def test_good_plan_passes(self) -> None:
        proc = run_gate(GOOD)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("PLAN GATE: PASS", proc.stdout)

    def test_prints_model_and_effort_per_dispatch(self) -> None:
        out = run_gate(GOOD).stdout
        self.assertIn("Builder 1: normal -> sonnet, effort medium", out)
        self.assertIn("Builder 2: mechanical -> haiku, effort low", out)

    def test_estimated_tokens_reported(self) -> None:
        report = json.loads(run_gate(GOOD, "--json").stdout)
        self.assertGreater(report["estimated_tokens"], 0)
        self.assertEqual(report["verdict"], "PASS")

    def test_shared_file_fails_exclusive_ownership(self) -> None:
        plan = GOOD.replace("docs/a.md, docs/b.md", "src/api/routes.ts")
        proc = run_gate(plan)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PLAN GATE: FAIL", proc.stdout)
        self.assertIn("src/api/routes.ts", proc.stdout)

    def test_same_file_in_two_builders_fails(self) -> None:
        proc = run_gate(GOOD.replace("docs/a.md, docs/b.md", "src/types.ts"))
        self.assertEqual(proc.returncode, 1)

    def test_missing_complexity_fails(self) -> None:
        proc = run_gate(GOOD.replace("complexity: mechanical\n", ""))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Builder 2", proc.stdout)

    def test_frontier_builder_fails(self) -> None:
        proc = run_gate(GOOD.replace("### Builder 1 (claude)", "### Builder 1 (claude, model: opus)"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("frontier", proc.stdout)

    def test_missing_foundation_fails(self) -> None:
        start = GOOD.index("## Foundation")
        end = GOOD.index("### Builder 1")
        proc = run_gate(GOOD[:start] + GOOD[end:])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Foundation", proc.stdout)

    def test_foundation_none_needed_passes(self) -> None:
        start = GOOD.index("## Foundation")
        end = GOOD.index("### Builder 1")
        plan = GOOD[:start] + "## Foundation\nwave: 0\nFoundation: none needed — single module\n\n" + GOOD[end:]
        self.assertEqual(run_gate(plan).returncode, 0)

    def test_effort_table_matches_delegate(self) -> None:
        gate = load()
        spec = importlib.util.spec_from_file_location("delegate_ref", PLUGIN_ROOT / "scripts" / "delegate.py")
        assert spec is not None and spec.loader is not None
        delegate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(delegate)
        self.assertEqual(gate.EFFORT, delegate.EXECUTION_EFFORT)

    def test_overlap_helper_handles_prefix_and_glob(self) -> None:
        gate = load()
        self.assertTrue(gate.overlaps("src/", "src/a.py"))
        self.assertTrue(gate.overlaps("src/*.py", "src/a.py"))
        self.assertFalse(gate.overlaps("src/", "srcx/a.py"))
        self.assertFalse(gate.overlaps("a.py", "b.py"))


class CheckpointWiringTests(unittest.TestCase):
    def test_plan_checkpoint_prints_the_gate(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-1-plan.md").read_text(encoding="utf-8")
        self.assertIn("plan-gate.py", text)
        self.assertIn("PLAN GATE", text)


if __name__ == "__main__":
    unittest.main()
