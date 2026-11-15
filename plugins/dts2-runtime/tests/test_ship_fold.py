"""scripts/ship_fold.py: the fold reasons and their order, the plan ordering, Stray.from_dict and the CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import ship_fold  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ship_fold.py"
AUTHOR: Final[str] = "alice"
BASE: Final[str] = "dev"
SHIP_FILES: Final[tuple[str, ...]] = ("a.py", "b.py", "c.py")


def stray(number: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": number, "author": AUTHOR, "base": BASE,
        "files": ["a.py"], "mergeable": True, "ci": "green",
    }
    return {**base, **overrides}


def reason_for(raw: dict[str, Any]) -> str | None:
    return ship_fold.fold_reason(ship_fold.Stray.from_dict(raw), AUTHOR, BASE, frozenset(SHIP_FILES))


def run_cli(strays: list[dict[str, Any]], files: list[str]) -> subprocess.CompletedProcess[str]:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-ship-fold-"))
    (folder / "strays.json").write_text(json.dumps(strays), encoding="utf-8")
    (folder / "files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "plan", "--input", str(folder / "strays.json"),
         "--author", AUTHOR, "--base", BASE, "--files-file", str(folder / "files.txt")],
        capture_output=True, text=True, check=False,
    )


class FoldReasonTests(unittest.TestCase):
    def test_a_matching_stray_is_foldable(self) -> None:
        self.assertIsNone(reason_for(stray(1, files=["a.py", "b.py"])))

    def test_different_author(self) -> None:
        self.assertEqual(reason_for(stray(1, author="bob")), "opened by a different author")

    def test_different_base(self) -> None:
        self.assertEqual(reason_for(stray(1, base="main")), "targets a different base")

    def test_not_mergeable(self) -> None:
        self.assertEqual(reason_for(stray(1, mergeable=False)), "not mergeable")

    def test_ci_not_green_names_the_state(self) -> None:
        for state in ("red", "pending", "unknown"):
            self.assertEqual(reason_for(stray(1, ci=state)), f"CI is {state}")

    def test_files_outside_the_ship_branch(self) -> None:
        self.assertEqual(reason_for(stray(1, files=["a.py", "z.py"])), "changes files outside this PR")

    def test_priority_order_reports_the_earlier_failure(self) -> None:
        self.assertEqual(reason_for(stray(1, author="bob", base="main", mergeable=False, ci="red", files=["z.py"])),
                         "opened by a different author")
        self.assertEqual(reason_for(stray(1, base="main", mergeable=False, ci="red", files=["z.py"])),
                         "targets a different base")
        self.assertEqual(reason_for(stray(1, mergeable=False, ci="red", files=["z.py"])), "not mergeable")
        self.assertEqual(reason_for(stray(1, ci="red", files=["z.py"])), "CI is red")


class StrayTests(unittest.TestCase):
    def test_from_dict_defaults_missing_files_and_ci(self) -> None:
        raw: dict[str, Any] = {"number": "7", "author": AUTHOR, "base": BASE, "mergeable": 1}
        parsed: ship_fold.Stray = ship_fold.Stray.from_dict(raw)
        self.assertEqual(parsed, ship_fold.Stray(7, AUTHOR, BASE, (), True, "unknown"))

    def test_an_empty_stray_with_no_files_is_a_subset(self) -> None:
        self.assertEqual(reason_for({"number": 1, "author": AUTHOR, "base": BASE, "mergeable": True, "ci": "green"}), None)

    def test_foldable_ci_is_green_only(self) -> None:
        self.assertEqual(ship_fold.FOLDABLE_CI, frozenset({"green"}))


class PlanTests(unittest.TestCase):
    def test_lists_are_sorted_ascending_by_number(self) -> None:
        strays: list[dict[str, Any]] = [
            stray(9), stray(3, ci="red"), stray(5), stray(2, base="main"), stray(1),
        ]
        plan: dict[str, Any] = ship_fold.fold_plan(strays, AUTHOR, BASE, list(SHIP_FILES))
        self.assertEqual(plan["foldable"], [1, 5, 9])
        self.assertEqual(plan["listed"], [
            {"number": 2, "reason": "targets a different base"},
            {"number": 3, "reason": "CI is red"},
        ])

    def test_empty_input_gives_empty_plan(self) -> None:
        self.assertEqual(ship_fold.fold_plan([], AUTHOR, BASE, []), {"foldable": [], "listed": []})


class CliTests(unittest.TestCase):
    def test_plan_reads_input_and_files_file(self) -> None:
        strays: list[dict[str, Any]] = [stray(4, files=["a.py", "q.py"]), stray(2), stray(3, mergeable=False)]
        result: subprocess.CompletedProcess[str] = run_cli(strays, ["a.py", "", "b.py", ""])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "foldable": [2],
            "listed": [
                {"number": 3, "reason": "not mergeable"},
                {"number": 4, "reason": "changes files outside this PR"},
            ],
        })


if __name__ == "__main__":
    unittest.main()
