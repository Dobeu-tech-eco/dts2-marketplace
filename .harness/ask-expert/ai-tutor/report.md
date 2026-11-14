VERDICT: KEEP
CONFIDENCE: moderate

## Why
- It is the public coaching site for dobeu.tech, with a homepage on Vercel.
- The app has Vitest, a changelog, and a security-hardening merge on 2026-07-15. The 2026-08-12 push was a bot branch, not main.
- Quiet git history is normal for a marketing site that is already deployed.

## What your goal means
It is one of the few repos that can still bring coaching leads. The portfolio value is the live site, not more commits.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-08-12 | sourced | https://github.com/Dobeu-tech-eco/ai-tutor, 2026-11-12 |
| Homepage | ai-tutor-gamma-eosin.vercel.app | sourced | https://github.com/Dobeu-tech-eco/ai-tutor, 2026-11-12 |
| Open issues and PRs | 3 | sourced | https://github.com/Dobeu-tech-eco/ai-tutor, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 7 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 8 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 4 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 5 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 4 | Months of build still named in the README before it could earn. | estimated |
| projections | 4 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 4 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 6 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 64/100

## Template path
not sellable: it is the Dobeu coaching brand site. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
The whole Next.js app, the design-system v3 notes, and __tests__.

## What would change the answer
The Vercel project is deleted and no one uses dobeu.tech for coaching.

## Next step
Open the Vercel URL once and confirm the coaching offer is still the one you want public.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
