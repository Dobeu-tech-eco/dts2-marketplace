# run — Phase 1, plan

## Phase 1 — Plan (lead)
Dispatch `dts2-harness:lead` (seat: sign-off, tier `frontier`) with `model` = claude `frontier` (`opus`). Give it: the task verbatim, `.harness/config.yaml`, `.harness/end-state.md`, `.harness/discipline.md`, `.harness/lessons.md`, the scout report, the roster JSON, the probe JSON, and the workspace manifest if present. Tell it:
A lead report whose first line is `PARTIAL: hit turn cap at <step>` is not a plan: do not open the checkpoint; re-dispatch the lead with a narrower scope or a fresh agent, inside the fix-loop cap.
- Assign only agents in the probe's `usable` list. Builders are execution seats at every complexity: the cheapest capable agent by profile `tokenBurn.standard` (ties broken by `costTier`), never a frontier model. Axis reviews are advisory seats: the cheapest available agent whose roles include the seat. The strongest agent holds the sign-off seats: the plan, the verifier, and the final review (the `lead_provider` setting picks which provider, default claude).
- Rate every `### Builder N` with `complexity: mechanical|normal|design`.
- Plan from the `## Sections` table and end the plan with `## Ready queue` for sections that are ready but beyond the builder cap.

**Plan checkpoint.** It will not open without the lead's `## Done` section with at least one line. If the section is missing or empty, send the plan back to the lead once with "Add the Done section: one outcome per line with its check method." Still missing → stop and say why.

Show, in this order:
- The plan as the lead wrote it, including `## Done` and `Axes:`.
- `Team: N builders on separate file sets`, reviewer axes, and one line per seat: `<role> — <agent> (<tier>, effort <e>, <auth>)`, where auth is `subscription`, `api-key`, `installed (unverified)`, or `handoff` for IDE agents, for example `builder 2 — codex (standard, effort medium, api-key)`.
- One line per dropped agent: `Dropped: <agent> — <reason>`.
- The output of `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/metrics.py" <repo> trend` as one line (`Trend: no runs yet` on a first run).
- When `## Sections` exists, the whole batch in one line: `Sections this run: <n> of <total> (ready now: <k>, queued: <q>, blocked: <b>)`.
- **Harness sweep (evolve).** When `.harness/harness-lessons.md` has open lessons (lines not marked `done` or `dropped`), one line: `Harness improvements pending: <n> — applied through evolve after ship.` Nothing else happens here.

**Blueprint check.** If `.harness/end-state.md` has a `## Blueprint` block, the plan must carry a `## Blueprint coverage` section mapping every layer to `Builder N` or `unchanged`. A layer with no mapping blocks the checkpoint: send the plan back to the lead once with `Blueprint layer <x> unmapped`. Still unmapped → stop and say why.

Then say exactly: "Here is the plan, the done-criteria, and who does what. Approve, edit, or stop." Silence means stop. On edit, revise with the lead and show the checkpoint again. Any choice the user defers here goes to `.harness/action-items.md` → `## Decisions` as `| <item> | <context> | open | | <YYYY-MM-DD> |` (create the file from `${CLAUDE_PLUGIN_ROOT}/templates/action-items.md` if absent).
