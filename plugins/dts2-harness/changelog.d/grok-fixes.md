### Added
- grok-fixes: lane ownership gate. `merge-go` refuses a lane whose branch changed files outside its owned set (the integration lane is audited against its integration files), and `lanes.py audit <manifest> <lane> --head <sha>` shows why.
- grok-fixes: merge-order property tests (random dependency graphs and merge-go/merge-done interleavings).

### Fixed
- grok-fixes: the onboard skill counted six agents; there are seven.
