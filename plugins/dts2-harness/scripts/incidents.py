#!/usr/bin/env python3
"""Agent telemetry, incident capture, lesson injection and the tier ledgers. Deterministic: no model calls, no network.

Hooks (stdin is the hook JSON; always exit 0, print nothing on error):
  hook pre-agent | subagent-start | subagent-stop | post-tool-use | stop | session-end | session-start
CLI (JSON with --json):
  list [--open]  live  brief [--session S]  resolve <id> --root-cause T --how T  lessons stats
  promote --tier harness|knowledge <lesson-or-signature> [--text T]  review-input
Tier 5 (the marketplace) is never written here: `harness:` lines go through `evolve`."""
from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import incidents_detect as detect  # noqa: E402
import incidents_lessons as learn  # noqa: E402
import settings_cache  # noqa: E402
import state_io  # noqa: E402
import subagent_report  # noqa: E402

KIND_START: Final[str] = "agent-start"
KIND_STOP: Final[str] = "agent-stop"
KIND_INCIDENT: Final[str] = "incident"
KIND_RESOLUTION: Final[str] = "incident-resolution"
KIND_DEBRIEF: Final[str] = "debrief"
KIND_INJECTION: Final[str] = "injection"
KIND_BRIEFS: Final[str] = "briefs"
OPEN: Final[str] = "open"
AUTO: Final[str] = "auto"
LABEL_TREND: Final[str] = "trend"
LABEL_ISOLATED: Final[str] = "isolated"
NONE_FOUND: Final[str] = "none found"
BRIEF_THROTTLE_S: Final[int] = 600
PENDING_TTL_S: Final[int] = 600
TREND_SESSIONS: Final[int] = 3
TREND_DAYS: Final[int] = 14
HARNESS_TREND_PROJECTS: Final[int] = 2
SECONDS_PER_DAY: Final[int] = 86400
SECONDS_PER_MINUTE: Final[int] = 60
HUNG_LOOKBACK_S: Final[int] = SECONDS_PER_DAY
SON_RUNS_SCANNED: Final[int] = 5
LIVE_MAX_LINES: Final[int] = 3
REPORT_MAX_CHARS: Final[int] = 20000
SHORT_ID: Final[int] = 4
AUTO_REVIEW_MIN: Final[int] = 3
LANES_TIMEOUT_S: Final[int] = 3
SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]")
LEDGER_NAME: Final[str] = "incidents.jsonl"
HOOK_EVENTS: Final[tuple[str, ...]] = ("pre-agent", "subagent-start", "subagent-stop", "post-tool-use", "stop", "session-end",
                                       "session-start")
DEFAULT_SESSION: Final[str] = "unknown"


# --- plumbing --------------------------------------------------------------------------------------------------------
def settings(repo: Path) -> dict[str, Any]:
    try:
        return dict(settings_cache.build(repo)["local"])
    except Exception:  # noqa: BLE001 - unreadable settings fall back to the defaults
        return dict(settings_cache.DEFAULTS["local"])


def state_of(repo: Path) -> state_io.State:
    return state_io.State(state_io.FileStore(repo))


def clean(name: Any) -> str:
    return SAFE_NAME.sub("", str(name or "")) or DEFAULT_SESSION


def short(agent_id: str) -> str:
    return agent_id[-SHORT_ID:] if agent_id else "?"


def current_run(repo: Path) -> str | None:
    try:
        stamps: list[str] = sorted(state_of(repo).runs())
    except Exception:  # noqa: BLE001
        return None
    return stamps[-1] if stamps else None


def make(repo: Path, kind: str, event_key: tuple[Any, ...] | None, **fields: Any) -> dict[str, Any]:
    run: str | None = current_run(repo)
    return state_io.make_event(kind, run=run, id=state_io.event_id(kind, *event_key) if event_key else None, **fields)


def class_of(repo: Path, agent_id: str) -> str:
    for row in state_of(repo).events(state_io.AGENTS_REL, KIND_START):
        if row.get("agent_id") == agent_id:
            return str(row.get("agent_class") or detect.UNKNOWN_CLASS)
    return detect.UNKNOWN_CLASS


def cache_path(name: str) -> str:
    return state_io.rel("cache", name)


def locked_json(repo: Path, path: str, edit: Any) -> Any:
    """Read-edit-write one small JSON record under its lock; `edit(record)` returns the value handed back."""
    state: state_io.State = state_of(repo)
    with state.store.lock(path):
        record: dict[str, Any] = state.read_record(path) or {}
        result: Any = edit(record)
        state.write_record(path, record)
        return result


# --- incident records and the live queue -----------------------------------------------------------------------------
def record_incident(repo: Path, *, category: str, session_id: str, agent_id: str, klass: str, what: str, detected_by: str,
                    evidence: dict[str, Any] | None = None, key: str | None = None, severity: str | None = None,
                    now: int | None = None) -> dict[str, Any] | None:
    """Append one incident; None when the same (session, agent, category, key) was already recorded."""
    mast, default_severity = detect.CATEGORIES[category]
    proof: dict[str, Any] = evidence or {}
    paths: list[str] = [str(p) for p in proof.get("paths", [])]
    unique: str = key if key is not None else (uuid.uuid4().hex if not agent_id else "")
    ident: str = state_io.event_id(KIND_INCIDENT, session_id, agent_id, category, unique)
    event: dict[str, Any] = state_io.make_event(
        KIND_INCIDENT, run=current_run(repo), id=ident, ts=now, incident_id="INC-" + ident[:8], session_id=session_id,
        agent_id=agent_id or None, agent_class=klass, category=category, mast=mast, severity=severity or default_severity,
        what_happened=what, detected_by=detected_by, how_resolved=OPEN, root_cause=None, evidence=proof,
        signature=detect.signature(category, klass, paths))
    return event if state_of(repo).append_event(state_io.AGENTS_REL, event) else None


def queue_live(repo: Path, session_id: str, text: str, incident_id: str) -> None:
    event: dict[str, Any] = state_io.make_event("live-correction", session_id=session_id, text=text, incident_id=incident_id)
    state_of(repo).append_row(cache_path("incident-live.jsonl"), event)


def drain_live(repo: Path) -> list[str]:
    """Pending one-line corrections for the lead (newest few); the queue is emptied."""
    path: str = cache_path("incident-live.jsonl")
    state: state_io.State = state_of(repo)
    if state.store.read_text(path) is None:
        return []
    with state.store.lock(path):
        texts: list[str] = [str(r.get("text")) for r in state.read_rows(path) if r.get("text")]
        state.store.write_text(path, "")
    return texts[-LIVE_MAX_LINES:]


def incidents_merged(repo: Path) -> list[dict[str, Any]]:
    """Incident rows with the latest resolution applied; a hung-spawn whose agent later stopped counts as auto-resolved."""
    state: state_io.State = state_of(repo)
    rows: list[dict[str, Any]] = state.read_rows(state_io.AGENTS_REL)
    stopped: set[str] = {str(r.get("agent_id")) for r in rows if r.get("kind") == KIND_STOP}
    resolutions: dict[str, dict[str, Any]] = {str(r.get("incident_id")): r for r in rows if r.get("kind") == KIND_RESOLUTION}
    labels: dict[str, str] = {str(r.get("incident_id")): str(r.get("label")) for r in state.read_rows(state_io.HEAD_LEDGER_REL)
                              if r.get("kind") == KIND_DEBRIEF}
    merged: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") != KIND_INCIDENT:
            continue
        item: dict[str, Any] = dict(row)
        fix: dict[str, Any] | None = resolutions.get(str(row.get("incident_id")))
        if fix:
            item.update(root_cause=fix.get("root_cause"), how_resolved=fix.get("how_resolved"))
        elif row.get("category") == "hung-spawn" and str(row.get("agent_id")) in stopped:
            item["how_resolved"] = AUTO
        item["debrief"] = labels.get(str(row.get("incident_id")))
        merged.append(item)
    return merged


def open_incidents(repo: Path) -> list[dict[str, Any]]:
    return [i for i in incidents_merged(repo) if i.get("how_resolved") == OPEN]


def running_agents(repo: Path, now: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = state_of(repo).read_rows(state_io.AGENTS_REL)
    stopped: set[str] = {str(r.get("agent_id")) for r in rows if r.get("kind") == KIND_STOP}
    return [{"agent_id": r.get("agent_id"), "agent_class": r.get("agent_class"), "parent_agent_id": r.get("parent_agent_id"),
             "session_id": r.get("session_id"), "age_s": max(0, now - int(r.get("ts", now)))}
            for r in rows if r.get("kind") == KIND_START and str(r.get("agent_id")) not in stopped]


# --- hooks -----------------------------------------------------------------------------------------------------------
def pre_agent(repo: Path, payload: dict[str, Any], cfg: dict[str, Any], now: int) -> dict[str, Any] | None:
    """PreToolUse on the Agent tool: remember the brief (SubagentStart does not carry it) and, in prompt mode, inject."""
    tool_input: Any = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    prompt: str = str(tool_input.get("prompt") or "")
    klass: str = detect.agent_class(tool_input.get("subagent_type") or "general-purpose")
    paths: list[str] = detect.brief_paths(prompt)
    selected: list[dict[str, Any]] = []
    if cfg["incident_inject_mode"] == "prompt":
        selected = learn.select(repo, klass, paths, cfg["incident_inject_max"], now, f"{klass} {' '.join(paths)}")
    entry: dict[str, Any] = {"ts": now, "klass": klass, "chars": len(prompt.strip()), "sha": detect.sha_of(prompt), "paths": paths,
                             "problems": detect.brief_problems(prompt, cfg["incident_brief_min_chars"]), "lessons": selected}

    def add(record: dict[str, Any]) -> None:
        keep: list[dict[str, Any]] = [e for e in record.get("pending", []) if now - int(e.get("ts", 0)) < PENDING_TTL_S]
        record["pending"] = [*keep, entry]

    locked_json(repo, cache_path(f"incident-briefs-{clean(payload.get('session_id'))}.json"), add)
    block: str = learn.injection_block(selected)
    if not block:
        return None
    updated: dict[str, Any] = {**tool_input, "prompt": f"{prompt}\n\n{block}"}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}


def take_pending(repo: Path, session_id: str, klass: str, now: int) -> dict[str, Any] | None:
    found: list[dict[str, Any]] = []

    def pop(record: dict[str, Any]) -> None:
        live: list[dict[str, Any]] = [e for e in record.get("pending", []) if now - int(e.get("ts", 0)) < PENDING_TTL_S]
        for index, entry in enumerate(live):
            if entry.get("klass") == klass:
                found.append(entry)
                del live[index]
                break
        record["pending"] = live

    path: str = cache_path(f"incident-briefs-{clean(session_id)}.json")
    if state_of(repo).store.read_text(path) is not None:
        locked_json(repo, path, pop)
    return found[0] if found else None


def log_injections(repo: Path, session_id: str, agent_id: str, klass: str, selected: list[dict[str, Any]], now: int) -> None:
    state: state_io.State = state_of(repo)
    for item in selected:
        key: tuple[Any, ...] = (agent_id, item["id"])
        event: dict[str, Any] = make(repo, KIND_INJECTION, key, ts=now, inj_id=state_io.event_id(KIND_INJECTION, *key),
                                     session_id=session_id, agent_id=agent_id, agent_class=klass, lesson_id=item["id"],
                                     tier=item["tier"], reason=item["reason"], category=item.get("category"))
        if state.append_event(state_io.INJECTIONS_REL, event):
            learn.sidecar_for(int(item["tier"]), repo).update(
                functools.partial(learn.record_injected, lesson_id=item["id"], now=now))


def subagent_start(repo: Path, payload: dict[str, Any], cfg: dict[str, Any], now: int) -> dict[str, Any] | None:
    agent_id: str = str(payload.get("agent_id") or "")
    if not agent_id:
        return None
    session: str = str(payload.get("session_id") or DEFAULT_SESSION)
    klass: str = detect.agent_class(payload.get("agent_type"))
    pending: dict[str, Any] | None = take_pending(repo, session, klass, now)
    parent: str | None = str(payload.get("parent_agent_id") or "") or None
    start: dict[str, Any] = make(repo, KIND_START, (agent_id,), ts=now, agent_id=agent_id, agent_name=str(payload.get("agent_type") or ""),
                                 agent_class=klass, parent_agent_id=parent, session_id=session,
                                 brief_chars=pending["chars"] if pending else None, brief_sha=pending["sha"] if pending else None)
    state_of(repo).append_event(state_io.AGENTS_REL, start)
    if pending and pending["problems"]:
        found: dict[str, Any] | None = record_incident(
            repo, category="bad-brief", session_id=session, agent_id=agent_id, klass=klass, detected_by="subagent-start", now=now,
            what=f"{klass} {short(agent_id)} got a thin brief: {', '.join(pending['problems'])}",
            evidence={"brief_chars": pending["chars"], "problems": pending["problems"], "paths": pending["paths"]})
        if found:
            queue_live(repo, session, f"{klass} {short(agent_id)} started with a thin brief ({', '.join(pending['problems'])}); "
                       "give the next one a goal, file scope and done-definition.", found["incident_id"])
    paths: list[str] = list(pending["paths"]) if pending else []
    if cfg["incident_inject_mode"] == "prompt":
        selected: list[dict[str, Any]] = list(pending["lessons"]) if pending else []
    else:
        selected = learn.select(repo, klass, paths, cfg["incident_inject_max"], now, f"{klass} {' '.join(paths)}")
    log_injections(repo, session, agent_id, klass, selected, now)
    block: str = learn.injection_block(selected) if cfg["incident_inject_mode"] != "prompt" else ""
    return {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": block}} if block else None


def stored_report(repo: Path, agent_id: str) -> str | None:
    record: dict[str, Any] | None = state_of(repo).read_record(cache_path(f"incident-report-{clean(agent_id)}.json"))
    return str(record.get("text")) if record and "text" in record else None


def score_outcomes(repo: Path, agent_id: str, now: int) -> None:
    """An incident (not bad-brief: that happens before the lesson could act) in the category a lesson targets makes it harmful."""
    state: state_io.State = state_of(repo)
    hit: set[str] = {str(r.get("category")) for r in state.read_rows(state_io.AGENTS_REL)
                     if r.get("kind") == KIND_INCIDENT and r.get("agent_id") == agent_id and r.get("category") != "bad-brief"}
    for row in state.events(state_io.INJECTIONS_REL, KIND_INJECTION):
        if row.get("agent_id") == agent_id and row.get("category") in hit:
            learn.sidecar_for(int(row["tier"]), repo).update(functools.partial(learn.record_harmful, lesson_id=row["lesson_id"]))


def feed_back(repo: Path, agent_id: str, report: str, now: int) -> None:
    """Parse the `Lessons:` line: an injected lesson the agent did not mention counts as unused."""
    verdicts: dict[str, str] = {k.casefold(): v for k, v in detect.parse_lessons_line(report).items()}
    for row in state_of(repo).events(state_io.INJECTIONS_REL, KIND_INJECTION):
        if row.get("agent_id") != agent_id:
            continue
        verdict: str = verdicts.get(str(row["lesson_id"]).casefold(), "unused")
        learn.sidecar_for(int(row["tier"]), repo).update(
            functools.partial(learn.record_verdict, lesson_id=row["lesson_id"], verdict=verdict, now=now))


def subagent_stop(repo: Path, payload: dict[str, Any], cfg: dict[str, Any], now: int) -> dict[str, Any] | None:
    agent_id: str = str(payload.get("agent_id") or "")
    if not agent_id:
        return None
    session: str = str(payload.get("session_id") or DEFAULT_SESSION)
    klass: str = detect.agent_class(payload.get("agent_type"))
    state: state_io.State = state_of(repo)
    starts: list[dict[str, Any]] = [r for r in state.events(state_io.AGENTS_REL, KIND_START) if r.get("agent_id") == agent_id]
    report: str = stored_report(repo, agent_id) or str(payload.get("last_assistant_message") or "")
    found: dict[str, Any] = detect.report_findings(report, klass, subagent_report.REQUIRED, subagent_report.missing_fields)
    duration: int | None = max(0, now - int(starts[0]["ts"])) if starts else None
    stop: dict[str, Any] = make(repo, KIND_STOP, (agent_id,), ts=now, agent_id=agent_id, agent_name=str(payload.get("agent_type") or ""),
                                agent_class=klass, session_id=session, duration_s=duration, report_chars=found["report_chars"],
                                partial=found["partial"], report_ok=found["report_ok"], missing_sections=found["missing_sections"])
    if not state.append_event(state_io.AGENTS_REL, stop) or not starts:
        return None
    new: list[dict[str, Any]] = []
    checks: list[tuple[bool, str, str]] = [
        (found["no_report"], "no-report", f"{klass} {short(agent_id)} ended with an empty or tiny report ({found['report_chars']} chars)"),
        (found["partial"], "partial", f"{klass} {short(agent_id)} returned a PARTIAL report"),
        (bool(found["missing_sections"]), "report-incomplete",
         f"{klass} {short(agent_id)} report lacks: {', '.join(found['missing_sections'])}")]
    for hit, category, what in checks:
        if hit:
            made = record_incident(repo, category=category, session_id=session, agent_id=agent_id, klass=klass, what=what,
                                   detected_by="subagent-stop", now=now, evidence={"report_chars": found["report_chars"],
                                   "missing_sections": found["missing_sections"], "duration_s": duration, "paths": []})
            if made:
                new.append(made)
    feed_back(repo, agent_id, report, now)
    score_outcomes(repo, agent_id, now)
    for item in new:
        if item["category"] != "report-incomplete":
            queue_live(repo, session, f"{item['what_happened']}; re-run or check its output before relying on it.", item["incident_id"])
    line: str = "; ".join(str(i["what_happened"]) for i in new if i["category"] != "report-incomplete")
    return {"systemMessage": f"dts2 incident: {line}"} if line else None


def normalise_path(repo: Path, raw: str) -> str:
    try:
        return Path(raw).resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError):
        return raw


def rework_check(repo: Path, payload: dict[str, Any], now: int) -> None:
    agent_id: str = str(payload.get("agent_id") or "")
    tool_input: Any = payload.get("tool_input")
    raw: str = str(tool_input.get("file_path") or "") if isinstance(tool_input, dict) else ""
    if not agent_id or not raw:
        return
    session: str = str(payload.get("session_id") or DEFAULT_SESSION)
    path: str = normalise_path(repo, raw)
    owners: list[str | None] = []

    def claim(record: dict[str, Any]) -> None:
        files: dict[str, str] = record.setdefault("files", {})
        owners.append(detect.rework_owner(files, path, agent_id))
        files.setdefault(path, agent_id)

    locked_json(repo, cache_path(f"incident-files-{clean(session)}.json"), claim)
    other: str | None = owners[0]
    if other is None:
        return
    klass: str = detect.agent_class(payload.get("agent_type")) if payload.get("agent_type") else class_of(repo, agent_id)
    other_class: str = class_of(repo, other)
    made: dict[str, Any] | None = record_incident(
        repo, category="rework-other-agent", session_id=session, agent_id=agent_id, klass=klass, key=path, detected_by="post-tool-use",
        now=now, what=f"{klass} {short(agent_id)} edited {path}, written earlier by {other_class} {short(other)}",
        evidence={"paths": [path], "other_agent_id": other, "other_agent_class": other_class})
    if made:
        queue_live(repo, session, f"{klass} {short(agent_id)} edited {path} that {other_class} {short(other)} wrote; "
                   "tell the next agent to leave that file to its owner.", made["incident_id"])


def post_tool_use(repo: Path, payload: dict[str, Any], cfg: dict[str, Any], now: int) -> dict[str, Any] | None:
    tool: str = str(payload.get("tool_name") or "")
    agent_id: str = str(payload.get("agent_id") or "")
    if tool == "SubagentHandback" and agent_id:
        tool_input: Any = payload.get("tool_input")
        text: str = str(tool_input.get("message") or "")[:REPORT_MAX_CHARS] if isinstance(tool_input, dict) else ""
        state_of(repo).write_record(cache_path(f"incident-report-{clean(agent_id)}.json"), {"text": text})
        return None
    if tool in detect.EDIT_TOOLS:
        rework_check(repo, payload, now)
        return None
    if tool == "Agent" and not agent_id:
        lines: list[str] = drain_live(repo)
        if lines:
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                           "additionalContext": "dts2 incident watch: " + " | ".join(lines)}}
    return None


def watchdog(repo: Path, cfg: dict[str, Any], now: int) -> list[dict[str, Any]]:
    """Record a hung-spawn incident for every agent that started more than incident_hung_minutes ago and never stopped."""
    limit: int = int(cfg["incident_hung_minutes"]) * SECONDS_PER_MINUTE
    made: list[dict[str, Any]] = []
    for agent in running_agents(repo, now):
        if limit <= agent["age_s"] <= HUNG_LOOKBACK_S:
            item = record_incident(
                repo, category="hung-spawn", session_id=str(agent["session_id"]), agent_id=str(agent["agent_id"]),
                klass=str(agent["agent_class"]), detected_by="watchdog", now=now, evidence={"age_s": agent["age_s"], "paths": []},
                what=f"{agent['agent_class']} {short(str(agent['agent_id']))} started {agent['age_s'] // SECONDS_PER_MINUTE} min ago and never stopped")
            if item:
                made.append(item)
    return made


def son_parks(repo: Path) -> list[dict[str, Any]]:
    """Tier 1: son-park incidents from each recent run's model ledger, copied to runs/<stamp>/incidents.jsonl."""
    from lanes.common import MODEL_LEDGER_NAME  # noqa: PLC0415 - lanes.py is the one module that names the supervisor files

    state: state_io.State = state_of(repo)
    made: list[dict[str, Any]] = []
    for stamp in sorted(state.runs())[-SON_RUNS_SCANNED:]:
        for row in state.read_rows(state_io.run_rel(stamp, MODEL_LEDGER_NAME)):
            reason: str = str(row.get("reason") or row.get("detail") or "")
            if not ((row.get("event") == "park" and reason in detect.SON_PARK_REASONS) or row.get("event") == "stuck"):
                continue
            lane: str = str(row.get("lane") or "-")
            item = record_incident(repo, category="son-park", session_id=f"run-{stamp}", agent_id=lane, klass="son", detected_by="reader",
                                   key=f"{row.get('t')}:{reason}", evidence={"reason": reason, "paths": []},
                                   what=f"son lane {lane} parked: {reason}")
            if item:
                made.append(item)
                state.append_event(state_io.run_rel(stamp, LEDGER_NAME), item)
    return made


def debrief(repo: Path, session_id: str, now: int) -> list[dict[str, Any]]:
    """Tier 2 debrief by counting: isolated, or trend when the signature shows in 3+ sessions within 14 days."""
    incidents: list[dict[str, Any]] = [i for i in incidents_merged(repo) if i.get("signature")]
    window: int = now - TREND_DAYS * SECONDS_PER_DAY
    state: state_io.State = state_of(repo)
    out: list[dict[str, Any]] = []
    for item in (i for i in incidents if i.get("session_id") == session_id):
        sessions: set[str] = {str(o.get("session_id")) for o in incidents if o["signature"] == item["signature"] and int(o["ts"]) >= window}
        label: str = LABEL_TREND if len(sessions) >= TREND_SESSIONS else LABEL_ISOLATED
        event: dict[str, Any] = state_io.make_event(KIND_DEBRIEF, ts=now, id=state_io.event_id(KIND_DEBRIEF, item["incident_id"], label),
                                                    incident_id=item["incident_id"], signature=item["signature"], label=label,
                                                    sessions=len(sessions), session_id=session_id)
        state.append_event(state_io.HEAD_LEDGER_REL, event)
        out.append(event)
    return out


def class_table(repo: Path, session_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [r for r in state_of(repo).read_rows(state_io.AGENTS_REL) if session_id is None or r.get("session_id") == session_id]
    table: dict[str, dict[str, Any]] = {}
    for row in rows:
        klass: str = str(row.get("agent_class") or detect.UNKNOWN_CLASS)
        entry: dict[str, Any] = table.setdefault(klass, {"agent_class": klass, "spawned": 0, "finished": 0, "partial": 0, "no_report": 0,
                                                         "incidents": 0, "rework": 0, "durations": []})
        kind: str = str(row.get("kind"))
        if kind == KIND_START:
            entry["spawned"] += 1
        elif kind == KIND_STOP:
            entry["finished"] += 1
            entry["partial"] += bool(row.get("partial"))
            entry["no_report"] += int(row.get("report_chars") or 0) < detect.NO_REPORT_CHARS
            if row.get("duration_s") is not None:
                entry["durations"].append(int(row["duration_s"]))
        elif kind == KIND_INCIDENT:
            entry["incidents"] += 1
            entry["rework"] += row.get("category") == "rework-other-agent"
    for entry in table.values():
        durations: list[int] = entry.pop("durations")
        entry["avg_duration_s"] = round(sum(durations) / len(durations)) if durations else None
    return sorted(table.values(), key=lambda e: e["agent_class"])


def brief_markdown(repo: Path, session_id: str, now: int) -> str:
    table: list[dict[str, Any]] = class_table(repo, session_id)
    lines: list[str] = [f"# Agent brief for session {session_id}", "", "| class | spawned | finished | partial | no-report | incidents | rework | avg s |",
                        "|---|---|---|---|---|---|---|---|"]
    for e in table:
        lines.append(f"| {e['agent_class']} | {e['spawned']} | {e['finished']} | {e['partial']} | {e['no_report']} | "
                     f"{e['incidents']} | {e['rework']} | {e['avg_duration_s'] if e['avg_duration_s'] is not None else '-'} |")
    mine: list[dict[str, Any]] = [i for i in incidents_merged(repo) if i.get("session_id") == session_id]
    lines += ["", "## Incidents", ""] + ([f"- {i['incident_id']} {i['category']} ({i['severity']}, {i.get('debrief') or 'not debriefed'}): "
                                          f"{i['what_happened']}" for i in mine] or ["- none"])
    return "\n".join(lines) + "\n"


def end_of_run(repo: Path, session_id: str, cfg: dict[str, Any], now: int) -> str | None:
    """Watchdog, son-park reader, debrief, per-session brief file and metrics row. Returns the one-line summary."""
    watchdog(repo, cfg, now)
    son_parks(repo)
    labels: list[dict[str, Any]] = debrief(repo, session_id, now)
    table: list[dict[str, Any]] = class_table(repo, session_id)
    spawned: int = sum(e["spawned"] for e in table)
    incidents: int = sum(e["incidents"] for e in table)
    if not table and not labels:
        return None
    path: Path = repo / state_io.BRIEFS_DIR_REL / f"{clean(session_id)}.md"
    state_io.atomic_write(path, brief_markdown(repo, session_id, now))
    trends: int = sum(1 for e in labels if e["label"] == LABEL_TREND)
    row: dict[str, Any] = state_io.make_event(KIND_BRIEFS, ts=now, id=state_io.event_id(KIND_BRIEFS, session_id, spawned, incidents),
                                              session_id=session_id, spawned=spawned, finished=sum(e["finished"] for e in table),
                                              incidents=incidents, trends=trends)
    state_io.append_event_at(repo / state_io.METRICS_REL, row)
    return (f"dts2 agents: {spawned} spawned, {sum(e['finished'] for e in table)} finished, {incidents} incidents"
            f"{f' ({trends} trend)' if trends else ''}; brief at {path.relative_to(repo).as_posix()}")


def throttled(repo: Path, session_id: str, now: int) -> bool:
    """True when the stop-time brief already ran for this session in the last 10 minutes; otherwise claims the slot."""
    verdict: list[bool] = []

    def claim(record: dict[str, Any]) -> None:
        if now - int(record.get("last", 0)) < BRIEF_THROTTLE_S:
            verdict.append(True)
            return
        record["last"] = now
        verdict.append(False)

    locked_json(repo, cache_path(f"incident-brief-{clean(session_id)}.json"), claim)
    return verdict[0]


def session_note(repo: Path, cfg: dict[str, Any], now: int) -> str | None:
    open_now: list[dict[str, Any]] = open_incidents(repo)
    hung: int = sum(1 for a in running_agents(repo, now)
                    if int(cfg["incident_hung_minutes"]) * SECONDS_PER_MINUTE <= a["age_s"] <= HUNG_LOOKBACK_S)
    parts: list[str] = [*drain_live(repo)]
    if open_now or hung:
        counts: dict[str, int] = {}
        for item in open_now:
            counts[str(item["category"])] = counts.get(str(item["category"]), 0) + 1
        detail: str = ", ".join(f"{n} {c}" for c, n in sorted(counts.items()))
        parts.append(f"dts2 incidents: {len(open_now)} open{f' ({detail})' if detail else ''}"
                     f"{f', {hung} agent(s) possibly hung' if hung else ''}. See /dts2:incidents.")
        if cfg["incidents_auto_review"] and any(n >= AUTO_REVIEW_MIN for n in counts.values()):
            parts.append("dts2 incidents: 3+ open incidents share a category; run /dts2:incidents review.")
    return "\n".join(parts) if parts else None


def run_hook(event: str, payload: dict[str, Any], now: int | None = None) -> dict[str, Any] | str | None:
    repo: Path = Path(str(payload.get("cwd") or Path.cwd()))
    if not (repo / state_io.HARNESS).is_dir():
        return None
    cfg: dict[str, Any] = settings(repo)
    if not cfg["incident_capture"]:
        return None
    moment: int = int(time.time()) if now is None else now
    session: str = str(payload.get("session_id") or DEFAULT_SESSION)
    if event == "pre-agent":
        return pre_agent(repo, payload, cfg, moment)
    if event == "subagent-start":
        return subagent_start(repo, payload, cfg, moment)
    if event == "subagent-stop":
        return subagent_stop(repo, payload, cfg, moment)
    if event == "post-tool-use":
        return post_tool_use(repo, payload, cfg, moment)
    if event == "session-start":
        return session_note(repo, cfg, moment)
    if event == "stop" and (payload.get("agent_id") or throttled(repo, session, moment)):
        return None
    line: str | None = end_of_run(repo, session, cfg, moment)
    return {"systemMessage": line} if line else None


def hook_main(event: str) -> int:
    try:
        payload: Any = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        result: dict[str, Any] | str | None = run_hook(event, payload)
        if result:
            print(result if isinstance(result, str) else json.dumps(result))
    except Exception:  # noqa: BLE001 - an event hook must never fail the session
        return 0
    return 0


# --- CLI -------------------------------------------------------------------------------------------------------------
def cmd_list(repo: Path, args: argparse.Namespace) -> Any:
    items: list[dict[str, Any]] = open_incidents(repo) if args.open else incidents_merged(repo)
    return items


def cmd_live(repo: Path) -> dict[str, Any]:
    now: int = int(time.time())
    out: dict[str, Any] = {"running": running_agents(repo, now), "lanes": None}
    stamp: str | None = current_run(repo)
    script: Path = Path(__file__).resolve().parent / "lanes.py"
    if stamp and script.is_file():
        try:
            done = subprocess.run([sys.executable, "-I", str(script), "status", stamp], capture_output=True, text=True,
                                  timeout=LANES_TIMEOUT_S, check=False, cwd=str(repo))
            out["lanes"] = json.loads(done.stdout) if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            out["lanes"] = None
    return out


def latest_session(repo: Path) -> str | None:
    rows: list[dict[str, Any]] = [r for r in state_of(repo).read_rows(state_io.AGENTS_REL) if r.get("session_id")]
    return str(rows[-1]["session_id"]) if rows else None


def cmd_resolve(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    known: dict[str, dict[str, Any]] = {str(i["incident_id"]): i for i in incidents_merged(repo)}
    if args.incident_id not in known:
        return {"ok": False, "detail": f"no incident {args.incident_id}"}
    cause: str = args.root_cause.strip() or NONE_FOUND
    event: dict[str, Any] = state_io.make_event(KIND_RESOLUTION, incident_id=args.incident_id, root_cause=cause, how_resolved=args.how.strip())
    state_of(repo).append_row(state_io.AGENTS_REL, event)
    return {"ok": True, "incident_id": args.incident_id, "root_cause": cause, "how_resolved": args.how.strip()}


def lesson_table(repo: Path, now: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tier in (learn.TIER_PROJECT, learn.TIER_HARNESS, learn.TIER_KNOWLEDGE):
        for lid, entry in sorted(learn.sidecar_for(tier, repo).entries().items()):
            rows.append({"id": lid, "tier": tier, **{k: entry.get(k) for k in learn.EMPTY_STATS}, "status": learn.lesson_status(entry, now)})
    return rows


def trend_counts(repo: Path, now: int) -> dict[str, dict[str, int]]:
    window: int = now - TREND_DAYS * SECONDS_PER_DAY
    seen: dict[str, dict[str, set[str]]] = {}
    for item in incidents_merged(repo):
        if item.get("signature") and int(item["ts"]) >= window:
            bucket: dict[str, set[str]] = seen.setdefault(str(item["signature"]), {"sessions": set(), "incidents": set()})
            bucket["sessions"].add(str(item.get("session_id")))
            bucket["incidents"].add(str(item["incident_id"]))
    return {sig: {"sessions": len(b["sessions"]), "incidents": len(b["incidents"])} for sig, b in sorted(seen.items())}


def cmd_review_input(repo: Path) -> dict[str, Any]:
    now: int = int(time.time())
    table: list[dict[str, Any]] = lesson_table(repo, now)
    counts: dict[str, dict[str, int]] = trend_counts(repo, now)
    return {"open_incidents": open_incidents(repo), "trends": {s: c for s, c in counts.items() if c["sessions"] >= TREND_SESSIONS},
            "signature_counts": counts, "lessons": table, "demoted": [r["id"] for r in table if r["status"] == "demoted"],
            "expired": [r["id"] for r in table if r["status"] == "expired"], "trend_threshold": {"sessions": TREND_SESSIONS, "days": TREND_DAYS}}


def cmd_promote(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    if args.tier == "harness":
        return learn.promote_harness(repo, args.ref, args.text, date.today())
    return learn.promote_knowledge(repo, args.ref, args.text)


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repo root (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="run one hook handler (JSON on stdin)")
    hook.add_argument("event", choices=HOOK_EVENTS)
    lister = sub.add_parser("list")
    lister.add_argument("--open", action="store_true")
    lister.add_argument("--json", action="store_true")
    sub.add_parser("live")
    brief = sub.add_parser("brief")
    brief.add_argument("--session", default=None)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("incident_id")
    resolve.add_argument("--root-cause", required=True)
    resolve.add_argument("--how", required=True)
    lesson = sub.add_parser("lessons")
    lesson.add_argument("action", choices=("stats",))
    promote = sub.add_parser("promote")
    promote.add_argument("--tier", choices=("harness", "knowledge"), required=True)
    promote.add_argument("ref", help="lesson id such as L-014, or a signature category|class|glob")
    promote.add_argument("--text", default=None, help="rule text when promoting a signature")
    sub.add_parser("review-input")
    return parser


def render_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "no incidents"
    return "\n".join(f"{i['incident_id']} {i['category']} {i['severity']} [{i['how_resolved']}] {i['what_happened']}" for i in items)


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    if args.command == "hook":
        return hook_main(args.event)
    repo: Path = Path(args.repo)
    now: int = int(time.time())
    if args.command == "list":
        items: list[dict[str, Any]] = cmd_list(repo, args)
        print(json.dumps(items) if args.json else render_list(items))
        return 0
    if args.command == "brief":
        session: str | None = args.session or latest_session(repo)
        print(brief_markdown(repo, session, now) if session else "no agent activity recorded", end="")
        return 0
    results: dict[str, Any] = {"live": lambda: cmd_live(repo), "resolve": lambda: cmd_resolve(repo, args),
                               "lessons": lambda: lesson_table(repo, now), "promote": lambda: cmd_promote(repo, args),
                               "review-input": lambda: cmd_review_input(repo)}
    result: Any = results[args.command]()
    print(json.dumps(result))
    return 0 if not isinstance(result, dict) or result.get("ok", True) or result.get("skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
