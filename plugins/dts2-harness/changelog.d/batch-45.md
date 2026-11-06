### Added

- Unattended permission profile: `templates/settings.unattended.json` (`dontAsk`, an allowlist for normal harness work, deny rules mirroring `templates/policy.json` and the approvals file, bypass mode disabled, sandbox on) and `scripts/unattended.py` (`diff`, `apply`, `status`; append-only merge with a `.bak` backup). `/dts2:setup` step 9b offers it as `autonomy: unattended`, diff first.
- PermissionDenied in unattended mode: besides the Handoff action item, a lane gets a `need-human` mailbox item and parks (`incomplete`, reason `permission-denied`), so a run does not stall on a prompt. Normal mode is unchanged.
- `docs/GUIDE.md`: an "Unattended mode" section.
