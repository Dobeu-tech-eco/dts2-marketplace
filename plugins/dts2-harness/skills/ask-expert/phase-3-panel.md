# ask-expert - phase 3, the expert panel

This reuses the autopilot mechanics for seats and the council; only the panel count is its own (`ask_expert.py panel-tally`). The detail of each mechanism is in `autopilot` section 1 (`skills/autopilot/phase-1-gate.md`); read it when you need it. All saved material goes under `.harness/ask-expert/<repo>/run/` (the "run folder" below).

## 1. Seats
Three frontier models from three different providers, picked with `roster.py` exactly as the autopilot gate picks its voters (`roster.py command --agent <name> --role second-opinion --tier frontier --prompt-file <ballot>`). Fewer than three usable providers: say so, run with the ones available, and record the shortfall in the memo. A seat that returns nothing usable is replaced once by the next usable provider.

## 2. Blind plans
Write a prompt file with the goal, the side-by-side and the code facts (`compare.md`), the research notes if any, and the instruction to answer with a first line `VERDICT: KEEP|FOLD INTO <repo>|SELL AS TEMPLATE|ARCHIVE|DELETE`, then reasons (three at most), what the goal implies, the template-path price check, and the salvage list. Dispatch the three seats in one message exactly as the autopilot gate dispatches its panel voters (`skills/autopilot/phase-1-gate.md`, step 2: Agent tool for Claude, `lanes.py call` for the others), each answer saved to `<run folder>/round-<n>/<seat>.md`. Do not use `ballot_dispatch.py` for the panel: it only records `APPROVE` or `REJECT`, so a `KEEP`, `FOLD`, `TEMPLATE`, `ARCHIVE` or `DELETE` verdict would be lost. No seat sees another's plan. Save every response verbatim.

## 3. Cross-review and vote
Strip authorship and shuffle the order with `council.py blind --proposals <dir> --out <dir> --voters <seats> --seed <stamp>-<repo>-<round>`. Send each seat the other two plans and ask for one line per plan, `VOTE <seat>: AGREE` or `VOTE <seat>: DISAGREE`, then at most ten findings. Count the round with `ask_expert.py panel-tally --plans <seat>=<plan file> ... --votes <seat>=<vote file> ...` (three seats, two votes each). It prints the majority `verdict` of the plans (`no-majority` on a three-way split), whether they were `unanimous`, the `agree` and `disagree` counts and `pass`. Do not use `council.py tally` or `contracts.parse_ballot` here: the tally wants five seats and a ballot carries one `APPROVE` or `REJECT` line.
- `pass` is true (all three plans name the same verdict and no seat disagrees): pass. That verdict goes to the memo with confidence `high` when the numbers are sourced.
- Otherwise run another round on the plans that survived, carrying the findings forward. At most three rounds. Every ballot and plan is saved verbatim in the run folder, named `<NN>-<kind>-r<round>-<seat>.md`.

## 4. The council
Only after three failed rounds. Check `council.py eligible --votes-dir <run folder>`; it must say `eligible: true`. The council then sits exactly as in `autopilot` section 1b (`skills/autopilot/phase-1-gate.md`): dossier, five seats, tally, dissent briefs, head of council, with one difference: the council commands take `--allow-research`.

The head of council has a fourth option, `DECISION: RESEARCH`, which is valid only on ask-expert runs. It must come with a non-empty `## Research brief` listing the open questions. Check the record with `council.py check-decision <record> --tally <tally> --entries <n> --allow-research`, and route with `council.py route ... --allow-research`; a RESEARCH decision returns the action `research`.
- Any other decision (`APPROVE`, `FIX`, `STRIKE`) is carried out as in autopilot and gives the verdict the head signed off.
- `RESEARCH`: go to `phase-4-research.md` for the full research team, then reconvene the head once with the study in hand. The head must then choose a verdict; a second RESEARCH is not allowed. If it still cannot decide, the memo says so plainly with confidence `low`.

Whatever the panel decides, the template path was priced first. If no seat priced it, run the light snapshot in `phase-4-research.md` before the memo.
