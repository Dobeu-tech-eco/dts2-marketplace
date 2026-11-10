> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# ask-expert - phase 1, the goal

The goal is stored and scopes every later phase. Ask in plain words, one or two questions at a time. Do not use harness jargon.

## 1. The questions
Take the repo name and the "what I'm unsure about" text from the command when given; ask for whatever is missing.
1. What is the goal for this project: make money, a passion or learning project, a portfolio piece, or not sure?
2. What are you unsure about?
3. What would a good outcome look like for you?
4. How much time or money are you willing to put in?
5. Which of your repos do you use actively? (These are the places useful parts could be folded into. "None" is a fine answer.)
6. Who is it for, or is it just for you?

## 2. The clarity check
Write the answers so far to `.harness/ask-expert/<repo>/answers.json` with the keys `goal` (`money`, `passion`, `learning`, `portfolio` or `unsure`), `unsure`, `outcome`, `budget`, `fold_targets` (a list of repo names, or the string `none`), `audience` (text, or `just me`) and `restatement_confirmed` (true or false). Then run:

`python3 "$PLUGIN/scripts/dt_gate.py" bridge ask_expert.py clarity --answers .harness/ask-expert/<repo>/answers.json --asked <number of questions asked so far>`

The output has `score`, `threshold` (95 unless `ask_expert.clarity_threshold` is set in `.harness/config.yaml`), `passed`, `slots`, `next_slot` and `budget_exhausted`. Exit 0 means passed; exit 3 means not yet.
- Not passed and `budget_exhausted` is false: ask one more question about `next_slot`, in plain words, update the answers file and run the check again.
- `budget_exhausted` is true (eight questions asked): stop. List the slots that are still open, say plainly that the review needs those answers, and do not guess them. Offer to resume when the user has them.

A short answer such as "make money" earns only part of a slot. Ask for a concrete detail: a number, a name, a date.

## 3. The restatement
When every slot except the restatement is full, write one paragraph in your own words: what the project is, what the user wants from it, what they are unsure about, what they will put in, and where useful parts could go. Ask the user to confirm it or correct it. A correction means rewrite and ask again. Only on a clear yes set `restatement_confirmed` to true and run the clarity check once more.

## 4. Record the goal
When `passed` is true: `python3 "$PLUGIN/scripts/dt_gate.py" bridge ask_expert.py goal record --repo <repo> --answers .harness/ask-expert/<repo>/answers.json`. It refuses (exit 3) unless the check passes, and writes `goal.json` beside the answers with the score and a timestamp. Continue with `phase-2-compare.md`.
