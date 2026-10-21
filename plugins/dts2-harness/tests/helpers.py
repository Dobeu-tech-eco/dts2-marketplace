"""Shared helpers for dts2-harness script tests."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def run_script(name: str, *args: str) -> dict[str, Any]:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["python3", "-I", str(PLUGIN_ROOT / "scripts" / name), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def make_tmp_home() -> Path:
    return Path(tempfile.mkdtemp(prefix="dts2-test-"))
