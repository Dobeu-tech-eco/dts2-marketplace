Ship status: pending independent review and GitHub checks.

Task 1 evaluation: Chairman/head/tiebreaker now names latest-frontier-claude in the Claude profile and autopilot specification. scripts/chairman.py resolves the evidenced authenticated runtime catalog, selects the highest ranked generally available frontier Claude, or the best available Claude fallback. It writes the selected identity and aliases; the specification requires recording each dispatch attempt and the successful runtime response's actual identity. No eligible Claude parks. Council allocation requires that resolution record and excludes Chairman identity/aliases from seats and bench; overlap with a panel voter parks.

As of November 10, 2026 the current generally available frontier target is Claude Fable 5.2, per Anthropic's November 9 release and model documentation:
https://www.anthropic.com/claude-fable-and-mythos-5-2
https://platform.claude.com/docs/en/models/fable-5-2/whats-new-fable-5-2
This dated evaluation is separate from each run's authenticated availability resolution; no live Chairman inference was executed for this documentation change. Mythos 5.2 is vetted-organization restricted and explicitly excluded from the general seat, including when an individual org has access.

The three frontier voter panel, tiebreak decisions, mandatory dissent briefs, red-check hard stops, HEAD-pinned human-default dts2_approvals, sons' inability to write approvals, and standing merge_policy remain in force.

Task 2 canonical commands (derived from runtime skills/*/SKILL.md):
/dt:action-items, /dt:ask-expert, /dt:autopilot, /dt:check-in, /dt:composio, /dt:cooldown, /dt:dpp, /dt:dpp-full, /dt:evolve, /dt:feature, /dt:find-skills, /dt:fleet, /dt:fullauto, /dt:gtm, /dt:incidents, /dt:knowledge, /dt:learn, /dt:machine-prep, /dt:model, /dt:onboard, /dt:pr-sweep, /dt:repo-sweep, /dt:run, /dt:sdk, /dt:setup, /dt:ship, /dt:steer

Sweep (reference cleanup only):

| File | Stale reference | Action |
|---|---|---|
| docs/superpowers/plans/2026-10-21-dts2-v3.md | /dts2-harness:action-items | /dt:action-items |
| docs/superpowers/plans/2026-10-21-dts2-v3.md | /dts2-harness:evolve | /dt:evolve |
| docs/superpowers/plans/2026-10-21-dts2-v3.md | /dts2-harness:run | /dt:run |
| docs/superpowers/plans/2026-10-21-dts2-v3.md | /dts2-harness:setup | /dt:setup |
| docs/superpowers/specs/2026-10-21-dts2-v3-design.md | /dts2-harness:action-items | /dt:action-items |
| docs/superpowers/specs/2026-10-21-dts2-v3-design.md | /dts2-harness:evolve | /dt:evolve |
| docs/superpowers/specs/2026-10-21-dts2-v3-design.md | /dts2-harness:run | /dt:run |
| docs/superpowers/specs/2026-10-21-dts2-v3-design.md | /dts2-harness:setup | /dt:setup |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:action-items | /dt:action-items |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:autopilot | /dt:autopilot |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:check-in | /dt:check-in |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:dpp | /dt:dpp |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:dpp-full | /dt:dpp-full |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:feature | /dt:feature |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:find-skills | /dt:find-skills |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:fullauto | /dt:fullauto |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:model | /dt:model |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:ship | /dt:ship |
| plugins/dts2-runtime/CHANGELOG.md | /dts2-harness:upgrade | removed invocation; historical description |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:action-items | /dt:action-items |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:autopilot | /dt:autopilot |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:check-in | /dt:check-in |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:dpp | /dt:dpp |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:dpp-full | /dt:dpp-full |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:feature | /dt:feature |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:find-skills | /dt:find-skills |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:fullauto | /dt:fullauto |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:model | /dt:model |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:ship | /dt:ship |
| plugins/dts2-harness/CHANGELOG.md | /dts2-harness:upgrade | removed invocation; historical description |
| plugins/dts2-runtime/scripts/fleet.py | dt:handoff | dt:check-in |
| plugins/dts2-runtime/skills/setup/phase-2-scaffold.md | /dts2-harness:run | /dt:run |
| plugins/dts2-harness/skills/setup/phase-2-scaffold.md | /dts2-harness:run | /dt:run |
| plugins/dts2-runtime/tests/test_fleet.py | dt:handoff | dt:check-in |

Legacy migration inputs in agent-memory.py and its test deliberately retain old namespace for compatibility; no behavior change.
Role references (dt:lead/builder/reviewer/verifier/scout/fixer/auditor/incident-reviewer) are agent definitions, not commands.
