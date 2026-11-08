---
name: dt-action-items
description: "Cursor name /dt-action-items for the Claude Code command /dt:action-items. Show open action items (Secrets, Decisions, Handoff, Deploy, Promotions) with age, owner and resolving command; mark done, add, or assign. Use when asked what is left, what is blocked on me, action item..."
---

# /dt-action-items

Cursor command for the Claude Code command `/dt:action-items`. Read-only in this package.

If `.harness/action-items.md` is missing, say there is no action-items file and stop. If it exists, show rows whose status starts with `open`, with the row id and the group (Secrets, Decisions, Handoff, Deploy, Promotions). Do not print a secret's value. Do not mark a row done, add a row, or assign one.
