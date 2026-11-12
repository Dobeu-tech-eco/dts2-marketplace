VERDICT: KEEP
CONFIDENCE: moderate

## Why
- The README says it is the shared CI baseline for Dobeu-tech-eco, pinned at an immutable @v1.
- The last push, 2026-11-01, corrects that versioning model.
- Callers are the other repos, so archiving this breaks the portfolio gate.

## What your goal means
Shared CI is how the org stays reviewable. The value is fewer copied workflows, not a product page.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-01 | sourced | https://github.com/Dobeu-tech-eco/standards, 2026-11-12 |
| Size | 62 KB | sourced | https://github.com/Dobeu-tech-eco/standards, 2026-11-12 |
| Pin | @v1 immutable | sourced | https://github.com/Dobeu-tech-eco/standards, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 8 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 8 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 2 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Months of build still named in the README before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 4 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 8 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 63/100

## Template path
not sellable: the checks encode this org's policy. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
checks/ and ci-baseline.yml.

## What would change the answer
Every caller has copied the workflow back into its own repo.

## Next step
No archive. Keep pinning callers at @v1.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
