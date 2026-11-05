#!/usr/bin/env python3
"""Q-16: SessionEnd releases the lane leases this session took. Reads the hook JSON on stdin; best effort, always exits 0.

Only a lease whose record carries this session's `session_id` is released (never another session's, never one with no
owner), and only for reasons `logout`, `prompt_input_exit` and `other`. Lease expiry (G-16) stays the guarantee."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

REASONS: Final[frozenset[str]] = frozenset({"logout", "prompt_input_exit", "other"})
OWNER_KEY: Final[str] = "session_id"
STATUS_ACTIVE: Final[str] = "active"


def owned(lease: dict[str, Any] | None, session: str) -> bool:
    return bool(lease) and lease is not None and lease.get(OWNER_KEY) == session and lease.get("status") == STATUS_ACTIVE


def release_session(repo: Path, session: str) -> list[str]:
    """Close every active lease stamped with `session`; the `<stamp>/<lane>` pairs released."""
    store = state_io.State(state_io.FileStore(repo))
    released: list[str] = []
    for stamp in store.runs():
        try:
            lanes: list[str] = store.lanes(stamp)
        except (state_io.StateError, ValueError):
            continue
        for lane in lanes:
            try:
                lease: dict[str, Any] | None = store.lease(stamp, lane)
                if not owned(lease, session):
                    continue
                store.release_lease(stamp, lane, epoch=state_io.epoch_of(lease))
                released.append(f"{stamp}/{lane}")
            except (state_io.StateError, ValueError):
                continue  # best effort: expiry reclaims what this misses
    return released


def run(payload: dict[str, Any]) -> list[str]:
    session: str = str(payload.get("session_id") or "")
    if not session or payload.get("reason") not in REASONS:
        return []
    repo: Path = Path(str(payload.get("cwd") or "."))
    return release_session(repo, session) if repo.is_dir() else []


def main() -> int:
    try:
        payload: Any = json.load(sys.stdin)
        released: list[str] = run(payload) if isinstance(payload, dict) else []
    except Exception:  # noqa: BLE001 - SessionEnd must never fail
        return 0
    print(json.dumps({"released": released}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
