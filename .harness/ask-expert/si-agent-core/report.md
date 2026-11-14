VERDICT: KEEP
CONFIDENCE: moderate

## Why
- It is the most active and best-tested repo in this pass: 87 commits, 42 test files, four CI workflows, and a merge to main on 2026-11-13.
- The README states one clear job, a promotion gate for agent system instructions, and the tree is a packaged Python CLI at v0.6.0 with an MIT license, changelog and security policy.
- Five pull requests are open, including one that adds a services offer, so the work is in motion and not parked.

## What your goal means
This is the strongest portfolio piece among the 20: a narrow developer tool with tests, CI and a written decision rule. It shows engineering discipline better than any app screenshot would.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push and last commit on main | 2026-11-13 | sourced | https://github.com/Dobeu-tech-eco/si-agent-core, 2026-11-14 |
| Commits, all branches | 87 | sourced | https://github.com/Dobeu-tech-eco/si-agent-core, 2026-11-14 |
| Open pull requests | 5 | sourced | https://github.com/Dobeu-tech-eco/si-agent-core, 2026-11-14 |
| Version in pyproject | 0.6.0, MIT | sourced | https://github.com/Dobeu-tech-eco/si-agent-core, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 8 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 9 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 8 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 5 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 4 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 4 | Work still needed before it could earn. | estimated |
| projections | 3 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 5 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 6 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 70/100

## Template path
Not a template. It is a tool, and the open services pull request is the more likely way to earn from it. As a paid starter it would sit in the $20-$60 band at most, and selling it that way would undercut the MIT release.

## Salvage list
The promotion rule, the sealed-holdout handling, the SQLite registry and the reusable promotion workflow.

## What would change the answer
The owner decides the tool will not be released or sold, and no other repo calls the reusable workflow.

## Next step
Keep it. Decide whether it stays private or is published, since the license and README are already written for a public reader.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
