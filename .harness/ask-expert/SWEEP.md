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

Not visible to the reviewing agent: 20 private repositories. Their names are left out of this public file. Eleven of them were last pushed before 2026-09-20, which makes them older than half of the repos reviewed here. The owner has the list. Update 2026-11-14: part 2 below reviewed all 20 and lists them by name.

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

Nothing was archived, folded, deleted, transferred or changed in any swept repo. Each was cloned read-only and read with git. This pull request adds documents only.

The goal used for scores is portfolio, as in part 1, so the two tables compare. The owner has not confirmed it.

7 KEEP, 0 FOLD, 13 ARCHIVE. Of the ARCHIVE rows, three are empty repositories and seven more hold no product code: Replit-Design-Project, prompthooks, comp-gradiant-v0-temp, re-dobeutech-agents, re-sset-trajectory, ruflo-setup and ruflo-memory.

### Cleanup screen, part 2

Sorted by score, highest first. Tick only KEEP, FOLD, TEMPLATE, or ARCHIVE. DELETE is not on this screen.

| Repo | Score | Verdict | Confidence | Reason | Salvage |
|---|---|---|---|---|---|
| si-agent-core | 70 | KEEP | moderate | Active, tested CLI that gates agent prompt changes. v0.6.0, MIT. | The promotion rule, registry and reusable workflow. |
| dobeu-online | 58 | KEEP | moderate | Astro and Stripe rebuild of the company site. The domain answers from Vercel. | Cart store and Stripe checkout route with tests. |
| dts-portfolio | 58 | KEEP | moderate | Store of record for cross-repo specs, plans and findings. In use on 2026-11-07. | The design spec, plans and findings. |
| ex-staffing | 55 | KEEP | moderate | Staffing-site demo template for prospects. History still carries the old client's identity. | Marketing site, applicant flow and admin dashboard. |
| t3-android-setup | 54 | KEEP | moderate | One-command Android coding-host setup, written 2026-11-07, 12 KB. | The full setup script and README notes. |
| dobeu-knowledge-pilot | 49 | ARCHIVE | moderate | Mock-first search pilot. The owner's notes say preserve it as a reference. | Full-text retrieval, the 60-case evaluation and security tests. |
| claude-code-config-backup | 48 | KEEP | moderate | Scheduled config backup still pushing. Archive would break it. A credential sits in history. | The whitelist ignore file, hooks and rules. |
| ona-ubuntu | 45 | KEEP | low | Persistent SSH dev container. Usage is unknown, so keep is the reversible call. | SSH container, verify and backup scripts. |
| re-dobeutech-dev-enforcer | 41 | ARCHIVE | moderate | December 2025 standards CLI import. The standards repo is the live answer. | The four rule files and the pre-commit template. |
| ruflo-setup | 36 | ARCHIVE | moderate | Backup mirror of an earlier harness config, idle since July. | The notification script and two design notes. |
| re-webapp-maker | 35 | ARCHIVE | moderate | Replit design-generation prototype with a placeholder readme. | The design-forge frontend and API routes. |
| ruflo-memory | 30 | ARCHIVE | moderate | July transcript archive with session logs in git. Keep private. | The org-wide agent instruction pack, moved elsewhere. |
| Replit-Design-Project | 29 | ARCHIVE | moderate | Unmodified Replit scaffold, one commit. | None. |
| prompthooks | 27 | ARCHIVE | moderate | Two-file editor hook snapshot, no readme. | The hook definition. |
| comp-gradiant-v0-temp | 25 | ARCHIVE | moderate | License and a two-line readme. The template was never added. | None. |
| re-dobeutech-agents | 25 | ARCHIVE | moderate | Import whose zip held only an ignore file. | None. |
| re-sset-trajectory | 25 | ARCHIVE | moderate | A zip of another org project plus a session log. No source. | Anything in the zip the live repo lacks. |
| DOT-Copilot-replit | 24 | ARCHIVE | moderate | Empty repository, no commits. | None. |
| re-ai-coach | 24 | ARCHIVE | moderate | Empty repository, no commits. | None. |
| re-gitdobeucloud-lastplate | 24 | ARCHIVE | moderate | Empty repository, no commits. | None. |

### Unreadable repos

None. All 20 could be listed and cloned. The three empty ones have memos that say so.

### Risks for the owner, in general terms

This file is public, so each risk is named without the detail. The detail is in the private repos themselves.

- claude-code-config-backup: a credentials-shaped string sits in the git history of a settings file. Rotate it.
- claude-code-config-backup: the backup job pushes to a branch that is not the default branch, so the repo looks idle since July when it was last backed up on 2026-11-13. Archiving it would break the job.
- ex-staffing: the current tree is a debranded demo apart from two harness files that still mention the old brand, and earlier commits still carry the original client's name, contact details and screenshots. Do not make this history public. Clean those two files, then publish from a fresh copy if it is ever shown outside the org.
- ruflo-memory: agent session transcripts are stored in git. A scanner found nothing real, and a scanner cannot clear free text. Keep it private whatever else is decided.
- re-sset-trajectory: a zip of another project and a session log are tracked as files. The zip's two credentials-shaped strings are placeholders. The log was scanned and not read.
- dobeu-knowledge-pilot: five pull requests are open. Archive freezes them, so settle them first.
- dobeu-online: the domain answers from Vercel, but this pass did not confirm that the deployment builds from this repo. The repo has tests and no CI.
- This pull request publishes the names of 20 private repositories for the first time, because the memo folders are named after them. Part 1 left those names out. The names became public when this branch reached the public remote. Closing the pull request does not withdraw them.

No tracked `.env` file was found in the history of any of the 20. The env files that exist are examples, and the scan found no secrets in them.

### What ran and what did not, part 2

- `ask_expert.py check-report --goal portfolio`: ran on all 20 memos, all pass. It also passes on the 20 part 1 memos.
- `ask_expert.py sweep add`: ran. The ledger for part 2 is `sweep-20261114T153814Z.jsonl` in this folder. Part 1 has no ledger, so `sweep show` lists only these 20.
- Goal clarity questions: not asked. This pass ran unattended and reused part 1's unconfirmed portfolio goal.
- Three-seat panel: not seated. It would send private-repo facts to outside providers, and the request did not ask for paid calls. Each memo is one reviewer, so no confidence is high.
- Secret scan: gitleaks 8.30 over the full history of every branch of the 17 non-empty repos, with every hit classified by hand. The three zips tracked in re-dobeutech-agents, re-dobeutech-dev-enforcer and re-sset-trajectory were opened and scanned too. Not opened: six compressed skill archives on the claude-code-config-backup backup branch, and one zip that exists only in the early history of ex-staffing.
- OpenSSF Scorecard and dependency scans: not run. Security scores are estimated.
- No code from any swept repo was run. Test counts are counts of test files, not passing tests.
- Dates: push dates are UTC and commit dates are the committer's local date, so the two can differ by a day.
- Review: six independent reviewers checked the memos against the clones and read every added line for public safety, and a second set re-ran each finding. 36 findings survived and were addressed. No verdict or score changed.
- Ticks: none applied. No to-do file was written and no archive command was run.
