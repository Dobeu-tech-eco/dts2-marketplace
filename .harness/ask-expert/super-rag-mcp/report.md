VERDICT: KEEP
CONFIDENCE: moderate

## Why
- Phase 1, local-file RAG behind an MCP server, is marked shipped in the README.
- The repo is MIT, has tests, and took a Dependabot CI commit on 2026-10-11.
- Nothing else among the 33 visible repos is this retrieval server.

## What your goal means
It is a working tool you can point agents at. Hosting a vector index is the upkeep, and the code itself is in good shape for a portfolio.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-10-11 | sourced | https://github.com/Dobeu-tech-eco/super-rag-mcp, 2026-11-12 |
| License | MIT | sourced | https://github.com/Dobeu-tech-eco/super-rag-mcp, 2026-11-12 |
| Size | 207 KB | sourced | https://github.com/Dobeu-tech-eco/super-rag-mcp, 2026-11-12 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 6 | OpenSSF Scorecard was not published for these repos (sample call returned 404). Score is from tests, license, and whether data files sit in git. | estimated |
| code_health | 7 | Tests or CI in the tree, size, and months since the last push. | estimated |
| product_viability | 6 | Whether the README's job can be done in the tree that exists today. | estimated |
| market_size | 4 | One-org or one-client use, not a category forecast. | estimated |
| revenue_potential | 3 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 3 | Months of build still named in the README before it could earn. | estimated |
| projections | 3 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 4 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 53/100

## Template path
After personal connectors are stripped, a self-hosted RAG MCP could sit in the $17-$97 starter band. It is not packaged for sale. Generic Next.js starters list at $17-$97 (https://themeforest.net/item/nextsaas-saas-software-startup-nextjs-template/59610421 and https://vibeboot.gumroad.com/l/saas-starter, checked 2026-11-12).

## Salvage list
src/, tests/, and config.example.yaml.

## What would change the answer
Nobody can run the phase-1 path, or a hosted RAG product replaced it.

## Next step
Run the documented local-file query once. If it fails, flip this to archive.

## Appendix
Single reviewer. The three-seat panel was not seated: `dt_gate.py bridge roster.py` returned BLOCKED unsupported-runtime-script, and paid provider calls stay unexecuted in the Cursor package. Confidence is not high. The sweep goal was taken as portfolio and is not confirmed. OpenSSF Scorecard returned 404 for the probed public repo, so security scores are estimated. No archive, delete, or fold was applied.
