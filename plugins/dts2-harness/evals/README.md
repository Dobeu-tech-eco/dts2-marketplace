# Smoke eval

Five small frozen fixtures that drive the deterministic parts of the harness pipeline with fake `claude` and `gh`
binaries. It is run on demand and is not part of CI. It never starts a real model and never touches the network.

    python3 plugins/dts2-harness/evals/run.py
    python3 plugins/dts2-harness/evals/run.py --fixture split-vote
    python3 plugins/dts2-harness/evals/run.py --update-baseline    # re-record evals/baseline.json

Each fixture under `fixtures/<name>/` holds `task.md` (the spec), `repo/` (a tiny repo snapshot), `scenario.json`
(lane manifest, scripted builder rounds with token and cost numbers, panel votes, optional council ballots) and
`expected.json` (the outcome that must be observed). The fakes live in `fakes/` and are wired in through
`DTS2_CLAUDE_BIN` and `DTS2_GH_BIN`.

## What the runner covers

scope-check (session scope), `lanes.py check` (lane overlap), `lanes.py lease` (epoch, stale-epoch refusal),
`lanes.py call` (one builder round per scripted round through the fake claude), `checks.py gate` (a red round blocks
the vote and counts as a fix round), `council.py route` (pass, fix, escalate) and `council.py tally`.

It does not cover the son brief, the lead brief, `spawn --dry-run` or prefix byte-stability; those wait for the
`lanes.py` batch.

## Output

`results/<stamp>.json` records pass/fail, tokens, wall-clock milliseconds and fix rounds per fixture plus totals. The
`results/` folder is gitignored. `baseline.json` is the committed reference; the baseline here was recorded with the
fake binaries, so its token numbers are scripted and its wall-clock numbers are machine dependent. A baseline from
real sessions is a manual step for the owner.

The runner prints the delta of tokens and wall-clock against the baseline, per fixture and in total. The exit code is 1
only when a fixture that passed in the baseline now fails; cost deltas never fail the run. Exit 2 means the runner could not run: a bad argument, an unreadable baseline (corrupt, not an object, or missing at a path given with `--baseline`), or `--update-baseline` while a chosen fixture fails. With `--fixture`, `--update-baseline` replaces only those fixtures' rows.
