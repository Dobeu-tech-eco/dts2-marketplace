### Fixed

- `append_text` with a `header` now creates the log with the header already inside (temp file plus `os.link`), so a row appended by a concurrent writer can no longer be overwritten by the header write.
- `test_resume_charges_only_the_difference` no longer flakes with `no-final-status`: the fake son wrote `status.json` unlocked while the supervisor recorded `son_pid` as a read-merge-write, so the son's final status could be lost; it now waits for `son_pid` and replaces the file atomically.
