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
DEFAULT_MODE: Final[int] = 0o666


def target_mode(target: Path) -> int:
    """Keep an existing file's mode; a new file gets the mode plain open() would give it (mkstemp uses 0600)."""
    try:
        return target.stat().st_mode & 0o777
    except OSError:
        umask: int = os.umask(0)
        os.umask(umask)
        return DEFAULT_MODE & ~umask


def fsync_dir(folder: Path) -> None:
    """Flush the directory entry too, so the rename survives a power cut. Not every platform allows it."""
    try:
        descriptor: int = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass  # some filesystems refuse fsync on a directory; the rename itself already happened
    finally:
        os.close(descriptor)


def atomic_write(path: Path | str, text: str, *, newline: str | None = None) -> Path:
    """Replace `path` with `text` atomically. Creates the parent folder. Returns the path written.

    `newline` goes to the text-mode handle: pass "" to write line endings exactly as given (CRLF stays CRLF)."""
    target: Path = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode: int = target_mode(target)
    descriptor, temp_name = tempfile.mkstemp(prefix=TEMP_PREFIX + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding=ENCODING, newline=newline) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    fsync_dir(target.parent)
    return target


def append_text(path: Path | str, text: str, *, header: str = "") -> Path:
    """Append `text` to an append-only log in one O_APPEND write, so concurrent writers never drop a record.

    Use this, not atomic_write, for logs such as metrics.jsonl or the council decisions file: a read-then-replace
    would lose any line another process appended in between. `header` is written first only when the file is new."""
    target: Path = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if header:
        try:
            created: int = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, DEFAULT_MODE)
        except FileExistsError:
            pass
        else:
            try:
                os.write(created, header.encode(ENCODING))
            finally:
                os.close(created)
    descriptor: int = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, DEFAULT_MODE)
    try:
        os.write(descriptor, text.encode(ENCODING))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return target
