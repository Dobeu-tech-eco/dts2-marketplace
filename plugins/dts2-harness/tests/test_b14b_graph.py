"""G-26, G-27, G-28, Q-22: provides/consumes, prefix and glob owners, package-root areas, cycle check, critical path."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_graph  # noqa: E402
from lanes.common import LaneError  # noqa: E402

LANES_CLI: Final[Path] = SCRIPTS / "lanes.py"
GRAPH_CLI: Final[Path] = SCRIPTS / "plan_graph.py"
STAMP: Final[str] = "20261105-1"


def lane(lane_id: str, files: list[str], **extra: Any) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {}, "depends_on": [], "tier": "standard", **extra}


def manifest(*lanes: dict[str, Any]) -> dict[str, Any]:
    return {"stamp": STAMP, "base": "abc", "scope": "single", "lanes": list(lanes)}


def kinds(report: dict[str, Any], key: str = "errors") -> list[str]:
    return [e["kind"] for e in report[key]]


class ContractTests(unittest.TestCase):
    def analyse(self, *lanes: dict[str, Any]) -> dict[str, Any]:
        return plan_graph.analyse(manifest(*lanes), Path(tempfile.mkdtemp()))

    def test_plain_consumer_waits_for_its_provider(self) -> None:
        report = self.analyse(lane("a", ["src/a/x.py"], provides=["Api"]), lane("b", ["src/b/y.py"], consumes=["Api"]))
        self.assertEqual(report["start_after"], {"b": ["a"]})
        self.assertEqual(kinds(report), ["depends_on"])
        self.assertEqual(report["errors"][0]["lanes"], ["b"])
        self.assertEqual(report["order"], ["a", "b"])

    def test_stubbed_consumer_starts_at_once_and_merges_after(self) -> None:
        report = self.analyse(lane("b", ["src/b/y.py"], consumes=["Api"], stubbed_on=["Api"]), lane("a", ["src/a/x.py"], provides=["Api"]))
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["start_after"], {})
        self.assertEqual(report["merge_after"], {"b": ["a"]})
        self.assertEqual(report["order"], ["a", "b"])

    def test_unresolved_duplicate_and_stray_stub(self) -> None:
        report = self.analyse(lane("a", ["src/a/x.py"], provides=["Api"], consumes=["Ghost"]),
                              lane("b", ["src/b/y.py"], provides=["Api"], stubbed_on=["Other"]))
        details = " | ".join(e["detail"] for e in report["errors"])
        self.assertIn("no lane provides it", details)
        self.assertIn("both provide 'Api'", details)
        self.assertIn("does not consume it", details)

    def test_cycle_is_an_error_without_a_critical_path(self) -> None:
        report = self.analyse(lane("a", ["src/a/x.py"], depends_on=["b"]), lane("b", ["src/b/y.py"], depends_on=["a"]))
        self.assertEqual(kinds(report), ["cycle"])
        self.assertEqual(sorted(report["errors"][0]["lanes"]), ["a", "b"])
        self.assertEqual(report["order"], [])
        self.assertIn("cycle", report["critical_path_line"])

    def test_cycle_through_a_contract(self) -> None:
        report = self.analyse(lane("a", ["src/a/x.py"], provides=["A"], consumes=["B"], stubbed_on=["B"]),
                              lane("b", ["src/b/y.py"], provides=["B"], consumes=["A"], stubbed_on=["A"]))
        self.assertIn("cycle", kinds(report))

    def test_critical_path_is_the_heaviest_chain(self) -> None:
        report = self.analyse(
            lane("a", ["src/a/x.py"], tasks=["1", "2"]), lane("b", ["src/b/y.py"], tasks=["1", "2", "3"], depends_on=["a"]),
            lane("c", ["src/c/z.py"], tasks=["1"]))
        self.assertEqual(report["critical_path"], ["a", "b"])
        self.assertEqual(report["critical_path_weight"], 5)
        self.assertEqual(report["critical_path_line"], "Critical path: a (2) -> b (3) = 5")

    def test_spend_total_weighs_a_lane(self) -> None:
        heavy = lane("a", ["src/a/x.py"], estimated_spend={"total": 40})
        self.assertEqual(plan_graph.lane_weight(heavy), 40)
        self.assertEqual(plan_graph.lane_weight(lane("b", ["x"])), 1)

    def test_provider_first_order_beats_manifest_order(self) -> None:
        m = manifest(lane("b", ["src/b/y.py"], consumes=["Api"], stubbed_on=["Api"]), lane("a", ["src/a/x.py"], provides=["Api"]))
        start, merge, _ = plan_graph.contract_edges(m)
        self.assertEqual(plan_graph.merge_sequence(m, plan_graph.needs_of(m, start, merge)), ["a", "b"])

    def test_merge_sequence_refuses_a_cycle(self) -> None:
        m = manifest(lane("a", ["a"], depends_on=["b"]), lane("b", ["b"], depends_on=["a"]))
        start, merge, _ = plan_graph.contract_edges(m)
        with self.assertRaises(LaneError):
            plan_graph.merge_sequence(m, plan_graph.needs_of(m, start, merge))


class OwnerTests(unittest.TestCase):
    def test_empty_files_are_rejected(self) -> None:
        errors = plan_graph.owner_errors(lane("a", []))
        self.assertEqual([e["kind"] for e in errors], ["owners"])
        self.assertIn("owns no files", errors[0]["detail"])

    def test_repo_wide_owner_is_rejected(self) -> None:
        for entry in ("*", "**", "./*", "**/*"):
            self.assertTrue(plan_graph.owner_errors(lane("a", [entry])), entry)
        self.assertFalse(plan_graph.owner_errors(lane("a", ["src/**/*.py"])))

    def test_entry_overlaps(self) -> None:
        cases = [("src/a/", "src/a/x.py", True), ("src/a/", "src/ab.py", False), ("src/a/", "src/a/b/", True),
                 ("src/*.py", "src/x.py", True), ("src/*.py", "docs/x.py", False), ("src/*.py", "src/*.ts", False),
                 ("src/**/*.py", "src/a/*.py", True), ("src/a/", "src/*.py", True), ("docs/", "src/*.py", False),
                 ("src/a.py", "src/a.py", True)]
        for a, b, expected in cases:
            self.assertEqual(plan_graph.entries_overlap(a, b), expected, (a, b))
            self.assertEqual(plan_graph.entries_overlap(b, a), expected, (b, a))

    def test_prefix_and_glob_owners_overlap_a_file(self) -> None:
        found = plan_graph.owner_overlaps(lane("a", ["src/auth/"]), lane("b", ["src/auth/login.py"]))
        self.assertEqual([f["kind"] for f in found], ["owners"])
        self.assertIn("src/auth/ overlaps src/auth/login.py", found[0]["detail"])
        self.assertEqual(plan_graph.owner_overlaps(lane("a", ["src/auth/"]), lane("b", ["src/authz/x.py"])), [])

    def test_equal_exact_files_stay_with_the_file_check(self) -> None:
        self.assertEqual(plan_graph.owner_overlaps(lane("a", ["src/x.py"]), lane("b", ["src/x.py"])), [])

    def test_manifest_owns_its_lockfile(self) -> None:
        a = lane("a", ["web/package.json"])
        self.assertEqual(plan_graph.implied_lockfiles(a), {"web/package-lock.json", "web/npm-shrinkwrap.json", "web/pnpm-lock.yaml",
                                                           "web/yarn.lock", "web/bun.lockb"})
        self.assertIn("Cargo.lock", plan_graph.owned_entries(lane("c", ["Cargo.toml"])))
        self.assertNotIn("web/package-lock.json", plan_graph.implied_lockfiles(lane("a", ["web/package.json", "web/package-lock.json"])))

    def test_a_lane_that_lists_another_lanes_lockfile_conflicts(self) -> None:
        found = plan_graph.owner_overlaps(lane("a", ["web/package.json"]), lane("b", ["web/yarn.lock"]))
        self.assertEqual(len(found), 1)
        self.assertIn("web/yarn.lock", found[0]["detail"])

    def test_different_folders_have_different_lockfiles(self) -> None:
        self.assertEqual(plan_graph.owner_overlaps(lane("a", ["web/package.json"]), lane("b", ["admin/package.json"])), [])


class PackageRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = Path(tempfile.mkdtemp(prefix="dts2-pkg-"))
        for pkg in ("packages/web", "packages/api"):
            (self.cwd / pkg).mkdir(parents=True)
            (self.cwd / pkg / "package.json").write_text("{}", encoding="utf-8")

    def test_root_is_the_nearest_manifest_folder(self) -> None:
        self.assertEqual(plan_graph.package_root("packages/web/src/ui/a.tsx", self.cwd), "packages/web")
        self.assertEqual(plan_graph.package_root("packages/web/src/", self.cwd), "packages/web")
        self.assertEqual(plan_graph.package_root("packages/web/src/**/*.ts", self.cwd), "packages/web")
        self.assertIsNone(plan_graph.package_root("scripts/x.py", self.cwd))
        self.assertIsNone(plan_graph.package_root("../x/package.json", self.cwd))

    def test_vertical_slices_in_one_package_are_not_an_area_conflict(self) -> None:
        a = lane("a", ["packages/web/src/api/users.ts", "packages/web/src/ui/users.tsx"])
        b = lane("b", ["packages/web/src/api/orders.ts", "packages/web/src/ui/orders.tsx"])
        found = {"lane": "a", "with": "b", "kind": "area", "detail": "both work under packages/web/src/"}
        by_id = {"a": a, "b": b}
        self.assertTrue(plan_graph.cleared_area(found, by_id, self.cwd, ()))

    def test_unrooted_lane_keeps_its_area_conflict(self) -> None:
        a = lane("a", ["packages/web/src/api/users.ts"])
        b = lane("b", ["tools/x/y.py"])
        found = {"lane": "a", "with": "b", "kind": "area", "detail": "d"}
        self.assertFalse(plan_graph.cleared_area(found, {"a": a, "b": b}, self.cwd, ()))
        self.assertFalse(plan_graph.cleared_area({**found, "kind": "files"}, {"a": a, "b": a}, self.cwd, ()))

    def test_layer_cake_warns(self) -> None:
        m = manifest(lane("a", ["src/models/user.py"]), lane("b", ["src/api/user.py"]), lane("c", ["src/components/user.tsx"]))
        self.assertEqual([w["kind"] for w in plan_graph.layer_warnings(m)], ["layers"])
        slices = manifest(lane("a", ["src/models/a.py", "src/api/a.py"]), lane("b", ["src/models/b.py", "src/api/b.py"]),
                          lane("c", ["src/ui/c.tsx", "src/api/c.py"]))
        self.assertEqual(plan_graph.layer_warnings(slices), [])


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-b14b-"))
        self.repo = self.root / "repo"
        for pkg in ("packages/web",):
            (self.repo / pkg).mkdir(parents=True)
            (self.repo / pkg / "package.json").write_text("{}", encoding="utf-8")

    def run_cli(self, script: Path, *args: str) -> tuple[int, dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", str(script), "--cwd", str(self.repo), *args], capture_output=True, text=True, check=False)
        return done.returncode, json.loads(done.stdout)

    def write(self, name: str, data: Any) -> str:
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def plan(self, lanes: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        draft = self.write("draft.json", manifest(*lanes))
        checkin = self.write("checkin.json", {"outstanding_items": [f"S{x['id']}" for x in lanes]})
        return self.run_cli(LANES_CLI, "--no-prs", "plan", "--from-checkin", checkin, "--draft", draft)

    def test_plan_prints_the_critical_path_and_clears_package_slices(self) -> None:
        a = lane("a", ["packages/web/src/api/u.ts", "packages/web/src/ui/u.tsx"], tasks=["x", "y"])
        b = lane("b", ["packages/web/src/api/o.ts", "packages/web/src/ui/o.tsx"], tasks=["z"])
        code, out = self.plan([a, b])
        self.assertEqual(code, 0, out)
        total = out["manifest"]["lanes"][0]["estimated_spend"]["total"]
        self.assertEqual(out["graph"]["critical_path_line"], f"Critical path: a ({total}) = {total}")
        self.assertEqual([c["kind"] for c in out["feasibility"]["cleared"]], ["area"])
        self.assertEqual(out["feasibility"]["conflicts"], [])

    def test_plan_without_package_roots_keeps_the_area_conflict(self) -> None:
        a = lane("a", ["src/api/u.py", "src/ui/u.py"])
        b = lane("b", ["src/api/o.py", "src/ui/o.py"])
        code, out = self.plan([a, b])
        self.assertEqual(code, 2)
        self.assertIn("area", [c["kind"] for c in out["feasibility"]["conflicts"]])

    def test_plan_fails_on_a_cycle_and_check_agrees(self) -> None:
        lanes = [lane("a", ["src/a/x.py"], depends_on=["b"]), lane("b", ["src/b/y.py"], depends_on=["a"])]
        code, out = self.plan(lanes)
        self.assertEqual(code, 2)
        self.assertEqual(kinds(out["graph"]), ["cycle"])
        code, checked = self.run_cli(LANES_CLI, "--no-prs", "check", self.write("m.json", manifest(*lanes)))
        self.assertEqual(code, 2)
        self.assertIn("cycle", kinds(checked["graph"]))

    def test_lease_refuses_an_empty_owner_set_and_a_plain_consumer(self) -> None:
        path = self.write("m.json", manifest(lane("a", []), lane("b", ["src/b/y.py"], consumes=["Api"]), lane("c", ["src/c/z.py"], provides=["Api"])))
        code, out = self.run_cli(LANES_CLI, "--no-prs", "lease", path, "--lane", "a")
        self.assertEqual((code, out["ok"]), (2, False))
        code, out = self.run_cli(LANES_CLI, "--no-prs", "lease", path, "--lane", "b")
        self.assertFalse(out["ok"])
        code, out = self.run_cli(LANES_CLI, "--no-prs", "lease", path, "--lane", "c")
        self.assertTrue(out["ok"], out)

    def test_stubbed_consumer_leases_and_merge_order_is_provider_first(self) -> None:
        m = manifest(lane("b", ["src/b/y.py"], consumes=["Api"], stubbed_on=["Api"]), lane("a", ["src/a/x.py"], provides=["Api"]))
        path = self.write("m.json", m)
        for lane_id in ("a", "b"):
            code, out = self.run_cli(LANES_CLI, "--no-prs", "lease", path, "--lane", lane_id)
            self.assertTrue(out["ok"], out)
        runs = self.repo / "runs"
        code, out = self.run_cli(GRAPH_CLI, "merge-order", path, "--runs-dir", str(runs))
        self.assertEqual((code, out["order"]), (0, ["a", "b"]))
        saved = json.loads((runs / STAMP / "merge-order.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["order"], ["a", "b"])

    def test_brief_has_the_six_sections(self) -> None:
        path = self.write("m.json", manifest(lane("a", ["packages/web/package.json"], provides=["Api"], tasks=["build it"])))
        done = subprocess.run([sys.executable, "-I", str(GRAPH_CLI), "brief", path, "--lane", "a"], capture_output=True, text=True, check=False)
        headings = [line[3:] for line in done.stdout.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, list(plan_graph.BRIEF_SECTIONS))
        self.assertIn("provides `Api`", done.stdout)
        self.assertIn("packages/web/package-lock.json", done.stdout)


if __name__ == "__main__":
    unittest.main()
