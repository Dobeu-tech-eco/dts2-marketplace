# run — Phase 3, review and verify

## Phase 3 — Review and verify
Use the run stamp taken in preflight. Pass it to every reviewer and verifier. Every verifier dispatch applies its HEAD guard: it records `git rev-parse HEAD` at its start and end and, if HEAD moved, reports per check which commit it ran against; treat `HEAD moved` as blocking only for the checks it names, and re-run those on the new HEAD.
0. **Deterministic gate, before any vote or verdict.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" run --stamp <stamp>`: tests, typecheck, lint, secret scan (gitleaks or trufflehog, skipped with a warning when neither is installed) and scope check. Each writes one line (`name`, `status`, `duration_ms`, `log_path`) to `.harness/runs/<stamp>/ledger.jsonl`; build the lead brief and the PR receipt from `checks.py summary`, and do not re-run what the ledger holds. Any red check means a fix round with zero votes. Record missing env var names (never values) with `checks.py env-missing`.
0b. **Scout, then verifier.** Dispatch `dts2-harness:scout` (`Mode: evidence`, model `sonnet`) to run the remaining commands and save raw evidence; it never emits a verdict. Dispatch the verifier with `Evidence: <path>` so the frontier seat makes every VERIFIED / BLOCKED call from that file and the ledger.
1. **Verifier walkthrough first**, when `Axes:` include `walkthrough`: dispatch `dts2-harness:verifier` (seat: sign-off, `model: opus`, one per repo touched) with the plan, the stamp, and the repo. Wait for its table; the reviewers need its screenshots and FAIL rows. Without the walkthrough axis, dispatch the verifier together with the reviewers in step 3.
2. **Critique report**, when `Axes:` include `critique`: if `/impeccable` is available, run `/impeccable critique` on the changed screens and save its report to `.harness/review/critique-<stamp>.md`. Otherwise the critique reviewer writes it, and you save its `### Critique` section to that same path.
3. Then dispatch the reviewers in parallel, in one message: one `dts2-harness:reviewer` per axis (tier S: one reviewer on all axes), capped at `max_reviewers`, each on its assigned agent (seat: advisory; `standard` by default, `frontier` only for a design-risk diff, per `delegate.py --seat advisory`). Give each the diff, the plan, the stamp, and the critique report path when there is one. For `walkthrough-findings`, include the verifier's table.
4. Second opinion: for each usable agent holding `second-opinion` (or the `second_opinion` setting when it names an installed CLI), write the review prompt to `.harness/runs/<stamp>/prompts/second-opinion-<agent>.md` and the diff beside it, then run the `shell` value of `roster.py command --agent <name> --role second-opinion --tier standard --prompt-file <file>` from the repo, through Bash. Mark its findings advisory. Classify its output the same way; an `unavailable (billing/quota)` agent is dropped, not counted as a review failure. Axis reviewers on a non-Claude agent are classified too, passing `--usable <probe usable list>`: when copilot's `reviewer:security` run returns the context-budget error, `classify` returns `fallback: grok`. The seat it checks is `<role>:<axis>` when you pass `--axis`, else the role as given, else the profile's only suffixed form of a bare role (copilot `--role reviewer` is `reviewer:security`); re-run that seat on grok (`roster.py command --agent grok --role reviewer:security`) for this run and note `Fallback: reviewer:security copilot -> grok (context budget)` in the status block. With no usable fallback, give the seat to claude.
5. **Final review.** After the axis reviews return, dispatch one `dts2-harness:reviewer` on the whole diff, all axes, at `frontier` (seat: sign-off), with the axis findings, to catch what crosses axes. It also checks the receipt's `Delegation policy` line: a `VIOLATION` (a builder that ran a frontier model) is a ship-blocking finding.

## Phase 3b — Finish pass
Runs only when `/impeccable` is available and the diff touched UI components named in `.harness/end-state.md`. If the diff touched such components and Impeccable is not installed, print one line, `Finish pass skipped: Impeccable not installed (github.com/pbakaus/impeccable)`, and go to Phase 4.

The builder that owns the files runs, inside its file set, in one dispatch:
- `/impeccable polish <components>` always (it consumes the critique's Fix list);
- `/impeccable harden <components>` when the diff touches data loading, network, or error paths;
- `/impeccable clarify <components>` when it touches error, empty, or confirmation states;
- `/impeccable optimize <components>` only when the walkthrough marked a screen slow.

One round, no loop. Then go to Phase 3c; its verifier run covers this result.

## Phase 3c — Code finish pass
Runs on every code diff, after Phase 3b (or straight after Phase 3 when 3b was skipped) and before the final verifier tests. Two extra reviewer axes on the diff, dispatched as one `dts2-harness:reviewer` (seat: advisory) at `standard`:
- `simplify`: duplication, dead code, functions over about 20 lines, unclear names, speculative abstraction.
- `optimize`: only for files the walkthrough marked slow or a test marked slow; never speculative. No slow marker → report `optimize: n/a`.

The builder that owns the files applies the resulting fix list inside its file set, once. Then dispatch the verifier (seat: sign-off, `model: opus`) to run the configured tests on the result; its table replaces the earlier test rows and adds a `Coverage:` line for changed source files with no test that imports or exercises them. This pass counts toward the 3-round cap in Phase 4: it is one of the rounds, not an extra one.

## Votes after the gate
Panel and council votes start only once `checks.py gate` allows them. Run the three voters in parallel on ballots from `council.py blind` (author identity removed, option order shuffled per voter from a seed written to the ledger). Feed the votes to `council.py route --ledger <ledger> --votes A,B,C`: unanimous approve passes, unanimous reject goes to a fix round, and only a split escalates. The head of council cannot approve over a red check: pass `--ledger` to `council.py check-decision`.
