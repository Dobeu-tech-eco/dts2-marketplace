VERDICT: ARCHIVE
CONFIDENCE: low

## Why
- This is Design System v2, with tokens, React, icons, and motifs, last pushed 2026-09-21.
- No package.json in the org installs @dobeu/tokens, but new-dobeu-net's Tailwind config names it as the source of truth and copies its values.
- RouteReady, Chima, and the coaching site describe later design-system copies.

## What your goal means
A design system is a portfolio asset only while apps still build from it. No app installs v2, and the production site still follows its values by hand.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-09-21 | sourced | https://github.com/Dobeu-tech-eco/dobeu-design-system, 2026-11-12 |
| Packages named | @dobeu/tokens, components-react, icons, motifs | sourced | https://github.com/Dobeu-tech-eco/dobeu-design-system, 2026-11-12 |
| Consumers | no package.json installs it; new-dobeu-net copies its values | sourced | https://github.com/Dobeu-tech-eco/new-dobeu-net, 2026-11-13 |

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
| moat | 4 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 5 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 45/100

## Template path
not sellable: the tokens are the Dobeu brand. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
@dobeu/tokens and docs/token-contract.md if a brand site still needs v2 values.

## What would change the answer
A production app still installs @dobeu/tokens from this repo, or dobeu.net still takes its token values from here.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/dobeu-design-system. First confirm where new-dobeu-net's tokens are maintained.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
