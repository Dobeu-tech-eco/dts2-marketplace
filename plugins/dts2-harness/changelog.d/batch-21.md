### Fixed
- Policy gate and merge guard: bundled `env` flags (`env -iu PATH git push --force`) no longer hide the command word, so the force-push rule still applies (review findings).
- Policy gate: a flag-only deny rule (`gh ... --admin`, `vercel --prod`) fails closed when an argument is a shell expansion, with or without a sub-command.
- Policy gate: `$(...)` and backticks inside single quotes are text, so `git commit -m '$(env)'` is no longer denied as an environment dump; double-quoted and bare substitutions are still checked.
- Policy gate: a rule's sub-command matches only at the sub-command position, so `gh pr create --title secret` is no longer denied as `gh secret`.
- G-54 dedupe: `lessons.py regress`, `action-items.py add` and `council.py` keep the dedupe id only after the write succeeded; a failed first attempt no longer turns the retry into a silent duplicate.
- `council.py next-round` seeds the instance counter from earlier allocations in `instances.json`, so a resumed run never reuses an instance id.
- Preflight head push probe runs `git -c core.hooksPath=/dev/null push --dry-run --no-verify`, so the repo's `pre-push` hook never runs during the probe.
- `lanes.py publish` is head-only: denied in a son's Bash (guard and launch deny list), refused for a son, voter or council role even without env markers, and `lanes.py call` refuses a wrapped command that sets or unsets `DTS2_SON*`.
