# Team charter

Optional. Copy this file to the root of a repo that uses the harness (or to `.harness/TEAM.md`) when you want named providers on the seats the harness already assigns. If this file is not in the repo, `/dt:model`, lanes and the autopilot vote assign those seats exactly as they do today.

`scripts/team_charter.py` is the only reader. It does not start a provider, call a connector, or grant a merge, a deploy or a spend.

## Roles

The Providers column is tried left to right. The first name the roster probe marks available is used. A name that is missing, cooling, or whose CLI, MCP server or other connector does not answer is skipped. When none of the names answer, that role uses the harness roster, the command prints one warning line, and the run continues.

| Role | Seat | Providers |
| --- | --- | --- |
| lead | lead | claude |
| builder | execution | codex, claude |
| reviewer | advisory | grok, claude |
| playtester | signoff | claude |
| copywriter | advisory | gemini, claude |
| dispatcher | lead | claude |

`lead` is the planner. `/dt:model` still stores `lead_provider`; this row is the preference, and `lead_provider` is the fallback when every name here is unreachable. `builder` is the execution seat lanes dispatch. `reviewer` is the advisory seat. `playtester` is the verifier (sign-off, read-only): it reports bugs and does not fix them. `copywriter` is an advisory handoff for the README, the changelog and user-facing strings. `dispatcher` is the lead filing the next task through `roster.py` and `lanes.py`. It is not a second orchestrator.

A combined `lead/planner` row sets the lead. A combined `reviewer/playtester` row sets both seats when each has no row of its own.

## Rules

- Every handoff uses the seven-field brief (`templates/brief.md`, rendered by `team_charter.py brief`): objective, context, scope, authorized and prohibited actions, inputs, deliverable and evidence, deadline and dependencies.
- A review loop stops after 3 rounds. The next round asks the person (`team_charter.py review-cap`). The five-round fix cap for a red check is unchanged.
- Merges, deploys and spending need an explicit human approval. A confident review does not merge, deploy or spend.
- An unreachable seat is one warning line and the next provider, or the harness roster. It never fails the run.

## Brief

Objective, context, scope, authorized and prohibited actions, inputs, deliverable and evidence, deadline and dependencies. The renderer always states that merges, deploys and spending stay with the person.
