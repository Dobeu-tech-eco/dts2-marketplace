### Fixed

- Intake hook: the prompt hook no longer waits about 5 seconds on a busy intake lock. It tries the lock once and skips recording instead of eating the hook timeout; the CLI commands still retry.
