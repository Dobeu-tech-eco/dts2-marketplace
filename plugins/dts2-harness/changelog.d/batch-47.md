# Batch 47: license

- License: the plugin and marketplace now ship under the Dobeu Source-Available License 1.0 instead of MIT (`LICENSE` at the repo root and in the plugin folder; `plugin.json` license is `SEE LICENSE IN LICENSE`). You can still use, change and share it free; selling it or relicensing it needs permission. Copies released under MIT stay MIT.
- Lanes: when an old son's process group ignores SIGINT and gets SIGKILL, re-dispatch now waits (up to 5 seconds) until the group is actually gone, so a lane is never restarted while the old processes are still exiting.
