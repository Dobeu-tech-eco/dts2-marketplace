#!/usr/bin/env python3
"""Lane manifest tools for parallel autopilot: overlap check, lane leases, branch-name collision check, the son command line,
and the dpp head's helpers: plan (admission, spend, feasibility, --full selection), status, sendback, release, fold,
stop-check and report-check. It is the only writer of lane state: leases, status.json fields the head owns (heartbeat,
session id, park reason), send-backs, the budget counter, the model-call ledger and merge order. Its supervisor commands:
preflight (pin the CLI version), spawn (start a son under every cap), call (any other model call behind the shared
limit), heartbeat, budget, loop, merge-order, merge-plan, merge-go, merge-go-step and merge-done. Its lifecycle commands:
transition (the one writer of a lane's phase, against a table of legal moves), shutdown (the graceful end of a run),
reconcile (ask GitHub before creating, merging or resuming), run-record, builder and run-resume (the typed run record and
builders.jsonl), fold-done, merge-resume and walkthrough-failed (the merge journal) and report (the run as a table).
`amend` changes one lane of a running manifest; check, lease and plan also run the graph checks of plan_graph.py
(contracts, owners, cycles, critical path)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lanes.common import COST_SOURCES, DEFAULT_CALL_TIMEOUT_S, HEARTBEAT_PHASES, LaneError, RUNS_DIR, load_manifest  # noqa: E402
from lanes.gitrefs import branch_check  # noqa: E402
from lanes.amend import amend_lane, split_list  # noqa: E402
from lanes.journal import fold_done, walkthrough_failed  # noqa: E402
from lanes.mergeplan import merge_plan  # noqa: E402
from lanes.merge import merge_done, merge_go, merge_go_step, merge_order, set_merge_target  # noqa: E402
from lanes.mergeresume import merge_resume  # noqa: E402
from lanes.phases import ALL_PHASES, transition  # noqa: E402
from lanes.planner import load_draft, plan, read_checkin, son_command  # noqa: E402
from lanes.reconcile import reconcile, reconcile_step  # noqa: E402
from lanes.runend import VERDICT_MERGED, VERDICT_SHUTDOWN, record_run_end, run_report_view, warn_thin_plan  # noqa: E402
from lanes.runrecord import BUILDER_STATUSES, RUN_KINDS, init_run, read_run, record_builder, resume_view  # noqa: E402
from lanes.runstate import budget_report, fold, heartbeat, release, report_check, sendback, spend_state, status, stop_check  # noqa: E402
from lanes.shutdown import GRACE_S, shutdown  # noqa: E402
from lanes.supervisor import gc_restore, loop, model_call, preflight, spawn  # noqa: E402
from plan_graph import annotate_plan, graph_check as check, graph_lease as lease  # noqa: E402


def split_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def add_supervisor_parsers(sub: Any) -> None:
    """Subcommands that start models and keep the budget, heartbeat and merge order."""
    for name in ("preflight", "budget", "loop"):
        sub.add_parser(name).add_argument("stamp")
    spawn_p = sub.add_parser("spawn")
    spawn_p.add_argument("manifest")
    spawn_p.add_argument("--lane", required=True)
    spawn_p.add_argument("--worktree", required=True)
    spawn_p.add_argument("--resume", action="store_true", help="continue the lane's saved session with --resume")
    spawn_p.add_argument("--unsafe-no-sandbox", action="store_true",
                         help="allow a second unattended son with the sandbox off; logs a warning")
    call_p = sub.add_parser("call")
    call_p.add_argument("stamp")
    call_p.add_argument("--label", required=True)
    call_p.add_argument("--timeout", type=int, default=DEFAULT_CALL_TIMEOUT_S)
    call_p.add_argument("--cost-source", choices=COST_SOURCES, default=None,
                        help="claude: the CLI prints a cost (default for claude or DTS2_CLAUDE_BIN); none: it never does")
    call_p.add_argument("--prompt-file", default=None, help="piped to the command's stdin (the ballot or prompt)")
    call_p.add_argument("--out", default=None, help="write stdout here instead of returning it; the command follows --")
    beat_p = sub.add_parser("heartbeat")
    beat_p.add_argument("stamp")
    beat_p.add_argument("--lane", required=True)
    beat_p.add_argument("--turn", type=int, default=None)
    beat_p.add_argument("--status", choices=HEARTBEAT_PHASES, default=None, help="set the lane's phase")
    beat_p.add_argument("--reason", default=None, help="why, recorded with --status")
    beat_p.add_argument("--blocked-by", default="", help="item ids a blocked lane waits for, comma separated")
    sub.add_parser("merge-order").add_argument("manifest")
    plan_p = sub.add_parser("merge-plan")
    plan_p.add_argument("manifest")
    plan_p.add_argument("--base", help="ref to probe lanes against (default origin/<merge target>)")
    go_p = sub.add_parser("merge-go")
    go_p.add_argument("manifest")
    go_p.add_argument("--lane", required=True)
    go_p.add_argument("--head", required=True, help="the verified HEAD sha the merge is cleared for")
    go_p.add_argument("--base", default=None, help="the base commit approved against; default origin/<target> now")
    target_p = sub.add_parser("merge-target")
    target_p.add_argument("stamp")
    target_p.add_argument("--set", default=None, help="record the branch this run merges into (default: dev)")
    target_p.add_argument("--yes-default-branch", action="store_true", help="record an explicit yes to merging into the default branch")
    step_p = sub.add_parser("merge-go-step")
    step_p.add_argument("stamp")
    step_p.add_argument("--step", required=True, help="the autopilot step the merge belongs to")
    step_p.add_argument("--head", required=True, help="the verified HEAD sha of the step's PR")
    step_p.add_argument("--base", default=None, help="the base commit approved against; default origin/<target> now")
    gc_p = sub.add_parser("gc-restore")
    gc_p.add_argument("stamp")
    done_p = sub.add_parser("merge-done")
    done_p.add_argument("manifest")
    done_p.add_argument("--lane", required=True)


def add_lifecycle_parsers(sub: Any) -> None:
    """Subcommands for the lane lifecycle: phases, shutdown, reconcile, the typed run record and the merge journal."""
    move_p = sub.add_parser("transition", help="move a lane to a phase if the table of legal moves allows it")
    move_p.add_argument("stamp")
    move_p.add_argument("--lane", required=True)
    move_p.add_argument("--to", required=True, choices=ALL_PHASES)
    move_p.add_argument("--reason", default=None)
    move_p.add_argument("--blocked-by", default="", help="item ids a blocked lane waits for, comma separated")
    move_p.add_argument("--turn", type=int, default=None)
    down_p = sub.add_parser("shutdown", help="graceful end of a run: park lanes, stop sons, close leases")
    down_p.add_argument("stamp")
    down_p.add_argument("--grace-s", type=float, default=GRACE_S, help="seconds a son gets after SIGTERM before SIGKILL")
    recon_p = sub.add_parser("reconcile", help="ask GitHub what exists for each lane before creating, merging or resuming")
    recon_p.add_argument("stamp")
    recon_p.add_argument("--step", default=None, help="a standalone autopilot step: check its branch dts2/<stamp>/step-<step> instead of the lanes")
    rec_p = sub.add_parser("run-record", help="the run's typed record; --init opens it")
    rec_p.add_argument("stamp")
    rec_p.add_argument("--init", action="store_true")
    rec_p.add_argument("--kind", choices=RUN_KINDS, default="run")
    build_p = sub.add_parser("builder", help="append one builder row to builders.jsonl")
    build_p.add_argument("stamp")
    build_p.add_argument("--lane", required=True)
    build_p.add_argument("--section", required=True)
    build_p.add_argument("--branch", required=True)
    build_p.add_argument("--status", required=True, choices=BUILDER_STATUSES)
    build_p.add_argument("--round", type=int, default=0, dest="round_no")
    build_p.add_argument("--sha", default=None, help="the commit the builder reports; confirmed against the branch tip and diff")
    build_p.add_argument("--pr", type=int, default=None)
    build_p.add_argument("--base", default=None, help="the ref the diff is taken against when confirming the sha")
    sub.add_parser("run-resume", help="what `run resume` reads: the run record and the newest row of each builder").add_argument("stamp")
    fold_p = sub.add_parser("fold-done", help="record that a fold group's PR is shipped")
    fold_p.add_argument("stamp")
    fold_p.add_argument("--group", required=True, help="the group key `fold` printed")
    fold_p.add_argument("--pr", type=int, default=None)
    sub.add_parser("merge-resume", help="pick up a merge a dead head left half done").add_argument("manifest")
    walk_p = sub.add_parser("walkthrough-failed", help="record a failed post-merge walkthrough and file the revert action item")
    walk_p.add_argument("stamp")
    walk_p.add_argument("--lane", required=True)
    walk_p.add_argument("--reason", required=True)
    report_p = sub.add_parser("report", help="the run as a markdown table")
    report_p.add_argument("stamp")
    report_p.add_argument("--repo-url", default=None, help="turns PR numbers into links")


def add_run_parsers(sub: Any) -> None:
    """Subcommands keyed by run stamp, for the dpp head."""
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--from-checkin", required=True, help="check-in.py --json output")
    plan_p.add_argument("--draft", required=True, help="draft lanes.json")
    plan_p.add_argument("--outside", default="", help="'<item>: <why>' marks admitted outside check-in")
    plan_p.add_argument("--full", action="store_true", help="dpp-full: greedy fill, delegation lanes allowed")
    plan_p.add_argument("--max", type=int, default=0, help="most lanes --full selects; 0 (default) = no cap, the model-call limit throttles")
    plan_p.add_argument("--stamp", default=None)
    sub.add_parser("status").add_argument("stamp")
    for name in ("sendback", "release"):
        lane_p = sub.add_parser(name)
        lane_p.add_argument("stamp")
        lane_p.add_argument("--lane", required=True)
        if name == "sendback":
            lane_p.add_argument("--reason", required=True)
        else:
            lane_p.add_argument("--epoch", type=int, default=None, help="refuse when older than the stored epoch")
    sub.add_parser("fold").add_argument("stamp")
    add_supervisor_parsers(sub)
    add_lifecycle_parsers(sub)
    stop_p = sub.add_parser("stop-check")
    stop_p.add_argument("stamp")
    stop_p.add_argument("--from-checkin", required=True)
    report_p = sub.add_parser("report-check")
    report_p.add_argument("report")
    report_p.add_argument("--lanes", required=True, help="comma-separated lane ids")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--no-prs", action="store_true", help="skip the open-PR file check")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("manifest")
    lease_p = sub.add_parser("lease")
    lease_p.add_argument("manifest")
    lease_p.add_argument("--lane", required=True)
    lease_p.add_argument("--epoch", type=int, default=None, help="refuse when older than the stored lease epoch")
    amend_p = sub.add_parser("amend", help="change one lane's files or contracts, re-check, bump the epoch, rewrite brief.md")
    amend_p.add_argument("manifest")
    amend_p.add_argument("--lane", required=True)
    for flag in ("set-files", "add-files", "remove-files", "depends-on", "provides", "consumes", "stubbed-on", "merge-after"):
        amend_p.add_argument(f"--{flag}", default=None, help="comma separated")
    branch_p = sub.add_parser("branch-check")
    branch_p.add_argument("stamp")
    branch_p.add_argument("--lanes", required=True, help="comma-separated lane ids")
    son_p = sub.add_parser("son-command")
    son_p.add_argument("manifest")
    son_p.add_argument("--lane", required=True)
    son_p.add_argument("--worktree", required=True)
    add_run_parsers(sub)
    return parser


def amend_changes(args: argparse.Namespace) -> dict[str, list[str] | None]:
    return {name: split_list(getattr(args, name)) for name in ("set_files", "add_files", "remove_files", "depends_on", "provides",
                                                              "consumes", "stubbed_on", "merge_after")}


def dispatch_plan(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any]:
    draft: dict[str, Any] = load_draft(Path(args.draft))
    if args.stamp:
        draft = {**draft, "stamp": args.stamp}
    result: dict[str, Any] = plan(draft, read_checkin(Path(args.from_checkin)), args.outside, args.full,
                                  args.max or len(draft["lanes"]), runs_dir, cwd, not args.no_prs)
    warn_thin_plan(result)
    return annotate_plan(result, cwd)


def dispatch_run(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any] | None:
    """The stamp-keyed and report subcommands; None when the command needs a manifest."""
    if args.command == "plan":
        return dispatch_plan(args, runs_dir, cwd)
    if args.command == "status":
        return status(runs_dir, args.stamp, cwd)
    if args.command == "sendback":
        return sendback(runs_dir, args.stamp, args.lane, args.reason)
    if args.command == "release":
        return release(runs_dir, args.stamp, args.lane, args.epoch)
    if args.command == "fold":
        return fold(runs_dir, args.stamp)
    if args.command == "stop-check":
        return stop_check(runs_dir, args.stamp, Path(args.from_checkin))
    if args.command == "report-check":
        return report_check(Path(args.report), split_ids(args.lanes))
    if args.command == "branch-check":
        return branch_check(args.stamp, split_ids(args.lanes), cwd)
    return dispatch_supervisor(args, runs_dir, cwd)


def dispatch_supervisor(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any] | None:
    if args.command == "preflight":
        return preflight(runs_dir, args.stamp, cwd)
    if args.command == "budget":
        return budget_report(runs_dir, args.stamp, cwd)
    if args.command == "loop":
        return loop(runs_dir, args.stamp, cwd)
    if args.command == "merge-target":
        return set_merge_target(runs_dir, args.stamp, cwd, args.set, args.yes_default_branch)
    if args.command == "merge-go-step":
        return merge_go_step(runs_dir, args.stamp, args.step, args.head, cwd, args.base)
    if args.command == "gc-restore":
        return gc_restore(runs_dir, args.stamp, cwd)
    if args.command == "heartbeat":
        return heartbeat(runs_dir, args.stamp, args.lane, args.turn, args.status, args.reason, split_ids(args.blocked_by))
    if args.command == "call":
        return model_call(runs_dir, args.stamp, cwd, args.label, args.command_argv, args.timeout,
                          Path(args.out) if args.out else None, Path(args.prompt_file) if args.prompt_file else None,
                          args.cost_source)
    return dispatch_lifecycle(args, runs_dir, cwd)


def dispatch_lifecycle(args: argparse.Namespace, runs_dir: Path, cwd: Path) -> dict[str, Any] | None:
    if args.command == "transition":
        return transition(runs_dir, args.stamp, args.lane, args.to, reason=args.reason, turn=args.turn,
                          blocked_by=split_ids(args.blocked_by))
    if args.command == "shutdown":
        done: dict[str, Any] = shutdown(runs_dir, args.stamp, cwd, args.grace_s)
        if done.get("ok"):
            record_run_end(runs_dir, args.stamp, cwd, VERDICT_SHUTDOWN)
        return done
    if args.command == "reconcile":
        if args.step is not None:
            return reconcile_step(args.stamp, args.step, cwd)
        return reconcile(runs_dir, args.stamp, cwd)
    if args.command == "run-record":
        record = init_run(runs_dir, args.stamp, args.kind) if args.init else read_run(runs_dir, args.stamp)
        return {"ok": True, "run": record.to_dict()}
    if args.command == "builder":
        return record_builder(runs_dir, args.stamp, args.lane, section=args.section, branch=args.branch, status=args.status,
                              round_no=args.round_no, sha=args.sha, pr=args.pr, cwd=cwd, base=args.base)
    if args.command == "run-resume":
        return resume_view(runs_dir, args.stamp)
    if args.command == "fold-done":
        return fold_done(runs_dir, args.stamp, args.group, args.pr)
    if args.command == "walkthrough-failed":
        return walkthrough_failed(runs_dir, args.stamp, args.lane, args.reason, cwd)
    if args.command == "report":
        return run_report_view(runs_dir, args.stamp, args.repo_url)
    return None


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cwd: Path = Path(args.cwd)
    runs_dir: Path = Path(args.runs_dir) if Path(args.runs_dir).is_absolute() else cwd / args.runs_dir
    handled: dict[str, Any] | None = dispatch_run(args, runs_dir, cwd)
    if handled is not None:
        return handled
    manifest: dict[str, Any] = load_manifest(Path(args.manifest))
    if args.command == "lease":
        return lease(manifest, args.lane, runs_dir, cwd, not args.no_prs, args.epoch)
    if args.command == "amend":
        return amend_lane(Path(args.manifest), args.lane, runs_dir, cwd, not args.no_prs, amend_changes(args))
    if args.command == "son-command":
        remaining: float | None = spend_state(runs_dir, str(manifest["stamp"]), cwd)["remaining_usd"]
        return son_command(manifest, args.lane, Path(args.worktree), cwd, remaining)
    if args.command == "spawn":
        return spawn(manifest, args.lane, Path(args.worktree), runs_dir, cwd, args.resume, args.unsafe_no_sandbox)
    if args.command == "merge-order":
        return merge_order(manifest, runs_dir)
    if args.command == "merge-plan":
        return merge_plan(manifest, runs_dir, cwd, args.base)
    if args.command == "merge-go":
        return merge_go(manifest, runs_dir, args.lane, args.head, cwd, args.base)
    if args.command == "merge-resume":
        return merge_resume(manifest, runs_dir, cwd)
    if args.command == "merge-done":
        done: dict[str, Any] = merge_done(manifest, runs_dir, args.lane)
        if done.get("all_merged"):
            gc_restore(runs_dir, str(manifest["stamp"]), cwd)
            record_run_end(runs_dir, str(manifest["stamp"]), cwd, VERDICT_MERGED)
        return done
    return check(manifest, runs_dir, cwd, not args.no_prs)


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """Everything after the first `--` is a command for `call`, kept away from argparse."""
    return (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])


def main() -> int:
    own, command = split_command(sys.argv[1:])
    args = build_parser().parse_args(own)
    args.command_argv = command
    try:
        result: dict[str, Any] = dispatch(args)
    except LaneError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
