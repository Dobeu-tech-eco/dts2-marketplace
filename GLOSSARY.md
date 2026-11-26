# Glossary

The words the harness uses, each with one meaning.

## For people

Use this page when a skill, a plan or a review uses a word you do not recognise. Each row gives the term, what it means in this repository, and the words not to use in its place. The full workflow is in [the guide](plugins/dts2-runtime/docs/GUIDE.md).

## For agents

- Use the **Term** column, spelled as shown, in code, plans, briefs, reviews and pull requests. Do not use a word from the **Avoid** column for the same idea.
- Add a row in the same change that introduces a new harness concept. Keep each meaning to one line.
- `tests/test_metadata_ci.py` checks that every row has all three cells and that `AGENTS.md` links this page.

## Terms

| Term | Meaning | Avoid |
|---|---|---|
| head | The one Claude session that plans lanes, grants merges and talks to the user during `dpp` or `autopilot`. | orchestrator, master, main agent |
| son | A headless `autopilot --son` process that builds one lane in its own worktree and reports to the head, never to the user. | child, worker, subagent |
| lane | One disjoint file set with its tasks, branch, lease and merge order, run by one son. | track, stream, shard |
| lead | The read-only role that slices the end state into tasks with exclusive file ownership. It never writes code. | planner, architect, PM |
| builder | The role that implements one section of the lead's plan inside its owned files. It never reviews its own work. | coder, implementer, dev agent |
| reviewer | The read-only role that rates a diff on its axes and returns a verdict. It never edits. | critic, checker |
| verifier | The read-only role that runs the configured build, type, lint and test commands and collects evidence. It never fixes. | tester, QA agent |
| scout | The read-only role that sizes a repository and recommends a team tier before planning. | explorer, surveyor |
| auditor | The read-only role that inventories a machine's agent tooling against a profile. | inspector, scanner |
| fixer | The fresh-context role that takes fix round 2 on the same failure with the hypothesis the lead picked. | debugger, patcher |
| council | Five frontier seats that sit only after three failed autopilot rounds, vote blind, and are decided by the Chairman. | panel, jury, committee |
| end state | The approved description of done for a project, with numbered sections, kept in `.harness/end-state.md`. | spec, PRD, requirements doc |
| receipt | The record that closes a run: tests run, merge danger, evidence, verdict, approver, open risks and rollback point. | summary, report, changelog |
| ledger | An append-only JSON Lines record of checks, decisions or tasks, such as `.harness/runs/<stamp>/ledger.jsonl`. | log, journal, history file |
| handoff | The resume pointer at `.harness/handoff/latest.md` that the next session reads first. | notes, context dump |
| roster | The confirmed list of agents and providers a project may use, and the seats each one fills. | team list, model list |
| keep-set | The plugins and companion skills a profile or `.harness/keep.yaml` says must stay on. | allowlist, whitelist |
| tier | The prune level `machine-prep` applies: light, standard or strict. | mode, level, preset |
| action item | A row in `.harness/action-items.md` that a person must act on, such as a missing secret or a decision. | todo, ticket, task |
| lesson | A rule learned from a run and stored in `.harness/lessons.md` for every later run to read. | memory, note, insight |
| incident | A recorded harness failure that `incidents.py` tracks until a review finds its root cause. | bug, outage, error |
| one-way door | A change that cannot be undone after it lands, such as a merge to public `main`, a published release or pushed history. | irreversible-ish, risky change |
| two-way door | A change that can be reverted cheaply, such as a local edit, a draft pull request or a branch. | safe change, minor change |
| merge danger | The pull request line that names the door type and the blast radius: who or what breaks if the change is wrong. | risk level, severity |
| instruction edition | The generated copy of the plugin in `plugins/dts2-harness/`, written by `directory_edition.py`. | lite version, docs build |
| Cursor surface | The generated Cursor files in `.cursor/`, `.cursor-plugin/` and `plugins/dt-cursor/`, written by `cursor_surface.py`. | Cursor port, Cursor build |
