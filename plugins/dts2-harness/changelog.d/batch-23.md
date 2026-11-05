### Fixed

- R3 (review findings): `guard.mask_literals` opens a substitution context only for an unescaped `$(`, so an escaped `\$(` or `$$(` no longer hides a following `$(printenv)`; `git commit -m '$(env)'` and the batch-22 nested-quote case are unchanged.
