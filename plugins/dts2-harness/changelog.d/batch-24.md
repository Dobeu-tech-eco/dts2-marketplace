### Changed

- Breaking: plugin renamed `dts2-harness` -> `dts2` (version 4.0.0); commands are now `/dts2:<command>` and agents `dts2:<agent>`. The plugin folder, the settings file `.claude/dts2-harness.local.md` and the `.harness/` state paths keep their names.
- Migration: existing installs run `/plugin uninstall dts2-harness@dts2`, `/plugin marketplace update dts2`, `/plugin install dts2@dts2`, `/reload-plugins`; settings and `.harness/` state need no change.
