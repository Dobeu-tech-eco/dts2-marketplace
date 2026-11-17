# dt 5.3.0: setup guide

## For people

New to dt? Follow "New users". Already on an older version? Follow "Upgrading". Then run `/dt:go` and let it lead.

## For agents

- Do not run user-only commands unless the person typed them.
- Never approve the end state or the roadmap for the person. Never do anything unattended on `main`.
- `/dt:go` works with only `dt` installed.
- A PR to `main` that changes shipped plugin files needs a version bump and a `## [X.Y.Z]` entry in `plugins/dts2-runtime/CHANGELOG.md`. `release-gate.py` checks both.

## Overview

This guide covers four things: setting up dt for the first time, upgrading from an older version, using `/dt:go` to take a repo from where it is now to deployed, and the checks to run after the 5.3.0 merge. Each step lists what a person types. Notes for agents are marked **Agents**.

**You only need `dt`.** It gives you the full `/dt:go` path on its own. Fleet-ledger is an optional add-on for teams with several seats that run on Supabase. Skip it unless you are in that pilot. Every step below works without it.

## Before you start

You need:

- Claude Code
- bash
- git
- Python 3.10 or newer, available as `python3`. Without it, the safety hooks (the merge guard and the policy gate) cannot run and stay off.
- The `gh` CLI. It is optional, but without it `/dt:go` skips the open-PR step.

## New users

1. **Add the marketplace:** `/plugin marketplace add Dobeu-tech-eco/dts2-marketplace`
2. **Install the plugin:** `/plugin install dt@dts2`
3. **Restart Claude Code** so the commands and hooks load.
4. **Run the guided tour:** `/dt:onboard`. It explains the roles and the commands, asks the optional Composio question, and offers extra hooks after showing a dry run.
5. **Optional, once per computer:** `/dt:machine-prep`. It turns off extra plugins and skills that slow startup. It backs up settings first and never deletes anything.
6. **Open the repo you want to work on and run `/dt:go`.** From here on, `/dt:go` tells you what comes next. See "From current state to deployed" below.

**Agents:** do not run user-only commands (`composio`, `dpp-full`, `fullauto`, `knowledge`, `machine-prep`, `model`, `onboard`, `sdk`) unless the person typed them.

## Upgrading from an older version

Find your current plugin name with `/plugin`, then follow the matching row.

| You have | Do this |
|---|---|
| `dt` 5.x | `/plugin marketplace update dts2`, then `claude plugin update dt@dts2`, then `/reload-plugins` |
| `dts2` 4.x | `/plugin uninstall dts2@dts2`, `/plugin marketplace update dts2`, `/plugin install dt@dts2`, `/reload-plugins` |
| `dts2-harness` (before 4.0) | `/plugin uninstall dts2-harness@dts2`, then the same steps as the `dts2` 4.x row |
| Old `harness` or `harness-ops` copies | Disable them, or run `/dt:machine-prep` |

`/plugin marketplace update dts2` only refreshes the catalog. It does not move the installed plugin, so the `claude plugin update dt@dts2` step is required. If `dt` is installed at project scope, run that command from the project directory. A project-scope install only advances when the update runs there.

After any upgrade:

1. **Confirm the version:** `/plugin` should list `dt` at 5.3.0.
2. **Confirm the router:** `/dt:go status` should print the next step without changing anything.
3. **Keep your existing state.** The marketplace is still called `dts2`, and your settings and `.harness/` folders are unchanged. You do not need to re-run `/dt:setup` on repos that already have an approved end state.

## From current state to deployed

`/dt:go` reads the repo, picks the first rung of the ladder below that applies, and runs that command. When the command finishes, run `/dt:go` again. It repeats until the repo is complete.

| Rung | When this applies | What `/dt:go` does |
|---|---|---|
| 0 | `.harness/STOP` exists | Stops. A person deletes the file to continue. |
| 1 | No Composio decision has been recorded | Asks you to type `/dt:composio` (user-only). Answering "no" is fine. |
| 2 | There is no end state | Runs `/dt:setup` |
| 3 | The end state is not approved | Runs `/dt:setup` to finish approval |
| 4 | The roadmap is not approved | Stops for you. See "Approving the roadmap" below. |
| 5 | Sections are still to do | Runs `/dt:dpp` if 2 or more are to do, otherwise `/dt:run` |
| 6 | PRs are open | Runs `/dt:pr-sweep`. This rung is skipped when `gh` is not installed. |
| 7 | Action items are open | Runs `/dt:action-items` |
| 8 | A deploy is planned | Runs `/dt:run` for the deploy |
| 9 | Acceptance checks are still outstanding | Runs `/dt:run` to verify them |
| 10 | Everything is done | Runs `/dt:learn` to record lessons |

Two other forms:

- `/dt:go status` prints the current rung and changes nothing.
- `/dt:go stop <reason>` writes `.harness/STOP`, which halts every loop.

### What happens in a typical repo

1. **Day 1:** `/dt:go` asks the Composio question, then runs `/dt:setup`. You answer the interview and approve the end state.
2. **Approving the roadmap:** `/dt:go` runs `roadmap.py build`, which writes `.harness/roadmap.md`, and shows you a 12-character scope key. Read the roadmap. If you agree, add the key under `roadmap` in `.claude/settings.local.json`. That approval is tied to the scope. If a section or acceptance criterion is added, removed or renamed later, the key changes and `/dt:go` asks again. Finishing work does not change the key.
3. **Building:** each `/dt:go` builds outstanding sections, in parallel when there are several. Every section ends as a PR with a receipt.
4. **Cleaning up:** open PRs are swept, and items that need a person are listed for you.
5. **Deploying and accepting:** the planned deploy runs through `/dt:run`, and the acceptance checks are verified against the live result.
6. **Complete:** `/dt:learn` records what the run taught, for the next repo.

### What `/dt:go` never does

- It never overrides a hard gate: failing tests, the secret scan, or `do_not_touch` paths.
- It never merges to `main` unattended. The merge guard refuses.
- It never approves the end state or the roadmap for you.
- It never needs fleet-ledger or Supabase.

## Optional: fleet-ledger

Fleet-ledger (`fleet-ledger` 0.1.0) records seats, work claims and votes in a shared Supabase store for teams running many seats. It is not part of 5.3.0. It stays optional, and it is deferred until the Phase 0 answers and a 5-day pilot on the free tier.

- **Install it only if** you are in that pilot.
- **If you install it,** nothing in `dt` changes. `/dt:go` follows the same ladder.
- **If you remove it,** nothing in `dt` breaks.

## After the 5.3.0 merge

A person runs these checks once the release PR is merged to `main`.

1. **Versions agree on a fresh clone.** Run `python3 plugins/dts2-runtime/scripts/bump-version.py 5.3.0 --check`. It should exit 0.
2. **The marketplace picked up the release.** After `/plugin marketplace update dts2` and `claude plugin update dt@dts2` (run from the project directory for a project-scope install), the dt entry in `~/.claude/plugins/installed_plugins.json` should show version 5.3.0 and the merge commit SHA.
3. **Claude Code sees it.** `/plugin` should list `dt` 5.3.0, and `/dt:go` should be available.
4. **An upgrade from 5.2.0 advances.** Run `python3 plugins/dts2-runtime/scripts/upgrade-check.py --from-file <file holding the version recorded before the upgrade>`. It should report `advanced: true`.
5. **Fleet-ledger did not move.** Its plugin version is still 0.1.0.
6. **Retarget the Grok catalog item** from commit `d6bb00a3` to the 5.3.0 merge commit. This is done outside this repo.
7. **Delete old branches.** Run `bash docs/release-5.3.0/cleanup-branches.sh --dry-run` from a machine with `gh` signed in, check the list, then run it without `--dry-run`. Only `main` and `dev` should remain. The script skips any branch that still has an open PR.

## Maintainer notes

- **A promote to `main` is a release.** If a PR to `main` changes shipped plugin files, it must raise the version and add a `## [X.Y.Z]` entry to `plugins/dts2-runtime/CHANGELOG.md`. `scripts/release-gate.py` enforces both in CI on every PR to `main`, and you can run it locally: `python3 plugins/dts2-runtime/scripts/release-gate.py --base origin/main`.
- **MINOR or MAJOR.** Adding things is MINOR. Removing or breaking things is MAJOR, and the runtime cannot use 6.0.0, because the directory edition already uses that line.
- **Regenerate the editions after a plugin change.** From `plugins/dts2-runtime`, run `python3 scripts/directory_edition.py` and `python3 scripts/cursor_surface.py`, then check both with `--check`.
- **Keep fleet-ledger optional.** `tests/test_fleet_ledger_optional.py` fails if any runtime script, hook, skill, role, command or SDK file mentions it.
