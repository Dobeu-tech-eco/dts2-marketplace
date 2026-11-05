"""Eval statistics (G-75): k alternating A/B runs per fixture, then median, range and pass^k per arm and a verdict on
wall-clock. Pure functions plus `alternate`, which takes the two runners as callables so unit tests use a fake one."""
from __future__ import annotations

import statistics
from typing import Any, Callable, Final

MIN_RUNS: Final[int] = 5  # fewer runs than this cannot separate a real change from noise
DEFAULT_RUNS: Final[int] = MIN_RUNS
NO_DIFFERENCE_THRESHOLD: Final[float] = 0.10  # medians within 10% of arm A are "no difference"
FASTER: Final[str] = "faster"
SLOWER: Final[str] = "slower"
NO_DIFFERENCE: Final[str] = "no difference"
INCONCLUSIVE: Final[str] = "inconclusive"
Runner = Callable[[], dict[str, Any]]  # one fixture run -> a row with at least "pass" and "wall_ms"


def alternate(run_a: Runner, run_b: Runner, k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A, B, A, B ... k times each, so drift in machine load lands on both arms alike."""
    rows_a: list[dict[str, Any]] = []
    rows_b: list[dict[str, Any]] = []
    for _ in range(k):
        rows_a.append(run_a())
        rows_b.append(run_b())
    return rows_a, rows_b


def summarize(rows: list[dict[str, Any]], key: str = "wall_ms") -> dict[str, Any]:
    """Median, min/max range and pass^k of one arm. pass^k is the observed pass rate raised to k: the chance that k fresh
    runs all pass if the rate holds. Only runs that passed feed the timing, so a crash cannot look fast."""
    k: int = len(rows)
    passed: int = sum(1 for r in rows if r.get("pass") is True)
    values: list[float] = [float(r[key]) for r in rows if r.get("pass") is True]
    rate: float = passed / k if k else 0.0
    return {"k": k, "passed": passed, "pass_rate": rate, "pass_k": rate ** k if k else 0.0,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def verdict(a: dict[str, Any], b: dict[str, Any], threshold: float = NO_DIFFERENCE_THRESHOLD, min_runs: int = MIN_RUNS) -> str:
    """How arm B compares with arm A on the median. Inconclusive when either arm has too few runs, has a failed run, or
    when the medians differ by more than the threshold but the two ranges overlap (noise could explain it)."""
    if min(a["k"], b["k"]) < min_runs or a["passed"] != a["k"] or b["passed"] != b["k"]:
        return INCONCLUSIVE
    base: float = float(a["median"])
    if base <= 0:
        return INCONCLUSIVE
    change: float = (float(b["median"]) - base) / base
    if abs(change) <= threshold:
        return NO_DIFFERENCE
    if b["min"] <= a["max"] and a["min"] <= b["max"]:
        return INCONCLUSIVE
    return FASTER if change < 0 else SLOWER


def compare(run_a: Runner, run_b: Runner, k: int = DEFAULT_RUNS) -> dict[str, Any]:
    """Alternate k runs of each arm and report both summaries with the verdict (B against A)."""
    rows_a, rows_b = alternate(run_a, run_b, k)
    a, b = summarize(rows_a), summarize(rows_b)
    return {"a": a, "b": b, "verdict": verdict(a, b)}
