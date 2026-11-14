VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- It is an autonomous full-stack agent package, last pushed 2026-09-05.
- dts2-marketplace, pushed 2026-11-10, is the harness the org actually ships.
- The agent entry and workflows would have to be rewritten to land in the marketplace, so this is not a fold.

## What your goal means
Two harnesses split the portfolio story. The marketplace is the one with a release train. Monty is the earlier experiment.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-09-05 | sourced | https://github.com/Dobeu-tech-eco/monty-ai-fullstackdev-coder, 2026-11-12 |
| Marketplace push | 2026-11-10 | sourced | https://github.com/Dobeu-tech-eco/dts2-marketplace, 2026-11-12 |
| License named in README | CC BY-NC 4.0 | sourced | https://github.com/Dobeu-tech-eco/monty-ai-fullstackdev-coder, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 5 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 6 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 4 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 3 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 2 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 2 | Months of build still named in the README before it could earn. | estimated |
| projections | 2 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 5 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 44/100

## Template path
not sellable: the license is non-commercial and the current product is dts2-marketplace. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
AUTONOMOUS_WORKFLOWS.md and templates/ if a workflow there is missing from the marketplace.

## What would change the answer
A feature in Monty that the marketplace still lacks and that you want to port.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/monty-ai-fullstackdev-coder.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
