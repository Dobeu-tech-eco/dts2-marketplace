# Runtimes: Linux, macOS, native Windows, WSL and T3 Code

Which runtimes the harness supports and the exit codes each one reports. It is for anyone running `dpp` or the headless runner outside plain Linux or macOS.

`scripts/doctor.py` reports the platform, the sandbox tools (`bwrap`, `socat` on Linux) and the auth method (named, never the value). It also reports the host (`claude-code` or `t3code`). `dpp` runs on every platform below; native Windows needs one extra approval.

## For people

`dpp` runs on all of these. Run `scripts/doctor.py` to see what your machine supports.

| Platform | Sandbox | What `dpp` needs |
|---|---|---|
| Linux | `bwrap` + `socat` | nothing extra |
| macOS | `sandbox-exec` | nothing extra |
| Native Windows | none (Claude Code has no OS sandbox there) | the `unsafe_no_sandbox` approval, or `--unsafe-no-sandbox` on `lanes.py spawn`. The deny hook, tool allowlist, minimal env, `--setting-sources local` and the `settings.local.json` deny rules all stay |
| WSL2 | `bwrap` + `socat` | nothing extra; recommended on Windows for full sandboxing |
| T3 Code | that of the machine the session runs on | see below |

### Running in T3 Code

T3 Code (app.t3.codes) is detected best-effort: set `DTS2_HOST=t3code`, or any variable starting with `T3_CODE` or `T3CODE` is present. `doctor.py` reports the host. Sons are still started with `lanes.py spawn` on the machine running the session, signed in with that machine's own Claude login. T3's own thread launch is not used for sons. Tokens such as `the GitHub token` and `the SSH agent socket` are never passed.

## For agents

- The exit-code table below must match `TIMEOUT_MAPPING` in `scripts/doctor.py`. `tests/test_batch11_report.py` fails when they differ, so change both together.
- On native Windows `dpp` spawn needs the `unsafe_no_sandbox` approval or `--unsafe-no-sandbox`. Ask for it; never skip it, and never start a son any way but `lanes.py spawn`.
- In T3 Code, do not use T3's thread launch for sons. Use `lanes.py spawn`.
- `doctor.py` names the auth method and never prints its value. Keep it that way in anything you write.
- `TEAM.md` is optional. When it is absent, do not invent seats and do not call `team_charter.py` for a decision: `/dt:model`, lanes and the autopilot vote already assign them. When it is present, `scripts/team_charter.py` is the only reader. If it warns that a seat is unreachable, show that one line and use the agent it names, or the harness roster when the agent is null. Do not stop the run, and do not retry a connector that did not answer.

## Exit codes by runtime

The constants live in `scripts/doctor.py` (`TIMEOUT_MAPPING`); `tests/test_batch11_report.py` fails when this table and the constants differ.

| Runtime | Timeout | Killed (SIGKILL) | Terminated (SIGTERM) | Notes |
|---|---|---|---|---|
| WSL | 124 | 137 | 143 | GNU `timeout`; same as Linux |
| Docker | 124 | 137 | 143 | 137 is also the OOM kill; `docker stop` sends SIGTERM, then SIGKILL after its grace period |
| Native Windows | none | none | none | no POSIX signals; no `timeout`; dpp needs the `unsafe_no_sandbox` approval |

## Team charter

A repo may keep a team charter at `TEAM.md` or `.harness/TEAM.md`. The root file is used when both are present. The template is `templates/TEAM.md`. It maps charter roles onto seats the harness already has:

| Charter role | Harness seat | Assigned by |
|---|---|---|
| lead (planner) | lead | `/dt:model` (`lead_provider`), then `failover.py` when that provider stalls |
| builder | execution | `delegate.py` and lanes |
| reviewer | advisory | the review dispatch and the autopilot vote |
| playtester | sign-off (verifier) | the verifier walkthrough; read-only |
| copywriter | advisory | a docs handoff (README, changelog, user-facing strings) |
| dispatcher | lead | the lead filing work through `roster.py` and `lanes.py` |

The dispatcher is not a second orchestrator, and the copywriter is not a new role. Both are preferences for providers already on the roster.

Every handoff while the charter is present uses the seven-field brief in `templates/brief.md`: objective, context, scope, authorized and prohibited actions, inputs, deliverable and evidence, deadline and dependencies. `scripts/team_charter.py brief` fills it. The prohibited section always says that merges, deploys and spending need an explicit human approval.

A review loop under the charter runs at most 3 rounds (`team_charter.py review-cap`). The next round asks the person. The five-round fix cap for a red check is a different cap and stays in force. The autopilot vote and its council are unchanged.

If T3 Code, its MCP server, a provider CLI, or any other connector named in the charter does not answer, `team_charter.py resolve` exits 0. It warns once and uses the next provider in that row, or the harness roster when none answer. A repo with no `TEAM.md` never takes this path: resolve reports `mode: harness` and the run proceeds as it does today. The script does not start a provider and does not call a connector itself. It reads an optional roster probe, and a probe that cannot run is the same warning and the same fallback. If the reader itself cannot run (the command is missing, blocked, or exits non-zero), print `team charter: reader unavailable; using the harness roster` once and keep today's seats. Do not stop the run.
