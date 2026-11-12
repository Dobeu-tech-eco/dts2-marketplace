VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- replit.md describes a WhatsApp Business Cloud API bot plus a React dashboard.
- The last push was 2026-08-16 and there is no README on the GitHub API.
- No newer org repo is the WhatsApp product, and this one is a Replit workspace.

## What your goal means
A working WhatsApp desk would be a product. This tree has not moved since August, so the portfolio is carrying a prototype.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-08-16 | sourced | https://github.com/Dobeu-tech-eco/whatsapp-bot, 2026-11-12 |
| Size | 305 KB | sourced | https://github.com/Dobeu-tech-eco/whatsapp-bot, 2026-11-12 |
| Stack note | Express 5, Postgres, Drizzle, React | sourced | https://github.com/Dobeu-tech-eco/whatsapp-bot, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 4 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 4 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 4 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 4 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 3 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 2 | Months of build still named in the README before it could earn. | estimated |
| projections | 2 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 4 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 37/100

## Template path
Could be a starter after the Replit wiring is removed, in the $17-$97 band, and it is not ready. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
The webhook and keyword-reply server under artifacts/api-server, if a client later wants WhatsApp.

## What would change the answer
A live WhatsApp Business number still points at this webhook.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/whatsapp-bot.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
