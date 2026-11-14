VERDICT: ARCHIVE
CONFIDENCE: moderate

## Why
- The owner's own notes on a branch record a decision to preserve this pilot as a reference and put the time into another product instead.
- Main has not moved since 2026-09-21. The later pushes are two Dependabot branches, four environment-setup branches from October and that handoff note.
- It is a mock-first pilot by design: the README says customer documents are prohibited and cloud deployment is deferred.

## What your goal means
A well-built pilot that will not be extended is best shown as a finished reference. Archiving keeps it readable and stops Dependabot from asking for attention.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-09 | sourced | https://github.com/Dobeu-tech-eco/dobeu-knowledge-pilot, 2026-11-14 |
| Last commit on main | 2026-09-21 | sourced | https://github.com/Dobeu-tech-eco/dobeu-knowledge-pilot, 2026-11-14 |
| Open pull requests | 5 | sourced | https://github.com/Dobeu-tech-eco/dobeu-knowledge-pilot, 2026-11-14 |
| Test files | 16 | sourced | https://github.com/Dobeu-tech-eco/dobeu-knowledge-pilot, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 6 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 5 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 3 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 2 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 2 | Work still needed before it could earn. | estimated |
| projections | 2 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 5 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 49/100

## Template path
The FastAPI and React search scaffold could be a starter in the $20-$60 band. The owner's notes say a template business is unvalidated, so do not prepare it on speculation.

## Salvage list
The SQLite full-text retrieval, the 60-case deterministic evaluation, the security tests and the gated deploy workflow.

## What would change the answer
A named user asks for the pilot, or the owner's validation experiment on the other product ends and attention returns here.

## Next step
Merge or close all five open pull requests first, because archive freezes them: the handoff, the two Dependabot ones and the two drafts. Then leave it unarchived until you approve archive for Dobeu-tech-eco/dobeu-knowledge-pilot.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
