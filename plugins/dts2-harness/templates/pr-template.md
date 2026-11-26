## Summary

<what changed and why, in two or three sentences>

## Linked work

- Section / roadmap item: <end-state section # and name, feature slug, or "none">
- Action items closed: <ids from .harness/action-items.md, or "none">
- Supersedes / folds: <PR numbers this one replaces or absorbs, or "none">
- Follows: <the PR this one builds on, as #<n>, or "none">
- Merge: merge commit only (no squash, no rebase)

## Type

- [ ] feat
- [ ] fix
- [ ] refactor
- [ ] chore / deps
- [ ] docs
- [ ] test

## Pre-checks

- [ ] Skills pre-check ran (companions and keep.yaml skills current)
- [ ] Type-check, lint, tests and build pass locally (commands in the receipt below)
- [ ] No secrets in the diff (scan clean)
- [ ] No `do_not_touch` paths changed
- [ ] New or changed behaviour has a test
- [ ] Docs, `.env.example` and the end state updated where this change touches them

## Consensus (autopilot only)

<three frontier verdicts per round and the tiebreak; if the step went to council, the council tally, the head of council's decision, its rationale and its response to each dissent; or "n/a: human approved">

## Decisions and declined findings

<generated from the ledger: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_payload.py" decisions --ledger <ledger>`; each decision and each finding the builder declined, with the reason, or "none">

## Screenshots / walkthrough

<changed screens, or "n/a">

## Change receipt

### Tests run

| Command | Pass | Fail | Skip |
|---|---|---|---|
| <command> | 0 | 0 | 0 |

### Merge danger

Merge danger: <one-way | two-way> door — blast radius: <who or what breaks if this is wrong>

### Evidence

<before and after: a test that failed before this change and passes now, a command's output, or a screenshot pair; or "none" with the reason>

### Review verdict

<verdict>

### Approved by

<name, date>

### Steps outside this change

<steps or "none">

### Open risks

<risks or "none">

### Rollback point

<commit SHA or tag>
