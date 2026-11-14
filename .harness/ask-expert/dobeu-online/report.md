VERDICT: KEEP
CONFIDENCE: moderate

## Why
- The README says this is the Astro and Stripe rebuild of the dobeu.online site, and that domain answers from Vercel today, which is where this repo deploys.
- The tree is small and complete: 10 pages, a checkout route, three unit test files and one end-to-end smoke test.
- It has only two commits, both on 2026-10-05, and no CI, so it is a finished conversion that nobody has had to touch since.

## What your goal means
A public company site is a portfolio piece by definition. If this repo is what serves the domain, it has to stay.

## Numbers that mattered
| Number | Value | Label | Source and date |
|---|---|---|---|
| Last push and last commit on main | 2026-10-05 | sourced | https://github.com/Dobeu-tech-eco/dobeu-online, 2026-11-14 |
| Commits | 2 | sourced | https://github.com/Dobeu-tech-eco/dobeu-online, 2026-11-14 |
| Domain served by | Vercel | sourced | https://dobeu.online, 2026-11-14 |
| Size | 969 KB | sourced | https://github.com/Dobeu-tech-eco/dobeu-online, 2026-11-14 |

## Scorecard
| Factor | Score | Method | Evidence |
|---|---|---|---|
| security | 7 | No OpenSSF Scorecard (private repo) and no dependency scan. Score is from a gitleaks pass over the full history of every branch, data or archive files in git, and whether CI and a security policy exist. | estimated |
| code_health | 6 | Tests and CI in the tree, size, and time since the last commit on the default branch. Nothing was run. | estimated |
| product_viability | 7 | Whether the README's job can be done with the tree that exists today. | estimated |
| market_size | 3 | One-owner or one-client use, not a category forecast. | estimated |
| revenue_potential | 4 | Whether this repo can charge or already serves a paying relationship. | estimated |
| time_to_profit | 4 | Work still needed before it could earn. | estimated |
| projections | 2 | No three-year model. Score follows how specific the buyer is. | assumed |
| moat | 3 | Brand, customer data, or a harness others would have to rewrite. | estimated |
| upkeep_cost | 7 | 10 means cheap to keep. Score follows size, hosting, and how often it must move. | estimated |

Overall: 58/100

## Template path
Could be an Astro storefront starter after the brand content is removed, in the $20-$60 band. It is not prepared for that, and the content is the company's own.

## Salvage list
The cart store, the line-item builder and the Stripe checkout route, with their tests.

## What would change the answer
The Vercel project for the domain builds from a different repo, or the site goes back to its previous host.

## Next step
Keep it. Confirm in Vercel that the production deployment builds from this repo, then add the shared CI baseline so the tests run on push.

## Appendix
Single reviewer, part 2 of the sweep, 2026-11-14. The three-seat panel was not seated: it would send private-repo facts to outside providers and the request did not ask for paid calls, so confidence is capped at moderate. The goal was taken as portfolio, as in part 1, and the owner has not confirmed it. The repo was cloned read-only and read with git. No code was run. Security evidence is a gitleaks 8.30 pass over the full history of every branch, with findings classified by hand. No OpenSSF Scorecard and no dependency scan were run. Push dates are UTC and commit dates are the committer's local date, so the two can differ by a day. This file is public, so risks are described in general terms and the detail goes to the owner. No archive, delete, fold, transfer, visibility or settings change was applied.
