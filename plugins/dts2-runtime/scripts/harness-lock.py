#!/usr/bin/env python3
"""Lock a shared .harness record for one writer. Only a head may lock shared records; sons write their run dir only."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Final

SHARED_FILES: Final[tuple[str, ...]] = (
    ".harness/state.md", ".harness/action-items.md", ".harness/council.md", ".harness/lessons.md",
    ".harness/end-state.md", ".harness/handoff/latest.md", ".harness/autopilot/latest.md",
)
RUN_DIR_PREFIX: Final[str] = ".harness/runs/"
ROLE_HEAD: Final[str] = "head"
ROLE_SON: Final[str] = "son"
ACTIONS: Final[tuple[str, ...]] = ("acquire", "release", "check")
DEFAULT_TTL_SEC: Final[int] = 1800
LOCK_SUBDIR: Final[str] = "dts2-locks"
FALLBACK_LOCK_DIR: Final[str] = ".harness/.locks"
SON_REASON: Final[str] = "son may not write shared records; write under .harness/runs/<stamp>/<lane>/ only"
RECLAIMED: Final[str] = "reclaimed stale lock"


def default_lock_dir() -> Path:
    """Shared across worktrees: <git-common-dir>/dts2-locks. Without git, .harness/.locks."""
    try:
        common: str = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True,
                                     check=True).stdout.strip()
        return Path(common).resolve() / LOCK_SUBDIR
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path(FALLBACK_LOCK_DIR)


def lock_path(lock_dir: Path, shared: str) -> Path:
    return lock_dir / (shared.strip("/").replace("/", "__") + ".lock")


def is_shared(shared: str) -> bool:
    normalized: str = shared.strip("/")
    return normalized in SHARED_FILES or not normalized.startswith(RUN_DIR_PREFIX)


def role_allowed(role: str, shared: str) -> str | None:
    """None when allowed, else the refusal reason."""
    if role == ROLE_SON and is_shared(shared):
        return SON_REASON
    return None


def read_lock(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_stale(record: dict[str, Any] | None, ttl_sec: int) -> bool:
    created: Any = (record or {}).get("created", 0)
    return not isinstance(created, (int, float)) or time.time() - created > ttl_sec


def try_create(path: Path, holder: str) -> bool:
    """Exclusive create with the record already in place: write a temp file, then os.link it to the lock path.

    os.link fails if the path exists, so a concurrent holder is never replaced and no empty-file window exists.
    """
    record: dict[str, Any] = {"holder": holder, "pid": os.getpid(), "created": time.time()}
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_name, path)
    except FileExistsError:
        return False
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return True


def acquire(path: Path, holder: str, ttl_sec: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if try_create(path, holder):
        return {"ok": True, "holder": holder, "reason": None}
    current: dict[str, Any] | None = read_lock(path)
    if not is_stale(current, ttl_sec):
        return {"ok": False, "holder": (current or {}).get("holder"), "reason": "held"}
    path.unlink(missing_ok=True)
    created: bool = try_create(path, holder)
    return {"ok": created, "holder": holder if created else None, "reason": RECLAIMED if created else "held"}


def release(path: Path, holder: str) -> dict[str, Any]:
    current: dict[str, Any] | None = read_lock(path)
    if current is None:
        return {"ok": True, "holder": None, "reason": "not held"}
    if current.get("holder") != holder:
        return {"ok": False, "holder": current.get("holder"), "reason": "held by another"}
    path.unlink(missing_ok=True)
    return {"ok": True, "holder": holder, "reason": None}


def check(path: Path, holder: str, ttl_sec: int) -> dict[str, Any]:
    current: dict[str, Any] | None = read_lock(path)
    free: bool = current is None or is_stale(current, ttl_sec) or current.get("holder") == holder
    return {"ok": free, "holder": (current or {}).get("holder", holder), "reason": None if free else "held"}


def perform(args: argparse.Namespace) -> dict[str, Any]:
    refusal: str | None = role_allowed(args.role, args.file)
    if refusal is not None:
        return {"ok": False, "holder": args.holder, "reason": refusal}
    path: Path = lock_path(Path(args.lock_dir) if args.lock_dir else default_lock_dir(), args.file)
    if args.action == "acquire":
        return acquire(path, args.holder, args.ttl_sec)
    if args.action == "release":
        return release(path, args.holder)
    return check(path, args.holder, args.ttl_sec)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--file", required=True, help="repo-relative shared record, e.g. .harness/state.md")
    parser.add_argument("--holder", required=True)
    parser.add_argument("--role", choices=(ROLE_HEAD, ROLE_SON), default=ROLE_HEAD)
    parser.add_argument("--ttl-sec", type=int, default=DEFAULT_TTL_SEC)
    parser.add_argument("--lock-dir", default=None)
    return parser


def main() -> int:
    args: argparse.Namespace = build_parser().parse_args()
    result: dict[str, Any] = perform(args)
    result["file"] = args.file
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
