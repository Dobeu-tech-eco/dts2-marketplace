# Harness discipline (Rule 8)

Read by lead, builder, reviewer and verifier. Copied to `.harness/discipline.md` at scaffold.

1. **Define done first.**
   Where it bites: the plan checkpoint will not open without a Done section: outcome plus check method (tests, visual, source, review). Lead refuses to plan without it.
2. **End with a receipt.**
   Where it bites: `receipt.md` lists tests run with pass/fail counts, review verdict, approver, steps outside the change, open risks, rollback point. Shown at the ship checkpoint and appended to the PR body.
3. **Cap fix rounds at three.**
   Where it bites: in `run` and per builder. After three rounds, stop and escalate with what failed; the escalation goes into `.harness/state.md`.
4. **Repeat mistake becomes a check.**
   Where it bites: `learn` detects a lesson seen twice (same normalized text or same file+rule) and offers to promote it: a line in `.harness/checks.sh` (run by the Stop hook), a test skeleton in the repo's test dir, or a line in `review-checklist.md`. It records "lives at <path>" in `lessons.md`.
5. **State outside the chat.**
   Where it bites: `.harness/state.md` holds decisions, failures and open items, appended by run and learn, and read at session start by `session-lessons.sh`. The file is the record.
6. **Auto-add the receipt.**
   Where it bites: `hooks/pr-receipt.sh` runs on `gh pr create` and `gh pr edit`. If the PR body lacks `## Change receipt`, it edits it in, and it adds or extends the PR template in the same branch when neither the repo nor the org default has the section.

## Push exception

Agents never push. The one exception is `pr-receipt.sh`, which pushes only the PR's own branch, and only to add or extend the PR template. It never pushes any other branch.
