---
name: dpp-full
description: dpp with --full. The head fills up to five lanes from the check-in list plus a delegation scan of sons' questions, parked items and new action items. Outside autopilot it asks before each new lane while dpp_full_ask_each_lane is true, which is the default. Autopilot and fullauto skip that ask. Use when the user says dpp-full or full parallel autopilot.
disable-model-invocation: true
---

# dpp-full — dpp with `--full`

Everything is `skills/dpp/SKILL.md`; run it with `--full`.
The only differences: the delegation scan joins the lane sources (section 1), and continuous dispatch starts the next eligible lane (section 5). Outside autopilot, section 8 asks before each new lane while `dpp_full_ask_each_lane` is true (the default). Autopilot and fullauto skip that ask.
It still stops at `pr-open` and never merges a `blocked` PR.
