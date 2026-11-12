VERDICT: KEEP
CONFIDENCE: moderate

## Why
- It is the native iOS trainer and trainee app for RouteReady, homepage listed, last pushed 2026-11-06.
- Swift package tests, a harness, and release notes are in the tree.
- The web app routeready moved again on 2026-11-12, so this client is part of a live product.

## What your goal means
RouteReady is a product line. The iOS app is how trainers and trainees use it away from the dashboard.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-06 | sourced | https://github.com/Dobeu-tech-eco/routeready-trainer-ios, 2026-11-12 |
| Web app push | 2026-11-12 | sourced | https://github.com/Dobeu-tech-eco/routeready, 2026-11-12 |
| Open issues | 5 | sourced | https://github.com/Dobeu-tech-eco/routeready-trainer-ios, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 6 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 8 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 8 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 3 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 4 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 3 | Months of build still named in the README before it could earn. | estimated |
| projections | 3 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 5 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 5 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 62/100

## Template path
not sellable: it is the RouteReady client, tied to that database and brand. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
MyApp/, Tests/, and the mobile API usage.

## What would change the answer
RouteReady drops native iOS and this app is unreleased on purpose.

## Next step
Keep it aligned with routeready. No archive.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
