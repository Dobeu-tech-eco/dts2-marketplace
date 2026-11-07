# Changelog

All notable marketplace-level changes are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This project follows [Semantic Versioning](https://semver.org/).

The plugin's full release history lives in [plugins/dts2-harness/CHANGELOG.md](plugins/dts2-harness/CHANGELOG.md).

## Unreleased

- License: the current tree is MIT. Copyright Dobeu Tech Solutions LLC. Forks may add, remove, and ship the work, including in paid products. Keep the copyright notice.

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
