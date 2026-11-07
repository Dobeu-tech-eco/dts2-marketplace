#!/usr/bin/env python3
"""Report OS, WSL status, and which Claude home is live. Read-only."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Final

PROC_VERSION: Final[Path] = Path("/proc/version")
WSL_MARKER: Final[str] = "microsoft"
WINDOWS_MOUNT: Final[str] = "/mnt/c/"
TOOLS: Final[tuple[str, ...]] = ("claude", "codex", "gemini", "cursor", "git", "python3", "node")


def is_wsl() -> bool:
    if not PROC_VERSION.exists():
        return False
    return WSL_MARKER in PROC_VERSION.read_text(errors="ignore").lower()


def claude_binary() -> str | None:
    return shutil.which("claude")


def wraps_windows_claude(binary: str | None) -> bool:
    if binary is None:
        return False
    resolved: str = os.path.realpath(binary)
    if resolved.startswith(WINDOWS_MOUNT) or resolved.lower().endswith(".exe"):
        return True
    try:
        head: str = Path(resolved).read_text(errors="ignore")[:2000].lower()
    except (OSError, UnicodeDecodeError):
        return False
    return "claude.exe" in head


def live_claude_home(wsl: bool, wraps: bool) -> str:
    if wsl and wraps:
        return "Windows home (%USERPROFILE%\\.claude) via the WSL wrapper"
    return str(Path.home() / ".claude")


def detect() -> dict[str, object]:
    wsl: bool = is_wsl()
    binary: str | None = claude_binary()
    wraps: bool = wraps_windows_claude(binary)
    return {
        "os": platform.system(),
        "release": platform.release(),
        "wsl": wsl,
        "claudeBinary": binary,
        "claudeWrapsWindows": wraps,
        "liveClaudeHome": live_claude_home(wsl, wraps),
        "tools": {name: shutil.which(name) is not None for name in TOOLS},
    }


def main() -> int:
    print(json.dumps(detect(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
