VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- The whole repository is two small files: one editor hook definition and one state file.
- It has one commit, from 2026-10-08, described as a snapshot.
- There is no readme, and the hook points at a script that is not in the repo.

## What your goal means
A two-file snapshot is not something to show. If the hook matters, it belongs in the repo that owns the editor configuration.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push and last commit on main | 2026-10-08 | sourced | https://github.com/Dobeu-tech-eco/prompthooks, 2026-11-14 |
| Commits | 1 | sourced | https://github.com/Dobeu-tech-eco/prompthooks, 2026-11-14 |
| Files | 2 | sourced | https://github.com/Dobeu-tech-eco/prompthooks, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 1 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 1 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 0 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 0 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 0 | Work still needed before it could earn. | estimated |
| projections | 0 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 0 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 8 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 27/100

## Template path
not sellable: two configuration files.

## Salvage list
The hook definition, copied into whichever repo carries the editor setup.

## What would change the answer
Something clones this repo to install the hook.

## Next step
Leave it unarchived until you approve archive for Dobeu-tech-eco/prompthooks.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
