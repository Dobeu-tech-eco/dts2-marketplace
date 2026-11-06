### Added

- `/dts2:incidents` (`list`, `live`, `brief`, `review`, `resolve`, `promote`, `lessons`): see agent incidents (thin briefs, empty or partial reports, rework of another agent's files, hung spawns), the live agent view and the end-of-run brief, and run a reviewed debrief. It explains the two loops (live correction by hook, end-of-shift review) and the five-tier ladder that moves only repeat trends up, ending at `evolve` and a PR with an explicit yes.
- `incident-reviewer` agent (read-only, sonnet): finds a root cause with a short five-whys for each open incident, marks it isolated or trend, and proposes local lessons, promotions and `harness:` lines. It never edits files.
- Docs: incidents sections in `COMMANDS.md`, `GUIDE.md`, `ARCHITECTURE.md` and `INVENTORY.md`; skill count 26 and agent count 8.
