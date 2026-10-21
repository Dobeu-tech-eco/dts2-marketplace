# dts2 marketplace

Claude Code plugin marketplace for Dobeu Tech Solutions.

| Plugin | What it does |
|---|---|
| [`dts2-harness`](plugins/dts2-harness) | Plan-build-review-verify agent harness: end-state interview, Plan and Ship checkpoints, agent roster, deployment verification, GTM, machine prep, multi-repo scaffolding, lessons memory, and a headless Agent SDK runner. Windows, WSL, Linux, macOS. |

## What's new in 3.0.0
- End-state interview: `setup` asks rounds on repos, agents, and skills until you approve the end state.
- Plan and Ship checkpoints: `run` pauses for approval twice and writes a PR receipt at ship.
- Rule 8, harness discipline: agents follow the harness rules instead of improvising around them.
- Agent roster: claude, codex, gemini, grok, opencode, and copilot, with subscription-first auth and cost tiers (cheapest capable agent first).
- Finish passes: an Impeccable-style critique and polish pass for UI, and a code finish pass.
- Deployment verification: detects the deploy target, verifies the live result, and offers a build-a-production and troubleshoot round.
- `action-items`: open secrets, decisions, and handoffs in one list, plus a pass-off file (`.harness/handoff/latest.md`) any agent can resume with `run resume`.
- `learn`: auto mode, metrics, and harness lessons.
- `gtm`: go-to-market in one pass through the `marketing-skills` plugin, ending in a readiness scorecard.
- `machine-prep` tiers: graded keep and prune levels with redundancy checks.
- `evolve`: change the harness in its source repo, validate, test, bump, commit.

## Skills
| Skill | Use it to |
|---|---|
| `onboard` | Explain the harness, its agents and skills, and where to start. Explanation only. |
| `machine-prep` | Scan the computer, prune plugins to the blueprint keep-set, set up the slim startup. Once per machine. |
| `setup` | Interview to an approved end state, then scaffold `.harness/` in one repo, many repos, or a multi-repo workspace. |
| `run` | Do a task: scout sizes it, lead plans, builders build, reviewers and verifier check, with Plan and Ship checkpoints. |
| `learn` | Turn reviewer findings into lessons that every future run reads. |
| `evolve` | Change the harness itself in its source repo: edit, validate, test, bump both manifests, commit. |
| `gtm` | Go-to-market in one pass through the `marketing-skills` plugin, ending in a `readiness.md` scorecard. |
| `sdk` | Run the same pipeline headless with the Agent SDK. |
| `action-items` | List open secrets, decisions, handoffs, and deploy steps with the command that resolves each. |

Six agents: lead, builder, reviewer, verifier, scout, auditor.

## Install
Inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dts2-harness@dts2
```

Then turn off older copies so agents are not duplicated: `/plugin`, Installed, disable `harness` and `harness-ops` if present. Or run `/dts2-harness:machine-prep`, which does it with a settings backup.

Restart Claude Code and run `/dts2-harness:onboard`.

## Update

```
/plugin marketplace update dts2
```

## WSL note

If your WSL `claude` command wraps the Windows `claude.exe`, both shells share the Windows Claude home. Install once from Windows. Install inside WSL only when you run the native Linux CLI there.

## Known limits
- Login state for gemini, grok, and opencode is self-reported by you; the harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Grok CLI commands are untested.
- The Sol 6.1 roster slot is user-editable; check it matches what you run.

## Acknowledgements
dts2-harness builds on patterns from these projects. We learned from them and wrote our own implementation; no code was copied.
- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.

## License

MIT
