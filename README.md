# dts2 marketplace

Claude Code plugin marketplace for Dobeu Tech Solutions.

| Plugin | What it does |
|---|---|
| [`dts2-harness`](plugins/dts2-harness) | Plan-build-review-verify agent harness: machine prep from the agent-startup-blueprint, single and multi-repo scaffolding, auto-scaled agent teams, a lessons memory, and a headless Agent SDK runner. Windows, WSL, Linux, macOS. |

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

## License

MIT
