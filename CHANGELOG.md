# Changelog

All notable marketplace-level changes are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This project follows [Semantic Versioning](https://semver.org/).

The plugin's full release history lives in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md). The Claude directory listing is the generated instruction edition at [plugins/dts2-harness](plugins/dts2-harness).

## Unreleased

## [5.6.1]

_Released 2026-11-26_

A fix to 5.6.0. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Fixed

- `/dt:ship`, run phase 4 and the discipline rules now fill the receipt's Merge danger and Evidence fields.

## [5.6.0]

_Released 2026-11-26_

Planning and pull request rules, a glossary, and an onboarding step for your own `CLAUDE.md`. Nothing breaking. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Added

- [GLOSSARY.md](GLOSSARY.md): one meaning per harness term, with the words to avoid.
- `AGENTS.md` section "Plans and checks": the repository's planning rules.
- `claude-md-rules.py` and `/dt:machine-prep` step 7: add the planning and PR rules to your own `CLAUDE.md`, after you see the diff.
- PR template: Merge danger and Evidence sections.

## [5.5.2]

_Released 2026-11-25_

A dependency update for the headless runner. Nothing breaking. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Changed

- Dependency update from Dependabot: `claude-agent-sdk` 0.2.185.

## [5.5.1]

_Released 2026-11-25_

The team charter reads the roster from `.harness/config.yaml`. Nothing breaking. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Fixed

- Without a saved probe file, a charter whose roster lives in `.harness/config.yaml` no longer falls back to claude on every seat. The older `.claude/dts2-harness.local.md` roster still works.

## [5.5.0]

_Released 2026-11-25_

An optional team charter maps named providers onto the seats the harness already uses, and the root README badge stays on the plugin version. Nothing breaking. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Added

- Optional `TEAM.md` names which roster provider fills the lead, builders, reviewer, playtester, copywriter and dispatcher. Without the file, seat assignment is unchanged. A provider or connector that does not answer is a one-line warning and the next provider, or the usual roster.
- Handoffs under a charter use a seven-field brief. A review loop stops after 3 rounds and asks the person. Merges, deploys and spending still need an explicit human approval.

### Fixed

- The root README version badge now tracks the plugin version through `bump-version.py`.
- A charter warning keeps the provider `resolve` chose. A provider whose profile cannot fill the seat is skipped for the next one in the row. A roster alias of an API-key profile cannot take lead or sign-off.

## [5.4.0]

_Released 2026-11-18_

Reviews judge a diff against the base branch's own rules, pre-existing findings no longer block a change, and a stuck failure escalates sooner. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Added

- Base-branch review rules: reviewers judge a diff against the checklist and lessons as they stand on the base ref, so a diff cannot edit the rules that judge it.
- Stuck-failure escalation: a deterministic check that stays red the same way three reruns in a row escalates to the user instead of spending the remaining fix rounds.
- Context scrub now covers every rostered agent and runs as `setup` Round 2d.

### Changed

- Pre-existing findings are separated from the change and left out of the verdict caps; a pre-existing label on a line the diff did change becomes a blocking finding.
- A test that fails and then passes on an unchanged tree is recorded as flaky, not a clean pass.

### Removed

- The `fleet-ledger` plugin is removed from the marketplace, with its SQL, client, tests and CI job. No agent could reach its database, so it did nothing useful. `dt` never depended on it and is unchanged. If you installed it, remove it with `claude plugin uninstall fleet-ledger@dts2`.

## [5.3.0]

_Released 2026-11-16_

One command now guides the harness, ships are tied to the roadmap, and every edition reports the version it really carries. Nothing breaking. Full notes are in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md).

### Added

- `/dt:go` picks the next command from the repo's state and runs it, so a new user needs only one command.
- Ship revamp: every PR names an end-state section or an open action item, a repo at its open-PR cap gets no new PR, and only safe strays are folded in.
- A release gate on pull requests to `main`: a change under `plugins/dts2-runtime/` without a version bump fails the check.
- `fleet-ledger` 0.1.0 is listed as an optional second plugin.

### Changed

- Dependency updates rolled up from Dependabot: `claude-agent-sdk` 0.2.180, `pytest` 9.2.0, `pytest-xdist` 3.8.0, `hypothesis` 6.170.15 and `actions/setup-node` 7.1.0.
- Docs: `AGENTS.md` at the repository root holds the rules for AI coding assistants that edit this repository. Every documentation page now opens with a "For people" section and a "For agents" section.
- Branches: `main` and `dev` are the two long-lived branches. The Cursor package README now installs from `main`.
- License: the current tree is MIT. Copyright Dobeu Tech Solutions LLC. Forks may add, remove, and ship the work, including in paid products. Keep the copyright notice.

## [5.2.0]

_Released 2026-11-10_

### Added

- `/dt:loop` researches one role instruction on a frozen batch of past receipts, with fixed token and time caps, and keeps or reverts each change mechanically.

## [5.1.1]

_Released 2026-11-07_

### Added

- Publisher metadata in both manifests: Dobeu Tech Solutions LLC, the dobeu.net homepage, a one-sentence description and a display name. The plugin also gets a listing icon.
- `.github/CODEOWNERS` requests a review from the repository owner on every pull request. The review is not required.
- `.github/FUNDING.yml`, with comments only until a handle is set.

### Changed

- The root README is rewritten as a storefront: what the plugin is, install, update, uninstall and where to read next.
- License: the marketplace and plugin ship under the Dobeu Source-Available License 1.0 instead of MIT. Copies released earlier under MIT stay MIT.

### Security

- `main` is protected. Pull requests need passing `test (3.12)` and `lint` checks, force-push and deletion are blocked, and workflow runs from outside contributors need approval.

## [5.1.0]

_Released 2026-11-06_

### Changed

- Marketplace manifest version bumped to 5.1.0 to match the plugin.

## [5.0.0]

_Released 2026-11-06_

### Changed

- The plugin is renamed from `dts2` to `dt`. Commands are now `/dt:<command>`. The marketplace keeps the name `dts2`, so the install command is `/plugin install dt@dts2`.

## [4.0.0]

_Released 2026-11-05_

### Changed

- The plugin is renamed from `dts2-harness` to `dts2`. Commands became `/dts2:<command>`.

## [2.0.0]

_Released 2026-10-17 (first publish) and 2026-11-04 (CI)_

### Added

- The `dts2` marketplace, published with the `dts2-harness` plugin (version 2.0.0 at the time).
- A GitHub Actions workflow (`.github/workflows/test.yml`) that runs the plugin tests, linters and manifest checks on every pull request.
