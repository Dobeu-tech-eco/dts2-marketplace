"""Branch-name planning and the collision check against existing refs."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Final

from proc import EXIT_NOT_FOUND

from .common import BRANCH_PREFIX, GIT_VERSION, HEAD_NAME, LANE_PREFIX, MIN_GIT, STEP_PREFIX, binary, run

GH_TRIES: Final[int] = 3  # one try and two retries: a flaky gh gets a second chance, a missing one fails the same way each time
GH_RETRY_WAIT_S: Final[float] = 0.4
PR_FIELDS: Final[str] = "number,state,mergedAt,headRefOid,url"
PR_STATE_OPEN: Final[str] = "OPEN"
PR_STATE_MERGED: Final[str] = "MERGED"


def head_ref(stamp: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{HEAD_NAME}"


def lane_ref(stamp: str, lane_id: str) -> str:
    return f"{BRANCH_PREFIX}/{stamp}/{LANE_PREFIX}{lane_id}"


def step_ref(stamp: str, step: str) -> str:
    """The branch a standalone autopilot step builds on: dts2/<stamp>/step-<step>."""
    return f"{BRANCH_PREFIX}/{stamp}/{STEP_PREFIX}{step}"


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


def gh_json(args: list[str], cwd: Path, sleep: Callable[[float], None] = time.sleep) -> tuple[Any, str | None]:
    """(parsed JSON, None), or (None, why) once GH_TRIES attempts failed. A gh that is not installed is not retried: it
    would fail the same way. Callers that must not guess (lease, plan, reconcile) treat the failure as closed."""
    why: str = "gh did not answer"
    for attempt in range(GH_TRIES):
        code, out = run([*binary("DTS2_GH_BIN", "gh"), *args], cwd)
        if code == EXIT_NOT_FOUND:
            return None, f"gh is not installed ({out.strip()})"
        if code == 0:
            try:
                return json.loads(out or "[]"), None
            except ValueError:
                why = "gh printed output that is not JSON"
        else:
            why = f"gh {' '.join(args[:2])} exited {code}"
        if attempt < GH_TRIES - 1:
            sleep(GH_RETRY_WAIT_S)
    return None, why


def branch_prs(cwd: Path, branch: str, sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Every PR (open, merged or closed) whose head is `branch`, newest first; (None, why) when GitHub could not be asked."""
    data, why = gh_json(["pr", "list", "--head", branch, "--state", "all", "--json", PR_FIELDS, "--limit", "10"], cwd, sleep)
    if why is not None:
        return None, why
    if not isinstance(data, list):
        return None, "gh pr list did not return a list"
    prs: list[dict[str, Any]] = [pr for pr in data if isinstance(pr, dict)]
    return sorted(prs, key=lambda pr: int(pr.get("number") or 0), reverse=True), None


def gh_down(command: str) -> str:
    """The refusal a command that needs the open-PR check gives when gh could not answer."""
    return (f"gh is unavailable, so open PRs could not be checked; {command} fails closed. Fix gh, or pass --no-prs "
            "to skip the check on purpose")
