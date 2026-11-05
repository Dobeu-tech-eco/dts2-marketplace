"""G-44, G-45, G-48, G-49: the head/son mailbox. Messages are small versioned JSON files in the lane's run dir (the absolute
path the head hands the son, G-42): `questions/` (a question or a need-human), `answers/`, `requests/` (out-of-lane),
`send-back-<n>.json` and `merge-go.json`. Every wait has a deadline and a defined park transition when it runs out."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Final

from state_io import atomic_write

from .common import (
    DEFAULT_WAIT_MIN, LEASE_NAME, MERGE_GO_JSON_NAME, MESSAGE_VERSION, PHASE_INCOMPLETE, PLUGIN_ROOT, SECONDS_PER_MINUTE, WAIT_FIELD,
    LaneError, binary, run,
)
from .leases import lease_epoch, read_lease, stale_epoch
from .phases import lane_path, transition
from .planner import read_setting
from .records import inside_son, son_refusal

QUESTIONS_DIR: Final[str] = "questions"
ANSWERS_DIR: Final[str] = "answers"
REQUESTS_DIR: Final[str] = "requests"
KIND_QUESTION: Final[str] = "question"
KIND_NEED_HUMAN: Final[str] = "need-human"
ID_PREFIX: Final[dict[str, str]] = {KIND_QUESTION: "q", KIND_NEED_HUMAN: "h"}
STATE_ANSWERED: Final[str] = "answered"
STATE_WAITING: Final[str] = "waiting"
STATE_EXPIRED: Final[str] = "expired"
POLL_S: Final[float] = 2.0
REASON_MAILBOX_TIMEOUT: Final[str] = "mailbox-timeout"
# Why a son parks itself (G-45): the pool of agent seats collapsed, the context guard fired, a walkthrough needs a browser
# and none exists (a park, never a skip), a wait ran out.
PARK_REASONS: Final[tuple[str, ...]] = ("seat-pool-collapse", "context-guard", "no-browser", REASON_MAILBOX_TIMEOUT)
ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z][0-9]{1,6}")
# G-48: a request to touch files outside the lane climbs this ladder, one rung at a time; only the user ends it.
OUT_OF_LANE_ROUTE: Final[tuple[str, ...]] = ("head", "vote", "council", "user")
# G-49: the rule files a son re-reads at start and before each vote, ship and merge (paths under the plugin root).
RULE_SOURCES: Final[tuple[str, ...]] = ("templates/discipline.md", "skills/run/*.md", "skills/ship/SKILL.md", "agents/*.md")
RULES_NAME: Final[str] = "rules.json"
RULE_POINTS: Final[tuple[str, ...]] = ("start", "vote", "ship", "merge")
SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{7,40}$")


def lane_dir(runs_dir: Path, stamp: str, lane_id: str) -> Path:
    return lane_path(runs_dir, stamp, lane_id).parent


def read_message(path: Path) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_message(path: Path, message: dict[str, Any]) -> None:
    atomic_write(path, json.dumps({"v": MESSAGE_VERSION, **message}, indent=2) + "\n")


def lane_epoch(folder: Path) -> int:
    return lease_epoch(read_lease(folder / LEASE_NAME))


def wait_seconds(cwd: Path) -> int:
    """The deadline of every mailbox wait: `mailbox_wait_min` (default DEFAULT_WAIT_MIN) in minutes."""
    raw: str = read_setting(cwd, WAIT_FIELD, str(DEFAULT_WAIT_MIN))
    return (int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_WAIT_MIN) * SECONDS_PER_MINUTE


def next_id(folder: Path, kind: str) -> str:
    prefix: str = ID_PREFIX[kind]
    return f"{prefix}{len(list((folder / QUESTIONS_DIR).glob(f'{prefix}*.json'))) + 1}"


def ask(runs_dir: Path, stamp: str, lane_id: str, text: str, cwd: Path, *, kind: str = KIND_QUESTION,
        epoch: int | None = None, now: int | None = None) -> dict[str, Any]:
    """A son's question to the head (or, for `need-human`, what it would have put to the user: a son never prompts a person).
    Writes `questions/<id>.json` (id, lane, epoch, deadline) and a readable `<id>.md`; the deadline is what `check` enforces."""
    if kind not in ID_PREFIX:
        raise LaneError(f"kind must be one of {', '.join(ID_PREFIX)}")
    folder: Path = lane_dir(runs_dir, stamp, lane_id)
    asked: int = int(time.time()) if now is None else now
    qid: str = next_id(folder, kind)
    message: dict[str, Any] = {"kind": kind, "id": qid, "lane": lane_id, "epoch": lane_epoch(folder) if epoch is None else epoch,
                               "text": text, "asked": asked, "deadline": asked + wait_seconds(cwd)}
    write_message(folder / QUESTIONS_DIR / f"{qid}.json", message)
    atomic_write(folder / QUESTIONS_DIR / f"{qid}.md", f"# {kind} {qid} from lane {lane_id}\n\n{text}\n")
    return {"ok": True, "id": qid, "kind": kind, "deadline": message["deadline"], "path": str(folder / QUESTIONS_DIR / f"{qid}.json")}


def answer(runs_dir: Path, stamp: str, lane_id: str, qid: str, text: str) -> dict[str, Any]:
    """The head's answer to one question; stamped with the lane's current epoch. A son never answers."""
    if inside_son():
        return {**son_refusal("answering a question"), "lane": lane_id}
    if ID_PATTERN.fullmatch(qid) is None:
        raise LaneError(f"not a message id: {qid!r}")
    folder: Path = lane_dir(runs_dir, stamp, lane_id)
    if not (folder / QUESTIONS_DIR / f"{qid}.json").is_file():
        return {"ok": False, "lane": lane_id, "id": qid, "detail": f"no question {qid} in lane {lane_id}'s mailbox"}
    write_message(folder / ANSWERS_DIR / f"{qid}.json", {"kind": "answer", "id": qid, "lane": lane_id, "epoch": lane_epoch(folder),
                                                          "text": text, "answered": int(time.time())})
    return {"ok": True, "lane": lane_id, "id": qid}


def check(runs_dir: Path, stamp: str, lane_id: str, qid: str, *, now: int | None = None) -> dict[str, Any]:
    """Where a question stands: answered, waiting, or expired. An answer written for an older epoch than the lane's is
    ignored. Past the deadline the lane parks (`incomplete`, reason `mailbox-timeout`) through `transition`: the defined end of a wait."""
    if ID_PATTERN.fullmatch(qid) is None:
        raise LaneError(f"not a message id: {qid!r}")
    folder: Path = lane_dir(runs_dir, stamp, lane_id)
    question: dict[str, Any] | None = read_message(folder / QUESTIONS_DIR / f"{qid}.json")
    if question is None:
        return {"ok": False, "lane": lane_id, "id": qid, "state": "unknown", "detail": f"no question {qid}"}
    reply: dict[str, Any] | None = read_message(folder / ANSWERS_DIR / f"{qid}.json")
    if reply is not None and not stale_epoch(int(reply.get("epoch", 0)), lane_epoch(folder)):
        return {"ok": True, "lane": lane_id, "id": qid, "state": STATE_ANSWERED, "text": reply.get("text", "")}
    clock: int = int(time.time()) if now is None else now
    if clock < int(question.get("deadline", 0)):
        return {"ok": True, "lane": lane_id, "id": qid, "state": STATE_WAITING, "left_s": int(question["deadline"]) - clock}
    moved: dict[str, Any] = transition(runs_dir, stamp, lane_id, PHASE_INCOMPLETE, reason=REASON_MAILBOX_TIMEOUT,
                                       extra={"waiting_on": qid}, now=clock)
    return {"ok": True, "lane": lane_id, "id": qid, "state": STATE_EXPIRED, "parked": bool(moved.get("ok")),
            "reason": REASON_MAILBOX_TIMEOUT}


def wait(runs_dir: Path, stamp: str, lane_id: str, qid: str, *, sleep: Any = time.sleep) -> dict[str, Any]:
    """Block until the question is answered or its deadline parks the lane; polls `check` every POLL_S seconds."""
    while True:
        state: dict[str, Any] = check(runs_dir, stamp, lane_id, qid)
        if state.get("state") != STATE_WAITING:
            return state
        sleep(POLL_S)


def park(runs_dir: Path, stamp: str, lane_id: str, reason: str, session_id: str | None = None,
         epoch: int | None = None) -> dict[str, Any]:
    """A son parks itself: `incomplete` with a reason from PARK_REASONS, and the session id so the head can resume it."""
    if reason not in PARK_REASONS:
        raise LaneError(f"reason must be one of {', '.join(PARK_REASONS)}")
    extra: dict[str, Any] = {"session_id": session_id} if session_id else {}
    return transition(runs_dir, stamp, lane_id, PHASE_INCOMPLETE, reason=reason, extra=extra, epoch=epoch)


def head_sha(worktree: Path) -> str | None:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", "HEAD"], worktree)
    return out.strip() if code == 0 and SHA_PATTERN.match(out.strip()) else None


def merge_go_check(runs_dir: Path, stamp: str, lane_id: str, worktree: Path) -> dict[str, Any]:
    """The son's side of merge-go: refuse unless the payload is for this lane and epoch and the worktree's HEAD is exactly the
    `verified_head_sha` the head cleared (a commit made after the head verified voids the grant)."""
    folder: Path = lane_dir(runs_dir, stamp, lane_id)
    payload: dict[str, Any] | None = read_message(folder / MERGE_GO_JSON_NAME)
    if payload is None:
        return {"ok": False, "lane": lane_id, "detail": "no merge-go payload; wait for the head's grant"}
    if payload.get("lane") != lane_id or stale_epoch(int(payload.get("epoch", 0)), lane_epoch(folder)):
        return {"ok": False, "lane": lane_id, "detail": "the merge-go payload is for another lane or an older epoch"}
    verified: str = str(payload.get("verified_head_sha", ""))
    current: str | None = head_sha(worktree)
    if current is None or not verified or not (current.startswith(verified) or verified.startswith(current)):
        return {"ok": False, "lane": lane_id, "verified_head_sha": verified, "head": current,
                "detail": "HEAD differs from verified_head_sha; the grant is void until the head verifies the new HEAD"}
    return {"ok": True, "lane": lane_id, "verified_head_sha": verified, "base_sha": payload.get("base_sha"),
            "epoch": payload.get("epoch")}


def request_out_of_lane(runs_dir: Path, stamp: str, lane_id: str, files: list[str], reason: str,
                        epoch: int | None = None) -> dict[str, Any]:
    """G-48: a son asks to change files outside its lane. It starts at the head and climbs head -> vote -> council -> user."""
    folder: Path = lane_dir(runs_dir, stamp, lane_id)
    rid: str = f"r{len(list((folder / REQUESTS_DIR).glob('r*.json'))) + 1}"
    write_message(folder / REQUESTS_DIR / f"{rid}.json", {"kind": "out-of-lane", "id": rid, "lane": lane_id, "files": files,
                                                           "reason": reason, "epoch": lane_epoch(folder) if epoch is None else epoch,
                                                           "stage": OUT_OF_LANE_ROUTE[0], "outcome": None})
    return {"ok": True, "lane": lane_id, "id": rid, "stage": OUT_OF_LANE_ROUTE[0]}


def advance_request(runs_dir: Path, stamp: str, lane_id: str, rid: str, outcome: str) -> dict[str, Any]:
    """Head only. `escalate` moves the request one rung up; `granted` or `denied` closes it. Nothing skips a rung, and the
    user's rung is the last: it can be granted or denied there, not escalated further."""
    if inside_son():
        return {**son_refusal("deciding an out-of-lane request"), "lane": lane_id}
    path: Path = lane_dir(runs_dir, stamp, lane_id) / REQUESTS_DIR / f"{rid}.json"
    request: dict[str, Any] | None = read_message(path) if ID_PATTERN.fullmatch(rid) else None
    if request is None or request.get("outcome"):
        return {"ok": False, "lane": lane_id, "id": rid, "detail": "no open request with that id"}
    stage: str = str(request["stage"])
    if outcome == "escalate":
        if stage == OUT_OF_LANE_ROUTE[-1]:
            return {"ok": False, "lane": lane_id, "id": rid, "stage": stage, "detail": "the user is the last rung; grant or deny"}
        request = {**request, "stage": OUT_OF_LANE_ROUTE[OUT_OF_LANE_ROUTE.index(stage) + 1]}
    elif outcome in ("granted", "denied"):
        request = {**request, "outcome": outcome, "decided_at": stage}
    else:
        raise LaneError("outcome must be escalate, granted or denied")
    write_message(path, request)
    return {"ok": True, "lane": lane_id, "id": rid, "stage": request["stage"], "outcome": request["outcome"]}


def rule_files(root: Path = PLUGIN_ROOT) -> list[Path]:
    return sorted({f for pattern in RULE_SOURCES for f in root.glob(pattern) if f.is_file()})


def rules_digest(root: Path = PLUGIN_ROOT) -> dict[str, str]:
    """File (relative to the plugin root) -> sha256 of its bytes, for every rule source (G-49)."""
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in rule_files(root)}


def check_rules(runs_dir: Path, stamp: str, lane_id: str, point: str, root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    """A son calls this at start and before each vote, ship and merge. It returns the rule files that changed since its last
    call (all of them at `start`), so it re-reads exactly those; the new digest becomes the baseline."""
    if point not in RULE_POINTS:
        raise LaneError(f"point must be one of {', '.join(RULE_POINTS)}")
    path: Path = lane_dir(runs_dir, stamp, lane_id) / RULES_NAME
    now: dict[str, str] = rules_digest(root)
    before: dict[str, str] = (read_message(path) or {}).get("files", {}) if point != "start" else {}
    changed: list[str] = sorted(f for f in {*now, *before} if now.get(f) != before.get(f))
    write_message(path, {"kind": "rules", "files": now, "point": point, "at": int(time.time())})
    return {"ok": True, "lane": lane_id, "point": point, "changed": changed, "reread": bool(changed), "files": len(now)}
