# dt: a Claude Code harness for planned, reviewed pull requests

![License: Dobeu Source-Available 1.0](https://img.shields.io/badge/license-Dobeu%20Source--Available%201.0-5A4FAB)
![Version 5.1.1](https://img.shields.io/badge/version-5.1.1-6B5CE7)

`dt` turns one task into a planned, built, reviewed and verified pull request, with you approving at the points that matter.

This repository is a Claude Code plugin marketplace from [Dobeu Tech Solutions LLC](https://dobeu.net). It carries one plugin, `dt`. It is for developers and small teams who already use Claude Code and want a repeatable way to run larger changes.

You approve an end state once. Separate roles plan, build, review and verify the work, and every run ends with a receipt and a pull request. Single-file fixes do not need it.

## Quick start

Prerequisites:

- Claude Code with plugin support
- `git`
- the `gh` CLI, for anything that opens pull requests
- Python 3.10 or newer (`python3`), standard library only

Install, inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dt@dts2
```

Restart Claude Code, then run `/dt:onboard`. It explains the roles and commands, and writes nothing until you pick.

Update later:

```
/plugin marketplace update dts2
/reload-plugins
```

## How it works

- **End state first.** You approve what "done" means once. `/dt:check-in` shows `N of M complete` against it at any time.
- **Separate roles.** A lead plans, builders build on disjoint files, reviewers review and a verifier checks the result. Builders never review their own work.
- **Checkpoints.** The run pauses for your `approve`, `edit` or `stop` at the plan and before shipping. Nothing merges or deploys unless you approved it.
- **Parallel lanes.** `/dt:dpp` gives each lane its own git worktree and merges one lane at a time.
- **Handoff file.** Any role can resume where the last one stopped, so a closed session does not lose context.
- **Cost discipline.** Frontier models advise and sign off. Builders use the cheapest capable model.

The plugin has 27 skills (the slash commands) and 8 roles: lead, builder, fixer, reviewer, verifier, scout, auditor and incident-reviewer.

## Repository layout

```mermaid
flowchart TD
    M["Marketplace manifest<br/>.claude-plugin/marketplace.json"] --> P["Plugin folder<br/>plugins/dts2-harness"]
    P --> PJ["Plugin manifest<br/>.claude-plugin/plugin.json"]
    P --> SK["Skills and commands<br/>skills/ (27)"]
    P --> AG["roles (agents/)"]
    P --> HK["Hooks<br/>hooks/"]
    P --> SC["Scripts and SDK runner<br/>scripts/, sdk/"]
    P --> TP["Templates and profiles<br/>templates/, profiles/"]
    P --> DC["Docs<br/>docs/, README, CHANGELOG"]
    P --> TS["Tests<br/>tests/"]
    CI["CI<br/>.github/workflows/test.yml"] -.-> TS
    SK --> AG
    SK --> SC
    HK --> SC

    classDef brand fill:#6B5CE7,stroke:#5A4FAB,color:#FFF8F0
    classDef plugin fill:#5A4FAB,stroke:#5A4FAB,color:#FFF8F0
    classDef part fill:#FFF8F0,stroke:#5A4FAB,color:#1A1A2E
    classDef accent fill:#F4A261,stroke:#1A1A2E,color:#1A1A2E
    class M brand
    class P plugin
    class PJ,SK,HK,SC,TP,DC part
    class AG,TS,CI accent
```

## What's new in 5.1.1

- Passes the Claude plugin directory's static checks. Hook scripts are statically readable.
- Ships under the Dobeu Source-Available License 1.0.
- Public READMEs with an "All commands" table, a listing icon and publisher metadata.
- Composio fixes: connection mapping is corrected, including a `composio` CLI installed inside WSL.
- Composio always-use is now on by default when you answer yes during onboarding. `composio-setup.py decide --account yes` saves `always_use: true`. Pass `--no-always-use` to opt out.
- `main` is protected: pull requests need green `test (3.12)` and `lint` checks.

### What's new in 3.0.0

The first release of the end-state interview, Plan and Ship checkpoints, roster and deployment verification. Every later release is in the [plugin changelog](plugins/dts2-harness/CHANGELOG.md).

## Where to go next

| Read | For |
|---|---|
| [Plugin README](plugins/dts2-harness/README.md) | The manual: wiring, config files, all commands, troubleshooting |
| [Guide](plugins/dts2-harness/docs/GUIDE.md) | Which command to use when, and how to talk to the harness |
| [Command reference](plugins/dts2-harness/docs/COMMANDS.md) | Exact invocation of every command |
| [Plugin changelog](plugins/dts2-harness/CHANGELOG.md) | Full release history |
| [Marketplace changelog](CHANGELOG.md) | Marketplace-level changes |
| [LICENSE](LICENSE) | Dobeu Source-Available License 1.0 |

Day to day: `/dt:run <task>` runs one task with checkpoints, `/dt:check-in` shows progress and `/dt:ship` opens a pull request.

## Known limits

- Login state for gemini, grok, muse and opencode is self-reported by you. The harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Parallel runs need Linux, macOS, WSL or Docker.
- If your WSL `claude` command wraps the Windows `claude.exe`, install once from Windows. Install inside WSL only when you run the native Linux CLI there.

## Updating and uninstalling

Update with the two commands in [Quick start](#quick-start). To remove the plugin:

```
/plugin uninstall dt@dts2
/plugin marketplace remove dts2
```

Your repos' `.harness/` folders and `~/.dts2/` stay in place.

Coming from an older name? Uninstall the old plugin first (`/plugin uninstall dts2@dts2`, or `dts2-harness@dts2` before 4.0), then install `dt@dts2`. Settings and `.harness/` state are unchanged.

## Acknowledgements

dt builds on patterns from these projects. We learned from them and wrote our own implementation. No code was copied.

- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.

## More from Dobeu Tech Solutions

- [StatMiner](https://github.com/Dobeu-tech-eco/statminer) ([live](https://statminer.vercel.app)): data-driven answers to complex questions.
- [DOT Copilot](https://github.com/Dobeu-tech-eco/DOT-Copilot) ([live](https://dot-copilot.vercel.app))
- [Super RAG MCP](https://github.com/Dobeu-tech-eco/super-rag-mcp): self-hosted RAG over local and cloud sources, exposed as an MCP server.
- [Claude Harness (minimal)](https://github.com/Dobeu-tech-eco/plugin-claudeharness): a four-role lead, builder, reviewer, verifier pipeline for Claude Code.
- [Dobeu v0 Skills Pack](https://github.com/Dobeu-tech-eco/dobeu-v0-skills-pack): a skills pack for v0.

## License and support

Dobeu Source-Available License 1.0. Copyright Dobeu Tech Solutions LLC. See [LICENSE](LICENSE).

You can install and use it, including at work. You can read it, change it for your own use, and share copies for free if the license and copyright notices stay with them. You cannot sell it, put it in a paid product or hosted service, or relicense it without written permission. Dobeu can end the license with 30 days' notice. Versions released earlier under the MIT License stay MIT for copies people already have.

For commercial licensing or questions, get in touch through [dobeu.net](https://dobeu.net).
