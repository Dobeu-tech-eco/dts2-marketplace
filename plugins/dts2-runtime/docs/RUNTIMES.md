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

T3 Code (app.t3.codes) is detected best-effort: set `DTS2_HOST=t3code`, or any variable starting with `T3_CODE` or `T3CODE` is present. `doctor.py` reports the host. Sons are still started with `lanes.py spawn` on the machine running the session, signed in with that machine's own Claude login. T3's own thread launch is not used for sons. Tokens such as `GH_TOKEN` and `SSH_AUTH_SOCK` are never passed.

## For agents

- The exit-code table below must match `TIMEOUT_MAPPING` in `scripts/doctor.py`. `tests/test_batch11_report.py` fails when they differ, so change both together.
- On native Windows `dpp` spawn needs the `unsafe_no_sandbox` approval or `--unsafe-no-sandbox`. Ask for it; never skip it, and never start a son any way but `lanes.py spawn`.
- In T3 Code, do not use T3's thread launch for sons. Use `lanes.py spawn`.
- `doctor.py` names the auth method and never prints its value. Keep it that way in anything you write.

## Exit codes by runtime

The constants live in `scripts/doctor.py` (`TIMEOUT_MAPPING`); `tests/test_batch11_report.py` fails when this table and the constants differ.

| Runtime | Timeout | Killed (SIGKILL) | Terminated (SIGTERM) | Notes |
|---|---|---|---|---|
| WSL | 124 | 137 | 143 | GNU `timeout`; same as Linux |
| Docker | 124 | 137 | 143 | 137 is also the OOM kill; `docker stop` sends SIGTERM, then SIGKILL after its grace period |
| Native Windows | none | none | none | no POSIX signals; no `timeout`; dpp needs the `unsafe_no_sandbox` approval |
