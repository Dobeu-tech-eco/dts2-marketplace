VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- It is an archive of agent session transcripts and memory exports from July, and nothing has been added since 2026-08-15.
- Session transcripts sit in git, about 52 MB uncompressed, and transcripts can contain whatever was typed or printed in those sessions.
- The one live thing in it is an org-wide instruction pack for a coding agent, which belongs in a repo that is maintained.

## What your goal means
A private transcript dump is not a portfolio piece. The risk is that it holds more than anyone remembers, so it should be frozen and kept private.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-08-15 | sourced | https://github.com/Dobeu-tech-eco/ruflo-memory, 2026-11-14 |
| Last commit on main | 2026-08-14 | sourced | https://github.com/Dobeu-tech-eco/ruflo-memory, 2026-11-14 |
| Commits, all branches | 18 | sourced | https://github.com/Dobeu-tech-eco/ruflo-memory, 2026-11-14 |
| Size on GitHub | 5870 KB | sourced | https://github.com/Dobeu-tech-eco/ruflo-memory, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 3 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 3 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 3 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 1 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Work still needed before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 6 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 30/100

## Template path
not sellable: it is private session data.

## Salvage list
The org-wide agent instruction pack and its drop-in template, moved to the .github or standards repo.

## What would change the answer
Other repos still read the instruction pack from this repo by path, in which case move it first.

## Next step
Move the instruction pack to a maintained repo. Then leave this one unarchived until you approve archive for Dobeu-tech-eco/ruflo-memory. Do not change its visibility.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
