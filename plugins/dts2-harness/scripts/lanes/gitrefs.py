"""Branch-name planning and the collision check against existing refs."""
from __future__ import annotations

from pathlib import Path
from typing import Any


from .common import BRANCH_PREFIX, GIT_VERSION, HEAD_NAME, LANE_PREFIX, MIN_GIT, binary, run


def head_ref(stamp: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{HEAD_NAME}"


def lane_ref(stamp: str, lane_id: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{LANE_PREFIX}{lane_id}"


def planned_refs(stamp: str, lanes: list[str]) -> list[str]:
    return [head_ref(stamp), *(lane_ref(stamp, lane_id) for lane_id in lanes)]


def git_version_error(cwd: Path) -> str | None:
    """None when git is at least MIN_GIT, else why not. Fails closed on output it cannot parse."""
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "--version"], cwd)
    match = GIT_VERSION.search(out) if code == 0 else None
    need: str = ".".join(str(part) for part in MIN_GIT)
    if match is None:
        return f"cannot read the git version; git merge-tree --write-tree needs git {need} or newer"
    found: tuple[int, int] = (int(match.group(1)), int(match.group(2)))
    if found < MIN_GIT:
        return (f"git {match.group(1)}.{match.group(2)} found; git merge-tree --write-tree needs git {need} "
                f"or newer")
    return None


def existing_refs(cwd: Path) -> list[str]:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "for-each-ref", "--format=%(refname:short)", "refs/heads",
                     "refs/remotes"], cwd)
    if code != 0:
        return []
    return [line.split("/", 1)[1] if line.startswith("origin/") else line for line in out.splitlines() if line.strip()]


def ref_collides(planned: str, existing: str) -> bool:
    return planned == existing or existing.startswith(planned + "/") or planned.startswith(existing + "/")


def branch_check(stamp: str, lanes: list[str], cwd: Path) -> dict[str, Any]:
    version_error: str | None = git_version_error(cwd)
    if version_error is not None:
        return {"ok": False, "planned": [], "collisions": [], "error": version_error}
    planned: list[str] = planned_refs(stamp, lanes)
    present: list[str] = existing_refs(cwd)
    collisions: list[dict[str, str]] = [
        {"planned": p, "existing": e, "detail": "a ref cannot be both a branch and a directory of branches"}
        for p in planned for e in present if ref_collides(p, e)
    ]
    return {"ok": not collisions, "planned": planned, "collisions": collisions}
