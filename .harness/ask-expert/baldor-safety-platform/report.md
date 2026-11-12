VERDICT: FOLD
FOLD_TARGET: baldor-safety-insights
CONFIDENCE: moderate

## Why
- The README title is Baldor Safety Insights, the same product as baldor-safety-insights.
- This public tree was last pushed 2026-09-19. The private insights repo was pushed 2026-11-05.
- Upload types, Lovable hosting, and the chart set match the later repo.

## What your goal means
One Baldor app should be the portfolio piece. Two trees means the older public one can drift from the private one.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| This repo last push | 2026-09-19 | sourced | https://github.com/Dobeu-tech-eco/baldor-safety-platform, 2026-11-12 |
| Later repo last push | 2026-11-05 | sourced | https://github.com/Dobeu-tech-eco/baldor-safety-insights, 2026-11-12 |
| Size | 1418 KB | sourced | https://github.com/Dobeu-tech-eco/baldor-safety-platform, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 5 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 5 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 6 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 2 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Months of build still named in the README before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 4 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 42/100

## Template path
not sellable: it is a confidential fleet-safety app for one customer. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
Any chart or supabase migration in this tree that is missing from baldor-safety-insights.

## What would change the answer
A screen here that the November repo never received.

## Next step
Diff src/ and supabase/ against baldor-safety-insights, move anything missing, then decide on archive. Do not archive first.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
