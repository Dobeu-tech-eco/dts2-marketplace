# Dobeu-tech-eco repo sweep, oldest 20 of the 33 visible repos

Reviewed 2026-11-12. The reviewing agent could see 33 repositories in `Dobeu-tech-eco`, none archived. The org has 53: a full listing on 2026-11-13 shows 20 more private repositories that the agent's token could not see. This pass is the 20 with the oldest `pushedAt` among the 33 visible. It is not the org's 20 oldest. Only 10 of these 20 are in the org-wide oldest 20; the other 10 org-wide oldest are among the repositories the agent could not see. 33 repositories were not reviewed: 13 visible and 20 not visible.

Nothing was archived, folded, or deleted. `dt_gate.py bridge ask_expert.py` is blocked in the Cursor package (`unsupported-runtime-script`), so there is no official ledger and no tick was applied.

The goal used for scores is portfolio. You have not confirmed it. If the goal is money, or one of these repos is in daily use, say so and the verdicts move.

## Cleanup screen

Sorted by score, highest first. Tick only KEEP, FOLD, TEMPLATE, or ARCHIVE. DELETE is not on this screen.

| Repo | Score | Verdict | Confidence | Reason | Salvage |
|---|---|---|---|---|---|
| .github | 67 | KEEP | moderate | Org default PR template other repos inherit. | The change-receipt section. |
| ai-tutor | 64 | KEEP | moderate | Live coaching site for dobeu.tech. | The Next.js app and its tests. |
| standards | 63 | KEEP | moderate | Shared CI baseline pinned at @v1. | checks/ and the baseline workflow. |
| routeready-trainer-ios | 62 | KEEP | moderate | iOS client of the live RouteReady product. | MyApp/ and Tests/. |
| ikram-meme-and-co | 57 | KEEP | moderate | Client sticker store with a Stripe fix. | Storefront and webhook patterns. |
| dts-contract-engine | 56 | KEEP | moderate | Quote and consulting-hour tool, phase 1 still open. | Pricing engine and PDF path. |
| dobeutech-sales-funnel-itconsult | 55 | KEEP | moderate | Private prospect-to-invoice app, still in the working set. | Authenticated prospect API. |
| super-rag-mcp | 53 | KEEP | moderate | Shipped local-file RAG MCP, MIT, tests. | src/ and config.example.yaml. |
| baldor-safety-insights | 52 | KEEP | moderate | Private Baldor app, the later of the two trees. | Upload detectors and charts. |
| one-composio-mcp | 49 | ARCHIVE | moderate | Tested bridge, idle since June, Composio MCP is already connected. | src/ and tests/ if you self-host sessions. |
| nailpro-inventory-purchase-platform | 48 | KEEP | low | Salon inventory app. Usage is unknown, so keep is the reversible call. | Multi-tenant inventory screens. |
| dobeu-design-system | 45 | ARCHIVE | low | Design System v2. No app installs @dobeu/tokens, but new-dobeu-net copies its values. | @dobeu/tokens and the token contract. |
| monty-ai-fullstackdev-coder | 44 | ARCHIVE | moderate | Earlier agent package. The marketplace is the harness you ship. | AUTONOMOUS_WORKFLOWS.md if a workflow is missing. |
| baldor-safety-platform | 42 | FOLD | moderate | Same Baldor product as baldor-safety-insights, older and public. | Charts or migrations the November repo lacks. |
| whatsapp-bot | 37 | ARCHIVE | moderate | Replit WhatsApp prototype, last push 2026-08-16, no README. | Webhook server if a client still wants WhatsApp. |
| plugin-claudeharness | 37 | ARCHIVE | moderate | 8 KB sketch of the pipeline the marketplace already ships. | The pipeline diagram. |
| vercel-ai-gateway-demo | 33 | ARCHIVE | moderate | Untouched Vercel AI Gateway demo. | None. |
| ai-sdk-feature-flags-edge-config | 32 | ARCHIVE | moderate | Untouched Vercel AI SDK example. | None. |
| bookmark-software-cat | 32 | ARCHIVE | moderate | Personal registry plus a password vault, with data files in git. | The bookmark idea, after the dumps are reviewed offline. |
| dobeutech-designsystem-weaver | 30 | ARCHIVE | low | Replit workspace, no README text. Artifacts were not opened. | Whatever converter lives under artifacts/. |

## Not reviewed

Visible to the reviewing agent, newer pushes:

routeready, new-dobeu-net, dev_usp-com, DOT-Copilot, dobeu-space, routereadyhq-apk, dts2-marketplace, chimacomics, lastplateprod, androidbackend, dobeu-v0-skills-pack, accident-dobeu, statminer.

Not visible to the reviewing agent: 20 private repositories. Their names are left out of this public file. Eleven of them were last pushed before 2026-09-20, which makes them older than half of the repos reviewed here. The owner has the list. Update 2026-11-14: part 2 below reviewed all 20 under neutral labels; the names stay out of this file.

## Gates that did not run

- `roster.py detect` and `lead_skills.py gaps`: BLOCKED unsupported-runtime-script. Skill parity was not synced and no agent was marked behind.
- `hooks-setup.py recommend`: BLOCKED, maps to hook-install. No hooks were added.
- `ask_expert.py` clarity, check-report, sweep add, archive, backup, delete: BLOCKED. Do not treat this file as that ledger.
- Three-seat panel: not seated. Paid provider calls stay unexecuted. Each memo is one reviewer, so confidence is not high.
- OpenSSF Scorecard: the public API returned 404 for one-composio-mcp. Security scores are estimated.

Memos and comparisons are in `.harness/ask-expert/<repo>/`.

## Review corrections, 2026-11-13

A second reviewer checked the 20 memos against GitHub. No verdict or score changed. One confidence dropped: dobeu-design-system, moderate to low. All 20 scorecards match the portfolio weighting.

- Scope: the org has 53 repositories, not 33. See the first paragraph and the Not reviewed section.
- Dates: five memos gave a branch push date to a commit on the default branch. Corrected in ai-tutor, dts-contract-engine, standards, nailpro-inventory-purchase-platform and whatsapp-bot.
- Counts: the rows labelled open issues are GitHub's combined count of open issues and open pull requests. The label now says so. In most of these repos the count is all pull requests.
- Claims that nothing else in the org does the same job now say nothing else among the visible repos.
- dobeu-design-system: the memo said v2 is no longer a source for any app. new-dobeu-net, the dobeu.net production site, names @dobeu/tokens as its source of truth and copies the values. The verdict stays ARCHIVE and confidence is now low.
- baldor-safety-insights `.env`: opened read-only. It holds the Supabase project id, URL and publishable key, the values a browser build ships. No service-role key or database password, on any branch. `.gitignore` does not list `.env`.
- bookmark-software-cat data files: opened read-only. The findings went to the owner and are not in this public file. Archiving does not change who can read a repository, so visibility is a separate decision from archive.
- Since the review, baldor-safety-insights and ikram-meme-and-co received new branch pushes on 2026-11-12, and the three open pull requests on ai-tutor were closed. The memos are a 2026-11-12 snapshot and were not re-dated.

## Part 2, 2026-11-14: the 20 private repos part 1 could not see

Reviewed 2026-11-14 with a token that can read private repositories. A fresh listing shows 53 repositories in `Dobeu-tech-eco`, none archived. Taking out the 20 that part 1 reviewed and the 13 it listed as visible but not reviewed leaves 20, and they are exactly the 20 names the owner expected. All 20 were readable. Three of them are empty: no commits and no branches.

One difference from the brief for this pass: it describes part 1 as covering 33 repos. Part 1 wrote memos for 20. The other 13 are the newer visible repos in its Not reviewed section, and they are still not reviewed after this pass. So the org stands at 40 reviewed and 13 not.

Nothing was archived, folded, deleted, transferred or changed in any swept repo. Each was cloned read-only and read with git. This change adds documents only.

The goal used for scores is portfolio, as in part 1, so the two tables compare. The owner has not confirmed it.

7 KEEP, 0 FOLD, 13 ARCHIVE. Of the ARCHIVE rows, three are empty repositories and seven more hold no product code.

### What this public file leaves out

This repository is public and the 20 repos are private. Each one appears here only as a label, P2-01 to P2-20. The per-repo memos, the comparison notes, the sweep ledger, the map from label to name, the reason and salvage note for each row, and the per-repo risks are held privately by the owner. `.gitignore` excludes `.harness/ask-expert/private/`, the folder they are kept in.

### Cleanup screen, part 2

Sorted by score, highest first. Tick only KEEP, FOLD, TEMPLATE, or ARCHIVE. DELETE is not on this screen. The reason behind each row is in the owner's private copy.

| Repo | Score | Verdict | Confidence |
|---|---|---|---|
| P2-01 | 70 | KEEP | moderate |
| P2-02 | 58 | KEEP | moderate |
| P2-03 | 58 | KEEP | moderate |
| P2-04 | 55 | KEEP | moderate |
| P2-05 | 54 | KEEP | moderate |
| P2-06 | 49 | ARCHIVE | moderate |
| P2-07 | 48 | KEEP | moderate |
| P2-08 | 45 | KEEP | low |
| P2-09 | 41 | ARCHIVE | moderate |
| P2-10 | 36 | ARCHIVE | moderate |
| P2-11 | 35 | ARCHIVE | moderate |
| P2-12 | 30 | ARCHIVE | moderate |
| P2-13 | 29 | ARCHIVE | moderate |
| P2-14 | 27 | ARCHIVE | moderate |
| P2-15 | 25 | ARCHIVE | moderate |
| P2-16 | 25 | ARCHIVE | moderate |
| P2-17 | 25 | ARCHIVE | moderate |
| P2-18 | 24 | ARCHIVE | moderate |
| P2-19 | 24 | ARCHIVE | moderate |
| P2-20 | 24 | ARCHIVE | moderate |

### Unreadable repos

None. All 20 could be listed and cloned. The three empty ones have memos that say so.

### Risks for the owner

The pass recorded risks against six of the 20 repos. They are not repeated in this public file. The owner's private copy lists each one with the action it needs, and some need action before any archive tick is applied.

No tracked `.env` file was found in the history of any of the 20. The env files that exist are examples, and the scan found no secrets in them.

### What ran and what did not, part 2

- `ask_expert.py check-report --goal portfolio`: ran on all 20 memos, all pass. It also passes on the 20 part 1 memos.
- `ask_expert.py sweep add`: ran. The ledger for part 2 is kept in the ignored `private/` folder. Part 1 has no ledger, so `sweep show` lists only these 20.
- Goal clarity questions: not asked. This pass ran unattended and reused part 1's unconfirmed portfolio goal.
- Three-seat panel: not seated. It would send private-repo facts to outside providers, and the request did not ask for paid calls. Each memo is one reviewer, so no confidence is high.
- Secret scan: gitleaks 8.30 over the full history of every branch of the 17 non-empty repos, with every hit classified by hand. Tracked archives were opened and scanned too, apart from seven that the private copy lists as not opened.
- OpenSSF Scorecard and dependency scans: not run. Security scores are estimated.
- No code from any swept repo was run. Test counts are counts of test files, not passing tests.
- Dates: push dates are UTC and commit dates are the committer's local date, so the two can differ by a day.
- Review: six independent reviewers checked the memos against the clones and read every added line for public safety, and a second set re-ran each finding. 36 findings survived and were addressed. No verdict or score changed.
- Ticks: none applied. No to-do file was written and no archive command was run.
- This section replaces pull request #107. That branch carried the private names in an earlier commit's file paths, so it was closed without merging and this text was written as a new commit.
