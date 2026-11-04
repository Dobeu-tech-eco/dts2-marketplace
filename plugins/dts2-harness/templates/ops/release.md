# Release: <project>

## Version and changelog

- Version numbers follow semver: a breaking change raises the major number, a new feature the minor, a fix the patch.
- Every release gets an annotated tag `v<major>.<minor>.<patch>` on the commit that was deployed, and one changelog entry written for the people who use the app.
- The changelog entry and the tag are made as part of shipping, not afterwards.

## Promotion path

| stage | what runs there | gate to move on |
|---|---|---|
| preview | one per pull request | CI green, reviewer approved |
| staging | the merged main branch | smoke test passes, migrations applied with a backup |
| production | the same build that passed staging | person approves; post-deploy watch starts |

Promote the same build, not a rebuild. If staging does not exist yet, preview stands in and the gap is written in the runbook.

## Feature flags for risky work

Put risky changes behind a flag that defaults to off.

| field | value |
|---|---|
| flag tool | <provider flags, config value, or environment variable> |
| naming | `<area>.<change>` |
| default | off in production |
| rollout | internal users, then a small share, then everyone |
| removal | delete the flag and the old path within two releases of reaching everyone |

The hook is one function that reads the flag, `isEnabled("<name>")`, so the tool can change without touching call sites.
