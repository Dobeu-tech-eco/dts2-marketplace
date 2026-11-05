---
name: setup
description: Interview the user to an approved end state (.harness/end-state.md), then scaffold dts2 config in one repo, many repos or a workspace. Use to set up, init or configure the harness, run the interview, or revise the end state. --scaffold-only skips it.
---

# Setup — interview to an end state, then scaffold

Setup has two parts. **Part 1** interviews the user until the end state is clear and approved. **Part 2** writes the harness files. Part 2 never starts until the user approves the end state, unless `--scaffold-only` was given.

## First contact (code-review, once per repo)

First, check for a `.harness/` directory at the project root. If there is none, the harness has never been in this repo: install and run `npx skills add https://github.com/mattpocock/skills --skill code-review` (see Companion skills in `.harness/discipline.md`) on the repo, show its findings, then write the marker with `mkdir -p .harness && date +%F > .harness/seen`. A repo that already has `.harness/` (including one `run` just marked) is skipped, so this fires once per repo, on first contact only. A missing or failed install never blocks: print `Skill code-review not installed (npx unavailable or offline); continuing without it.`, add a Decisions action item with the command, and still write the marker.

## Scope and keep list

Before anything else, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .`.
- `workspace-member` → ask once `This folder is a member of workspace <root>. Run setup at the workspace root instead? (y/n)`. Yes → continue with the workspace root as the project path.
- `workspace-root` with an existing manifest → offer `Re-link the existing workspace (no interview) or revise the end state?`.
- If `.harness/keep.yaml` exists at the effective root, read it and say `Keeping <n> plugins, <n> skills, <n> agents from .harness/keep.yaml`. Skip the install question for every listed skill (never re-ask), pre-include the listed agents in the Agents round (still show them), and never propose disabling a listed plugin. A re-link or pivot re-run never rewrites keep.yaml except to append.

## Mode

- One path or the current repo → **single**: Part 1, then Part 2.
- Several paths, a folder of git repos, or "all my repos" → **batch**: Part 2 only, per repo, in parallel (batch is always scaffold-only; run setup in a repo later to interview it).
- Repos that ship together (shared API, shared types, one release), or any repo tagged `linked` in the Repos round → **workspace**: one interview, then a per-repo end state, a root end state for cross-repo components, and a workspace manifest.
- `--scaffold-only` → skip Part 1 and run Part 2 directly. Leave any existing `.harness/end-state.md` as it is.

If batch vs workspace is unclear, ask once. Default to batch.

If `.harness/end-state.md` already exists, show its status and ask once: revise it, keep it and scaffold (only if its status is `approved`), or start over. For revise and keep-and-scaffold, read `roster` from its metadata and the decisions from its Other harnesses table, and re-run `dts2-harness:scout` for fresh `Harnesses:` and `Marketing surface:` lines. Revise resumes the interview from the file's contents; keep-and-scaffold goes straight to Part 2.

## Phase files
Read the file for a part only when you reach it; do not read ahead. All files are in this folder.

| File | Read when |
|---|---|
| `phase-1-interview-a.md` | Read `phase-1-interview-a.md` (same folder) when Part 1 starts: greenfield or brownfield, repos, deploy target, other harnesses, agents. |
| `phase-1-interview-b.md` | Read `phase-1-interview-b.md` (same folder) after the agents question: topology, sections, the question loop, skills, grilling the draft, the end-state approval, and questions from the user. |
| `phase-2-scaffold.md` | Read `phase-2-scaffold.md` (same folder) when Part 2 starts: single, batch and workspace scaffolding. Skip Part 1 files with `--scaffold-only`. |

## Guardrails
- Never scaffold before the end state is approved, unless `--scaffold-only` was given.
- Never overwrite existing config without the user's choice.
- Never guess commands. Leave them empty and say so.
- Never write into a context repo, a `coexist` harness folder, `CLAUDE.md` or `AGENTS.md`, except the single pointer line and the managed block that `agent-memory.py` writes in Part 2 (Single).
- Never install skills outside project scope.
- Never overwrite an existing `ci.yml`, `RUNBOOK.md` or `ops/` file, and never change branch protection or enter production credentials.
- Never commit or push.
