# dt 5.3.0: council plan and adjudication

Council date: 2026-11-16. Base: `main` at `660010d`. Release branch: `claude/project-thread-218ldt`, one PR to `main`.

## Outcome

- **Ships in this PR:** dt runtime 5.3.0. It covers the version and changelog fix, a CI release gate that stops this from happening again, the rolled-up Dependabot bumps, a test that keeps fleet-ledger optional, and the guides.
- **Versions that do not move:** the directory edition (`dts2-harness`) and the Cursor surface stay at 6.0.0. `fleet-ledger` stays at 0.1.0 and stays optional.
- **Done when:**
  - CI on the PR is green (`test (3.12)`, `lint`, `metadata`, including the new release gate).
  - Jeremy merges it.
  - The post-merge checks in the setup guide read back 5.3.0.

## Inputs

1. *Version fix write-up* (Frontline): the 5.2.0 to dev to main promote shipped new content under an unchanged version.
2. *dt simplification plan*, draft 1: workstreams A to E and conflicts 1 to 5.
3. *dt + Fleet Ledger unified proposal* (Muse): increments A, B and C, plus the decisions requested of Jeremy.

## How the council ruled

Lenses: Architect, Operator, Skeptic, Guardian, Strategist, with the Steward synthesising.

Four rules decided every item:

1. **Ship what is verified today.** An item enters this PR only if it has tests and passes CI in this branch.
2. **No behaviour change that needs a MAJOR.** The runtime cannot take 6.0.0, because the directory edition already uses that line (write-up section 2).
3. **No spend and no unattended merges to main.** Supabase Pro is not authorised, and no change may widen merge rights.
4. **Hard gates beat votes.** Tests, the secret scan and `do_not_touch` cannot be overridden by any council or vote.

## Adjudication

Status values: **Implemented** (in this PR), **Already shipped** (merged before this PR), **Deferred** (with the reason and what unblocks it), **Dismissed** (with the reason).

### Version fix write-up

| Item | Status | Reason |
|---|---|---|
| 1.1 to 1.2: the promote skipped the release step | Implemented | The runtime goes to 5.3.0 in all four version slots (`bump-version.py 5.3.0 --check` passes). |
| 1.3: things that are not wrong | Implemented | The 6.0.0 editions and `fleet-ledger` 0.1.0 were left alone. `test_listing_version_is_independent_of_the_runtime` still passes. |
| 2: MINOR to 5.3.0, not 6.0.0 | Implemented | The PR adds `/dt:go` and adds ship gates. It removes nothing. |
| Step 1: bump | Implemented | `plugin.json`, `marketplace.json`, the README badge line and the CHANGELOG header. |
| Step 2: cut the changelog | Implemented | `## [5.3.0]` and `## [5.2.0]` are cut from the `changelog.d/` fragments, and the fragments are removed. |
| Step 2 side issue: `changelog-join.py` read `changelog.d/README.md` as a fragment | Implemented | `FRAGMENT_SKIP={"README.md"}`. Found during the cut. |
| Step 3: stale labels (5.1.1 header, "28 skills") | Implemented | COMMAND-GUIDE now says 5.3.0, and the root README says 29 skills. The Cursor surface keeps 28 on purpose. |
| Step 4: regenerate the editions | Implemented | Both generators were re-run, and both `--check` runs exit 0. Only content changed, and no versions moved. |
| Step 5: test | Implemented | 3,143 tests pass, ruff is clean, context-tax is 0. |
| Step 6: ship | Implemented | This PR. Jeremy merges it. |
| 4: post-merge verification | Implemented as a checklist | These checks can only run after the merge. They are in `setup-guide.md`, "After the 5.3.0 merge". |
| 5: release gate for main | Implemented | `scripts/release-gate.py` (8 tests) runs in CI on every PR to `main`. If shipped plugin files changed, the PR fails unless the version is higher than the base and `CHANGELOG.md` has a `## [X.Y.Z]` entry. It writes a JSON verdict, so `/dt:ship` and local runs can call the same check. |
| 5: one checklist line ("a promote to main is a release") | Implemented | The gate enforces it in CI, and the setup guide says it in maintainer notes. |
| 6: retarget the Grok catalog item to the 5.3.0 merge commit | Deferred | It needs the merge commit SHA, which exists only after Jeremy merges. It happens outside this repo. Owner: Jeremy, right after the merge. |

### Simplification plan

| Item | Status | Reason |
|---|---|---|
| A: `/dt:go` router (`next_step.py`) | Already shipped | Merged in #119 and released in 5.3.0. |
| A: works with or without fleet-ledger and Supabase | Implemented | The router has no fleet-ledger dependency. `tests/test_fleet_ledger_optional.py` scans the scripts, hooks, skills, roles, commands and SDK for any reference, and fails on a hit. The setup guide says `dt` on its own gives the full `/dt:go` path. |
| B1: tooling round inside setup | Deferred | Not needed for 5.3.0. `/dt:find-skills` already does this job on demand. It waits on Phase 0 answers (Muse section 14) and a design pass so setup stays short. |
| B2: fleet round (seat cards, ledger connection) | Deferred | It depends on the Fleet Ledger pilot (increment B), and Supabase is not authorised. |
| B3: Composio T3 mapping | Deferred | The connector is not mapped yet. It needs a working T3 account to test against. |
| C: ship revamp (roadmap link, strays, fold safety, one pipeline, per-repo PR cap) | Already shipped | Merged in #120 and released in 5.3.0. |
| D: fullauto remake | Deferred | It needs increment B evidence. Its merge-on-green behaviour depends on conflict 1, which is dismissed below. Revisit after the Ledger pilot passes. |
| E1: single roadmap file | Already shipped | `roadmap.py` (#119). |
| E2: hash-bound approval record | Already shipped | `roadmap.py build`, plus the scope key the owner adds. The merge guard still refuses unattended merges to main. |
| E3: production-readiness checklist | Deferred | It belongs in increment C. It needs a deploy target to test against. |
| E4: post-deploy watch and auto-rollback | Deferred | Muse section 12 says there is no automatic rollback until there is evidence for the trigger. It waits on increment C. |
| E5: spend ledger | Deferred | It needs the Ledger (increment B) as its store. |
| E6: secrets registry with earmarked stubs | Deferred | It waits on increment C, and the rule from conflict 4 applies: earmarked secrets block only the deploy step that uses them. |
| E7: tool-route log | Deferred | It ships with the fullauto remake (D). |
| E8: Fleet Ledger wired into setup and run | Deferred | It waits on the pilot. Fleet-ledger also has to stay optional, so any wiring must be off unless installed. |
| Conflict 1: unattended merges to main under the roadmap hash | Dismissed | One approval would cover an unbounded scope. This conflicts with AGENTS.md and the merge guard. Muse section 13 rejects it too. Revisit only for a narrower form that Jeremy approves exactly. |
| Conflict 2: is pre-production review a second human stop? | Open, Jeremy decides | The council recommends yes, because production is hard to reverse. Nothing in 5.3.0 depends on the answer. |
| Conflict 3: votes are not a safety control | Implemented (stands as policy) | No change was needed. The hard gates already cannot be overridden, and this PR keeps that. |
| Conflict 4: secrets that do not block | Deferred with E6 | The rule is recorded here for when E6 is built. |
| Conflict 5: fold strays or close them | Open, Jeremy decides | The ship revamp folds only small, green, same-area strays. Closing strays older than 30 days is Muse decision 2. |
| Section 5: six PRs to dev | Superseded | PRs 1 and 4 shipped. PRs 2 and 3 partly shipped. PRs 5 and 6 are deferred as above. |

### Fleet Ledger unified proposal

| Item | Status | Reason |
|---|---|---|
| Increment A: read-only router, roadmap, approval record, kill switch | Already shipped | `/dt:go`, `roadmap.py`, `.harness/STOP` and `/dt:go stop`. |
| Increment B: Fleet Ledger pilot (5 days, free tier) | Deferred | It waits on the Phase 0 answers (section 14) and on per-seat GitHub identity (section 10). The plugin stays at 0.1.0 and optional. |
| Increment C: wiring, ship/fullauto remake | Deferred | It runs only if B passes its pass marks. |
| Section 10: per-seat GitHub identity | Deferred | This is a Phase 0 blocker for voting. It needs one GitHub App or machine account per seat, which is outside this repo. |
| Section 11: Supabase Pro (about $35 a month) | Dismissed for now | Not authorised. It goes to the single roll-up budget decision after the pilot. |
| Section 13: unattended merge to main | Dismissed | Same as simplification conflict 1. |
| Section 15, decisions 1 to 5 | Open, Jeremy decides | See "Decisions for Jeremy" below. |

## Open PRs and branches

| PR | What | Ruling |
|---|---|---|
| #112 | `actions/setup-node` bump | Rolled into this PR, then closed with a pointer here. |
| #114 | `claude-agent-sdk` to 0.2.180 | Rolled in, then closed. |
| #115 | `pytest` to 9.2.0 | Rolled in, then closed. |
| #116 | `pytest-xdist` to 3.8.0 | Rolled in, then closed. |
| #117 | `hypothesis` to 6.170.15 | Rolled in, then closed. |

**Branch cleanup.** Cloud sessions cannot delete refs. Jeremy runs `cleanup-branches.sh` after this PR merges, and it leaves only `main` and `dev`. Each branch is checked first, and any branch with an open PR is skipped.

## Plan to delivery (today)

1. ✓ Sync with `main` at `660010d`, read every open PR, adjudicate (this file).
2. ✓ Bump to 5.3.0, cut the changelog, fix the labels, regenerate the editions.
3. ✓ Add the release gate and its tests, add the fleet-ledger independence test, roll up Dependabot.
4. ✓ Write the guides: `command-guide.md`, `setup-guide.md`, this file, `cleanup-branches.sh`.
5. ✓ Full checks green, then open the PR to `main` and close #112 and #114 to #117.
6. Jeremy merges the PR.
7. Jeremy runs the post-merge checks, `cleanup-branches.sh`, and retargets the Grok catalog item.

## Decisions for Jeremy

None of these block the merge.

1. Second human stop before production deploys. Recommend: yes.
2. Strays: fold only small, green, same-area ones, and close those older than 30 days with a note. Recommend: accept.
3. Sequence: run the Ledger pilot (B) only after the Phase 0 answers, then C only if B passes. Recommend: accept.
4. PR #109 (fleet-ledger): merge only after its pre-merge conditions are verified by a seat other than its builder. Recommend: accept.
5. Cost: the pilot stays at $0, and Supabase Pro goes to a later roll-up decision. Recommend: accept.
