#!/usr/bin/env python3
"""Loop guard for unattended fullauto: decides, between passes, whether the outer loop may go on.

`check` stops on the kill-switch (a STOP file in the harness state dir, or an open PR labelled `dts2:stop`) and on the
budget (`loop.max_passes`, `loop.max_hours`). `record` appends one pass to a progress ledger and answers `stall` when
the progress hash did not change for `loop.no_progress_limit` passes in a row (default 3) or the same failure signature
came back three times in a row. `park` and `sweep` keep the items the loop could not finish and list the ones whose
blocker is resolved so the loop can retry them. `notify` upserts one GitHub issue titled "dts2: needs you" through gh
(DTS2_GH_BIN overrides the binary) and always writes a local note; it never fails the loop. Prints one JSON object."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import miniyaml  # noqa: E402
import proc  # noqa: E402
import state_io  # noqa: E402
from state_io import append_text, atomic_write  # noqa: E402

CONFIG_FILE: Final[str] = state_io.CONFIG_REL
STOP_REL: Final[str] = state_io.rel("STOP")
LEDGER_REL: Final[str] = state_io.rel("loop", "progress.jsonl")
PARKED_REL: Final[str] = state_io.rel("loop", "parked.json")
MAILBOX_REL: Final[str] = state_io.rel("loop", "need-human.md")
STOP_LABEL: Final[str] = "dts2:stop"
ISSUE_TITLE: Final[str] = "dts2: needs you"
GH_ENV: Final[str] = "DTS2_GH_BIN"
NOW_ENV: Final[str] = "DTS2_LOOP_NOW"  # epoch seconds; lets a test or a replay pin the clock
GH_TIMEOUT_S: Final[int] = 30
DEFAULT_NO_PROGRESS: Final[int] = 3
DEFAULT_MAX_PASSES: Final[int] = 200
DEFAULT_MAX_HOURS: Final[float] = 24.0
SAME_SIGNATURE_LIMIT: Final[int] = 3
SIGNATURES_SHOWN: Final[int] = 5
SIGNATURE_CHARS: Final[int] = 300
VERDICT_CONTINUE: Final[str] = "continue"
VERDICT_STALL: Final[str] = "stall"
VERDICT_STOP: Final[str] = "stop"
EXIT_STOP: Final[int] = 2


def now() -> float:
    raw: str | None = os.environ.get(NOW_ENV)
    try:
        return float(raw) if raw else time.time()
    except ValueError:
        return time.time()


def read_config(repo: Path) -> dict[str, Any]:
    try:
        text: str = (repo / CONFIG_FILE).read_text(encoding="utf-8")
    except OSError:
        return {}
    return miniyaml.parse(text)


def limits(repo: Path) -> dict[str, Any]:
    config: dict[str, Any] = read_config(repo)
    hours: float = miniyaml.get_float(config, "loop.max_hours", DEFAULT_MAX_HOURS)
    return {
        "no_progress_limit": max(1, miniyaml.get_int(config, "loop.no_progress_limit", DEFAULT_NO_PROGRESS)),
        "max_passes": max(1, miniyaml.get_int(config, "loop.max_passes", DEFAULT_MAX_PASSES)),
        "max_hours": hours if hours > 0 else DEFAULT_MAX_HOURS,
    }


def normalise(signature: str) -> str:
    """One line, lower case, digits folded, so the same failure with another line number or id counts as the same."""
    text: str = " ".join(signature.lower().split())[:SIGNATURE_CHARS]
    return "".join("#" if char.isdigit() else char for char in text)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_ledger(repo: Path) -> list[dict[str, Any]]:
    try:
        lines: list[str] = (repo / LEDGER_REL).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row: Any = json.loads(line)
        except ValueError:
            continue  # a torn or foreign line is skipped, never fatal
        if isinstance(row, dict):
            rows.append(row)
    return rows


def gh(args: list[str], repo: Path) -> tuple[int, str]:
    return proc.run([*proc.binary(GH_ENV, "gh"), *args], repo, timeout_s=GH_TIMEOUT_S)


def stop_label_present(repo: Path) -> bool:
    """True when an open PR carries the `dts2:stop` label. A missing or failing gh counts as no label (soft)."""
    code, out = gh(["pr", "list", "--state", "open", "--label", STOP_LABEL, "--json", "number"], repo)
    if code != 0:
        return False
    try:
        found: Any = json.loads(out)
    except ValueError:
        return False
    return isinstance(found, list) and len(found) > 0


def budget_reason(repo: Path, ledger: list[dict[str, Any]], at: float) -> str:
    cap: dict[str, Any] = limits(repo)
    if len(ledger) >= cap["max_passes"]:
        return f"budget-passes: {len(ledger)} of {cap['max_passes']} passes used"
    started: float = float(ledger[0].get("ts", at)) if ledger else at
    if (at - started) / 3600.0 >= cap["max_hours"]:
        return f"budget-hours: {cap['max_hours']:g} hours used"
    return ""


def check(repo: Path) -> dict[str, Any]:
    """Kill-switch first, then the budget. `stop` true means the loop must end now."""
    if (repo / STOP_REL).exists():
        return {"ok": False, "stop": True, "verdict": "STOP", "reason": "stop-file", "detail": f"{STOP_REL} exists"}
    if stop_label_present(repo):
        return {"ok": False, "stop": True, "verdict": "STOP", "reason": "stop-label", "detail": f"an open PR carries {STOP_LABEL}"}
    spent: str = budget_reason(repo, read_ledger(repo), now())
    if spent:
        return {"ok": False, "stop": True, "verdict": "STOP", "reason": spent.split(":")[0], "detail": spent}
    return {"ok": True, "stop": False, "verdict": "OK"}


def tail_equal(values: list[str], count: int) -> bool:
    return len(values) >= count and len(set(values[-count:])) == 1


def record(repo: Path, signature: str, progress: str) -> dict[str, Any]:
    """Append one pass. The progress hash covers the text the loop passes (open items plus merged PRs); the chain value
    folds in the previous entry, so the ledger head moves on every pass and a damaged ledger is visible."""
    ledger: list[dict[str, Any]] = read_ledger(repo)
    at: float = now()
    cap: dict[str, Any] = limits(repo)
    sig: str = normalise(signature)
    progress_hash: str = digest(progress)
    previous: str = str(ledger[-1].get("chain", "")) if ledger else ""
    entry: dict[str, Any] = {"pass": len(ledger) + 1, "ts": at, "signature": sig, "progress": progress_hash,
                             "chain": digest(previous + progress_hash + sig + str(at))}
    append_text(repo / LEDGER_REL, json.dumps(entry, sort_keys=True) + "\n")
    ledger.append(entry)
    hashes: list[str] = [str(row.get("progress", "")) for row in ledger]
    signatures: list[str] = [str(row.get("signature", "")) for row in ledger]
    reasons: list[str] = []
    if tail_equal(hashes, cap["no_progress_limit"]):
        reasons.append(f"no-progress: {cap['no_progress_limit']} passes with the same progress hash")
    if sig and tail_equal(signatures, SAME_SIGNATURE_LIMIT):
        reasons.append(f"same-failure: {sig!r} {SAME_SIGNATURE_LIMIT} times in a row")
    spent: str = budget_reason(repo, ledger, at)
    verdict: str = VERDICT_STALL if reasons else (VERDICT_STOP if spent else VERDICT_CONTINUE)
    return {"ok": verdict == VERDICT_CONTINUE, "verdict": verdict, "pass": entry["pass"], "progress": progress_hash,
            "chain": entry["chain"], "reasons": reasons or ([spent] if spent else [])}


def read_parked(repo: Path) -> list[dict[str, Any]]:
    try:
        data: Any = json.loads((repo / PARKED_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in data if isinstance(row, dict) and "id" in row] if isinstance(data, list) else []


def write_parked(repo: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write(repo / PARKED_REL, json.dumps(rows, indent=2, sort_keys=True) + "\n")


def park(repo: Path, item: str, reason: str, blocker: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [row for row in read_parked(repo) if row["id"] != item]
    rows.append({"id": item, "reason": reason, "blocker": blocker, "parked_at": now()})
    write_parked(repo, rows)
    return {"ok": True, "parked": len(rows), "id": item}


def pr_resolved(repo: Path, number: str) -> bool:
    code, out = gh(["pr", "view", number, "--json", "state"], repo)
    if code != 0:
        return False
    try:
        return str(json.loads(out).get("state", "")).upper() in {"MERGED", "CLOSED"}
    except (ValueError, AttributeError):
        return False


def item_resolved(repo: Path, item_id: str) -> bool:
    try:
        ledger_module: Any = _load.load("task-ledger")
        rows: dict[str, dict[str, Any]] = ledger_module.read_items(repo, date.today())
        row: dict[str, Any] | None = rows.get(item_id)
        return row is not None and not _load.load("action-items").is_open(row["status"])
    except Exception:  # noqa: BLE001 - an unreadable items file means "not resolved", never a crash of the loop
        return False


def blocker_resolved(repo: Path, blocker: dict[str, str]) -> bool:
    kind: str = blocker.get("kind", "")
    ref: str = blocker.get("ref", "")
    if kind == "pr":
        return pr_resolved(repo, ref)
    if kind == "item":
        return item_resolved(repo, ref)
    if kind == "file":
        return (repo / ref).exists()
    return False  # no blocker named: only a human un-parks it


def sweep(repo: Path, release: bool) -> dict[str, Any]:
    parked: list[dict[str, Any]] = read_parked(repo)
    ready: list[dict[str, Any]] = [row for row in parked if blocker_resolved(repo, row.get("blocker") or {})]
    if release and ready:
        gone: set[str] = {row["id"] for row in ready}
        write_parked(repo, [row for row in parked if row["id"] not in gone])
    return {"ok": True, "ready": ready, "still_parked": len(parked) - len(ready), "released": bool(release and ready)}


def body_text(repo: Path, reason: str) -> str:
    parked: list[dict[str, Any]] = read_parked(repo)
    ledger: list[dict[str, Any]] = read_ledger(repo)
    signatures: list[str] = [str(row.get("signature", "")) for row in ledger if row.get("signature")]
    lines: list[str] = ["The unattended loop stopped and needs a person.", "", f"Reason: {reason or 'stall'}", "",
                        f"Passes recorded: {len(ledger)}", "", "Parked items:"]
    lines += [f"- {row['id']}: {row.get('reason', '')} (blocked by {(row.get('blocker') or {}).get('kind', 'unknown')} "
              f"{(row.get('blocker') or {}).get('ref', '')})".rstrip() for row in parked] or ["- none"]
    lines += ["", "Last failure signatures:"]
    lines += [f"- {sig}" for sig in signatures[-SIGNATURES_SHOWN:]] or ["- none"]
    lines += ["", "What is needed: clear the blockers above (merge or close the PR, answer the item, add the file), "
              f"remove {STOP_REL} if present, then restart the loop. The loop retries parked items once their blocker "
              "is resolved."]
    return "\n".join(lines) + "\n"


def find_open_issue(repo: Path) -> int | None:
    code, out = gh(["issue", "list", "--state", "open", "--search", f'"{ISSUE_TITLE}" in:title', "--json",
                    "number,title"], repo)
    if code != 0:
        return None
    try:
        for row in json.loads(out):
            if row.get("title") == ISSUE_TITLE:
                return int(row["number"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return None


def notify(repo: Path, reason: str) -> dict[str, Any]:
    """Upsert the single "needs you" issue; always write the local note. Soft: a gh failure is reported, not raised."""
    body: str = body_text(repo, reason)
    atomic_write(repo / MAILBOX_REL, f"# {ISSUE_TITLE}\n\n{body}")
    number: int | None = find_open_issue(repo)
    if number is not None:
        code, _ = gh(["issue", "comment", str(number), "--body", body], repo)
        action: str = "commented" if code == 0 else "failed"
    else:
        code, _ = gh(["issue", "create", "--title", ISSUE_TITLE, "--body", body], repo)
        action = "created" if code == 0 else "failed"
    return {"ok": True, "issue": action, "number": number, "mailbox": MAILBOX_REL}


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--repo", default=".", help="the repo whose .harness/ holds the loop state")
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="exit 2 and print STOP when the kill-switch is set or the budget is spent")
    rec = sub.add_parser("record", help="append one pass; verdict continue, stall or stop")
    rec.add_argument("--signature", default="", help="short text naming this pass's failure, empty when it passed")
    rec.add_argument("--progress", required=True, help="text that changes when work gets done: open items + merged PRs")
    pk = sub.add_parser("park", help="park an item the loop cannot finish")
    pk.add_argument("--id", required=True)
    pk.add_argument("--reason", required=True)
    group = pk.add_mutually_exclusive_group()
    group.add_argument("--blocker-pr")
    group.add_argument("--blocker-item")
    group.add_argument("--blocker-file")
    sw = sub.add_parser("sweep", help="list parked items whose blocker is resolved")
    sw.add_argument("--release", action="store_true", help="also remove them from the parked list")
    nt = sub.add_parser("notify", help="upsert the 'dts2: needs you' issue and write the local note")
    nt.add_argument("--reason", default="")
    return top


def main() -> int:
    args = parser().parse_args()
    repo: Path = Path(args.repo)
    result: dict[str, Any]
    code: int = 0
    if args.command == "check":
        result = check(repo)
        if result["stop"]:
            print(f"STOP {result['reason']}: {result['detail']}", file=sys.stderr)
            code = EXIT_STOP
    elif args.command == "record":
        result = record(repo, args.signature, args.progress)
        code = 0 if result["verdict"] == VERDICT_CONTINUE else EXIT_STOP
    elif args.command == "park":
        blocker: dict[str, str] = {}
        for kind, ref in (("pr", args.blocker_pr), ("item", args.blocker_item), ("file", args.blocker_file)):
            if ref:
                blocker = {"kind": kind, "ref": ref}
        result = park(repo, args.id, args.reason, blocker)
    elif args.command == "sweep":
        result = sweep(repo, args.release)
    else:
        result = notify(repo, args.reason)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
