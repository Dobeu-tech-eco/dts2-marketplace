VERDICT: KEEP
CONFIDENCE: moderate

## Why
- It is the second-newest repo in this pass, created 2026-11-06 and last changed on main on 2026-11-12, and its stated job is a staffing-site template for prospect demos.
- The current tree is debranded, apart from two harness files that still mention the old brand, and runs in an offline demo mode, with four CI workflows, an MIT license and a security policy.
- The history is not debranded: early commits still carry the original client's name, contact details and screenshots.

## What your goal means
A demo you can put in front of a prospect is direct portfolio value. It only works as a public showpiece if the old client's identity is out of the history as well as the tree.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-13 | sourced | https://github.com/Dobeu-tech-eco/ex-staffing, 2026-11-14 |
| Last commit on main | 2026-11-12 | sourced | https://github.com/Dobeu-tech-eco/ex-staffing, 2026-11-14 |
| Commits, all branches | 24 | sourced | https://github.com/Dobeu-tech-eco/ex-staffing, 2026-11-14 |
| Size | 55064 KB | sourced | https://github.com/Dobeu-tech-eco/ex-staffing, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 5 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 7 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 7 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 4 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 4 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 4 | Work still needed before it could earn. | estimated |
| projections | 2 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 5 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 55/100

## Template path
The best template candidate in this pass: a trilingual staffing site with an applicant flow and an admin dashboard. Part 1 of this sweep benchmarked generic Next.js starters at $17-$97 on 2026-11-12. That was not rechecked here. It is not ready to sell or publish until the history is rewritten.

## Salvage list
The marketing site, the application form with resume upload, the admin dashboard and the demo-mode data layer.

## What would change the answer
The owner decides the demo will never leave the private org, which removes the history concern, or stops using it for prospects.

## Next step
Keep it private. Before any visibility change, publish from a fresh single-commit copy instead of this history, and clean the two files that still mention the old brand, and drop the 11 MB test PDF and the 18 one-off test, verification and SQL scripts at the root.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
