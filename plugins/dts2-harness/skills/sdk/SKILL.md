---
name: sdk
description: Set up and run the dts2 pipeline headless with the Claude Agent SDK (Python) for CI, cron, servers, WSL, or machines without the desktop app — with authentication from an environment API key, a user-supplied key command such as an Anthropic CLI, or the existing Claude Code login — and optional Codex or Gemini second-opinion review. Use when the user asks to run the harness headless, in CI, from a script, with the Agent SDK, with an API key, or with another coding agent.
---

# SDK — headless runner

Runner: `${CLAUDE_PLUGIN_ROOT}/sdk/dts2-run.py`. It reuses this plugin's agent files, so headless and interactive runs follow the same rules.

## 1. Install
- Python 3.10+ and the Claude Code CLI must be installed; the Agent SDK drives it.
- `python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/sdk/requirements.txt"` (on Debian/Ubuntu system Python, use a venv or add `--break-system-packages`).

## 2. Pick authentication (first match wins, keys are never printed or saved)
On your own machine the existing login (subscription) is the default; an exported `ANTHROPIC_API_KEY` takes precedence and bills per use, so unset it for subscription runs. CI uses an API key.
1. `--api-key-env NAME` reads the key from a variable you name.
2. `ANTHROPIC_API_KEY` already exported, for example from a CI secret.
3. `DTS2_KEY_COMMAND` holds a command you trust that prints the key, such as your Anthropic CLI's key command or a secret manager (`op read ...`, `doppler secrets get ... --plain`). Ask the user for the exact command; do not guess CLI syntax.
4. Nothing set: the SDK uses the login the installed Claude Code CLI already has (run `claude auth login` first). Note to the user: subscription login is fine for their own runs; anything shared with other people or offered as a product should use an API key, and Anthropic's current terms decide.

Help the user set exactly one of these. Never write a key into a file in the repo.

## 3. Run
```
python3 "${CLAUDE_PLUGIN_ROOT}/sdk/dts2-run.py" "<task>" --repo <path> [--yes] [--ship] [--live-only] [--second-opinion codex|gemini]
```
- Without `--yes` it stops after the plan and asks for approval on stdin.
- `--yes` approves only the plan checkpoint. It is for CI on a throwaway branch only; say so if the user wants it anywhere else.
- The ship checkpoint writes `.harness/runs/<stamp>/receipt.md` and never commits. `--ship` additionally commits, and only when the current branch matches `DTS2_SHIP_BRANCH`; otherwise it refuses. Neither flag pushes.
- `--live-only` reassigns any handoff lane (a builder section the plan gave to a handoff agent) to Claude, so the run can finish unattended.
- Exit codes: 0 verified and receipt written, 1 plan not approved, 2 blocked by reviewer or verifier, or a handoff lane (a plan builder assigned to a handoff agent) needs a person (without `--live-only`).
- Output: `.harness/runs/<stamp>/1-plan.md`, `2-build.md`, `3-review.md`, `4-verify.md`, `receipt.md`, and `5-<backend>.md` for a second opinion. Lesson candidates go to `.harness/lessons-inbox.md`.

## 4. Other coding agents
- `--second-opinion codex` runs `codex exec` with stdin from /dev/null. `--second-opinion gemini` runs the gemini profile's reviewer command from `roster.py command --agent gemini --role second-opinion` (headless agy in plan mode), falling back to `agy -p … --mode plan --print-timeout 9m` if the roster lookup fails. The diff is written to a file in a temporary folder passed as `--add-dir`; agy runs from the repo with stdin from /dev/null and is never asked to run commands. Each is skipped with a note if its CLI is missing, and a run that passes the 600s limit leaves a `second opinion timed out` note instead of stopping the run. Their findings are advisory and never override the reviewer verdict.
- Codex users can also install the blueprint's `codex/agents/*.toml` so Codex has the same four roles natively.

## 5. CI example (GitHub Actions)
Offer this when asked; adjust paths:
```yaml
- run: npm i -g @anthropic-ai/claude-code && pip install claude-agent-sdk
- run: python3 .dts2/sdk/dts2-run.py "${{ inputs.task }}" --repo . --yes
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```
Runs on a branch, never on main, and never pushes on its own.

## Limits
- Both checkpoints need a human; headless runs stop at each and write what a human would have seen (`--yes`, and `--ship` with `DTS2_SHIP_BRANCH`, stand in for the person in CI).
- The runner is a single-builder pipeline. For auto-scaled parallel teams use the interactive `run` skill.
