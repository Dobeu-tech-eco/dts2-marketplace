#!/usr/bin/env python3
"""Briefs and the cached prompt prefix for sons and the lead (B1, N5, Q-11). Nothing here starts a process.

  son-brief  <manifest> --lane L --epoch N [--max-bundle K] [--out FILE]   the ~4 KB son brief (templates/son-brief.md)
  prefix     --stamp S [--cwd D]                                            the stable cached prefix (discipline, roster, probe)
  dry-run    <manifest> --lane L --worktree W [--cwd D]                     the exact son command, env names, byte counts
  lead-brief --stamp S [--cwd D] [--task-file F] [--roster-json F] [--probe-json F]
                                                                           one page for the lead instead of raw JSON dumps
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SON_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "son-brief.md"
DISCIPLINE_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "discipline.md"
DEFAULT_MAX_BUNDLE: Final[int] = 5
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{(\w+)\}\}")
NONE_TEXT: Final[str] = "none"
PROBE_NAME: Final[str] = "probe.json"
PREFIX_HEADINGS: Final[tuple[str, str, str]] = ("## 1. Discipline", "## 2. Roster", "## 3. Probe")
PREFIX_TITLE: Final[str] = "# dts2-harness shared prefix (identical for every dispatch of this run)"
NO_PROBE: Final[str] = "no probe recorded for this run\n"
PROMPT_FLAG: Final[str] = "-p"
PREFIX_FLAG: Final[str] = "--append-system-prompt"


def canonical(value: Any) -> str:
    """Stable JSON text: sorted keys, fixed separators, one trailing newline."""
    return json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


class BriefError(Exception):
    """A brief cannot be built (unknown lane, unreadable template or input)."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BriefError(f"cannot read {path}: {exc}") from exc


def find_lane(manifest: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in manifest.get("lanes", []):
        if lane.get("id") == lane_id:
            return dict(lane)
    raise BriefError(f"unknown lane '{lane_id}'")


def bullets(items: list[str]) -> str:
    return "\n".join(f"- `{i}`" for i in items) if items else f"- {NONE_TEXT}"


def task_lines(lane: dict[str, Any]) -> str:
    tasks: list[Any] = list(lane.get("tasks") or [])
    if not tasks:
        return f"- {lane.get('item', NONE_TEXT)}"
    return "\n".join(f"- {t}" for t in tasks)


def son_values(manifest: dict[str, Any], lane_id: str, epoch: int, max_bundle: int) -> dict[str, str]:
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    stamp: str = str(manifest.get("stamp"))
    files: list[str] = sorted({str(f).replace("\\", "/") for f in lane.get("files", []) if f})
    return {
        "stamp": stamp, "lane": str(lane["id"]), "epoch": str(epoch), "branch": f"dts2/{stamp}/lane-{lane['id']}",
        "base": str(manifest.get("base") or NONE_TEXT), "item": str(lane.get("item") or NONE_TEXT),
        "tier": str(lane.get("tier") or "standard"), "max_bundle": str(max_bundle),
        "depends": ", ".join(str(d) for d in lane.get("depends_on", [])) or NONE_TEXT,
        "files": bullets(files), "tasks": task_lines(lane),
    }


def son_brief(manifest: dict[str, Any], lane_id: str, epoch: int, max_bundle: int = DEFAULT_MAX_BUNDLE) -> str:
    """The son's own brief: the lane facts filled into templates/son-brief.md."""
    values: dict[str, str] = son_values(manifest, lane_id, epoch, max_bundle)
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), read_text(SON_TEMPLATE))


def role_lines(roster: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"- {role}: {', '.join(names)}" for role, names in sorted((roster.get("assignments") or {}).items())]
    for key in ("handoff", "live"):
        if roster.get(key):
            lines.append(f"- {key}: {', '.join(roster[key])}")
    if roster.get("costOrder"):
        lines.append(f"- cheapest first: {', '.join(roster['costOrder'])}")
    return lines or ["- no agents configured"]


def probe_lines(probe: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"- usable: {', '.join(probe.get('usable') or []) or NONE_TEXT}"]
    dropped: list[str] = [f"{d.get('name')} ({d.get('reason')})" for d in probe.get("dropped") or []]
    if dropped:
        lines.append(f"- dropped: {', '.join(dropped)}")
    for name, agent in sorted((probe.get("agents") or {}).items()):
        if agent.get("available") and agent.get("budget") not in (None, "ok"):
            lines.append(f"- {name}: budget {agent['budget']}, roles {', '.join(agent.get('roles') or []) or NONE_TEXT}")
    return lines


def check_lines(ledger: list[dict[str, Any]]) -> list[str]:
    import checks  # lazy: checks.py reads the ledger format it also writes
    if not any(r.get("kind") == "check" for r in ledger):
        return ["no checks recorded yet"]
    return checks.summary(ledger).rstrip("\n").splitlines()


def lead_brief(task: str, roster: dict[str, Any], probe: dict[str, Any], ledger: list[dict[str, Any]], stamp: str) -> str:
    """One page for the lead: the task verbatim, the roster and probe in a few lines, the deterministic check results, and
    pointers to the files it reads itself. The caller no longer pastes roster, probe and ledger JSON."""
    lines: list[str] = [
        f"# Lead brief - run {stamp}", "", "## Task (verbatim)", task.strip(), "", "## Roster (assign roles only to these)",
        *role_lines(roster), "", "## Probe", *probe_lines(probe), "", "## Deterministic checks", *check_lines(ledger), "",
        "## Read yourself (not inlined)",
        "- `.harness/end-state.md` - the slice, `## Sections`, acceptance criteria",
        "- `.harness/discipline.md` - rules you follow; the plan defines done first",
        "- `.harness/config.yaml` - commands, paths, `do_not_touch`",
        "- `.harness/lessons.md` - apply every matching lesson and say which",
        "- the scout report, when the caller supplies one",
        "", "Handoff agents get a written brief in the plan, never a live dispatch. Builders never run on a frontier model.",
    ]
    return "\n".join(lines) + "\n"


def discipline_text(cwd: Path) -> str:
    """The repo's `.harness/discipline.md`, else the plugin's template. Never the run's mutable state."""
    for path in (cwd / ".harness" / "discipline.md", DISCIPLINE_TEMPLATE):
        try:
            return path.read_text(encoding="utf-8").rstrip("\n") + "\n"
        except OSError:
            continue
    return "(no discipline file found)\n"


def roster_text(cwd: Path) -> str:
    """The configured roster resolved to role assignments, as canonical JSON. Falls back to the raw entries."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import roster
    entries: list[dict[str, Any]] = roster.read_roster(cwd / ".harness" / "config.yaml")
    try:
        return canonical({"entries": entries, **roster.resolve(entries, roster.load_profiles())})
    except (roster.RosterError, OSError, ValueError, KeyError):
        return canonical({"entries": entries})


def probe_text(cwd: Path, stamp: str) -> str:
    """The probe the lead recorded for this run (`runs/<stamp>/probe.json`), re-serialised canonically."""
    try:
        return canonical(json.loads((cwd / ".harness" / "runs" / stamp / PROBE_NAME).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return NO_PROBE


def cached_prefix(cwd: Path, stamp: str) -> str:
    """The stable part of every son's prompt, in one fixed order: discipline, roster, probe. It holds nothing that differs
    between lanes, dispatches or callers (no lane, epoch, time or environment), so the bytes repeat and the provider's
    prompt cache can serve them. Lane facts come after it, in the brief."""
    parts: list[str] = [PREFIX_TITLE, "", PREFIX_HEADINGS[0], discipline_text(cwd), PREFIX_HEADINGS[1], roster_text(cwd),
                        PREFIX_HEADINGS[2], probe_text(cwd, stamp)]
    return "\n".join(parts)


def dry_run(manifest: dict[str, Any], lane_id: str, worktree: Path, cwd: Path) -> dict[str, Any]:
    """Build the exact son command and report it. Starts nothing and writes nothing: no preflight, no lease, no spawn."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lanes
    try:
        command: dict[str, Any] = lanes.son_command(manifest, lane_id, worktree, cwd)
    except lanes.LaneError as exc:
        raise BriefError(str(exc)) from exc
    argv: list[str] = list(command["argv"])
    prompt: str = argv[argv.index(PROMPT_FLAG) + 1]
    prefix: bytes = argv[argv.index(PREFIX_FLAG) + 1].encode("utf-8") if PREFIX_FLAG in argv else b""
    return {"ok": True, "started": False, "lane": lane_id, "cwd": command["cwd"], "command": shlex.join(argv), "argv": argv,
            "env_allowlist": sorted(command["env"]), "prompt": prompt, "prompt_bytes": len(prompt.encode("utf-8")),
            "prefix_bytes": len(prefix), "prefix_sha256": hashlib.sha256(prefix).hexdigest() if prefix else None}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read JSON {path}: {exc}") from exc


def run_lead(args: argparse.Namespace) -> dict[str, Any]:
    cwd: Path = Path(args.cwd).resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import checks
    roster: dict[str, Any]
    probe: dict[str, Any]
    if args.roster_json and args.probe_json:
        roster, probe = load_json(Path(args.roster_json)), load_json(Path(args.probe_json))
    else:
        import roster as roster_mod
        config: Path = cwd / ".harness" / "config.yaml"
        profiles = roster_mod.load_profiles()
        entries = roster_mod.read_roster(config)
        roster = load_json(Path(args.roster_json)) if args.roster_json else roster_mod.resolve(entries, profiles)
        probe = load_json(Path(args.probe_json)) if args.probe_json else roster_mod.probe(entries, profiles, roster_mod.read_budget(config))
    run_dir: Path = cwd / ".harness" / "runs" / args.stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    probe_file: Path = run_dir / PROBE_NAME
    if not probe_file.exists():
        probe_file.write_text(canonical(probe), encoding="utf-8")
    task: str = Path(args.task_file).read_text(encoding="utf-8") if args.task_file else sys.stdin.read()
    sys.stdout.write(lead_brief(task, roster, probe, checks.read_ledger(checks.ledger_path(cwd, args.stamp)), args.stamp))
    return {"ok": True}


def run_main(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "son-brief":
        text: str = son_brief(load_json(Path(args.manifest)), args.lane, args.epoch, args.max_bundle)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return {"ok": True, "bytes": len(text.encode("utf-8")), "out": args.out}
    if args.command == "lead-brief":
        return run_lead(args)
    if args.command == "prefix":
        sys.stdout.write(cached_prefix(Path(args.cwd).resolve(), args.stamp))
        return {"ok": True}
    if args.command == "dry-run":
        return dry_run(load_json(Path(args.manifest)), args.lane, Path(args.worktree), Path(args.cwd).resolve())
    raise BriefError(f"unknown command {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    son_p = sub.add_parser("son-brief")
    son_p.add_argument("manifest")
    son_p.add_argument("--lane", required=True)
    son_p.add_argument("--epoch", type=int, required=True)
    son_p.add_argument("--max-bundle", type=int, default=DEFAULT_MAX_BUNDLE)
    son_p.add_argument("--out", default=None)
    prefix_p = sub.add_parser("prefix")
    prefix_p.add_argument("--cwd", default=".")
    prefix_p.add_argument("--stamp", required=True)
    dry_p = sub.add_parser("dry-run")
    dry_p.add_argument("manifest")
    dry_p.add_argument("--lane", required=True)
    dry_p.add_argument("--worktree", required=True)
    dry_p.add_argument("--cwd", default=".")
    lead_p = sub.add_parser("lead-brief")
    lead_p.add_argument("--cwd", default=".")
    lead_p.add_argument("--stamp", required=True)
    lead_p.add_argument("--task-file", default=None, help="the task text; stdin when omitted")
    lead_p.add_argument("--roster-json", default=None, help="saved `roster.py resolve` output")
    lead_p.add_argument("--probe-json", default=None, help="saved `roster.py probe` output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_main(args)
    except BriefError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    if args.command == "dry-run" or (args.command == "son-brief" and args.out):
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
