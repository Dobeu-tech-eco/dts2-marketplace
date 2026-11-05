#!/usr/bin/env python3
"""The one writer for .harness/ state files: write a temp file in the same directory, fsync it, then os.replace.

A crash mid-write leaves either the old file or the new one, never a torn file. Scripts import it with
`sys.path.insert(0, str(Path(__file__).resolve().parent))` then `from state_io import atomic_write`, because the
tests run scripts under `python3 -I`, which leaves the script's own folder off sys.path."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Final

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


# --- G-8: the state port -----------------------------------------------------------------------------------------
# Everything below is the only code that knows where `.harness/` things live. Scripts ask for a location by name
# (`rel(...)`, `run_rel(...)`) or go through a `Store`; tests swap in `MemoryStore` and never touch the disk.
HARNESS: Final[str] = ".harness"
RUNS: Final[str] = "runs"
CONFIG_REL: Final[str] = f"{HARNESS}/config.yaml"
KEEP_REL: Final[str] = f"{HARNESS}/keep.yaml"
END_STATE_REL: Final[str] = f"{HARNESS}/end-state.md"
STATE_MD_REL: Final[str] = f"{HARNESS}/state.md"
ACTION_ITEMS_REL: Final[str] = f"{HARNESS}/action-items.md"
HANDOFF_LATEST_REL: Final[str] = f"{HARNESS}/handoff/latest.md"
METRICS_REL: Final[str] = f"{HARNESS}/metrics.jsonl"
RUNS_REL: Final[str] = f"{HARNESS}/{RUNS}"
MODEL_SLOTS_REL: Final[str] = f"{HARNESS}/cache/model-slots"
SETTINGS_CACHE_REL: Final[str] = f"{HARNESS}/settings.cache.json"
CHECKS_SH_REL: Final[str] = f"{HARNESS}/checks.sh"
LEASE_NAME: Final[str] = "lease.json"
STATUS_NAME: Final[str] = "status.json"
LEDGER_NAME: Final[str] = "ledger.jsonl"


def rel(*parts: str) -> str:
    """A repo-relative location under `.harness/`, always with forward slashes."""
    return "/".join((HARNESS, *(str(p).strip("/") for p in parts)))


def run_rel(stamp: object, *parts: str) -> str:
    return rel(RUNS, str(stamp), *parts)


def lane_rel(stamp: object, lane: object, *parts: str) -> str:
    return run_rel(stamp, str(lane), *parts)


def harness_path(repo: Path | str, *parts: str) -> Path:
    """`<repo>/.harness/<parts>` as a Path, for code that still needs a filesystem path."""
    return Path(repo).joinpath(*rel(*parts).split("/"))


class StateError(Exception):
    """Base class for state-port errors."""


class Store:
    """The port: text files addressed by a repo-relative path. `FileStore` is the disk adapter, `MemoryStore` the fake."""

    def read_text(self, path: str) -> str | None:
        raise NotImplementedError

    def write_text(self, path: str, text: str) -> None:
        raise NotImplementedError

    def append_text(self, path: str, text: str, header: str = "") -> None:
        raise NotImplementedError

    def create_exclusive(self, path: str, text: str) -> bool:
        """Create the file only if it does not exist; False when it does. The check and the create are one atomic step."""
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        return self.read_text(path) is not None

    def list(self, folder: str, pattern: str = "*") -> list[str]:
        """Repo-relative paths of the files directly inside `folder` that match the glob, sorted."""
        raise NotImplementedError

    def dirs(self, folder: str) -> list[str]:
        """Repo-relative paths of the sub-folders directly inside `folder`, sorted."""
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class FileStore(Store):
    def __init__(self, root: Path | str) -> None:
        self.root: Path = Path(root)

    def resolve(self, path: str) -> Path:
        target: Path = self.root.joinpath(*path.split("/"))
        if self.root.resolve() not in (target.resolve(), *target.resolve().parents):
            raise StateError(f"path escapes the repo: {path}")
        return target

    def read_text(self, path: str) -> str | None:
        try:
            return self.resolve(path).read_text(encoding=ENCODING)
        except (OSError, UnicodeDecodeError):
            return None

    def write_text(self, path: str, text: str) -> None:
        atomic_write(self.resolve(path), text)

    def append_text(self, path: str, text: str, header: str = "") -> None:
        append_text(self.resolve(path), text, header=header)

    def create_exclusive(self, path: str, text: str) -> bool:
        target: Path = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor: int = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, DEFAULT_MODE)
        except FileExistsError:
            return False
        try:
            os.write(descriptor, text.encode(ENCODING))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def exists(self, path: str) -> bool:
        return self.resolve(path).is_file()

    def list(self, folder: str, pattern: str = "*") -> list[str]:
        base: Path = self.resolve(folder)
        if not base.is_dir():
            return []
        return sorted(f"{folder}/{p.name}" for p in base.glob(pattern) if p.is_file())

    def dirs(self, folder: str) -> list[str]:
        base: Path = self.resolve(folder)
        return sorted(f"{folder}/{p.name}" for p in base.iterdir() if p.is_dir()) if base.is_dir() else []

    def delete(self, path: str) -> None:
        self.resolve(path).unlink(missing_ok=True)


class MemoryStore(Store):
    """An in-memory fake with the same contract as FileStore, for tests."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files: dict[str, str] = dict(files or {})
        self._guard: threading.Lock = threading.Lock()

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)

    def write_text(self, path: str, text: str) -> None:
        with self._guard:
            self.files[path] = text

    def append_text(self, path: str, text: str, header: str = "") -> None:
        with self._guard:
            self.files[path] = (self.files[path] if path in self.files else header) + text

    def create_exclusive(self, path: str, text: str) -> bool:
        with self._guard:
            if path in self.files:
                return False
            self.files[path] = text
            return True

    def exists(self, path: str) -> bool:
        return path in self.files

    def list(self, folder: str, pattern: str = "*") -> list[str]:
        prefix: str = folder.rstrip("/") + "/"
        return sorted(
            p for p in self.files
            if p.startswith(prefix) and "/" not in p[len(prefix):] and fnmatch.fnmatch(p[len(prefix):], pattern)
        )

    def dirs(self, folder: str) -> list[str]:
        prefix: str = folder.rstrip("/") + "/"
        return sorted({prefix + p[len(prefix):].split("/", 1)[0] for p in self.files
                       if p.startswith(prefix) and "/" in p[len(prefix):]})

    def delete(self, path: str) -> None:
        with self._guard:
            self.files.pop(path, None)


def parse_object(text: str | None) -> dict[str, Any] | None:
    """A JSON object from `text`; None for missing text, bad JSON, or anything that is not an object."""
    if text is None:
        return None
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# --- G-9: record versions ---------------------------------------------------------------------------------------
RECORD_VERSION: Final[int] = 1
VERSION_KEY: Final[str] = "v"
Migration = Callable[[dict[str, Any]], dict[str, Any]]
# File name -> record kind. Lanes' own supervisor files are registered by lanes.py (register_kind), not named here.
RECORD_KINDS: Final[dict[str, str]] = {LEASE_NAME: "lease", STATUS_NAME: "status"}
ROW_FILES: Final[set[str]] = {LEDGER_NAME}


def stamped(record: dict[str, Any]) -> dict[str, Any]:
    """A copy carrying the current version; a record that already says which version it is keeps it."""
    return record if VERSION_KEY in record else {**record, VERSION_KEY: RECORD_VERSION}


def to_current(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, VERSION_KEY: RECORD_VERSION}


# kind -> {from_version: upgrade}. Each upgrade returns the record at the next version. Version 0 is "no v field".
MIGRATIONS: Final[dict[str, dict[int, Migration]]] = {"lease": {0: to_current}, "status": {0: to_current}}


def register_kind(filename: str, kind: str) -> None:
    """Teach the port that `filename` holds records of `kind`; unregistered kinds without a table entry upgrade by stamping."""
    RECORD_KINDS[filename] = kind
    MIGRATIONS.setdefault(kind, {0: to_current})


def register_rows(filename: str) -> None:
    """Teach migrate_all that `filename` is a JSONL file whose rows carry `v`."""
    ROW_FILES.add(filename)


def kind_of(path: str) -> str | None:
    return RECORD_KINDS.get(path.rsplit("/", 1)[-1])


def version_of(record: dict[str, Any]) -> int:
    value: Any = record.get(VERSION_KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def migrate(kind: str | None, record: dict[str, Any], table: dict[str, dict[int, Migration]] | None = None,
            target: int | None = None) -> dict[str, Any]:
    """Upgrade `record` of `kind` to the target version, one table step at a time. Never mutates the input.
    A record newer than the target, or a missing step, raises StateError; an unknown kind passes through."""
    steps: dict[int, Migration] | None = (table if table is not None else MIGRATIONS).get(kind or "")
    goal: int = RECORD_VERSION if target is None else target
    current: dict[str, Any] = dict(record)
    if steps is None:
        return current
    if version_of(current) > goal:
        raise StateError(f"{kind} record is version {version_of(current)}, newer than this harness ({goal})")
    while version_of(current) < goal:
        have: int = version_of(current)
        step: Migration | None = steps.get(have)
        if step is None:
            raise StateError(f"no migration for {kind} from version {have}")
        current = step(dict(current))
        if version_of(current) <= have:
            raise StateError(f"migration for {kind} from version {have} did not advance the version")
    return current


def rows_to_current(text: str) -> str:
    """JSONL text with every well-formed object row stamped; torn and foreign lines are kept as they are."""
    out: list[str] = []
    for line in text.splitlines():
        row: dict[str, Any] | None = parse_object(line)
        out.append(json.dumps(stamped(row), sort_keys=True) if row is not None and VERSION_KEY not in row else line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def migrate_file(store: Store, path: str, report: dict[str, Any]) -> None:
    name: str = path.rsplit("/", 1)[-1]
    text: str | None = store.read_text(path)
    if text is None:
        return
    if name in ROW_FILES:
        updated: str = rows_to_current(text)
        if updated != text:
            store.write_text(path, updated)
            report["migrated"].append(path)
        return
    record: dict[str, Any] | None = parse_object(text)
    kind: str | None = kind_of(path)
    if record is None or kind is None:
        report["skipped"].append(path)
        return
    try:
        upgraded: dict[str, Any] = migrate(kind, record)
    except StateError as error:
        report["errors"].append({"path": path, "error": str(error)})
        return
    if upgraded != record:
        store.write_text(path, json.dumps(upgraded, indent=2, sort_keys=True) + "\n")
        report["migrated"].append(path)


def migrate_all(store: Store) -> dict[str, Any]:
    """Upgrade every known record and JSONL file under .harness/runs/ to the current version. Safe to repeat."""
    report: dict[str, Any] = {"migrated": [], "skipped": [], "errors": []}
    for run in store.dirs(RUNS_REL):
        folders: list[str] = [run, *store.dirs(run)]
        for folder in folders:
            for path in store.list(folder):
                if path.rsplit("/", 1)[-1] in {*RECORD_KINDS, *ROW_FILES}:
                    migrate_file(store, path, report)
    return report


class State:
    """Typed reads and writes over a Store. Records are JSON objects; rows are one JSON object per line."""

    def __init__(self, store: Store) -> None:
        self.store: Store = store

    def read_record(self, path: str) -> dict[str, Any] | None:
        """The record as an object, upgraded in memory to the current version when its file name has a registered kind."""
        record: dict[str, Any] | None = parse_object(self.store.read_text(path))
        kind: str | None = kind_of(path)
        return migrate(kind, record) if record is not None and kind is not None else record

    def write_record(self, path: str, record: dict[str, Any]) -> None:
        self.store.write_text(path, json.dumps(stamped(record), indent=2, sort_keys=True) + "\n")

    def merge_record(self, path: str, changes: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {**(self.read_record(path) or {}), **changes}
        self.write_record(path, merged)
        return merged

    def read_rows(self, path: str) -> list[dict[str, Any]]:
        """Every well-formed object line of a JSONL file; torn or foreign lines are skipped."""
        rows: list[dict[str, Any]] = []
        for line in (self.store.read_text(path) or "").splitlines():
            row: dict[str, Any] | None = parse_object(line)
            if row is not None:
                rows.append(row)
        return rows

    def append_row(self, path: str, row: dict[str, Any]) -> None:
        self.store.append_text(path, json.dumps(stamped(row), sort_keys=True) + "\n")

    def lease(self, stamp: object, lane: object) -> dict[str, Any] | None:
        return self.read_record(lane_rel(stamp, lane, LEASE_NAME))

    def status(self, stamp: object, lane: object) -> dict[str, Any] | None:
        return self.read_record(lane_rel(stamp, lane, STATUS_NAME))

    def runs(self) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p in self.store.dirs(RUNS_REL)]

    def lanes(self, stamp: object) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p in self.store.dirs(run_rel(stamp))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="State port tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    migrate_parser = sub.add_parser("migrate-all", help="upgrade every record under .harness/runs/ to the current version")
    migrate_parser.add_argument("repo", nargs="?", default=".")
    args = parser.parse_args(argv)
    if args.command == "migrate-all":
        json.dump(migrate_all(FileStore(args.repo)), sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
