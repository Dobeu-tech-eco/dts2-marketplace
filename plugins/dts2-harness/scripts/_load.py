"""The one loader for scripts that other scripts import.

Most scripts have hyphenated file names (`action-items.py`) because they are CLIs, so they cannot be imported by name.
`load("action-items")` and `load("action_items")` both return the same cached module, registered in `sys.modules` under
the importable (underscore) name. Scripts used to repeat the importlib recipe; they call this instead."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent


class ScriptNotFound(Exception):
    """Raised when no script matches the name."""


def module_name(name: str) -> str:
    return name.removesuffix(".py").replace("-", "_")


def script_path(name: str) -> Path:
    stem: str = name.removesuffix(".py")
    for candidate in (stem, stem.replace("_", "-"), stem.replace("-", "_")):
        path: Path = SCRIPT_DIR / f"{candidate}.py"
        if path.is_file():
            return path
    raise ScriptNotFound(f"no script named {name!r} in {SCRIPT_DIR}")


def load(name: str) -> ModuleType:
    """Import a script by hyphenated or underscore name. The module is cached under its underscore name."""
    key: str = module_name(name)
    cached: ModuleType | None = sys.modules.get(key)
    path: Path = script_path(name)
    if cached is not None and getattr(cached, "__file__", None) == str(path):
        return cached
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ScriptNotFound(f"cannot load {path}")
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[key] = module  # dataclasses in a script resolve their module namespace through sys.modules
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return module
