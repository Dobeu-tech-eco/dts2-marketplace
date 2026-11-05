# Runtimes: native Windows, WSL and Docker

`scripts/doctor.py` reports the platform, the sandbox tools (`bwrap`, `socat` on Linux) and the auth method (named, never the value). On native Windows `dpp` parks a run with the reason `windows-native` (ruling Q6); run it under WSL or in Docker instead.

## Exit codes by runtime

The constants live in `scripts/doctor.py` (`TIMEOUT_MAPPING`); `tests/test_batch11_report.py` fails when this table and the constants differ.

| Runtime | Timeout | Killed (SIGKILL) | Terminated (SIGTERM) | Notes |
|---|---|---|---|---|
| WSL | 124 | 137 | 143 | GNU `timeout`; same as Linux |
| Docker | 124 | 137 | 143 | 137 is also the OOM kill; `docker stop` sends SIGTERM, then SIGKILL after its grace period |
| Native Windows | none | none | none | no POSIX signals; dpp parks with `windows-native` |
