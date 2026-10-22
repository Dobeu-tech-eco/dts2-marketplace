---
name: find-skills
description: Rescan the repo at any time, ask one to three clarifying questions, suggest a ranked set of useful skills, and on a yes add them to the project keep list and the run workflow so they persist across a setup re-run. Runnable any time, not only during the setup interview. Use when the user says find skills, what skills should I use, suggest skills for this repo, or wants to add skills to the workflow mid-project.
---

# Find skills — rescan, ask, suggest, wire in

Runnable at any point in a project, not only during the setup deep interview. It never installs without a yes.

## 1. Rescan
Characterize the repo with the existing read-only scripts:
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .` (is there a harness, a workspace, an end state)
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo-size.py" .` (size and tier)
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/env-detect.py"` (tools available on this machine)

From those and a quick look at the root files, set these facts (true, false, or leave unset when unknown): `is_brownfield`, `is_large`, `has_tests`, `has_frontend`, `has_pr` (a GitHub remote or `.github/`), `has_ci`, `has_marketing` (a landing or pricing page), `has_agent_docs` (`CLAUDE.md`, `AGENTS.md`).

## 2. Ask
Ask one to three clarifying questions with AskUserQuestion about what the user wants next (for example: ship a feature, fix bugs, polish the UI, launch). Skip a question the scan already answers.

## 3. Suggest
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skill-suggest.py" --facts '<the facts as JSON>'`. It returns a ranked list of slugs from the mattpocock companion set (grill-me, improve-codebase-architecture, writing-for-agents, pr, resolving-merge-conflicts, ask-matt, research, diagnosing-bugs) plus design, test and marketing skills. Add any already-installed skills that fit the user's answers. Show at most eight, each with a one-line reason and whether it is installed. Then ask once which to add.

## 4. Wire in
On the user's yes, for each chosen skill:
1. Install it if missing, with `npx skills add <source> --skill <name>` (mattpocock skills use `https://github.com/mattpocock/skills`), into the project only; never `-g`. A failed install prints `Skill <name> not installed (npx unavailable or offline); continuing without it.` and becomes a Decisions action item.
2. Append it to `.harness/keep.yaml` under `skills:` as `- name: <name>` / `source: <exact install command>` / `serves: harness`, so a setup re-run keeps it. Append only; never remove entries.
3. Wire it into the run workflow: companion skills follow the table under Companion skills in `.harness/discipline.md`; for a skill outside that table add a row naming when `run` should invoke it, and add it to the `## Skills` table in `.harness/end-state.md` with its phase.
4. Report what was added, one line per skill.

## Guardrails
- Read-only until the user says yes.
- Project scope only; never install into the user's home folder.
- Never remove or overwrite existing keep-list entries.
