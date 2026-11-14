VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- The README is a personal software registry plus a password vault.
- The root contains csv, json, and zip dumps next to the app, last pushed 2026-09-03.
- A vault with data files in git is the wrong thing to leave in the active org list.

## What your goal means
It was a personal memory tool. The portfolio does not need a second password store, and the data files raise the cost of keeping the repo public.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-09-03 | sourced | https://github.com/Dobeu-tech-eco/bookmark-software-cat, 2026-11-12 |
| Size | 1100 KB | sourced | https://github.com/Dobeu-tech-eco/bookmark-software-cat, 2026-11-12 |
| Root data files | csv, json, and zip are present | sourced | https://github.com/Dobeu-tech-eco/bookmark-software-cat, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 3 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 4 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 4 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 2 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Months of build still named in the README before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 4 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 32/100

## Template path
not sellable: a password vault with committed dumps is not a starter kit. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
The bookmark browser idea only, after the dumps are reviewed offline. The first pass did not open those files.

## What would change the answer
You still use it as your daily registry and the dumps are fake.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/bookmark-software-cat. Review the dumps locally first. Do not paste them into chat. A read-only follow-up on 2026-11-13 opened the data files, and the findings went to the owner, not into this file. Archiving does not change who can read the repo, so decide visibility before archive.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
