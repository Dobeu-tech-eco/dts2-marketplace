---
name: dt-gtm
description: "Cursor name /dt-gtm for the Claude Code command /dt:gtm. Take a product through go-to-market in one pass: installs marketing-skills if missing, runs a short GTM deep-dive and the skills that apply, and ends with a launch-readiness scorecard. Use for go to market, launch readin..."
---

# /dt-gtm

Cursor command for the Claude Code command `/dt:gtm`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Take a product through go-to-market in one pass: installs marketing-skills if missing, runs a short GTM deep-dive and the skills that apply, and ends with a launch-readiness scorecard. Use for go to market, launch readiness, gtm, or SEO review.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/gtm/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


The instruction text still calls four marketing skills by old names. The credit register checked on 2026-11-07 maps them to the live names: `product-marketing-context` to `product-marketing`, `page-cro` to `cro`, `launch-strategy` to `launch`, and `analytics-tracking` to `analytics`. `competitor-profiling`, `seo-audit`, `copywriting`, and `copy-editing` still match. Do not install that pack from this command.
