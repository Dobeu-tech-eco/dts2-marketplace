"""Resolve a general Chairman from the caller's authenticated live Claude catalog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def resolve(rows: list[dict]) -> dict:
    """Unknown eligibility and restricted models never become general defaults."""
    available = [r for r in rows if r.get("provider") == "claude"
                 and r.get("available") is True and r.get("restricted") is False
                 and "mythos" not in str(r.get("id", "")).lower() and r.get("id")]
    frontier = [r for r in available if r.get("frontier") is True]
    candidates = frontier or available
    if not candidates:
        raise ValueError("No generally available Claude; park the run")
    chosen = max(candidates, key=lambda r: (r.get("rank", 0), r["id"]))
    return {"class": "latest-frontier-claude", "model": chosen["id"],
            "fallback": not bool(frontier), "aliases": chosen.get("aliases", [])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    result = resolve(json.loads(args.catalog.read_text(encoding="utf-8")))
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
