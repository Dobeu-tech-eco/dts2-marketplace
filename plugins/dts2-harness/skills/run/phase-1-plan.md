> Directory edition: do not run bundled scripts or hooks, a package launcher, or a download piped into a shell. Do not read tokens or credential files from the machine. Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.

# run — Phase 1, plan

## Phase 1 — Plan (lead)
Dispatch `dt:lead` (seat: sign-off, tier `frontier`) with `model` = claude `frontier` (`opus`) and `effort: high`. Give it one page, not raw JSON: save the task to a file, then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/briefs.py" lead-brief --stamp <stamp> --task-file <task file> --roster-json <roster.py resolve output> --probe-json <roster.py probe output>` and hand the lead its output. It carries the task verbatim, the roster and probe in a few lines each, and the deterministic check results, and it points at `.harness/config.yaml`, `.harness/end-state.md`, `.harness/discipline.md` and `.harness/lessons.md`, which the lead reads itself. Add the scout report and the workspace manifest if present. Never paste the roster, probe or ledger JSON into the dispatch. Tell it:
A lead report whose first line is `PARTIAL: hit turn cap at <step>` is not a plan: do not open the checkpoint; re-dispatch the lead with a narrower scope or a fresh agent (same `model` and `effort`), inside the fix-loop cap.
- Assign only agents in the probe's `usable` list. Builders are execution seats at every complexity: the cheapest capable agent by profile `tokenBurn.standard` (ties broken by `costTier`), never a frontier model. Axis reviews are advisory seats: the cheapest available agent whose roles include the seat. The strongest agent holds the sign-off seats: the plan, the verifier, and the final review (the `lead_provider` setting picks which provider, default claude).
- Rate every `### Builder N` with `complexity: mechanical|normal|design`.
- Plan from the `## Sections` table and end the plan with `## Ready queue` for sections that are ready but beyond the builder cap.
- Put a `## Foundation` section (`wave: 0`) before the builders: shared types, config, schema and skeleton built first, or `Foundation: none needed — <why>`.
- Prefer vertical slices: one builder per feature across data, api and ui, tests with it, not one builder per layer. Where two builders share a contract, declare it on the sections: `provides:` on the builder that creates it, `consumes:` on the one that uses it, and `stubbed_on:` when the consumer can build against a stub and start at once (it still merges after its provider).
- A parallel son's brief has six parts: Goal, Files owned, Files read-only, Interfaces, Order and timing, Done when; the dpp skill prints the skeleton with `plan_graph.py brief`.
- Owners are files, `dir/` prefixes or globs; never an empty set and never the whole repo. A builder that owns a package manifest owns the lockfile beside it.

**Plan checkpoint.** It will not open without the lead's `## Done` section with at least one line. If the section is missing or empty, send the plan back to the lead once with "Add the Done section: one outcome per line with its check method." Still missing → stop and say why.

**Plan gate.** Save the plan to `.harness/runs/<stamp>/plan.md`, then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan-gate.py" .harness/runs/<stamp>/plan.md`. It checks the `## Foundation` section, exclusive file ownership (no file or dir/ prefix owned twice), a `complexity:` per builder with its model and effort (never frontier), and prints estimated tokens. `PLAN GATE: FAIL` blocks the checkpoint: send the plan back to the lead once with the `FAIL:` lines. Still failing → stop and say why.

Show, in this order:
- The plan as the lead wrote it, including `## Done` and `Axes:`.
- The `plan-gate.py` output verbatim: one model and effort line per builder, `Estimated tokens: ~N`, and `PLAN GATE: PASS`.
- `Team: N builders on separate file sets`, reviewer axes, and one line per seat: `<role> — <agent> (<tier>, effort <e>, <auth>)`, where auth is `subscription`, `api-key`, `installed (unverified)`, or `handoff` for IDE agents, for example `builder 2 — codex (standard, effort medium, api-key)`.
- One line per dropped agent: `Dropped: <agent> — <reason>`.
- The output of `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/metrics.py" <repo> trend` as one line (`Trend: no runs yet` on a first run).
- For parallel dpp runs, the `graph` block of the dpp plan output: its `critical_path_line` and any `errors` (a cycle, an unresolved `consumes`, overlapping owners) before the table; an error blocks the checkpoint until the lead fixes the plan.
- When `## Sections` exists, the whole batch in one line: `Sections this run: <n> of <total> (ready now: <k>, queued: <q>, blocked: <b>)`.
- **Harness sweep (evolve).** When `.harness/harness-lessons.md` has open lessons (lines not marked `done` or `dropped`), one line: `Harness improvements pending: <n> — applied through evolve after ship.` Nothing else happens here.

**Blueprint check.** If `.harness/end-state.md` has a `## Blueprint` block, the plan must carry a `## Blueprint coverage` section mapping every layer to `Builder N` or `unchanged`. A layer with no mapping blocks the checkpoint: send the plan back to the lead once with `Blueprint layer <x> unmapped`. Still unmapped → stop and say why.

First run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo> --checkpoint "plan checkpoint, run <stamp>: plan shown, waiting for approve, edit or stop"`, so a session that ends here resumes at the checkpoint, not at the first action item; on approve or stop run it again with `--clear-checkpoint`. Then say exactly: "Here is the plan, the done-criteria, and who does what. Approve, edit, or stop." Silence means stop. On approve, append `- plan approved by <who>, <YYYY-MM-DD>` to `.harness/runs/<stamp>/state.md`; the context guard reads that line (or a saved `plan.md`) as the plan checkpoint, so a long build after approval is not stopped as a pre-plan spike. On edit, revise with the lead and show the checkpoint again. Any choice the user defers here goes to `.harness/action-items.md` → `## Decisions` as `| <item> | <context> | open | | <YYYY-MM-DD> |` (create the file from `${CLAUDE_PLUGIN_ROOT}/templates/action-items.md` if absent).
