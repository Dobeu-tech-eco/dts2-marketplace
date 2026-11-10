## Summary

Replace the pinned Council Chairman with a latest-frontier-Claude class, record its runtime resolution and exclude restricted/Mythos targets. Preserve voting and approval mechanics. Sweep stale command references against plugin skill definitions.

## Follows

Follows: none

Merge: squash, per Jeremy's explicit November 10 work order; exact reviewed head and required checks green.

## Change receipt

Chairman resolution/alias tests and skill contracts pass; runtime ruff 0.16.9, context tax and generated directory check pass. Local Windows-only ballot hash and bash-path failures require green Linux CI before merge.
Independent review/verifier evidence will be recorded before merge.
Approved by: Jeremy, November 10, 2026, explicit ship/merge work order.
Scope: this repository only. No unrelated branch cleanup.
Report: WORK-ORDER-REPORT.md; machine-readable sweep: command-sweep.json.
Rollback point: fb7e4d5b88ee5e93741f677fa3dce6af2edfa5c6
