VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- It is a small tested Python bridge, and the last push was 2026-06-21.
- Cursor already talks to Composio through a connected MCP, so this bridge is not the path in use.
- The marketplace has a Composio setup skill, not this server, so there is no file to drop in.

## What your goal means
As a portfolio piece it shows a clean MCP wrapper, and it no longer shows how the org connects tools. Keeping it means another package to patch for a job Composio now does.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-06-21 | sourced | https://github.com/Dobeu-tech-eco/one-composio-mcp, 2026-11-12 |
| Size | 23 KB | sourced | https://github.com/Dobeu-tech-eco/one-composio-mcp, 2026-11-12 |
| OpenSSF Scorecard | 404, not scored | sourced | https://api.securityscorecards.dev/projects/github.com/Dobeu-tech-eco/one-composio-mcp, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 6 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 7 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 3 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 2 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 2 | Months of build still named in the README before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 8 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 49/100

## Template path
not sellable: Composio ships Tool Router, and this repo is a profile wrapper around it. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
src/, tests/, and config.example.yaml if a self-hosted session broker is ever needed.

## What would change the answer
A running deployment that other agents still call.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/one-composio-mcp. Archiving is reversible from the repo settings.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
