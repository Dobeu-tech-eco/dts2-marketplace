---
name: dpp-full
description: dpp with --full. Adds a delegation scan and fills up to five lanes. Outside autopilot it asks before each new lane (dpp_full_ask_each_lane defaults true). Autopilot and fullauto skip that ask. Use when the user says dpp-full or full parallel autopilot.
disable-model-invocation: true
---

# dpp-full — dpp with `--full`

Everything is `skills/dpp/SKILL.md`; run it with `--full`.
The only differences: the delegation scan joins the lane sources (section 1), and continuous dispatch starts the next eligible lane (section 5). Outside autopilot, section 8 asks before each new lane while `dpp_full_ask_each_lane` is true (the default). Autopilot and fullauto skip that ask.
It still stops at `pr-open` and never merges a `blocked` PR.
