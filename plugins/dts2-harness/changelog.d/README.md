# changelog.d

One fragment per batch: `batch-<n>.md`, bullet lines only (each starts with `- `). A pull request adds its own fragment instead of editing `## Unreleased` in the README, so two open pull requests never touch the same lines.

At release the lead runs `python3 scripts/changelog-join.py --version <x.y.z> --apply`. It appends every fragment's bullets, in batch order, to `## Unreleased`, renames that section to `## <x.y.z> (<date>)`, opens a fresh `## Unreleased`, and deletes the joined fragments. Without `--apply` it only reports what it would do. Existing `Unreleased` lines stay where they are.
