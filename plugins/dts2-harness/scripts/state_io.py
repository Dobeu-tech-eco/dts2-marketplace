#!/usr/bin/env python3
"""The one writer for .harness/ state files: write a temp file in the same directory, fsync it, then os.replace.

A crash mid-write leaves either the old file or the new one, never a torn file. Scripts import it with
`sys.path.insert(0, str(Path(__file__).resolve().parent))` then `from state_io import atomic_write`, because the
tests run scripts under `python3 -I`, which leaves the script's own folder off sys.path."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

TEMP_PREFIX: Final[str] = ".tmp-"
ENCODING: Final[str] = "utf-8"


def fsync_dir(folder: Path) -> None:
    """Flush the directory entry too, so the rename survives a power cut. Not every platform allows it."""
    try:
        descriptor: int = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write(path: Path | str, text: str) -> Path:
    """Replace `path` with `text` atomically. Creates the parent folder. Returns the path written."""
    target: Path = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=TEMP_PREFIX + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding=ENCODING) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    fsync_dir(target.parent)
    return target
