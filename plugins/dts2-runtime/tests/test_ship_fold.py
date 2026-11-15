"""ship_fold.py: the safe stray-PR fold planner. It must fail closed on any field it cannot confirm."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ship_fold.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ship_fold", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ship_fold"] = module
    spec.loader.exec_module(module)
    return module


ship_fold: Final[ModuleType] = load()

AUTHOR: Final[str] = "alice"
BASE: Final[str] = "dev"
SHIP_FILES: Final[list[str]] = ["a.py", "b.py", "c.py"]


def stray(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": 10, "author": AUTHOR, "base": BASE, "files": ["a.py"],
        "mergeable": True, "ci": "green", "draft": False, "cross_repo": False,
    }
    base.update(over)
    return base


def plan(strays: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return ship_fold.fold_plan(strays, AUTHOR, BASE, SHIP_FILES, **kw)


class FoldableTests(unittest.TestCase):
    def test_clean_stray_is_foldable(self) -> None:
        self.assertEqual(plan([stray()]), {"foldable": [10], "listed": []})

    def test_mergeable_string_enum(self) -> None:
        self.assertEqual(plan([stray(mergeable="MERGEABLE")])["foldable"], [10])
        for bad in ("CONFLICTING", "UNKNOWN", "false", ""):
            got = plan([stray(mergeable=bad)])
            self.assertEqual(got["foldable"], [], bad)
            self.assertEqual(got["listed"][0]["reason"], ship_fold.REASON_MERGEABLE, bad)

    def test_missing_or_empty_files_is_refused(self) -> None:
        for files in ([], None):
            got = plan([stray(files=files)])
            self.assertEqual(got["foldable"], [])
            self.assertEqual(got["listed"][0]["reason"], ship_fold.REASON_NO_FILES)

    def test_missing_files_key_is_refused(self) -> None:
        s = stray()
        del s["files"]
        self.assertEqual(plan([s])["listed"][0]["reason"], ship_fold.REASON_NO_FILES)

    def test_non_list_files_is_refused(self) -> None:
        self.assertEqual(plan([stray(files="a.py")])["listed"][0]["reason"], ship_fold.REASON_NO_FILES)

    def test_files_outside_ship_set(self) -> None:
        self.assertEqual(plan([stray(files=["z.py"])])["listed"][0]["reason"], ship_fold.REASON_FILES)

    def test_draft_and_fork_refused(self) -> None:
        self.assertEqual(plan([stray(draft=True)])["listed"][0]["reason"], ship_fold.REASON_DRAFT)
        self.assertEqual(plan([stray(cross_repo=True)])["listed"][0]["reason"], ship_fold.REASON_FORK)

    def test_missing_draft_fails_closed(self) -> None:
        s = stray()
        del s["draft"]
        self.assertEqual(plan([s])["listed"][0]["reason"], ship_fold.REASON_DRAFT)

    def test_missing_cross_repo_fails_closed(self) -> None:
        s = stray()
        del s["cross_repo"]
        self.assertEqual(plan([s])["listed"][0]["reason"], ship_fold.REASON_FORK)

    def test_unknown_draft_or_fork_value_fails_closed(self) -> None:
        self.assertEqual(plan([stray(draft="maybe")])["listed"][0]["reason"], ship_fold.REASON_DRAFT)
        self.assertEqual(plan([stray(draft=None)])["listed"][0]["reason"], ship_fold.REASON_DRAFT)
        self.assertEqual(plan([stray(cross_repo="maybe")])["listed"][0]["reason"], ship_fold.REASON_FORK)

    def test_author_base_ci(self) -> None:
        self.assertEqual(plan([stray(author="bob")])["listed"][0]["reason"], ship_fold.REASON_AUTHOR)
        self.assertEqual(plan([stray(base="main")])["listed"][0]["reason"], ship_fold.REASON_BASE)
        self.assertEqual(plan([stray(ci="pending")])["listed"][0]["reason"], "CI is pending")

    def test_priority_order(self) -> None:
        # a stray that fails author, draft and mergeable reports the earliest: author.
        s = stray(author="bob", draft=True, mergeable="CONFLICTING")
        self.assertEqual(plan([s])["listed"][0]["reason"], ship_fold.REASON_AUTHOR)

    def test_self_exclusion(self) -> None:
        got = plan([stray(number=7)], exclude=7)
        self.assertEqual(got["foldable"], [])
        self.assertEqual(got["listed"][0]["reason"], ship_fold.REASON_SELF)

    def test_duplicate_numbers_refused(self) -> None:
        got = plan([stray(number=5, files=["a.py"]), stray(number=5, files=["b.py"])])
        self.assertEqual(got["foldable"], [])
        self.assertEqual([r["reason"] for r in got["listed"]], [ship_fold.REASON_DUPLICATE, ship_fold.REASON_DUPLICATE])

    def test_results_sorted_by_number(self) -> None:
        got = plan([stray(number=30), stray(number=10, author="bob"), stray(number=20)])
        self.assertEqual(got["foldable"], [20, 30])
        self.assertEqual(got["listed"], [{"number": 10, "reason": ship_fold.REASON_AUTHOR}])


class ParseTests(unittest.TestCase):
    def test_as_int_rejects_bool_and_float_and_words(self) -> None:
        for bad in (True, 3.9, "x", None):
            with self.assertRaises(ship_fold.StrayError):
                ship_fold.as_int(bad)
        self.assertEqual(ship_fold.as_int("12"), 12)

    def test_from_dict_requires_core_keys(self) -> None:
        with self.assertRaises(KeyError):
            ship_fold.Stray.from_dict({"author": AUTHOR, "base": BASE})


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str, text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False, input=text,
        )

    def test_plan_through_files(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="dts2-fold-"))
        (tmp / "strays.json").write_text(json.dumps([stray(), stray(number=11, author="bob")]), encoding="utf-8")
        (tmp / "files.txt").write_text("a.py\nb.py\n", encoding="utf-8")
        result = self.run_cli(
            "plan", "--input", str(tmp / "strays.json"), "--author", AUTHOR, "--base", BASE,
            "--files-file", str(tmp / "files.txt"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["foldable"], [10])

    def test_non_list_input_exits_two(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="dts2-fold-"))
        (tmp / "strays.json").write_text("{}", encoding="utf-8")
        (tmp / "files.txt").write_text("a.py\n", encoding="utf-8")
        result = self.run_cli(
            "plan", "--input", str(tmp / "strays.json"), "--author", AUTHOR, "--base", BASE,
            "--files-file", str(tmp / "files.txt"),
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_files_file_exits_two(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="dts2-fold-"))
        (tmp / "strays.json").write_text("[]", encoding="utf-8")
        result = self.run_cli(
            "plan", "--input", str(tmp / "strays.json"), "--author", AUTHOR, "--base", BASE,
            "--files-file", str(tmp / "nope.txt"),
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
