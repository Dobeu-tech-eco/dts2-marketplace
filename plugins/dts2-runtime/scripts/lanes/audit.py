"""Lane ownership audit: did the lane's branch change only files its manifest entry owns?"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import ownership_audit

from .common import binary, find_lane, lane_files, run

SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{7,40}$")
MERGE_STATUS: Final[str] = "MERGE"  # any status but DONE: an empty diff is not an ownership violation


def changed_paths(cwd: Path, base: str, head: str) -> tuple[list[str] | None, str]:
    """(paths changed on `head` since it left `base`, "") or (None, why git failed)."""
    # --no-renames: a rename shows as a delete of the old path plus an add of the new one, so both are audited
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "diff", "--name-only", "--no-renames", f"{base}...{head}"], cwd)
    if code != 0:
        return None, f"git diff --name-only {base}...{head} exited {code}"
    return [line for line in out.splitlines() if line.strip()], ""


def lane_audit(manifest: dict[str, Any], lane_id: str, head: str, base: str, cwd: Path) -> dict[str, Any]:
    """Audit lane `lane_id` (the integration lane against its integration files, which its manifest entry lists as `files`)
    over `base...head`. Fails closed: a bad sha or a git failure is `ok: False` with a `detail`."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    if not head or head.startswith("-") or not SHA_PATTERN.match(base):
        return {"ok": False, "lane": lane_id, "violations": [], "changed": [], "detail": "head must be a commit and base a commit sha"}
    changed, why = changed_paths(cwd, base, head)
    if changed is None:
        return {"ok": False, "lane": lane_id, "violations": [], "changed": [], "detail": why}
    result: dict[str, Any] = ownership_audit.audit(changed, sorted(lane_files(lane)), None, head=head,
                                                   status=MERGE_STATUS)
    return {"ok": bool(result["ok"]), "lane": lane_id, "violations": result["violations"], "changed": result["changed"]}
