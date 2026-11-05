"""Shared ownership audit (G-24, AA-1): did a builder stay inside its owned files and report the real HEAD?

Pure functions, no I/O. `scripts/builder-audit.py` is the thin CLI for the run flow and `lanes.py audit` calls
`audit()` for lane branches, so both gates agree on what counts as a violation."""
from __future__ import annotations

import fnmatch
from typing import Final, Iterable

EMPTY_DIFF: Final[str] = "empty_diff"
OUTSIDE_OWNED: Final[str] = "outside_owned"
CLAIMED_NOT_HEAD: Final[str] = "claimed_not_head"
DONE_STATUS: Final[str] = "DONE"
MAX_REDISPATCH: Final[int] = 1
STATUS_PREFIX: Final[int] = 3  # "XY " before the path
RENAME_CODES: Final[str] = "RC"
GLOB_CHARS: Final[tuple[str, ...]] = ("*", "?", "[")


def is_owned(path: str, owned: Iterable[str]) -> bool:
    """True when `path` is an owned file, sits under an owned `dir/` prefix, or matches an owned glob."""
    for entry in owned:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif any(ch in entry for ch in GLOB_CHARS):
            if fnmatch.fnmatchcase(path, entry):
                return True
        elif path == entry:
            return True
    return False


def parse_status_z(raw: str) -> list[str]:
    """Paths from `git status --porcelain -z --untracked-files=all`. A rename or copy entry (`R`/`C` in either column) is followed by
    its source path as a separate field; both the new and the old path count, so a rename cannot hide a file outside the owned set."""
    fields: list[str] = raw.split("\0")
    paths: list[str] = []
    index: int = 0
    while index < len(fields):
        entry: str = fields[index]
        index += 1
        if len(entry) < STATUS_PREFIX:
            continue
        paths.append(entry[STATUS_PREFIX:])
        if (entry[0] in RENAME_CODES or entry[1] in RENAME_CODES) and index < len(fields) and fields[index]:
            paths.append(fields[index])
            index += 1
    return paths


def same_commit(claimed: str, head: str) -> bool:
    """A claimed sha matches HEAD when one is a prefix of the other (short shas are fine)."""
    claimed = claimed.strip().lower()
    head = head.strip().lower()
    return bool(claimed) and bool(head) and (head.startswith(claimed) or claimed.startswith(head))


def audit(
    diff: Iterable[str],
    owned: Iterable[str],
    claimed_sha: str | None,
    head: str | None = None,
    status: str = DONE_STATUS,
) -> dict[str, object]:
    """Check a builder's result. `diff` is the changed paths since the builder's base, `claimed_sha` the commit
    it reported (None skips that check), `head` the current HEAD of its checkout.

    Fails on: an empty diff while the status is DONE, any changed file outside the owned set, a claimed commit
    that is not HEAD."""
    changed: list[str] = sorted({p for p in diff if p})
    owned_list: list[str] = list(owned)
    violations: list[dict[str, str]] = []
    if not changed and status.upper() == DONE_STATUS:
        violations.append({"code": EMPTY_DIFF, "detail": "reported DONE but the diff is empty"})
    outside: list[str] = [p for p in changed if not is_owned(p, owned_list)]
    if outside:
        violations.append({"code": OUTSIDE_OWNED, "detail": "outside the owned set: " + ", ".join(outside)})
    if claimed_sha and head is not None and not same_commit(claimed_sha, head):
        violations.append({"code": CLAIMED_NOT_HEAD, "detail": f"claimed {claimed_sha} but HEAD is {head}"})
    return {"ok": not violations, "violations": violations, "changed": changed}


def next_action(result: dict[str, object], redispatches: int) -> str:
    """accept a clean result; re-dispatch the builder once on a violation; after that mark the section blocked."""
    if result["ok"]:
        return "accept"
    return "redispatch" if redispatches < MAX_REDISPATCH else "blocked"
