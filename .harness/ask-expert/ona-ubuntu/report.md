VERDICT: KEEP
CONFIDENCE: low

## Why
- It defines a persistent SSH development container with deploy, verify and backup scripts, and usage today is unknown.
- The last commit on main is 2026-10-15, and the spec in the tree says the GPU part is researched and not yet built.
- Another repo in this pass has an open pull request, dated 2026-11-07, that would remove its own configuration for the same hosted environment as inactive. That suggests the environment may be winding down.

## What your goal means
Infrastructure that is still someone's daily workbench should not be frozen. If it is not in use, it is a small, tidy record of how the environment was built.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-09 | sourced | https://github.com/Dobeu-tech-eco/ona-ubuntu, 2026-11-14 |
| Last commit on main | 2026-10-15 | sourced | https://github.com/Dobeu-tech-eco/ona-ubuntu, 2026-11-14 |
| Files | 38 | sourced | https://github.com/Dobeu-tech-eco/ona-ubuntu, 2026-11-14 |
| Size | 80 KB | sourced | https://github.com/Dobeu-tech-eco/ona-ubuntu, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 6 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 5 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 5 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 1 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Work still needed before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 7 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 45/100

## Template path
not sellable: it is wiring for one hosted environment and one owner's access setup.

## Salvage list
The SSH container and its log supervisor, the verify and backup scripts, and the orchestration eval harness.

## What would change the answer
The owner confirms the hosted environment is no longer used. Then this becomes ARCHIVE.

## Next step
Keep it for now. Tell the sweep whether the environment is still running. If not, approve archive.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
