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

Not visible to the reviewing agent: 20 private repositories. Their names are left out of this public file. Eleven of them were last pushed before 2026-09-20, which makes them older than half of the repos reviewed here. The owner has the list.

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
