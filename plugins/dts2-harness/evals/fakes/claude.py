#!/usr/bin/env python3
"""Fake `claude` for the smoke eval. Never touches the network. Each call answers with the next scripted round.

DTS2_EVAL_SCRIPT: JSON file holding {"rounds": [{"tokens_in", "tokens_out", "cost_usd", "is_error"}, ...]}.
DTS2_EVAL_STATE: counter file; the n-th call answers rounds[n] (the last round repeats once the script runs out).
`--version` prints a fixed version so preflight-style checks work."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

FAKE_VERSION: Final[str] = "0.0.0-eval"


def next_round() -> dict[str, Any]:
    script: dict[str, Any] = json.loads(Path(os.environ["DTS2_EVAL_SCRIPT"]).read_text(encoding="utf-8"))
    state: Path = Path(os.environ["DTS2_EVAL_STATE"])
    index: int = int(state.read_text(encoding="utf-8")) if state.is_file() else 0
    state.write_text(str(index + 1), encoding="utf-8")
    rounds: list[dict[str, Any]] = script["rounds"]
    return rounds[min(index, len(rounds) - 1)]


def main() -> int:
    if "--version" in sys.argv:
        print(f"{FAKE_VERSION} (Claude Code)")
        return 0
    sys.stdin.read() if not sys.stdin.isatty() else None
    spec: dict[str, Any] = next_round()
    result: dict[str, Any] = {
        "type": "result", "subtype": "success", "is_error": bool(spec.get("is_error", False)), "num_turns": 3,
        "total_cost_usd": float(spec.get("cost_usd", 0.01)),
        "usage": {"input_tokens": int(spec.get("tokens_in", 0)), "output_tokens": int(spec.get("tokens_out", 0))},
        "result": "fake round",
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
