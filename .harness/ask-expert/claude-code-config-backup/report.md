VERDICT: KEEP
CONFIDENCE: moderate

## Why
- A scheduled job still pushes a backup to this repo, most recently on 2026-11-13, so archiving it would make the repo read-only and break that job.
- The ignore file is a whitelist that keeps runtime folders and credential files out, which is the right design for a config backup.
- A credentials-shaped string sits in the git history of a settings file.

## What your goal means
This is a working backup, not a showpiece. Its portfolio value is that the owner's agent setup can be rebuilt, and it should stay private.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-13 | sourced | https://github.com/Dobeu-tech-eco/claude-code-config-backup, 2026-11-14 |
| Last commit on the default branch | 2026-07-25 | sourced | https://github.com/Dobeu-tech-eco/claude-code-config-backup, 2026-11-14 |
| Commits on the backup branch | 83 | sourced | https://github.com/Dobeu-tech-eco/claude-code-config-backup, 2026-11-14 |
| Size | 11661 KB | sourced | https://github.com/Dobeu-tech-eco/claude-code-config-backup, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 3 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 5 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 8 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 1 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Work still needed before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 8 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 48/100

## Template path
not sellable: it is a private backup of one person's machine configuration.

## Salvage list
The whitelist ignore file and the hooks folder. The curated rules now exist only on the old default branch.

## What would change the answer
The scheduled backup is turned off or moved to another repo.

## Next step
Keep it. Rotate the credential noted above, then point the default branch at the branch the backup job actually pushes to.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
