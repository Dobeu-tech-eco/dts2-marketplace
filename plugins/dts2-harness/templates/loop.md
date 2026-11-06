# Unattended fullauto loop

Copy this file to `.claude/loop.md` and start it with `/loop` (no interval, so each pass starts when the last ends).
Set `autonomy: unattended` in `.harness/config.yaml` first; the `loop:` block there sets the stop limits.
Every command is `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/loop_guard.py"` followed by the arguments shown.

One pass, in this order:

1. `check`. If it exits 2 it printed `STOP <reason>` (a `.harness/STOP` file, an open PR labelled `dts2:stop`, or the pass or hour budget). Run `notify --reason "<reason>"` for a budget stop, then end the loop.
2. `sweep --release`. Every item it lists has a resolved blocker; put them back among the ready items.
3. Run `/dt:check-in` and pick the next ready item (an item that is not parked and needs no human). When none is left, run `record` once with the final progress text and end the loop: the work is done or parked.
4. Do the item through `/dt:fullauto` (a single dpp-full round). If it cannot finish and needs a person, `park --id <item> --reason "<why>" --blocker-pr <n>` (or `--blocker-item <id>` or `--blocker-file <path>`) and go on to the next item.
5. `record --progress "<open item ids> | <merged PR numbers>" --signature "<one line naming this pass's failure, empty when none>"`. A verdict of `continue` starts the next pass.
6. A verdict of `stall` or `stop` exits 2. Run `notify --reason "<the reasons it printed>"`, then end the loop. Do not retry the stalled item in the same loop.

Never edit the ledger by hand. To stop a running loop from outside, create `.harness/STOP` or label any open PR `dts2:stop`.
