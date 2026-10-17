#!/usr/bin/env python3
"""Size one or more repos and recommend a team tier. Read-only."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Final

MAX_FILE_BYTES: Final[int] = 1_000_000
TIER_S_LOC: Final[int] = 20_000
TIER_M_LOC: Final[int] = 150_000
TIER_L_LOC: Final[int] = 600_000
MONOREPO_MARKERS: Final[tuple[str, ...]] = (
    "pnpm-workspace.yaml", "turbo.json", "nx.json", "lerna.json", "go.work", "Cargo.toml",
)
TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".rs", ".rb", ".php", ".java",
    ".kt", ".cs", ".swift", ".sql", ".css", ".scss", ".html", ".vue", ".svelte", ".md",
})
TIERS: Final[dict[str, dict[str, object]]] = {
    "S": {"builders": 1, "reviewers": ["all"], "worktrees": False},
    "M": {"builders": 2, "reviewers": ["correctness", "security"], "worktrees": False},
    "L": {"builders": 4, "reviewers": ["correctness", "security", "performance"], "worktrees": True},
    "XL": {"builders": 6, "reviewers": ["correctness", "security", "performance", "style"], "worktrees": True},
}


def tracked_files(repo: Path) -> list[Path]:
    result = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True)
    if result.returncode != 0:
        return [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [repo / line for line in result.stdout.splitlines() if line]


def count_lines(path: Path) -> int:
    if path.suffix not in TEXT_SUFFIXES or not path.exists():
        return 0
    if path.stat().st_size > MAX_FILE_BYTES:
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def module_count(files: list[Path], repo: Path) -> int:
    tops: set[str] = {f.relative_to(repo).parts[0] for f in files if len(f.relative_to(repo).parts) > 1}
    return len(tops)


def tier_for(loc: int, monorepo: bool) -> str:
    if loc < TIER_S_LOC and not monorepo:
        return "S"
    if loc < TIER_M_LOC:
        return "M"
    return "L" if loc < TIER_L_LOC else "XL"


def size_repo(repo: Path, max_builders: int) -> dict[str, object]:
    files: list[Path] = tracked_files(repo)
    loc: int = sum(count_lines(f) for f in files)
    monorepo: bool = any((repo / marker).exists() for marker in MONOREPO_MARKERS)
    tier: str = tier_for(loc, monorepo)
    team: dict[str, object] = dict(TIERS[tier])
    team["builders"] = min(int(team["builders"]), max_builders)
    return {"repo": str(repo), "files": len(files), "loc": loc,
            "modules": module_count(files, repo), "monorepo": monorepo, "tier": tier, **team}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repos", nargs="*", default=["."])
    parser.add_argument("--max-builders", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reports: list[dict[str, object]] = [size_repo(Path(r).resolve(), args.max_builders) for r in args.repos]
    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
        return 0
    for r in reports:
        print(f"{r['repo']}: {r['files']} files, {r['loc']} LOC, tier {r['tier']}, builders {r['builders']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
