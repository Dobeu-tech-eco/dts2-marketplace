### Fixed

- Incidents: `incident_capture: false` now also stops the StopFailure and PermissionDenied hooks from writing api-error / permission-denied incidents or touching the cooldown state (action items are unchanged).
- Incidents: promoted knowledge keys for project-local lessons carry the repo folder name (`incident-<project>-l-001`), so two projects no longer overwrite each other's `L-001`; home-tier `H-` ids keep their plain key.
- Incidents: the `Lessons:` verdict line accepts every injected id form, including knowledge ids such as `K-incidentl001`, and keeps their case so feedback reaches the lesson that was injected.
- Incidents: tier 4 lessons are found by listing the learning entries and filtering by agent class and paths in Python, because `knowledge.py find` is a literal substring search and never matched a multi-word query.
