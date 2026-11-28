### Fixed

- `approvals.py lock-roadmap` no longer blocks forever in a non-Claude agent run with no terminal (for example `codex exec`, Gemini, WSL through `wsl.exe`, or native Windows) when agent detection fails. With no terminal attached it never prompts: it locks on the recorded sign-offs (two different providers, or an override with a reason) and logs the lock as `agent:undetected`. A missing key exits 2 and names the key; missing sign-offs exit 3 and say how many providers signed and how many are still needed.
- When a terminal is attached, the owner's "Type yes" prompt times out after 120 seconds with exit 2. Set `DTS2_LOCK_TTY_TIMEOUT` to change the limit.
- The Claude in-flow lock (`lock roadmap <key>`) and the detected-agent path are unchanged.
