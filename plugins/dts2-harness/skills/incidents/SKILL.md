---
name: incidents
description: See and learn from agent incidents (hung spawns, missing or partial reports, rework of another agent's files). Subcommands list, live, brief, review, resolve, promote, lessons. Use for incidents, what went wrong with an agent, or review the shift.
---

# Incidents — catch agent problems, learn from them

Hooks write every subagent start, stop and incident to `.harness/agents.jsonl` with no model call. This skill reads that record. All counting is plain Python; the only model step is `review`.

All commands: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/incidents.py" <sub>`.

## Two loops
1. **Live correction (the floor supervisor).** When a detector fires mid-run (rework of another agent's file, a hung spawn, a partial or empty report, a thin brief), the hook tells the lead on its next turn what happened and what to do. No model is spawned by the hook. At spawn time the SubagentStart hook also injects up to 3 matching lessons into the agent's context and logs each one in `.harness/injections.jsonl`.
2. **End-of-shift debrief.** On Stop and SessionEnd a hook writes `.harness/briefs/<session>.md`: per agent class, spawned, finished, partial, no-report, incidents, rework, average duration. `review` turns open incidents into root causes and lessons.

## Subcommands
- `list [--open] [--json]` — incidents with id, category, severity, agent and status. `--open` keeps only unresolved ones.
- `live` — agents started and not stopped (age, class, parent) plus active son lanes. A hung agent shows here first.
- `brief [--session S]` — print the end-of-run brief for this session, or for session S.
- `resolve <id> --root-cause "<text>" --how "<text>"` — close one incident by hand.
- `lessons stats` — helpful, harmful and unused counts per lesson, and which are demoted or expired.
- `promote --tier harness|knowledge <id>` — move a trend one tier up (see the ladder below).
- `review` — the debrief, described next.

## review
1. Run `python3 "$CLAUDE_PLUGIN_ROOT/scripts/incidents.py" review-input`. When it lists no open incidents, say so and stop; no model is spawned.
2. Spawn the `incident-reviewer` agent (`Agent(subagent_type: dts2:incident-reviewer)`, model `sonnet`; `haiku` is allowed for a short list) with that JSON as the whole brief.
3. Read its report and apply it in this order:
   - `## Incidents`: for each id run `resolve <id> --root-cause "<text>" --how "<text>"`. "none found" is a valid root cause. Keep the isolated or trend mark.
   - `## Lessons`: append each local lesson line to `.harness/lessons-inbox.md`, then run the normal `learn` flow so the user approves it into `lessons.md`.
   - `## Promote`: for each trend that meets the tier threshold below, run `promote --tier <tier> <id>`. A tier whose store is not set up is skipped with a note.
   - `## Harness`: every `harness:` line goes into `lessons-inbox.md` as written; `learn` files it in `harness-lessons.md` and `evolve` offers it as a plugin change. Never edit the plugin from here and never apply one without an explicit yes.
   - `## Lesson feedback`: apply each demote or keep with the helpful and harmful counts from `lessons stats`.
4. Report in one short message: incidents resolved, lessons queued, trends promoted, harness lines waiting for `evolve`.

## Tier ladder
A signature is `category + agent class + top path glob`, so one failure is counted as one trend. Each tier passes only trends (and counts) up; incidents marked isolated stay where they are.

| Tier | Scope | Goes up when (defaults) |
|---|---|---|
| 1 Son | one run or lane | always summarized up at run end |
| 2 Project | this repo, the lead | same signature in 3+ sessions within 14 days |
| 3 Harness | this device, all projects | same signature in 2+ projects |
| 4 Knowledge store | all devices, via `/dts2:knowledge` | plugin-caused and seen on 2+ devices or projects |
| 5 Marketplace | all users | never automatic: `harness:` line, `evolve`, a PR, an explicit yes |

## Lesson matching
A lesson line can carry optional fields that steer injection: `{paths: src/api/**}` matches the brief's file paths, `{cat: rework-other-agent}` ties it to an incident category (used to score it harmful when that incident repeats), and `{agents: builder, reviewer}` limits it to those agent classes. A line without fields can match any spawn.

## Lesson feedback
Agents end a report with `Lessons: L-012 helpful, L-019 not-helpful, L-020 unused`. A lesson whose harmful count reaches helpful plus 2 is demoted: no agent sees it again and it waits for review. A lesson unused 10 times in a row, or idle 30 days, expires.

## Settings
`incident_capture` (default true), `incident_hung_minutes` (20), `incident_brief_min_chars` (200), `incidents_auto_review` (false). With `incidents_auto_review` on, SessionStart only nudges the lead to run `review` when three or more open incidents share a category.

## Notes
- A hook never spawns a model. `review` is the only paid step, about one sonnet or haiku call, and only when incidents are open.
- The reviewer is read-only. All writes in this skill are done by you, through `incidents.py` and the learn flow.
