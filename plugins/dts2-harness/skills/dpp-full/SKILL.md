---
name: dpp-full
description: dpp with --full. The head fills up to five lanes from the check-in list plus a delegation scan of sons' questions, parked items and new action items, and keeps dispatching without asking. Use when the user says dpp-full or full parallel autopilot.
disable-model-invocation: true
---

# dpp-full — dpp with `--full`

Everything is `skills/dpp/SKILL.md`; run it with `--full`.
The only differences: the delegation scan joins the lane sources (section 1), and continuous dispatch starts the next lane without a new approval (section 5).
It still stops at `pr-open` and never merges a `blocked` PR.
