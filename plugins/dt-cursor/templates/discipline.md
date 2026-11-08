# Harness discipline

Copied into `.harness/discipline.md` by `dt_gate.py scaffold`.

1. Define done before planning. The plan file needs an outcome and a check.
2. End with a receipt. This package writes no pull request by itself.
3. Stop when `.harness/STOP` exists. The runtime text caps fix rounds at five and also sends rounds 1-3 to one model tier. This package does not switch models. Record each fix round in `.harness/state.md` and stop after five.
4. Do not merge, force-push, or deploy. `dt_gate.py blocked --action merge` does not run a merge.
5. Do not read credential files or `.env`.
6. Do not edit `AGENTS.md` or `CLAUDE.md` from scaffold.
7. Approvals bind to the sha256 of the accepted file. Editing the file after approval requires a new approval.
