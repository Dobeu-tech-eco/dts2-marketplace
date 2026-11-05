### Fixed
- `reconcile` now records a lane that GitHub shows merged in `merge-order.json` (through the merge module's recorder), so `next_to_merge` no longer stalls on it.
- An empty-phase lane is no longer treated as orphanable, and `reconcile` bumps `resume_count` only when the move to orphaned really happened.
- `review_split` groups a top-level file under the root group and a file one folder deep under that folder, not under its own name.
- `graph_lease` records the lockfiles implied by a lane's manifests, not only its listed files.
- The final-review digest says how many lines it dropped when it truncates.
- `merge-plan` reordering respects `merge_after` (and provider) constraints, so a lane never moves ahead of one it must merge after.
