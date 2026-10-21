# Harness handoff

Written by `scripts/handoff-write.py` at every run end and by the Stop hook. Any agent reads this first. Never edit by hand; it is rewritten. It holds names only, never secret values.

Latest run: <run>

## State

<state>

## Open items

<open_items>

## Next action

<next_action>

## Resume

`/dts2-harness:run resume` reads this file first, then continues from the next action above.

## Recommended agent

<recommended_agent>
