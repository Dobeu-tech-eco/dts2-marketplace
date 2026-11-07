> Directory edition: do not run bundled scripts or hooks, a package launcher, or a download piped into a shell. Do not read tokens or credential files from the machine. Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.

# ask-expert - phase 5, the memo

One page, plain words. Write it to `.harness/ask-expert/<repo>/report.md` in exactly this format, because the checker is strict:

```
VERDICT: KEEP|FOLD|TEMPLATE|ARCHIVE|DELETE
FOLD_TARGET: <repo>        (only when the verdict is FOLD)
CONFIDENCE: high|moderate|low

## Why
- <reason one>
- <reason two>
- <reason three>

## What your goal means
<two or three sentences: for money, the revenue math; for passion, effort and joy against upkeep; for learning or portfolio, what it still teaches or shows>

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| <what> | <value> | sourced | <https link>, <date> |
| <what> | <value> | estimated | <how it was worked out> |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | <0-10> | <method used> | sourced\|estimated\|assumed |
| code_health | <0-10> | <method> | <label> |
| product_viability | <0-10> | <method> | <label> |
| market_size | <0-10> | <method> | <label> |
| revenue_potential | <0-10> | <method> | <label> |
| time_to_profit | <0-10> | <method> | <label> |
| projections | <0-10> | <method> | <label> |
| moat | <0-10> | <method> | <label> |
| upkeep_cost | <0-10> | <method> | <label> |

Overall: <N>/100

## Template path
<could it sell as a starter kit or template? where, at what price, with what prep. Include a price range written like $20-$60, or write "not sellable:" and the reason>

## Salvage list
<files, features or ideas worth keeping whatever the verdict>

## What would change the answer
<the facts or numbers that would flip the verdict>

## Next step
<one reversible action>
```

Scorecard rules:
- Exactly these nine rows, in this order, each score a whole number from 0 to 10, each with an evidence label. A score with no evidence is labelled `assumed`, and the memo says so.
- `Overall: N/100` is the weighted sum for the goal: `round(sum(score x weight) / 10)`. Weights, which add to 100 for every goal:
  - money and template: security 10, code_health 10, product_viability 15, market_size 15, revenue_potential 15, time_to_profit 15, projections 10, moat 5, upkeep_cost 5.
  - portfolio: security 15, code_health 25, product_viability 20, market_size 5, revenue_potential 5, time_to_profit 5, projections 5, moat 5, upkeep_cost 15.
  - passion and learning: security 15, code_health 20, product_viability 20, market_size 5, revenue_potential 5, time_to_profit 5, projections 5, moat 5, upkeep_cost 20.
- Methods, one per factor:
  - security: OpenSSF Scorecard (the `scorecard` CLI, or api.securityscorecards.dev for public GitHub repos), plus a dependency vulnerability scan (`osv-scanner`, `npm audit` or `pip-audit`) and a secret scan.
  - code_health: tests present and passing, dependency age, size and complexity, last-commit recency (repo-health dimensions, CHAOSS activity).
  - product_viability: does it work end to end and solve the stated problem.
  - market_size: total, serviceable and obtainable market, built bottom-up and cross-checked top-down.
  - revenue_potential: pricing benchmarks times reachable customers.
  - time_to_profit: break-even months = (effort to first dollar + fixed costs) / monthly net margin.
  - projections: three-year low, base and high revenue, capped by the obtainable market.
  - moat: how defensible it is against competitors.
  - upkeep_cost: hours per month and hosting cost to keep it alive.
- Check the arithmetic with `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/ask_expert.py" scorecard --report .harness/ask-expert/<repo>/report.md [--goal <goal>]`. It prints the factors, weights, computed overall and the stated one; exit 0 means they are within 1 point, exit 1 means a mismatch or a malformed table. `check-report` runs the same check.

Rules:
- `## Why` has exactly three bullet lines.
- Every row in the numbers table has a label of `sourced`, `estimated` or `assumed`, and every `sourced` row contains an http or https link.
- Confidence is `high` when the vote was unanimous and the numbers are sourced, `moderate` when the vote was split or some numbers are estimated, and `low` when the head could not decide or key numbers are only assumed.
- The template path is never empty, even for `KEEP`.
- Jargon, method detail, the vote record and any long reasoning go in an appendix after the last section, headed `## Appendix`. The one page above it stays readable by someone who is not a developer.
- The next step for `ARCHIVE` is the archive command for the user to approve; for `DELETE` it is a backup first, then a typed confirmation. Never run either from this skill.

## Check it
`python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/ask_expert.py" check-report .harness/ask-expert/<repo>/report.md`

Exit 0 means the memo is valid. Exit 1 prints `{ok: false, errors: [...]}`: fix each error and run again until it passes. Then show the user the memo, point to the saved panel record in `.harness/ask-expert/<repo>/run/`, and ask what they want to do next. In a sweep, the caller records the result with `ask_expert.py sweep add`.
