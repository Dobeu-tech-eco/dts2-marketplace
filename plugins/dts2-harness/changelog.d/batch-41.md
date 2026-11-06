### Fixed

- Incident bot: tier-4 knowledge lessons with long keys (for example `incident-alpha-app-l-001` and `-l-002`) no longer collapse to the same `K-` id; ids are now a cleaned prefix plus a short hash of the full key, so each lesson is selected on its own and keeps its own feedback counters.
- Incident bot: the knowledge cap of three now applies after demoted and expired lessons are filtered out, so inactive entries can no longer permanently block an active one.
- Tests: the in-process hook speed check now times three runs and asserts the fastest stays under the 0.2s budget, so one slow sample on a shared CI runner no longer fails the build.
