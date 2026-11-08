---
name: dt-repo-sweep
description: "Review every repo of a GitHub owner, oldest first, with a quick expert pass each, then clean up from one screen: keep, fold, sell as template, archive. Deleting is one repo at a time, with a backup. Use for clean up my repos or sweep my old projects."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-repo-sweep/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Repo-sweep — decide on all your repos in one sitting

`/dt-repo-sweep [owner]` is the batch version of `/dt-ask-expert`. It reviews each repo quickly, collects the answers in one table, and lets you apply the cleanup in one go. Nothing is deleted automatically.

## Steps
1. **List the repos.** `gh repo list <owner> --json name,pushedAt,isArchived,description --limit 200` (no owner means the signed-in account). Sort by `pushedAt`, oldest first. Skip archived repos unless the user asks for them. Show the count and the first few names; ask to continue.
2. **Ask the goal once.** Ask the ask-expert goal questions (read `skills/ask-expert/phase-1-goal.md`) once for the whole sweep, including which repos the user uses actively. Then ask whether any repo needs a different goal; each override is asked per repo. The clarity check must pass for the sweep goal, and again for each override, exactly as in ask-expert.
3. **Quick pass per repo.** For each repo in order, run a short ask-expert: read the code (`phase-2-compare.md` step 1 and 3), then the expert panel (`phase-3-panel.md`), and the light market snapshot for money or template goals (`phase-4-research.md` step 1). Skip the side-by-side and the user's choice; the user reviews on the cleanup screen. Write each memo with `phase-5-report.md` and check it with `ask_expert.py check-report`. Then record it:
   `python3 "$PLUGIN/scripts/dt_gate.py" bridge ask_expert.py sweep add --ledger <ledger> --repo <name> --verdict <V> --confidence <C> --reason "<one line>" --score <overall 0-100 from the memo's scorecard> --salvage "<one line>" --report <path>`
   The first `sweep add` without `--ledger` prints the ledger path; reuse it for the rest of the sweep.
4. **The cleanup screen.** `python3 "$PLUGIN/scripts/dt_gate.py" bridge ask_expert.py sweep show --ledger <ledger>` returns the rows and a markdown table. Rows come sorted by score, highest first. Show it: repo, score out of 100, verdict, confidence, one-line reason, salvage. Ask the user to tick, per repo, the action to apply. Ticks are for `KEEP`, `FOLD`, `TEMPLATE` and `ARCHIVE` only; `DELETE` is not on this screen.
5. **Apply the ticks.**
   - `KEEP`, `FOLD` and `TEMPLATE` only write a to-do file (`.harness/ask-expert/todo.md`) with the next step from each memo. They change no repo.
   - `ARCHIVE` runs `python3 "$PLUGIN/scripts/dt_gate.py" bridge ask_expert.py archive --repo <owner>/<name>`, which archives the repo on GitHub. Archiving can be undone from the repo's settings.
6. **Deletes, one repo at a time.** For each repo the memo says `DELETE`, and only if the user asks to go on:
   1. Back it up: `ask_expert.py backup --repo <owner>/<name>`. It writes a verified bundle under `~/.dts2/repo-backups/`. Show the bundle path.
   2. Ask the user to type the repo name. Do not accept anything but the exact name.
   3. Run `ask_expert.py delete --repo <owner>/<name> --confirm <typed name> --bundle <bundle path>`. It refuses without the exact name and a verified bundle.
   There is no list or batch form of delete, and this skill never deletes on its own. A backup that fails means no delete.
7. **Report.** One line per repo: what was done. List the to-do file, the archived repos, the backup bundles and anything skipped.

## Guardrails
- The template path is checked and priced for every repo before `ARCHIVE` or `DELETE` is proposed.
- Never put `DELETE` in a bulk tick, a list or a loop without the per-repo backup and typed name.
- Never touch a repo the user did not tick. A failed `gh` call stops that repo, not the sweep.
- Every memo and panel record stays in `.harness/ask-expert/<repo>/` so the user can re-read why.
