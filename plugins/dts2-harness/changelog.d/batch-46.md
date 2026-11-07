### Fixed
- Hook scripts are statically readable by the plugin directory validator: every script path is spelled `${CLAUDE_PLUGIN_ROOT}/...`, `lib-settings.sh` reads settings in pure bash, inline `python3 -c` and `awk` programs moved to `scripts/hook_util.py`, and the PR-receipt logic moved to `scripts/pr_receipt.py` behind a thin wrapper.
