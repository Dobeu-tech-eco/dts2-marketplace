#!/usr/bin/env python3
"""Plan graph checks for a lane manifest: what each lane provides and consumes (G-26), prefix and glob owners (G-27),
vertical slices and package-root areas (G-28), and the cycle check plus critical path (Q-22). Read-only.

  analyse   <manifest>                    the graph report as JSON (errors, warnings, edges, critical path, merge order)
  merge-order <manifest> --runs-dir D   record the provider-first merge order (the lanes merge-order record)
  brief     <manifest> --lane L           the six-section lane brief skeleton for the lead

Lane fields it reads, all optional: `provides` (names), `consumes` (names), `stubbed_on` (consumed names the lane builds
against a stub, so it may start before the provider merges), `depends_on` (lanes that must merge first), `merge_after`.
A consumed name with no stub makes the consumer wait for its provider, like `depends_on`. A stubbed consumer starts
at once but merges after its provider (provider first). Owners are exact files, `dir/` prefixes or globs.

`lanes.py` calls `annotate_plan`, `graph_check` and `graph_lease`, so the plan, check and lease gates agree."""
from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lanes.common import KIND_AREA, KIND_DEPENDS, LEASE_NAME, LaneError, find_lane, lane_files, load_manifest  # noqa: E402
from lanes.conflicts import check, conflict  # noqa: E402
from lanes.integration import is_integration_file, route, shared_patterns  # noqa: E402
from lanes.gitrefs import gh_down  # noqa: E402
from lanes.leases import admission_lock, admission_refusal, busy, lane_lock, lease_ttl_s, refused, write_lease  # noqa: E402

PROVIDES: Final[str] = "provides"
CONSUMES: Final[str] = "consumes"
STUBBED_ON: Final[str] = "stubbed_on"
MERGE_AFTER: Final[str] = "merge_after"
DEPENDS_ON: Final[str] = "depends_on"
KIND_OWNERS: Final[str] = "owners"
KIND_PROVIDES: Final[str] = "provides"
KIND_CYCLE: Final[str] = "cycle"
KIND_LAYERS: Final[str] = "layers"
GLOB_CHARS: Final[tuple[str, ...]] = ("*", "?", "[")
EXACT: Final[str] = "exact"
PREFIX: Final[str] = "prefix"
GLOB: Final[str] = "glob"
SHOWN_OVERLAPS: Final[int] = 3
MIN_LAYER_LANES: Final[int] = 3
DEFAULT_WEIGHT: Final[int] = 1
CLEARED_BY: Final[str] = "package-roots"
# A manifest owns the lockfile in its own folder: a lane that lists the manifest owns the lockfile beside it.
MANIFEST_LOCKFILES: Final[dict[str, tuple[str, ...]]] = {
    "package.json": ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"),
    "Cargo.toml": ("Cargo.lock",),
    "pyproject.toml": ("uv.lock", "poetry.lock"),
    "go.mod": ("go.sum",),
    "Gemfile": ("Gemfile.lock",),
    "composer.json": ("composer.lock",),
}
PACKAGE_MANIFESTS: Final[tuple[str, ...]] = (*MANIFEST_LOCKFILES, "pom.xml", "build.gradle", "setup.py", "setup.cfg")
LAYER_DIRS: Final[dict[str, tuple[str, ...]]] = {
    "data": ("models", "model", "entities", "schemas", "db", "migrations", "repositories", "repository"),
    "api": ("api", "routes", "controllers", "handlers", "endpoints", "services", "service"),
    "ui": ("components", "pages", "views", "ui", "screens", "styles", "templates"),
}
LAYER_BY_DIR: Final[dict[str, str]] = {name: layer for layer, names in LAYER_DIRS.items() for name in names}
BRIEF_SECTIONS: Final[tuple[str, ...]] = (
    "Goal", "Files owned", "Files read-only", "Interfaces", "Order and timing", "Done when",
)


def names_of(lane: dict[str, Any], key: str) -> list[str]:
    raw: Any = lane.get(key) or []
    return [str(n) for n in raw if str(n)] if isinstance(raw, list) else []


def lane_ids_of(manifest: dict[str, Any]) -> list[str]:
    return [str(lane["id"]) for lane in manifest["lanes"]]


def issue(lanes: list[str], other: str, kind: str, detail: str, alternative: str | None) -> dict[str, Any]:
    """The conflict row shape, plus `lanes`: every lane the issue blocks."""
    return {**conflict(lanes[0], other, kind, detail, alternative), "lanes": lanes}


def providers_of(manifest: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """name -> providing lane, plus an error for a name two lanes provide."""
    owner: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    for lane in manifest["lanes"]:
        for name in names_of(lane, PROVIDES):
            if name in owner and owner[name] != lane["id"]:
                errors.append(issue([str(lane["id"]), owner[name]], owner[name], KIND_PROVIDES,
                                    f"both provide '{name}'", f"let one lane provide '{name}' and the other consume it"))
            owner.setdefault(name, str(lane["id"]))
    return owner, errors


def contract_edges(manifest: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]], list[dict[str, Any]]]:
    """(start_after, merge_after, errors). A plain consume must wait for its provider (start and merge). A consume the
    lane is `stubbed_on` starts at once and only merges after its provider."""
    owner, errors = providers_of(manifest)
    start: dict[str, set[str]] = {i: set() for i in lane_ids_of(manifest)}
    merge: dict[str, set[str]] = {i: set() for i in lane_ids_of(manifest)}
    for lane in manifest["lanes"]:
        lane_id: str = str(lane["id"])
        stubbed: list[str] = names_of(lane, STUBBED_ON)
        consumed: list[str] = names_of(lane, CONSUMES)
        for name in stubbed:
            if name not in consumed:
                errors.append(issue([lane_id], lane_id, KIND_PROVIDES, f"stubbed_on '{name}' but the lane does not consume it",
                                    f"add '{name}' to consumes, or drop it from stubbed_on"))
        for name in consumed:
            provider: str | None = owner.get(name)
            if provider is None:
                errors.append(issue([lane_id], lane_id, KIND_PROVIDES, f"consumes '{name}' but no lane provides it",
                                    f"add a lane that provides '{name}', or drop it from consumes"))
                continue
            if provider == lane_id:
                continue
            merge[lane_id].add(provider)
            if name not in stubbed:
                start[lane_id].add(provider)
        merge[lane_id].update(str(d) for d in names_of(lane, MERGE_AFTER) if str(d) in start)
    return start, merge, errors


def needs_of(manifest: dict[str, Any], start: dict[str, set[str]], merge: dict[str, set[str]]) -> dict[str, set[str]]:
    """Every wait edge: explicit depends_on plus the provider edges. Used for the cycle check, order and critical path."""
    ids: set[str] = set(lane_ids_of(manifest))
    return {str(lane["id"]): ({str(d) for d in names_of(lane, DEPENDS_ON)} & ids) | start[str(lane["id"])] | merge[str(lane["id"])]
            for lane in manifest["lanes"]}


def find_cycle(needs: dict[str, set[str]]) -> list[str]:
    """One cycle as a lane path that returns to its first lane, or [] when the graph is acyclic."""
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(needs.get(node, ())):
            if state.get(nxt) == 1:
                return [*stack[stack.index(nxt):], nxt]
            if nxt not in state:
                found: list[str] = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return []

    for start_node in sorted(needs):
        if start_node not in state:
            cycle: list[str] = visit(start_node)
            if cycle:
                return cycle
    return []


def lane_weight(lane: dict[str, Any]) -> int:
    """The spend total when plan added one, else the task count, never below 1."""
    spend: Any = lane.get("estimated_spend")
    total: Any = spend.get("total") if isinstance(spend, dict) else None
    if isinstance(total, int) and not isinstance(total, bool) and total > 0:
        return total
    return max(DEFAULT_WEIGHT, len(lane.get("tasks") or []))


def critical_path(manifest: dict[str, Any], needs: dict[str, set[str]]) -> tuple[list[str], int]:
    """The heaviest chain of lanes that must run one after another (needs must be acyclic)."""
    weight: dict[str, int] = {str(lane["id"]): lane_weight(lane) for lane in manifest["lanes"]}
    best: dict[str, tuple[int, list[str]]] = {}

    def solve(node: str) -> tuple[int, list[str]]:
        if node not in best:
            ahead: list[tuple[int, list[str]]] = [solve(d) for d in sorted(needs.get(node, ()))]
            base: tuple[int, list[str]] = max(ahead, key=lambda r: r[0]) if ahead else (0, [])
            best[node] = (base[0] + weight[node], [*base[1], node])
        return best[node]

    if not weight:
        return [], 0
    total, path = max((solve(n) for n in weight), key=lambda r: r[0])
    return path, total


def critical_line(path: list[str], manifest: dict[str, Any]) -> str:
    weight: dict[str, int] = {str(lane["id"]): lane_weight(lane) for lane in manifest["lanes"]}
    chain: str = " -> ".join(f"{i} ({weight[i]})" for i in path)
    return f"Critical path: {chain} = {sum(weight[i] for i in path)}" if path else "Critical path: none"


def merge_sequence(manifest: dict[str, Any], needs: dict[str, set[str]]) -> list[str]:
    """Stable topological order: provider before consumer, otherwise manifest order."""
    ids: list[str] = lane_ids_of(manifest)
    ordered: list[str] = []
    while len(ordered) < len(ids):
        ready: list[str] = [i for i in ids if i not in ordered and needs[i] <= set(ordered)]
        if not ready:
            raise LaneError("the lanes wait on each other in a cycle; no merge order exists")
        ordered.append(ready[0])
    return ordered


# ---- G-27: owners -------------------------------------------------------------------------------------------------

def owner_kind(entry: str) -> str:
    if entry.endswith("/"):
        return PREFIX
    return GLOB if any(ch in entry for ch in GLOB_CHARS) else EXACT


def static_head(glob: str) -> str:
    cut: list[int] = [glob.index(ch) for ch in GLOB_CHARS if ch in glob]
    return glob[:min(cut)] if cut else glob


def glob_tail(glob: str) -> str:
    last: int = max(glob.rfind(ch) for ch in GLOB_CHARS)
    return glob[last + 1:]


def covers(entry: str, path: str) -> bool:
    kind: str = owner_kind(entry)
    if kind == PREFIX:
        return path.startswith(entry)
    return fnmatch.fnmatchcase(path, entry) if kind == GLOB else entry == path


def entries_overlap(a: str, b: str) -> bool:
    """True when some path could be owned through both entries. Conservative for glob against glob."""
    kinds: tuple[str, str] = (owner_kind(a), owner_kind(b))
    if EXACT in kinds:
        exact, other = (a, b) if kinds[0] == EXACT else (b, a)
        return covers(other, exact)
    if kinds == (PREFIX, PREFIX):
        return a.startswith(b) or b.startswith(a)
    if PREFIX in kinds:
        prefix, glob = (a, b) if kinds[0] == PREFIX else (b, a)
        head: str = static_head(glob)
        return head.startswith(prefix) or prefix.startswith(head)
    head_a, head_b = static_head(a), static_head(b)
    tail_a, tail_b = glob_tail(a), glob_tail(b)
    return (head_a.startswith(head_b) or head_b.startswith(head_a)) and (tail_a.endswith(tail_b) or tail_b.endswith(tail_a))


def repo_wide(entry: str) -> bool:
    return not entry.strip("*/?.[]")


def implied_lockfiles(lane: dict[str, Any]) -> set[str]:
    """The lockfiles beside the package manifests the lane lists: the manifest's folder owns its lockfile."""
    found: set[str] = set()
    for path in lane_files(lane):
        locks: tuple[str, ...] = MANIFEST_LOCKFILES.get(PurePosixPath(path).name, ())
        parent: PurePosixPath = PurePosixPath(path).parent
        found.update(str(parent / lock) if str(parent) != "." else lock for lock in locks)
    return found - lane_files(lane)


def owned_entries(lane: dict[str, Any]) -> set[str]:
    """What a builder of this lane may write: its entries plus the lockfiles of its manifests."""
    return lane_files(lane) | implied_lockfiles(lane)


def owner_errors(lane: dict[str, Any]) -> list[dict[str, Any]]:
    lane_id: str = str(lane["id"])
    files: set[str] = lane_files(lane)
    if not files:
        return [issue([lane_id], lane_id, KIND_OWNERS, "owns no files",
                      "list the files, a dir/ prefix or a glob the lane writes; a lane that writes nothing is not a lane")]
    return [issue([lane_id], lane_id, KIND_OWNERS, f"owner '{e}' covers the whole repo", "narrow it to the lane's own folder")
            for e in sorted(files) if repo_wide(e)]


def owner_overlaps(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Overlaps the exact-file check cannot see: a prefix or glob against a file, a prefix or another glob, and a lockfile
    a manifest implies. Exact files both lanes list stay with the existing file check."""
    explicit_a, explicit_b = lane_files(a), lane_files(b)
    pairs: list[tuple[str, str]] = sorted(
        (ea, eb) for ea in owned_entries(a) for eb in owned_entries(b)
        if not (ea == eb and ea in explicit_a and eb in explicit_b) and entries_overlap(ea, eb))
    if not pairs:
        return []
    shown: str = "; ".join(f"{ea} overlaps {eb}" for ea, eb in pairs[:SHOWN_OVERLAPS])
    return [issue([str(a["id"]), str(b["id"])], str(b["id"]), KIND_OWNERS, shown,
                  f"narrow one owner, or run {b['id']} after {a['id']}")]


# ---- G-28: slices and package roots -------------------------------------------------------------------------------

def probe_path(entry: str) -> str | None:
    """A path under the entry whose folders can be searched for a package manifest."""
    kind: str = owner_kind(entry)
    if kind == EXACT:
        return entry
    head: str = entry if kind == PREFIX else static_head(entry)
    folder: str = head if head.endswith("/") else head[:head.rfind("/") + 1]
    return f"{folder}x" if folder else None


def package_root(entry: str, cwd: Path) -> str | None:
    """The nearest folder above the entry that holds a package manifest, never the repo root itself."""
    probe: str | None = probe_path(entry)
    if probe is None or probe.startswith(("../", "/")):
        return None
    for parent in PurePosixPath(probe).parents:
        if str(parent) != "." and any((cwd / parent / m).is_file() for m in PACKAGE_MANIFESTS):
            return str(parent)
    return None


def lane_roots(lane: dict[str, Any], cwd: Path, shared: tuple[str, ...]) -> tuple[set[str], bool]:
    """(package roots of the lane's files, whether every file has one). Files that route to the integration lane are left out."""
    entries: list[str] = [e for e in sorted(lane_files(lane)) if not is_integration_file(e, shared)]
    roots: list[str | None] = [package_root(e, cwd) for e in entries]
    return {r for r in roots if r}, bool(entries) and all(roots)


def cleared_area(found: dict[str, Any], by_id: dict[str, dict[str, Any]], cwd: Path, shared: tuple[str, ...]) -> bool:
    """A depth-2 area conflict between two lanes whose files all sit in package roots is not a conflict: vertical slices of
    one package share folders, and the file check already keeps their files apart."""
    if found.get("kind") != KIND_AREA or found["lane"] not in by_id or found["with"] not in by_id:
        return False
    return all(lane_roots(by_id[i], cwd, shared)[1] for i in (found["lane"], found["with"]))


def layer_of(path: str) -> str | None:
    for part in PurePosixPath(path).parts[:-1]:
        if part.lower() in LAYER_BY_DIR:
            return LAYER_BY_DIR[part.lower()]
    return None


def layer_warnings(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Three or more lanes that each own one horizontal layer (data, api, ui) are a layer cake, not vertical slices."""
    single: dict[str, str] = {}
    for lane in manifest["lanes"]:
        layers: set[str | None] = {layer_of(f) for f in lane_files(lane)}
        if len(layers) == 1 and None not in layers:
            single[str(lane["id"])] = str(next(iter(layers)))
    if len(set(single.values())) < MIN_LAYER_LANES:
        return []
    ids: list[str] = sorted(single)
    return [issue(ids, "plan", KIND_LAYERS, f"lanes {', '.join(ids)} each own one layer ({', '.join(sorted(set(single.values())))})",
                  "slice by feature instead: one lane per feature, across data, api and ui, tests with it")]


# ---- the report ---------------------------------------------------------------------------------------------------

def analyse(manifest: dict[str, Any], cwd: Path, shared: tuple[str, ...] = ()) -> dict[str, Any]:
    """The graph report. `errors` block the plan, check and lease; `warnings` are advice."""
    lanes: list[dict[str, Any]] = manifest["lanes"]
    start, merge, errors = contract_edges(manifest)
    for lane in lanes:
        errors.extend(owner_errors(lane))
    for index, lane in enumerate(lanes):
        for other in lanes[index + 1:]:
            errors.extend(owner_overlaps(lane, other))
    for lane in lanes:
        errors.extend(issue([str(lane["id"])], provider, KIND_DEPENDS, f"{lane['id']} consumes {provider}'s output",
                            f"start {lane['id']} after {provider} merges, or build it against a stub (stubbed_on)")
                      for provider in sorted(start[str(lane["id"])]))
    needs: dict[str, set[str]] = needs_of(manifest, start, merge)
    cycle: list[str] = find_cycle(needs)
    if cycle:
        errors.append(issue(sorted(set(cycle)), cycle[-1], KIND_CYCLE, f"cycle: {' -> '.join(cycle)}",
                            "break the cycle: move the shared part into one lane that the others consume"))
    report: dict[str, Any] = {"ok": not errors, "errors": errors, "warnings": layer_warnings(manifest),
                              "start_after": {k: sorted(v) for k, v in start.items() if v},
                              "merge_after": {k: sorted(v) for k, v in merge.items() if v},
                              "owned": {str(lane["id"]): sorted(owned_entries(lane)) for lane in lanes},
                              "packages": {str(lane["id"]): sorted(lane_roots(lane, cwd, shared)[0]) for lane in lanes}}
    if cycle:
        return {**report, "critical_path": [], "critical_path_line": "Critical path: none (cycle)", "order": []}
    path, total = critical_path(manifest, needs)
    return {**report, "critical_path": path, "critical_path_weight": total, "critical_path_line": critical_line(path, manifest),
            "order": merge_sequence(manifest, needs)}


def settle(report: dict[str, Any], manifest: dict[str, Any], cwd: Path, shared: tuple[str, ...]) -> dict[str, Any]:
    """Drop the area conflicts that package roots clear, then recompute `ok` from what is left."""
    by_id: dict[str, dict[str, Any]] = {str(lane["id"]): lane for lane in manifest["lanes"]}
    kept: list[dict[str, Any]] = []
    cleared: list[dict[str, Any]] = []
    for found in report["conflicts"]:
        (cleared if cleared_area(found, by_id, cwd, shared) else kept).append(found)
    cleared = [{**c, "cleared_by": CLEARED_BY} for c in cleared]
    return {**report, "conflicts": kept, "cleared": cleared, "ok": not [c for c in kept if not c.get("routed")]}


def annotate_plan(result: dict[str, Any], cwd: Path) -> dict[str, Any]:
    """Add `graph` to a lanes.py plan result and fold its errors and the cleared area conflicts into `ok`."""
    manifest: dict[str, Any] = result["manifest"]
    shared: tuple[str, ...] = shared_patterns(cwd)
    graph: dict[str, Any] = analyse(manifest, cwd, shared) if manifest["lanes"] else {"ok": True, "errors": [], "warnings": []}
    feasibility: dict[str, Any] = settle(result["feasibility"], manifest, cwd, shared)
    gh_ok: bool = bool(feasibility.get("prs_checked", True)) or "detail" not in result  # keep plan's gh fail-closed refusal
    ok: bool = bool(manifest["lanes"]) and not result["refused"] and feasibility["ok"] and graph["ok"] and gh_ok
    return {**result, "ok": ok, "feasibility": feasibility, "graph": graph}


def graph_check(manifest: dict[str, Any], runs_dir: Path, cwd: Path, with_prs: bool = True) -> dict[str, Any]:
    """lanes.py check plus the graph: package-root area clearing, owner overlaps, contracts and cycles."""
    shared: tuple[str, ...] = shared_patterns(cwd)
    graph: dict[str, Any] = analyse(manifest, cwd, shared)
    result: dict[str, Any] = settle(check(manifest, runs_dir, cwd, with_prs), manifest, cwd, shared)
    return {**result, "ok": result["ok"] and graph["ok"], "graph": graph}


def blocking_for(result: dict[str, Any], lane_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = [c for c in result["conflicts"] if lane_id in (c["lane"], c["with"]) and not c.get("routed")]
    return found + [e for e in result["graph"]["errors"] if lane_id in e["lanes"]]


def graph_lease(manifest: dict[str, Any], lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool,
                epoch: int | None = None) -> dict[str, Any]:
    """lanes.py lease with the graph gate: the same admission lock, gh fail-closed, epoch fence, TTL and record, but the
    conflicts come from graph_check."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    path: Path = runs_dir / str(manifest.get("stamp")) / lane_id / LEASE_NAME
    with admission_lock(runs_dir) as admitted:
        if not admitted:
            return busy(lane_id)
        result: dict[str, Any] = graph_check(manifest, runs_dir, cwd, with_prs)
        if with_prs and not result.get("prs_checked"):
            return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": gh_down("lease")}
        blocking: list[dict[str, Any]] = blocking_for(result, lane_id)
        if blocking:
            return {"ok": False, "lane": lane_id, "lease": None, "conflicts": blocking}
        why: str | None = admission_refusal(runs_dir, str(manifest.get("stamp")), lane_id, str(lane.get("item") or ""))
        if why is not None:
            return refused(lane_id, why)
        with lane_lock(path) as held:
            return write_lease(manifest, lane, path, epoch, lease_ttl_s(cwd), files=owned_entries(lane)) if held else busy(lane_id)


def record_merge_order(manifest: dict[str, Any], runs_dir: Path, cwd: Path) -> dict[str, Any]:
    """Write the provider-first order to the lanes merge-order record (through the merge module), integration lane last."""
    from lanes.merge import record_plan
    graph: dict[str, Any] = analyse(manifest, cwd, shared_patterns(cwd))
    if not graph["order"]:
        raise LaneError("cannot order the lanes: " + "; ".join(e["detail"] for e in graph["errors"]))
    files: list[str] = list(route(manifest, shared_patterns(cwd))["files"])
    return {"ok": record_plan(manifest, runs_dir, graph["order"], files), "order": graph["order"], "integration_files": files}


def lane_brief(manifest: dict[str, Any], lane_id: str) -> str:
    """The six-section lane brief skeleton: goal, files owned, files read-only, interfaces, order and timing, done when."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    start, merge, _ = contract_edges(manifest)
    owned: list[str] = sorted(owned_entries(lane))
    interfaces: list[str] = [f"- provides `{n}`" for n in names_of(lane, PROVIDES)]
    interfaces += [f"- consumes `{n}`" + (" (build against a stub)" if n in names_of(lane, STUBBED_ON) else "") for n in names_of(lane, CONSUMES)]
    timing: list[str] = [f"- starts after: {', '.join(sorted(start[lane_id])) or 'nothing'}",
                         f"- merges after: {', '.join(sorted(merge[lane_id] | set(names_of(lane, DEPENDS_ON)))) or 'nothing'}"]
    body: dict[str, list[str]] = {
        "Goal": [f"- {lane.get('item') or lane_id}", *[f"- {t}" for t in lane.get("tasks") or []]],
        "Files owned": [f"- `{f}`" for f in owned], "Files read-only": ["- everything else"],
        "Interfaces": interfaces or ["- none"], "Order and timing": timing,
        "Done when": ["- each task's done-when holds and the checks are green on HEAD"],
    }
    return "\n".join(f"## {name}\n" + "\n".join(body[name]) + "\n" for name in BRIEF_SECTIONS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("analyse").add_argument("manifest")
    order_p = sub.add_parser("merge-order")
    order_p.add_argument("manifest")
    order_p.add_argument("--runs-dir", required=True, help="the runs folder that holds the run stamp folders")
    brief_p = sub.add_parser("brief")
    brief_p.add_argument("manifest")
    brief_p.add_argument("--lane", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cwd: Path = Path(args.cwd)
    try:
        manifest: dict[str, Any] = load_manifest(Path(args.manifest))
        if args.command == "brief":
            print(lane_brief(manifest, args.lane), end="")
            return 0
        result: dict[str, Any] = (analyse(manifest, cwd, shared_patterns(cwd)) if args.command == "analyse"
                                  else record_merge_order(copy.deepcopy(manifest), Path(args.runs_dir), cwd))
    except LaneError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
