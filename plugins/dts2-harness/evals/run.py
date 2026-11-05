#!/usr/bin/env python3
"""Smoke eval runner: drive five frozen fixtures through the deterministic parts of the harness pipeline, using fake
`claude` and `gh` binaries (DTS2_CLAUDE_BIN, DTS2_GH_BIN). Never starts a real model and never touches the network.

  python3 evals/run.py [--fixture NAME ...] [--baseline PATH] [--results-dir DIR] [--update-baseline]

Steps covered per fixture, each through the real script:
  1. scope-check.py      where the session sits (workspace or single repo)
  2. lanes.py check      lane overlap conflicts for the fixture's lane manifest
  3. lanes.py lease      two leases (epoch 2); an optional stale-epoch claim that must be refused
  4. lanes.py call       one builder round per scripted round, through the fake claude (tokens and cost read from it)
  5. checks.py gate      a red round blocks the vote and counts as a fix round; ledger lines from checks.append_ledger
  6. council.py route    where a green step goes next (pass, fix, escalate); council.py tally on the fixture ballots
Not covered (need the lanes.py spawn path or a live model): son and lead briefs, spawn --dry-run, prefix stability.

It writes <results-dir>/<stamp>.json (pass/fail, tokens, wall-clock, fix rounds per fixture), prints the delta against the
baseline (token and wall-clock totals, per fixture and in total) and exits 1 only when a fixture that passed in the baseline
now fails. Cost deltas never change the exit code. Exit 2 means the runner itself could not run: an unknown fixture, an unreadable
baseline (corrupt, not an object, or missing at a path passed with --baseline), or --update-baseline with failing fixtures.
A missing default baseline is a warned "no baseline" run. --update-baseline with --fixture replaces only those rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Final

EVALS: Final[Path] = Path(__file__).resolve().parent
PLUGIN: Final[Path] = EVALS.parent
SCRIPTS: Final[Path] = PLUGIN / "scripts"
FIXTURES: Final[Path] = EVALS / "fixtures"
FAKE_CLAUDE: Final[Path] = EVALS / "fakes" / "claude.py"
FAKE_GH: Final[Path] = EVALS / "fakes" / "gh.py"
DEFAULT_BASELINE: Final[Path] = EVALS / "baseline.json"
DEFAULT_RESULTS: Final[Path] = EVALS / "results"
CHECK_NAMES: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "secret-scan", "scope-check")
CALL_TIMEOUT_S: Final[int] = 60
STEP_TIMEOUT_S: Final[int] = 120

sys.path.insert(0, str(SCRIPTS))
from checks import append_ledger  # noqa: E402
from state_io import atomic_write  # noqa: E402


class EvalError(Exception):
    """The runner could not drive a step (a script crashed or printed no JSON)."""


def script(name: str, args: list[str], env: dict[str, str], cwd: Path) -> dict[str, Any]:
    done = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *args], cwd=str(cwd), env=env, capture_output=True,
                          text=True, timeout=STEP_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    try:
        parsed: Any = json.loads(done.stdout)
    except ValueError as exc:
        raise EvalError(f"{name} {' '.join(args[:2])}: no JSON on stdout (exit {done.returncode}): {done.stderr[-300:]}") from exc
    if not isinstance(parsed, dict):
        raise EvalError(f"{name}: expected a JSON object")
    return parsed


def lanes(repo: Path, env: dict[str, str], *args: str) -> dict[str, Any]:
    return script("lanes.py", ["--cwd", str(repo), "--no-prs", *args], env, repo)


def builder_round(repo: Path, env: dict[str, str], stamp: str, index: int) -> dict[str, Any]:
    out = lanes(repo, env, "call", stamp, "--label", f"builder-{index}", "--timeout", str(CALL_TIMEOUT_S), "--",
                sys.executable, str(FAKE_CLAUDE), "-p", "build")
    try:
        usage: dict[str, Any] = json.loads(out["stdout"]).get("usage", {})
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalError(f"builder round {index}: fake claude printed no result") from exc
    return {"ok": out.get("ok") is True, "tokens": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
            "cost_usd": out.get("charged_usd")}


def record_checks(ledger: Path, status: str) -> None:
    for name in CHECK_NAMES:
        red: bool = status == "fail" and name == "test"
        append_ledger(ledger, {"kind": "check", "name": name, "status": "fail" if red else "pass", "head": "eval",
                               "duration_ms": 0, "log_path": ""})


def build_phase(repo: Path, env: dict[str, str], stamp: str, rounds: list[dict[str, Any]]) -> dict[str, Any]:
    ledger: Path = repo / ".harness" / "runs" / stamp / "ledger.jsonl"
    tokens: int = 0
    fix_rounds: int = 0
    blocked: bool = False
    final: str = "none"
    for index, spec in enumerate(rounds):
        tokens += int(builder_round(repo, env, stamp, index)["tokens"])
        final = str(spec["check"])
        record_checks(ledger, final)
        gate: dict[str, Any] = script("checks.py", ["gate", "--stamp", stamp, "--cwd", str(repo)], env, repo)
        if final == "fail":
            fix_rounds += 1
            blocked = blocked or gate.get("votes_allowed") is False
    return {"tokens": tokens, "fix_rounds": fix_rounds, "red_blocked_votes": blocked, "final_check": final, "ledger": ledger}


def council_phase(repo: Path, env: dict[str, str], ledger: Path, scenario: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    if route.get("action") != "escalate" or not scenario.get("ballots"):
        return {}
    folder: Path = repo / ".harness" / "ballots"
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for seat, text in sorted(scenario["ballots"].items()):
        (folder / f"{seat}.md").write_text(text, encoding="utf-8")
        record: dict[str, Any] = {"argv": ["eval-fixture-seat"], "model": "fixture", "session_id": None,  # G-68: tally needs a record
                                  "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        (folder / f"{seat}.md.dispatch.json").write_text(json.dumps(record), encoding="utf-8")
        paths.append(str(folder / f"{seat}.md"))
    tally: dict[str, Any] = script("council.py", ["tally", *paths], env, repo)
    return {"tally_majority": tally.get("majority"), "tally_ok": tally.get("ok"), "dissenters": tally.get("dissenters")}


def stored_epoch(lease_path: Any) -> Any:
    try:
        data: Any = json.loads(Path(str(lease_path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("epoch") if isinstance(data, dict) else None


def drive(fixture: Path, work: Path, env: dict[str, str]) -> dict[str, Any]:
    """Run one fixture and return what was observed plus tokens, fix rounds and the steps it covered."""
    scenario: dict[str, Any] = json.loads((fixture / "scenario.json").read_text(encoding="utf-8"))
    repo: Path = work / "repo"
    shutil.copytree(fixture / "repo", repo)
    stamp: str = "eval-" + fixture.name
    manifest: Path = work / "manifest.json"
    manifest.write_text(json.dumps({"stamp": stamp, "base": "eval", "scope": "single", "lanes": scenario["lanes"]}), encoding="utf-8")
    env = {**env, "DTS2_EVAL_SCRIPT": str(work / "script.json"), "DTS2_EVAL_STATE": str(work / "state")}
    (work / "script.json").write_text(json.dumps({"rounds": scenario["rounds"]}), encoding="utf-8")
    observed: dict[str, Any] = {"scope": script("scope-check.py", [str(repo)], env, repo).get("scope")}
    overlap: dict[str, Any] = lanes(repo, env, "check", str(manifest))
    observed["conflicts"] = len(overlap.get("conflicts", []))
    lane_id: str = str(scenario["lanes"][0]["id"])
    first: dict[str, Any] = lanes(repo, env, "lease", str(manifest), "--lane", lane_id)
    if first.get("ok"):
        second: dict[str, Any] = lanes(repo, env, "lease", str(manifest), "--lane", lane_id)
        observed["epoch"] = second.get("epoch")
        if "stale_epoch" in scenario:
            stale: dict[str, Any] = lanes(repo, env, "lease", str(manifest), "--lane", lane_id, "--epoch", str(scenario["stale_epoch"]))
            observed["stale_epoch_refused"] = stale.get("ok") is False
            observed["stored_epoch"] = stored_epoch(second.get("lease"))
    else:
        observed["lease_blocked"] = True
    built: dict[str, Any] = build_phase(repo, env, stamp, scenario["rounds"])
    for key in ("fix_rounds", "final_check"):
        observed[key] = built[key]
    if built["fix_rounds"]:
        observed["red_blocked_votes"] = built["red_blocked_votes"]
    route: dict[str, Any] = script("council.py", ["route", "--ledger", str(built["ledger"]), "--votes", ",".join(scenario["votes"])], env, repo)
    observed["route"] = route.get("action") if route.get("ok") else "blocked"
    observed.update(council_phase(repo, env, built["ledger"], scenario, route))
    return {"observed": observed, "tokens": built["tokens"], "fix_rounds": built["fix_rounds"]}


def run_fixture(fixture: Path, env: dict[str, str]) -> dict[str, Any]:
    expected: dict[str, Any] = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    started: float = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dts2-eval-") as tmp:
        try:
            driven: dict[str, Any] = drive(fixture, Path(tmp), env)
        except (EvalError, OSError, subprocess.TimeoutExpired, KeyError, ValueError) as exc:
            return {"pass": False, "tokens": 0, "wall_ms": int((time.monotonic() - started) * 1000), "fix_rounds": 0,
                    "error": str(exc)[:400], "mismatch": {}}
    mismatch: dict[str, Any] = {k: {"expected": v, "got": driven["observed"].get(k)} for k, v in expected.items()
                                if driven["observed"].get(k) != v}
    return {"pass": not mismatch, "tokens": driven["tokens"], "wall_ms": int((time.monotonic() - started) * 1000),
            "fix_rounds": driven["fix_rounds"], "mismatch": mismatch}


def totals(rows: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {"fixtures": len(rows), "passed": sum(1 for r in rows.values() if r["pass"]),
            "tokens": sum(int(r["tokens"]) for r in rows.values()), "wall_ms": sum(int(r["wall_ms"]) for r in rows.values()),
            "fix_rounds": sum(int(r["fix_rounds"]) for r in rows.values())}


def signed(now: int, then: int) -> str:
    return f"{now - then:+d}"


def delta_lines(rows: dict[str, dict[str, Any]], total: dict[str, int], baseline: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    base_rows: dict[str, Any] = baseline.get("fixtures", {})
    for name, row in sorted(rows.items()):
        old: dict[str, Any] | None = base_rows.get(name)
        status: str = "PASS" if row["pass"] else "FAIL"
        if old is None:
            lines.append(f"{name}: {status} tokens={row['tokens']} wall_ms={row['wall_ms']} (not in baseline)")
            continue
        lines.append(f"{name}: {status} tokens {row['tokens']} ({signed(row['tokens'], int(old['tokens']))}) "
                     f"wall_ms {row['wall_ms']} ({signed(row['wall_ms'], int(old['wall_ms']))})")
    shared: list[str] = [n for n in sorted(rows) if n in base_rows]
    missing: list[str] = [n for n in sorted(rows) if n not in base_rows]
    now_tokens: int = sum(int(rows[n]["tokens"]) for n in shared)
    now_wall: int = sum(int(rows[n]["wall_ms"]) for n in shared)
    if shared:
        old_tokens: int = sum(int(base_rows[n]["tokens"]) for n in shared)
        old_wall: int = sum(int(base_rows[n]["wall_ms"]) for n in shared)
        note: str = f" (compared over {len(shared)} fixture(s) in the baseline)" if missing else ""
        lines.append(f"TOTAL: {total['passed']}/{total['fixtures']} pass tokens {now_tokens} ({signed(now_tokens, old_tokens)}) "
                     f"wall_ms {now_wall} ({signed(now_wall, old_wall)}){note}")
    else:
        lines.append(f"TOTAL: {total['passed']}/{total['fixtures']} pass tokens {total['tokens']} wall_ms {total['wall_ms']} (no baseline)")
    if missing and shared:
        lines.append(f"not in baseline: {', '.join(missing)}")
    return lines


def regressions(rows: dict[str, dict[str, Any]], baseline: dict[str, Any]) -> list[str]:
    """Fixtures that passed in the baseline and fail now. Cost changes are never a regression."""
    base_rows: dict[str, Any] = baseline.get("fixtures", {})
    return sorted(name for name, row in rows.items() if not row["pass"] and base_rows.get(name, {}).get("pass") is True)


def load_baseline(path: Path) -> dict[str, Any]:
    """Return the baseline object, {} when the file is missing; raise ValueError when it exists but is unusable."""
    if not path.exists():
        return {}
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a JSON object")
    return data


def fake_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    env["DTS2_CLAUDE_BIN"] = str(FAKE_CLAUDE)
    env["DTS2_GH_BIN"] = str(FAKE_GH)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", action="append", default=[], help="run only this fixture (repeatable)")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    parser.add_argument("--update-baseline", action="store_true", help="write this run to the baseline path")
    args = parser.parse_args()
    names: list[str] = sorted(p.name for p in FIXTURES.iterdir() if (p / "scenario.json").is_file())
    chosen: list[str] = args.fixture or names
    unknown: list[str] = [n for n in chosen if n not in names]
    if unknown:
        print(json.dumps({"ok": False, "error": f"unknown fixture: {', '.join(unknown)}"}))
        return 2
    base_path: Path = Path(args.baseline)
    if not base_path.exists() and args.baseline != str(DEFAULT_BASELINE) and not args.update_baseline:
        print(json.dumps({"ok": False, "error": f"unreadable baseline: {base_path} does not exist"}))
        return 2
    try:
        baseline: dict[str, Any] = load_baseline(base_path)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": f"unreadable baseline: {exc}"}))
        return 2
    env: dict[str, str] = fake_env()
    rows: dict[str, dict[str, Any]] = {n: run_fixture(FIXTURES / n, env) for n in chosen}
    failing: list[str] = sorted(n for n, r in rows.items() if not r["pass"])
    if args.update_baseline and failing:
        print(json.dumps({"ok": False, "error": f"refusing to record a baseline with failing fixtures: {', '.join(failing)}"}))
        return 2
    total: dict[str, int] = totals(rows)
    stamp: str = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    record: dict[str, Any] = {"stamp": stamp, "fake_binaries": True, "fixtures": rows, "totals": total}
    out: Path = Path(args.results_dir) / f"{stamp}.json"
    atomic_write(out, json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not baseline:
        print(f"warning: no baseline at {base_path}; deltas not available")
    print("\n".join(delta_lines(rows, total, baseline)))
    failed: list[str] = regressions(rows, baseline)
    for name, row in rows.items():
        if not row["pass"]:
            print(f"  {name} mismatch: {json.dumps(row.get('mismatch') or row.get('error'))}")
    if args.update_baseline:
        merged: dict[str, dict[str, Any]] = {**baseline.get("fixtures", {}), **rows} if args.fixture else rows
        new_base: dict[str, Any] = {"fake_binaries": True, "fixtures": merged, "totals": totals(merged)}
        atomic_write(base_path, json.dumps(new_base, indent=2, sort_keys=True) + "\n")
        print(f"baseline written: {args.baseline}")
    print(f"results: {out}")
    if failed:
        print(f"REGRESSION: {', '.join(failed)} passed in the baseline and fail now")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
