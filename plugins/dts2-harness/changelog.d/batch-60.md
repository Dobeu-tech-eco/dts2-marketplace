# Batch 60: external review fold-ins (macOS stop hook) and the commands one-pager

- Stop hook works on stock macOS: when GNU `timeout` is missing it uses Homebrew's `gtimeout`, or runs the step with the hook's own timeout as the backstop. Before, every step failed with "command not found", the handoff note was never written, and each Stop re-ran the checks as red. `xargs -r` (GNU only) dropped from the change fingerprint.
- `COMMAND-GUIDE.md` at the plugin root: the one-page list of every command, with install, update and requirements (python3 is needed for the safety hooks).
