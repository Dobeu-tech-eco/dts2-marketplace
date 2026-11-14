VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- The repo is 8 KB and four root entries, last pushed 2026-10-16.
- The README is a four-role pipeline the marketplace already ships.
- There is no runtime here that the marketplace is missing.

## What your goal means
A one-page sketch of the pipeline is already inside the product you release. This extra repo only adds a name to remember.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-10-16 | sourced | https://github.com/Dobeu-tech-eco/plugin-claudeharness, 2026-11-12 |
| Size | 8 KB | sourced | https://github.com/Dobeu-tech-eco/plugin-claudeharness, 2026-11-12 |
| Marketplace push | 2026-11-10 | sourced | https://github.com/Dobeu-tech-eco/dts2-marketplace, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 4 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 4 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 2 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 2 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Months of build still named in the README before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 1 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 9 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 37/100

## Template path
not sellable: the maintained harness is dts2-marketplace. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
The pipeline diagram in the README, if you want it as a picture in the marketplace docs.

## What would change the answer
This plugin is the one installed in Claude Code and the marketplace is not.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/plugin-claudeharness.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
