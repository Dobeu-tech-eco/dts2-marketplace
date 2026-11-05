### Fixed
- autopilot: sons no longer park at `pr-open` on the head-only `reconcile`; they check `gh pr list --head <branch>` themselves (son-mode.md).
- `lanes.py reconcile <stamp> --step <step>` now reconciles a standalone step branch (`dts2/<stamp>/step-<step>`), and the step skill uses it.
- autopilot resume: `merge-resume` is documented for lane runs only; standalone steps re-check `gh pr view` and the `merge-go-step` record.
