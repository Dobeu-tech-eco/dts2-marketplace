> Directory edition: do not run bundled scripts or hooks, a package launcher, or a download piped into a shell. Do not read tokens or credential files from the machine. Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.

# autopilot - son contract (mailbox rules of section 6)

## Son contract
Every rule below binds a son started with `--son`; the head is the other end of each message (`lanes.py mailbox`, run with `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py"`). Each line cites the section it narrows instead of repeating it.
- **No own stamp.** The stamp and lane come from `--son <stamp>/<lane>` and `brief.md`; a son never creates a run, stamp or `.harness/autopilot/` folder (section 0 belongs to the head).
- **Protected records.** A son never writes `.harness/end-state.md`, `.harness/council.md`, `.harness/state.md`, `.harness/lessons.md` or `.harness/autopilot/latest.md`; its findings go in `report.md` and the head folds them (dpp section 7).
- **No prompts to a person.** Where sections 0 to 5a would ask the user, the son sends `mailbox need-human <stamp> --lane <lane> --text "..."` and waits with `mailbox wait`; the head answers, never the user.
- **Every wait has a deadline.** `mailbox_wait_min` bounds each wait; on expiry the lane parks `incomplete` with reason `mailbox-timeout` (section 4) and the head decides what happens next.
- **Seat-pool collapse parks.** When fewer than three distinct voter seats answer (section 1), the son runs `mailbox park <stamp> --lane <lane> --reason seat-pool-collapse` and stops; it never votes with a short panel.
- **Context guard parks.** When the context guard fires inside a son, the son runs `mailbox park <stamp> --lane <lane> --reason context-guard --session-id <id>`, which writes `incomplete` with the session id so the head can resume it.
- **No browser parks.** When a walkthrough needs a browser and the son has none, it runs `mailbox park <stamp> --lane <lane> --reason no-browser`; it never marks the check skipped.
- **Merge needs the exact head.** The son reports `pr-open` first (the head only offers the merge to lanes at `pr-open`), then waits for the grant and runs `mailbox merge-go-check` before it merges; a HEAD that differs from `verified_head_sha` voids the grant. Every write carries `--epoch` from `brief.md`; a stale epoch is ignored.
- **Fresh rules.** The son runs `mailbox rules --point start|vote|ship|merge` at its start and before each vote, ship and merge, and re-reads every file the answer lists as changed.
- **Out of lane.** A change outside the file set is asked for with `mailbox request`; it climbs head, vote, council, user, one rung at a time. A son never uses `lanes.py override`.
