#!/usr/bin/env python3
"""pr-sweep helpers: the PR inventory, the bucket classifier, the merge order and the run ledger and report.

Every subcommand prints one JSON object.
  inventory --repo OWNER/NAME [--stale-days N] [--head-prefix P] [--author A] --out DIR   read-only `gh api` REST inventory
  classify  --inventory FILE [--now ISO]                                                     bucket per PR, stale flag, overlaps, candidates
  order     --inventory FILE [--now ISO]                                                     merge waves: stack bases first, shared files one at a time
  record    --dir DIR --pr N --bucket B --action A [--sha S] [--reason R] [--ci V] [--worker M] [--verified-by W]
  report    --dir DIR                                                                        write report.md from DIR/ledger.jsonl
gh runs through DTS2_GH_BIN. Every gh call goes through `gh_api`."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proc import binary  # noqa: E402

ENCODING: Final[str] = "utf-8"
EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 2
GH_TIMEOUT_SECONDS: Final[int] = 120
DEFAULT_STALE_DAYS: Final[int] = 3
PER_PAGE: Final[int] = 100
INVENTORY_JSON: Final[str] = "inventory.json"
INVENTORY_MD: Final[str] = "inventory.md"
LEDGER: Final[str] = "ledger.jsonl"
REPORT: Final[str] = "report.md"

GREEN: Final[str] = "GREEN"
NEEDS_REBASE: Final[str] = "NEEDS_REBASE"
CI_RED: Final[str] = "CI_RED"
STACKED: Final[str] = "STACKED"
DRAFT: Final[str] = "DRAFT"
PENDING: Final[str] = "PENDING"
BUCKETS: Final[tuple[str, ...]] = (GREEN, NEEDS_REBASE, CI_RED, STACKED, DRAFT, PENDING)

PASSING: Final[frozenset[str]] = frozenset({"success", "neutral", "skipped"})
FAILING: Final[frozenset[str]] = frozenset({"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"})
CLEAN_STATES: Final[frozenset[str]] = frozenset({"clean", "unstable", "has_hooks"})
REBASE_STATES: Final[frozenset[str]] = frozenset({"dirty", "behind"})

SHARED_NAMES: Final[tuple[str, ...]] = (
    "CHANGELOG*", "plugin.json", "package.json", "pyproject.toml", "INVENTORY.md", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock", "Gemfile.lock", "go.sum", "composer.lock")
SHARED_DIRS: Final[tuple[str, ...]] = ("changelog.d/",)
NEEDS_ME_PATHS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\.github/workflows/"),
    re.compile(r"(^|/)(\.env[^/]*|secrets?[^/]*|credentials?[^/]*|id_rsa[^/]*|[^/]*\.pem|[^/]*\.key|[^/]*\.p12)$", re.IGNORECASE),
    re.compile(r"(^|/)(release|releases|publish|deploy)[^/]*$", re.IGNORECASE),
    re.compile(r"(^|/)(\.git/refs/tags|tags?)(/|$)"),
)
REPO_NAME: Final[re.Pattern[str]] = re.compile(r"^[\w.-]+/[\w.-]+$")

# Report actions.
MERGED: Final[str] = "merged"
CLOSED: Final[str] = "closed"
WAITING: Final[str] = "waiting"
BRANCH_KEPT: Final[str] = "branch-kept"
NEEDS_ME: Final[str] = "H"


class GhError(RuntimeError):
    """A gh call failed (non-zero exit, bad JSON, timeout)."""


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed: datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---- gh ------------------------------------------------------------------------------------------------------------

def run_gh(args: list[str]) -> str:
    try:
        done = subprocess.run([*binary("DTS2_GH_BIN", "gh"), *args], capture_output=True, text=True,
                              timeout=GH_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhError(str(exc)) from exc
    if done.returncode != 0:
        raise GhError((done.stderr or done.stdout).strip()[:500])
    return done.stdout


def split_json(text: str) -> list[Any]:
    """All JSON values in `text`; `gh api --paginate` prints one document per page."""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index: int = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        value, index = decoder.raw_decode(text, index)
        values.append(value)
    return values


def gh_api(path: str, paginate: bool = False) -> Any:
    """The one gh entry point (REST only). A paginated list comes back as one list; a paginated object keeps its first page."""
    args: list[str] = ["api", path] + (["--paginate"] if paginate else [])
    try:
        pages: list[Any] = split_json(run_gh(args))
    except json.JSONDecodeError as exc:
        raise GhError(f"bad JSON from gh api {path}: {exc}") from exc
    if len(pages) == 1:
        return pages[0]
    if all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    merged: dict[str, Any] = dict(pages[0]) if pages and isinstance(pages[0], dict) else {}
    for page in pages[1:]:
        for key, value in page.items():
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = merged[key] + value
    return merged


# ---- inventory -----------------------------------------------------------------------------------------------------

def check_rows(payload: Any) -> list[dict[str, Any]]:
    runs: list[Any] = payload.get("check_runs", []) if isinstance(payload, dict) else []
    return [{"name": str(r.get("name", "")), "status": str(r.get("status", "")), "conclusion": r.get("conclusion")}
            for r in runs]


def required_checks(repo: str, base: str) -> list[str] | None:
    """Required status check names for `base`; None when branch protection is unreadable, absent or lists none."""
    try:
        data: Any = gh_api(f"repos/{repo}/branches/{base}/protection")
    except GhError:
        return None
    section: dict[str, Any] = data.get("required_status_checks") or {} if isinstance(data, dict) else {}
    names: list[str] = [str(c) for c in section.get("contexts", [])]
    names += [str(c.get("context")) for c in section.get("checks", []) if c.get("context")]
    return sorted(set(names)) or None  # no required checks listed: treat every check as required


def pr_record(repo: str, summary: dict[str, Any]) -> dict[str, Any]:
    number: int = summary["number"]
    detail: dict[str, Any] = gh_api(f"repos/{repo}/pulls/{number}")
    files: Any = gh_api(f"repos/{repo}/pulls/{number}/files?per_page={PER_PAGE}", paginate=True)
    sha: str = summary["head"]["sha"]
    checks: Any = gh_api(f"repos/{repo}/commits/{sha}/check-runs?per_page={PER_PAGE}", paginate=True)
    return {
        "number": number, "title": summary.get("title", ""), "head": summary["head"]["ref"], "head_sha": sha,
        "base": summary["base"]["ref"], "draft": bool(summary.get("draft")), "author": (summary.get("user") or {}).get("login", ""),
        "created_at": summary.get("created_at", ""), "updated_at": summary.get("updated_at", ""),
        "mergeable": detail.get("mergeable"), "mergeable_state": detail.get("mergeable_state", "unknown"),
        "files": [str(f.get("filename", "")) for f in files], "checks": check_rows(checks),
    }


def build_inventory(repo: str, stale_days: int, head_prefix: str | None, author: str | None) -> dict[str, Any]:
    listed: list[dict[str, Any]] = gh_api(f"repos/{repo}/pulls?state=open&per_page={PER_PAGE}", paginate=True)
    wanted = [p for p in listed
              if (not head_prefix or p["head"]["ref"].startswith(head_prefix))
              and (not author or (p.get("user") or {}).get("login") == author)]
    prs: list[dict[str, Any]] = [pr_record(repo, p) for p in wanted]
    # Stack detection needs every open head, not only the filtered ones.
    open_heads: list[str] = sorted({p["head"]["ref"] for p in listed})
    bases: list[str] = sorted({p["base"] for p in prs})
    return {"repo": repo, "generated_at": now_utc().isoformat(timespec="seconds"), "stale_days": stale_days,
            "open_total": len(listed), "open_heads": open_heads, "prs": prs,
            "required": {base: required_checks(repo, base) for base in bases}}


def check_summary(pr: dict[str, Any]) -> str:
    checks: list[dict[str, Any]] = pr["checks"]
    if not checks:
        return "none"
    bad = [c["name"] for c in checks if c["conclusion"] in FAILING]
    pending = [c["name"] for c in checks if c["status"] != "completed"]
    return f"{len(checks)} checks, {len(bad)} failing, {len(pending)} pending"


def inventory_markdown(inv: dict[str, Any]) -> str:
    lines: list[str] = [f"# Open PRs in {inv['repo']}", "", f"Generated {inv['generated_at']}; stale after {inv['stale_days']} days; "
                        f"{len(inv['prs'])} of {inv['open_total']} open PRs in scope.", "",
                        "| PR | Title | Head -> base | Draft | Author | Updated | Mergeable | Checks | Files |",
                        "|---|---|---|---|---|---|---|---|---|"]
    for pr in inv["prs"]:
        title: str = str(pr["title"]).replace("|", "\\|")
        lines.append(f"| #{pr['number']} | {title} | {pr['head']} -> {pr['base']} | {'yes' if pr['draft'] else 'no'} | {pr['author']} "
                     f"| {pr['updated_at']} | {pr['mergeable_state']} | {check_summary(pr)} | {len(pr['files'])} |")
    lines += ["", "## Required checks by base branch", ""]
    for base, names in sorted(inv["required"].items()):
        lines.append(f"- `{base}`: " + ("unknown (every check treated as required)" if names is None else ", ".join(names) or "none"))
    return "\n".join(lines) + "\n"


def cmd_inventory(args: argparse.Namespace) -> int:
    if not REPO_NAME.match(args.repo):
        emit({"ok": False, "error": f"repo must be OWNER/NAME, got {args.repo!r}"})
        return EXIT_ERROR
    try:
        inv: dict[str, Any] = build_inventory(args.repo, args.stale_days, args.head_prefix, args.author)
    except GhError as exc:
        emit({"ok": False, "error": str(exc)})
        return EXIT_ERROR
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / INVENTORY_JSON).write_text(json.dumps(inv, indent=2) + "\n", encoding=ENCODING)
    (out / INVENTORY_MD).write_text(inventory_markdown(inv), encoding=ENCODING)
    emit({"ok": True, "repo": args.repo, "open_total": inv["open_total"], "in_scope": len(inv["prs"]),
          "inventory": str(out / INVENTORY_JSON), "markdown": str(out / INVENTORY_MD)})
    return EXIT_OK


# ---- classify ------------------------------------------------------------------------------------------------------

def load_inventory(path: str) -> dict[str, Any]:
    data: Any = json.loads(Path(path).read_text(encoding=ENCODING))
    return data if isinstance(data, dict) else {}


def shared_hits(files: list[str]) -> list[str]:
    hits: list[str] = []
    for name in files:
        base: str = name.rsplit("/", 1)[-1]
        if any(name.startswith(d) for d in SHARED_DIRS) or any(fnmatch.fnmatch(base, p) for p in SHARED_NAMES):
            hits.append(name)
    return hits


def needs_me_hits(files: list[str]) -> list[str]:
    return [name for name in files if any(p.search(name) for p in NEEDS_ME_PATHS)]


def failing_checks(pr: dict[str, Any]) -> list[str]:
    return [c["name"] for c in pr["checks"] if c["conclusion"] in FAILING]


def pending_checks(pr: dict[str, Any], required: list[str] | None) -> list[str]:
    names: list[str] = [c["name"] for c in pr["checks"] if c["status"] != "completed" or c["conclusion"] is None]
    reported: set[str] = {c["name"] for c in pr["checks"]}
    return names + [r for r in (required or []) if r not in reported]


def primary_bucket(pr: dict[str, Any], stacked: bool, required: list[str] | None) -> tuple[str, str, list[str], list[str]]:
    """(bucket, evidence, failing, failing_required). Unknown required checks mean every check is required."""
    failing: list[str] = failing_checks(pr)
    failing_required: list[str] = failing if required is None else [n for n in failing if n in required]
    state: str = pr["mergeable_state"]
    if pr["draft"]:
        return DRAFT, "draft", failing, failing_required
    if stacked:
        return STACKED, f"base {pr['base']} is the head of another open PR", failing, failing_required
    if pr["mergeable"] is False or state in REBASE_STATES:
        return NEEDS_REBASE, f"mergeable_state {state}", failing, failing_required
    if failing_required:
        return CI_RED, "failing: " + ", ".join(failing_required), failing, failing_required
    pending: list[str] = pending_checks(pr, required)
    if pending:
        return PENDING, "running or not yet reported: " + ", ".join(pending), failing, failing_required
    if state not in CLEAN_STATES:
        return PENDING, f"mergeable_state {state} (waiting on a review or a required check)", failing, failing_required
    note: str = f"; non-required failures ignored: {', '.join(failing)}" if failing else ""
    return GREEN, f"all checks passing, mergeable_state {state}{note}", failing, failing_required


def classify(inv: dict[str, Any], now: datetime) -> dict[str, Any]:
    prs: list[dict[str, Any]] = inv["prs"]
    open_heads: set[str] = set(inv.get("open_heads") or [p["head"] for p in prs])
    stale_after: timedelta = timedelta(days=int(inv.get("stale_days", DEFAULT_STALE_DAYS)))
    rows: list[dict[str, Any]] = []
    for pr in prs:
        stacked: bool = pr["base"] in open_heads and pr["base"] != pr["head"]
        bucket, evidence, failing, failing_req = primary_bucket(pr, stacked, inv.get("required", {}).get(pr["base"]))
        is_base: bool = pr["head"] in {p["base"] for p in prs if p is not pr}
        stale: bool = now - parse_time(pr["updated_at"]) > stale_after and not is_base
        candidates: dict[str, list[str]] = {"superseded": ["empty diff"] if not pr["files"] else [],
                                             "needs_me": needs_me_hits(pr["files"])}
        rows.append({"number": pr["number"], "bucket": bucket, "stale": stale, "evidence": evidence, "failing": failing,
                     "failing_required": failing_req, "candidates": candidates, "shared_files": shared_hits(pr["files"])})
    counts: dict[str, int] = {b: sum(1 for r in rows if r["bucket"] == b) for b in BUCKETS}
    return {"ok": True, "now": now.isoformat(timespec="seconds"), "prs": rows, "counts": counts,
            "stale": [r["number"] for r in rows if r["stale"]], "overlaps": overlaps(prs)}


def overlaps(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for i, first in enumerate(prs):
        for second in prs[i + 1:]:
            common: list[str] = sorted(set(first["files"]) & set(second["files"]))
            if common:
                found.append({"prs": [first["number"], second["number"]], "files": common})
    return found


def cmd_classify(args: argparse.Namespace) -> int:
    now: datetime = parse_time(args.now) if args.now else now_utc()
    emit(classify(load_inventory(args.inventory), now))
    return EXIT_OK


# ---- order ---------------------------------------------------------------------------------------------------------

def merge_waves(inv: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Waves of PR numbers: stack bases first, shared-file PRs one per wave, everything else in one parallel wave."""
    rows: dict[int, dict[str, Any]] = {r["number"]: r for r in classify(inv, now)["prs"]}
    prs: dict[int, dict[str, Any]] = {p["number"]: p for p in inv["prs"] if rows[p["number"]]["bucket"] != DRAFT}
    parent: dict[int, int | None] = {n: next((m for m, q in prs.items() if q["head"] == p["base"] and m != n), None) for n, p in prs.items()}
    has_child: set[int] = {p for p in parent.values() if p is not None}
    placed: set[int] = set()
    waves: list[list[int]] = []
    while len(placed) < len(prs):
        ready: list[int] = sorted(n for n in prs if n not in placed and (parent[n] is None or parent[n] in placed))
        if not ready:  # a cycle; do not loop forever
            waves.append(sorted(n for n in prs if n not in placed))
            break
        plain: list[int] = [n for n in ready if not rows[n]["shared_files"]]
        shared: list[int] = [n for n in ready if rows[n]["shared_files"]]
        bases: list[int] = [n for n in plain if n in has_child]
        wave: list[int] = bases or shared[:1] or plain
        waves.append(wave)
        placed.update(wave)
    skipped: list[int] = sorted(set(rows) - set(prs))
    return {"ok": True, "waves": waves, "skipped_drafts": skipped}


def cmd_order(args: argparse.Namespace) -> int:
    now: datetime = parse_time(args.now) if args.now else now_utc()
    emit(merge_waves(load_inventory(args.inventory), now))
    return EXIT_OK


# ---- ledger and report ---------------------------------------------------------------------------------------------

def cmd_record(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"at": now_utc().isoformat(timespec="seconds"), "pr": args.pr, "bucket": args.bucket,
                           "action": args.action, "sha": args.sha or "", "reason": args.reason or "", "ci": args.ci or "",
                           "worker": args.worker or "", "verified_by": args.verified_by or ""}
    with (directory / LEDGER).open("a", encoding=ENCODING) as handle:
        handle.write(json.dumps(row) + "\n")
    emit({"ok": True, "ledger": str(directory / LEDGER), "row": row})
    return EXIT_OK


def read_ledger(directory: Path) -> list[dict[str, Any]]:
    path = directory / LEDGER
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding=ENCODING).splitlines() if line.strip()]


def cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def final_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last non-branch row per PR, with the earliest bucket kept when the last row has none."""
    last: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row["action"] != BRANCH_KEPT:
            last[row["pr"]] = {**row, "bucket": row["bucket"] or last.get(row["pr"], {}).get("bucket", "")}
    return [last[n] for n in sorted(last)]


def before_count(directory: Path, table: list[dict[str, Any]]) -> int:
    path = directory / INVENTORY_JSON
    if path.is_file():
        return len(json.loads(path.read_text(encoding=ENCODING)).get("prs", []))
    return len(table)


def report_markdown(directory: Path, rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    table = final_rows(rows)
    before: int = before_count(directory, table)
    merged = [r for r in table if r["action"] == MERGED]
    closed = [r for r in table if r["action"] == CLOSED]
    waiting = [r for r in table if r["action"] == WAITING or r["bucket"] == NEEDS_ME]
    kept = [r for r in rows if r["action"] == BRANCH_KEPT]
    after: int = max(before - len(merged) - len(closed), 0)
    summary: dict[str, Any] = {"before": before, "after": after, "merged": len(merged), "closed": len(closed),
                               "waiting": len(waiting), "branches_not_deleted": len(kept)}
    lines: list[str] = ["# PR sweep report", "",
                        f"Open PRs {before} -> {after}. Merged {len(merged)}, closed {len(closed)}, waiting on you {len(waiting)}.", "",
                        "## Waiting on you", ""]
    lines += [f"- #{r['pr']}: {r['reason'] or 'decision needed'}" for r in waiting] or ["- none"]
    lines += ["", "## Branches not deleted", ""]
    lines += [f"- PR #{r['pr']}: {r['reason'] or 'deletion denied'}" for r in kept] or ["- none"]
    lines += ["", "## PRs", "", "| PR | Bucket | Action | Merge SHA or reason | CI verdict | Worker | Verified by |",
              "|---|---|---|---|---|---|---|"]
    for r in table:
        lines.append(f"| #{r['pr']} | {cell(r['bucket'])} | {cell(r['action'])} | {cell(r['sha'] or r['reason'])} | {cell(r['ci'])} "
                     f"| {cell(r['worker'])} | {cell(r['verified_by'])} |")
    return "\n".join(lines) + "\n", summary


def cmd_report(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    text, summary = report_markdown(directory, read_ledger(directory))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / REPORT).write_text(text, encoding=ENCODING)
    emit({"ok": True, "report": str(directory / REPORT), **summary})
    return EXIT_OK


# ---- cli -----------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr_sweep.py", description="pr-sweep helpers; every subcommand prints JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--repo", required=True)
    inv.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    inv.add_argument("--head-prefix", default=None)
    inv.add_argument("--author", default=None)
    inv.add_argument("--out", required=True)
    for name in ("classify", "order"):
        each = sub.add_parser(name)
        each.add_argument("--inventory", required=True)
        each.add_argument("--now", default=None)
    rec = sub.add_parser("record")
    rec.add_argument("--dir", required=True)
    rec.add_argument("--pr", type=int, required=True)
    rec.add_argument("--bucket", required=True)
    rec.add_argument("--action", required=True)
    for flag in ("sha", "reason", "ci", "worker", "verified-by"):
        rec.add_argument(f"--{flag}", default=None)
    sub.add_parser("report").add_argument("--dir", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handlers = {"inventory": cmd_inventory, "classify": cmd_classify, "order": cmd_order, "record": cmd_record, "report": cmd_report}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
