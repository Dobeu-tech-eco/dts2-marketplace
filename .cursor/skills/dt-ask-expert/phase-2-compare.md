> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# ask-expert - phase 2, what you said versus what the code shows

## 1. Read the code
Read the repo itself (clone it to a scratch folder when it is not local; never change it). Collect, as plain facts:
- purpose: what it does, from the README and the entry points;
- stack: languages, frameworks, services it needs;
- size: files and lines of code, rough order is enough;
- last commit: date and how active the history is;
- tests: whether there are any, whether they run;
- dependency age: how many dependencies are well out of date, and any known-vulnerable ones;
- reusable parts: modules, components or scripts that stand on their own.

## 2. The side-by-side
Show one table with two columns, "What you said" (from the goal answers) against "What the code shows". One row per claim: what it is for, how finished it is, how alive it is, how much upkeep it needs, what could be reused. Mark every row where the two disagree. Keep it short enough to read in a minute.

## 3. Against the rest of your code
Look at the repos the user named as active (`fold_targets`). For each one find overlap: the same job done twice, code that would drop straight in, a feature the active repo lacks. List the fold candidates, naming the files and features that would move and where they would land. When there is no overlap, say so; do not invent a candidate. When `fold_targets` is `none`, skip this step and say that FOLD is off the table.

## 4. Your choice
Ask once: "Do you want to decide from this comparison yourself, or should the expert panel decide?"
- Decide myself: take the user's verdict from the comparison, then go straight to `phase-4-research.md` for the price check and on to `phase-5-report.md`. The memo records that the user decided and still checks and prices the template path.
- Defer to the expert: continue with `phase-3-panel.md`.

Save the code facts, the side-by-side and the choice to `.harness/ask-expert/<repo>/compare.md`; the panel reads it as its evidence.
