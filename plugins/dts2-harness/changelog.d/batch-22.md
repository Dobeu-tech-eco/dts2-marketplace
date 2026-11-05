### Fixed
- R1 (review findings): `guard.mask_literals` keeps a quote stack, so a single quote inside a nested `$(...)` within double quotes is literal and `echo "$(echo "'$(printenv)'")"` is denied again; `git commit -m '$(env)'` stays allowed.
- R2 (review findings): `policy_gate.sub_slack` skips each leading `--name value` flag value, so `vercel --token x --scope y env ls` matches the `vercel-env` deny rule again; `gh pr create --title secret` stays allowed.
