VERDICT: KEEP
CONFIDENCE: moderate

## Why
- The README describes one job, turning a fresh Termux install into a persistent coding host, and one script does it.
- It was written on 2026-11-07 and is 12 KB, so it is current and costs nothing to keep.
- There are no tests and five of the ten files are superseded scripts kept in a legacy folder.

## What your goal means
A small, well-documented setup script is a useful portfolio footnote and a real time saver the next time a device is rebuilt.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push | 2026-11-08 | sourced | https://github.com/Dobeu-tech-eco/t3-android-setup, 2026-11-14 |
| Last commit on main | 2026-11-07 | sourced | https://github.com/Dobeu-tech-eco/t3-android-setup, 2026-11-14 |
| Files | 10 | sourced | https://github.com/Dobeu-tech-eco/t3-android-setup, 2026-11-14 |
| Size | 12 KB | sourced | https://github.com/Dobeu-tech-eco/t3-android-setup, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 5 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 7 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 2 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 1 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 1 | Work still needed before it could earn. | estimated |
| projections | 1 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 2 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 9 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 54/100

## Template path
not sellable: a one-command setup script is something people expect to find free. It could be published as a public gist or repo instead.

## Salvage list
The full setup script, the host restart loop and the README's notes on tunnel transport and boot location.

## What would change the answer
The owner stops running a coding host on Android, or the upstream tool ships its own installer.

## Next step
Keep it. Delete the legacy folder once the full script has survived one clean reinstall.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
