# Changelog

All notable marketplace-level changes are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This project follows [Semantic Versioning](https://semver.org/).

The plugin's full release history lives in [plugins/dts2-runtime/CHANGELOG.md](plugins/dts2-runtime/CHANGELOG.md). The Claude directory listing is the generated instruction edition at [plugins/dts2-harness](plugins/dts2-harness).

## Unreleased

### Added

- `fleet-ledger` 0.2.0: `sql/002-claims.sql` adds claim, heartbeat, complete and release with expiring leases and lease-version fencing, a `fleet_seat` group role, a typed Python client and SQL tests run in CI against Postgres.

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
