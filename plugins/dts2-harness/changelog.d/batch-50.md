### Added
- `dpp` runs on native Windows (approval-gated with `unsafe_no_sandbox`, no OS sandbox), macOS and T3 Code; `doctor.py` reports the host.
- Lock a roadmap by typing `lock roadmap <key>`.
- Windows and macOS CI job (`portable`).

### Changed
- `doctor.py` no longer parks `dpp` on native Windows; it warns that sons need the `unsafe_no_sandbox` approval.
