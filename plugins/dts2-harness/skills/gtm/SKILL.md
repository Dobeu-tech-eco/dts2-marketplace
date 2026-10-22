---
name: gtm
description: Take a product through go-to-market in one seamless pass. Auto-installs marketing-skills if it is missing, runs a short GTM deep-dive that reuses the approved end state, lets marketing-skills pick the skills that apply to the repo, runs them back to back, and ends with a readiness scorecard of what is ready and what blocks launch. Use when the user says go to market, launch readiness, gtm, or wants positioning, SEO, page and copy review, and launch planning for a repo.
---

# GTM — one seamless pass

This command never hard-stops. If something is missing it installs it, falls back, or continues with what is available.

## 1. Ensure marketing-skills (never stop)
- Already available? Check with `/plugin` or `ListPlugins`, or by whether the Skill tool can invoke `marketing-skills:<name>`. If so, use it.
- Not available: install headlessly with `npx skills add https://github.com/coreyhaines31/marketingskills` (the same headless mechanism the harness uses for its companion skills), then use the installed skills.
- Only if that genuinely cannot run (offline, or a non-synced environment): print ONE line — enable `marketing-skills@synced` under synced plugins, or run `/plugin install marketing-skills@claude-cowork` — and continue with whatever is available.
- Prefer the marketing-skills skills and do not hand-reimplement them when they are available.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-ignored.py" <repo>`.
Dispatch `dts2-harness:scout` for the marketing-surface list; without `.harness/end-state.md`, say so and continue with scout's output only.

## 2. GTM deep-dive
Before the pipeline, run a short deep-dive.
- Read `.harness/end-state.md` and `.harness/latest.md` first. Do not re-ask anything they settle: the rebrand direction is already approved, so treat it as fixed.
- Ask one to three clarifying questions, only on what is still open: positioning angle, primary audience, launch goal and date, priority channels.
- Offer to re-run the deep-interview project parse (the end-to-end sectioned parse) to feed GTM. If the user declines or is away, proceed from the existing end state.
- Write the answers into `.agents/product-marketing-context.md` as inputs.

## 3. Select the skills
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/marketing-select.py" --facts '<json>'` with facts from scout and the deep-dive (`has_web`, `has_landing`, `has_marketing_surface`, `analytics`). It returns the ordered subset of marketing skills this repo needs. The full pipeline, in canonical order, is below; selection chooses which of these run, never their order.

## 4. Run as one pass
Execute the selected skills back to back, feeding each the end state, the marketing-surface list, and `.agents/product-marketing-context.md`. Narrate it as a single GTM pass: do not announce each skill or present them as separate skills to the user. Each still writes its report behind the scenes.

Canonical order (the full pipeline):
1. `/marketing-skills:product-marketing-context` — auto-draft from the repo.
2. `/marketing-skills:competitor-profiling`
3. `/marketing-skills:seo-audit`
4. `/marketing-skills:page-cro`
5. `/marketing-skills:copywriting`
6. `/marketing-skills:copy-editing`
7. `/marketing-skills:launch-strategy`
8. `/marketing-skills:analytics-tracking` — runs only when selected (analytics fact true).

## 5. Outputs
Write to `.harness/gtm/<stamp>/` (`<stamp>` = `YYYYMMDD-HHMM`):
- one report per step that ran, named `<step>.md` (for example `seo-audit.md`);
- `readiness.md`: a table with columns `area | ready (yes/no) | blocker | owner`, one row per step plus any gap the steps surfaced.

Finish by showing `readiness.md` and naming the top blocker, as one unified result.
