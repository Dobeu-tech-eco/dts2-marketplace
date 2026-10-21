---
name: gtm
description: Take a product through go-to-market in one pass by running the installed marketing-skills plugin in a fixed order, feeding each step the harness's end state and marketing-surface list, and ending with a readiness scorecard of what is ready and what blocks launch. Use when the user says go to market, launch readiness, gtm, or wants positioning, SEO, page and copy review, and launch planning for a repo.
---

# GTM — one pass through marketing-skills

## Preflight
Check that `marketing-skills` is enabled with `/plugin` or `ListPlugins`. If it is not, print the install line (`/plugin install marketing-skills@<marketplace>`; on a claude.ai-synced account, enable it under synced plugins) and stop. Do not re-implement any step yourself.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-ignored.py" <repo>`.
Dispatch `dts2-harness:scout` for the marketing-surface list; without `.harness/end-state.md`, say so and continue with scout's output only.

## Inputs fed to every step
- Topology and acceptance criteria from `.harness/end-state.md`.
- The marketing-surface list from the `scout` agent (landing pages, pricing, docs, signup, emails, metadata).
- `.agents/product-marketing-context.md` once step 1 has written it.

## Sequence (exactly this order)
1. `/marketing-skills:product-marketing-context` — auto-draft from the repo.
2. `/marketing-skills:competitor-profiling`
3. `/marketing-skills:seo-audit`
4. `/marketing-skills:page-cro`
5. `/marketing-skills:copywriting`
6. `/marketing-skills:copy-editing`
7. `/marketing-skills:launch-strategy`
8. `/marketing-skills:analytics-tracking` — optional; ask once, skip on no.

## Outputs
Write to `.harness/gtm/<stamp>/` (`<stamp>` = `YYYYMMDD-HHMM`):
- one report per step, named `<step>.md` (for example `seo-audit.md`);
- `readiness.md`: a table with columns `area | ready (yes/no) | blocker | owner`, one row per step plus any gap the steps surfaced.

Finish by showing `readiness.md` and naming the top blocker.
