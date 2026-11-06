### Added

- `/dts2:fleet`: lists every harness session on this computer (label, repo@branch, state, last seen, turns, pending broadcasts), shows a session's handoff, task ledger, intake, lanes and cooldowns, and prints its recent turns, all read-only so a running session is never interrupted. `broadcast` sends one `note`, `handoff`, `pause`, `knowledge` or `checkin` message to all, or to `harness`, `repo:X`, `id:X` or `label:X` sessions; each session gets it once, on its next prompt, tool call or stop. The skill confirms the matching session count before sending. `status`, `label` and `prune` complete the set.
- `/dts2:check-in all`: gathers the check-in items from every session on the machine into one report that leads with what needs you, and offers (after a yes) to ask every live session for a fresh check-in. Without `all`, `/dts2:check-in` is unchanged.
- `hooks/fleet-session.sh` (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd) registers sessions and delivers broadcasts; `scripts/fleet.py` holds the registry and inbox in `DTS2_FLEET_HOME`, else `DTS2_HOME/fleet`, else `~/.dts2/fleet`.
- Limits: a session idle at the prompt receives a broadcast when next touched; a crashed session shows `stale`; the pid check is skipped on Windows; only sessions with the updated plugin register; per machine only.

### Fixed

- Fleet broadcast delivery no longer skips a message appended while a session was reading the inbox: each session keeps a `<id>.seen.json` marker holding the version of `broadcasts.jsonl` it read (captured before the read), instead of using the receipt write time. `prune` removes the marker with the receipt.
- `fleet.py broadcast --kind checkin --to all` (as used by `/dts2:check-in all`) now has a default text and no longer exits 2; other kinds still require text.
