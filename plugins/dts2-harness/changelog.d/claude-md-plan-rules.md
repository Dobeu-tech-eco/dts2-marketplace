### Added
- `claude-md-rules.py` (`plan`, `apply`, `check`) adds the planning, checks-over-prose and Merge danger rules to a user's `CLAUDE.md` between `dts2-plan-rules` markers; `machine-prep` step 7 shows the diff and writes only after a yes.
- PR template, plugin PR template and receipt carry `### Merge danger` (one-way or two-way door, blast radius) and `### Evidence` (before and after); tests pin both.

### Changed
- `discipline.md` rule 4: prose rules are for judgement calls only; a recurring mistake becomes a lint rule, test or hook.
