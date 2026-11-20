### Added
- `dpp` runs on native Windows (approval-gated with `unsafe_no_sandbox`, no OS sandbox), macOS and T3 Code; `doctor.py` reports the host.
- Lock a roadmap by typing `lock roadmap <key>`.
- Windows and macOS CI job (`portable`).

### Changed
- `dpp` on native Windows now gates every son (not only a second one) behind `--unsafe-no-sandbox` or the `unsafe_no_sandbox` approval, logs an `unsafe-no-sandbox` ledger event, and no longer emits the sandbox settings block (it failed preflight with a misleading bwrap message); preflight failure text names the right sandbox per platform.
- `doctor.py` no longer parks `dpp` on native Windows; it warns that sons need the `unsafe_no_sandbox` approval.
