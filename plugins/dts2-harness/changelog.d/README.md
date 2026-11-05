# changelog.d

One fragment per batch: `batch-<n>.md`. Each entry is a bullet starting with `- `; a wrapped bullet may continue on indented lines (they are joined onto the bullet), and `#` headings are ignored. Anything else (prose with no bullet) is reported as `dropped`. A pull request adds its own fragment instead of editing `## Unreleased` in the README, so two open pull requests never touch the same lines.

The README keeps its newest lines directly under `## Unreleased`, with the version history (`- 3.1.0 ...` down to the first release) below them in the same section. At release the lead runs `python3 scripts/changelog-join.py [--version <x.y.z>] --apply`:

- It inserts every fragment's bullets right after the `## Unreleased` heading, newest batch first (descending batch number; the lines of one fragment keep their order).
- With `--version`, only the lines above the first `- <semver>` history bullet move into a new `## <x.y.z> (<date>)` section under a fresh empty `## Unreleased`; the history bullets are left alone.
- It deletes the joined fragments after writing.
- If a fragment holds lines that are not bullets, continuations or headings, the JSON output lists them under `dropped` and `--apply` refuses (exit 1, nothing written, nothing deleted). Fix the fragment and run again.

Without `--apply` it only reports what it would do. Existing `Unreleased` lines stay where they are.
