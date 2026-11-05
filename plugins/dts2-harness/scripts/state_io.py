#!/usr/bin/env python3
"""The state port: the one module that knows where .harness/ files live and the one writer of them (atomic_write and
append_text below; Store, FileStore, MemoryStore and State further down). atomic_write writes a temp file in the same
directory, fsyncs it, then os.replace.

A crash mid-write leaves either the old file or the new one, never a torn file. Scripts import it with
`sys.path.insert(0, str(Path(__file__).resolve().parent))` then `from state_io import atomic_write`, because the
tests run scripts under `python3 -I`, which leaves the script's own folder off sys.path."""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Final, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_ids import InvalidId, LaneId, Stamp  # noqa: E402,F401

TEMP_PREFIX: Final[str] = ".tmp-"
ENCODING: Final[str] = "utf-8"
DEFAULT_MODE: Final[int] = 0o666
LOCK_MODE: Final[int] = 0o600


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
    if header and not target.exists():
        # Create the file with its header already inside: write a private temp file, then hard-link it into place.
        # os.link fails with FileExistsError when another writer got there first, so the header is always the first
        # bytes and is never written at offset 0 of a file that rows may already be appended to.
        scratch: str = f"{target}.{os.getpid()}.{uuid.uuid4().hex}.hdr"
        fd: int = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, DEFAULT_MODE)
        try:
            try:
                os.write(fd, header.encode(ENCODING))
            finally:
                os.close(fd)
            try:
                os.link(scratch, target)
            except FileExistsError:
                pass  # another writer created the file (with its header) first; our header is redundant
        finally:
            os.unlink(scratch)
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
DISCIPLINE_REL: Final[str] = f"{HARNESS}/discipline.md"
STATE_MD_REL: Final[str] = f"{HARNESS}/state.md"
ACTION_ITEMS_REL: Final[str] = f"{HARNESS}/action-items.md"
INTAKE_REL: Final[str] = f"{HARNESS}/intake.jsonl"
INTAKE_MD_REL: Final[str] = f"{HARNESS}/intake.md"
HANDOFF_LATEST_REL: Final[str] = f"{HARNESS}/handoff/latest.md"
METRICS_REL: Final[str] = f"{HARNESS}/metrics.jsonl"
RUNS_REL: Final[str] = f"{HARNESS}/{RUNS}"
MODEL_SLOTS_REL: Final[str] = f"{HARNESS}/cache/model-slots"
CACHE_REL: Final[str] = f"{HARNESS}/cache"
MERGE_GUARD_LOG_REL: Final[str] = f"{HARNESS}/merge-guard.log"
SETTINGS_CACHE_REL: Final[str] = f"{HARNESS}/settings.cache.json"
CHECKS_SH_REL: Final[str] = f"{HARNESS}/checks.sh"
LEASE_NAME: Final[str] = "lease.json"
STATUS_NAME: Final[str] = "status.json"
LEDGER_NAME: Final[str] = "ledger.jsonl"


def rel(*parts: str) -> str:
    """A repo-relative location under `.harness/`, always with forward slashes."""
    return "/".join((HARNESS, *(str(p).strip("/") for p in parts)))


def run_rel(stamp: object, *parts: str) -> str:
    return rel(RUNS, str(Stamp.coerce(stamp)), *parts)


def lane_rel(stamp: object, lane: object, *parts: str) -> str:
    return run_rel(stamp, str(LaneId.coerce(lane)), *parts)


def harness_path(repo: Path | str, *parts: str) -> Path:
    """`<repo>/.harness/<parts>` as a Path, for code that still needs a filesystem path."""
    return Path(repo).joinpath(*rel(*parts).split("/"))


class StateError(Exception):
    """Base class for state-port errors."""


class LockBusy(StateError):
    """The lock stayed taken for every try."""


class EpochRequired(StateError):
    """A lease change was attempted without saying which epoch the caller holds."""


class StaleEpoch(StateError):
    """The caller's epoch is older than the stored one; the lease is left as it was."""


LOCK_TRIES: Final[int] = 50
LOCK_WAIT_SEC: Final[float] = 0.1
LOCK_STALE_SEC: Final[float] = 60.0  # a lock guards one read-compare-write; older than this and its holder is gone
LOCK_SUFFIX: Final[str] = ".lock"
RECLAIM_SUFFIX: Final[str] = ".reclaim"
LOCK_READ_BYTES: Final[int] = 4096
MAX_SEND_BACKS: Final[int] = 2
SEND_BACK_FILE: Final[str] = "send-back-{n}.md"


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

    # The lock lives in the port: callers say what to lock, never how. Primitives are per adapter.
    clock: Callable[[], float] = staticmethod(time.time)  # type: ignore[assignment]
    sleep: Callable[[float], None] = staticmethod(time.sleep)  # type: ignore[assignment]

    def lock_create(self, path: str, token: str) -> bool:
        raise NotImplementedError

    def lock_reclaim(self, path: str, stale_s: float) -> bool:
        """Remove the lock if it is older than `stale_s`; True when one was removed."""
        raise NotImplementedError

    def lock_touch(self, path: str, token: str) -> bool:
        raise NotImplementedError

    def lock_drop(self, path: str, token: str) -> None:
        """Remove the lock only if `token` still owns it, so a holder that was reclaimed never frees its successor's lock."""
        raise NotImplementedError

    @contextlib.contextmanager
    def lock(self, path: str, tries: int = LOCK_TRIES, wait: float = LOCK_WAIT_SEC,
             stale_s: float = LOCK_STALE_SEC) -> Iterator[Held]:
        """Exclusive lock named by `path` (the file it guards). Raises LockBusy after `tries`. A lock older than
        `stale_s` is reclaimed; a long job calls `held.renew()` to stay alive."""
        token: str = uuid.uuid4().hex
        for _ in range(max(1, tries)):
            if self.lock_create(path, token):
                break
            if self.lock_reclaim(path, stale_s) and self.lock_create(path, token):
                break  # reclaimed on the last try still gets one acquire attempt before giving up
            self.sleep(wait)
        else:
            raise LockBusy(f"lock busy for {path}")
        try:
            yield Held(self, path, token)
        finally:
            self.lock_drop(path, token)


class Held:
    """A lock this caller owns."""

    def __init__(self, store: Store, path: str, token: str) -> None:
        self.store: Store = store
        self.path: str = path
        self.token: str = token

    def renew(self) -> bool:
        """Refresh the lock's age. False means it was reclaimed meanwhile and this caller no longer owns it."""
        return self.store.lock_touch(self.path, self.token)


class FileStore(Store):
    def __init__(self, root: Path | str, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.root: Path = Path(root)
        self.clock = clock  # type: ignore[assignment,method-assign]
        self.sleep = sleep  # type: ignore[assignment,method-assign]

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

    def lock_file(self, path: str) -> Path:
        return self.resolve(path + LOCK_SUFFIX)

    def lock_create(self, path: str, token: str) -> bool:
        target: Path = self.lock_file(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor: int = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, LOCK_MODE)
        except FileExistsError:
            return False
        try:
            os.write(descriptor, json.dumps({"token": token, "pid": os.getpid()}).encode(ENCODING))
        finally:
            os.close(descriptor)
        return True

    def lock_owner(self, target: Path) -> str | None:
        try:
            data: Any = json.loads(target.read_text(encoding=ENCODING))
        except (OSError, ValueError):
            return None
        return data.get("token") if isinstance(data, dict) else None

    def lock_reclaim(self, path: str, stale_s: float) -> bool:
        """Reclaim by rename: move the stale lock aside (atomic, so one reclaimer wins), confirm it was the same file
        that was seen stale, then delete it. One reclaimer at a time, held with a mkdir that is itself reclaimed when old."""
        target: Path = self.lock_file(path)
        guard: Path = target.with_name(target.name + RECLAIM_SUFFIX)
        try:
            seen = target.stat()
        except OSError:
            return False  # gone already: the next create decides who wins
        if self.clock() - seen.st_mtime <= stale_s:
            return False
        try:
            guard.mkdir()
        except FileExistsError:
            with contextlib.suppress(OSError):
                if self.clock() - guard.stat().st_mtime > stale_s:
                    guard.rmdir()  # the reclaimer died inside its few microseconds
            return False
        except OSError:
            return False
        grave: Path = target.with_name(f"{target.name}.stale-{uuid.uuid4().hex}")
        try:
            os.rename(target, grave)
            moved = grave.stat()
            if (moved.st_ino, moved.st_mtime_ns) != (seen.st_ino, seen.st_mtime_ns):
                with contextlib.suppress(OSError):
                    os.link(grave, target)  # we moved a fresh lock by mistake: put it back
                grave.unlink(missing_ok=True)
                return False
            grave.unlink(missing_ok=True)
            return True
        except OSError:
            return False
        finally:
            with contextlib.suppress(OSError):
                guard.rmdir()

    def lock_touch(self, path: str, token: str) -> bool:
        """Refresh the lock's age if `token` owns it. Owner check and refresh share one open file, so a successor's
        lock (a different file) is never refreshed."""
        target: Path = self.lock_file(path)
        try:
            descriptor: int = os.open(target, os.O_RDONLY)
        except OSError:
            return False
        try:
            if self.lock_owner_fd(descriptor) != token:
                return False
            if os.utime in os.supports_fd:
                os.utime(descriptor, None)
            else:  # pragma: no cover - platforms without fd utime
                os.utime(target, None)
        except OSError:
            return False
        finally:
            os.close(descriptor)
        return True

    @staticmethod
    def lock_owner_fd(descriptor: int) -> str | None:
        try:
            data: Any = json.loads(os.read(descriptor, LOCK_READ_BYTES).decode(ENCODING))
        except (OSError, ValueError):
            return None
        return data.get("token") if isinstance(data, dict) else None

    def lock_drop(self, path: str, token: str) -> None:
        """Move the lock aside first (atomic), then check the token on what was moved: ours is deleted, a
        successor's is put back, so a stale holder can never free a lock it does not own."""
        target: Path = self.lock_file(path)
        grave: Path = target.with_name(f"{target.name}.drop-{uuid.uuid4().hex}")
        try:
            os.rename(target, grave)
        except OSError:
            return  # already gone
        try:
            if self.lock_owner(grave) != token:
                with contextlib.suppress(OSError):
                    os.link(grave, target)  # not ours: restore (no-op if a newer lock already took the name)
        finally:
            grave.unlink(missing_ok=True)


class MemoryStore(Store):
    """An in-memory fake with the same contract as FileStore, for tests."""

    def __init__(self, files: dict[str, str] | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.files: dict[str, str] = dict(files or {})
        self.locks: dict[str, list[Any]] = {}  # path -> [token, taken-at]
        self._guard: threading.Lock = threading.Lock()
        self.clock = clock  # type: ignore[assignment,method-assign]
        self.sleep = sleep  # type: ignore[assignment,method-assign]

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

    def lock_create(self, path: str, token: str) -> bool:
        with self._guard:
            if path in self.locks:
                return False
            self.locks[path] = [token, self.clock()]
            return True

    def lock_reclaim(self, path: str, stale_s: float) -> bool:
        with self._guard:
            entry: list[Any] | None = self.locks.get(path)
            if entry is None or self.clock() - entry[1] <= stale_s:
                return False
            del self.locks[path]
            return True

    def lock_touch(self, path: str, token: str) -> bool:
        with self._guard:
            entry: list[Any] | None = self.locks.get(path)
            if entry is None or entry[0] != token:
                return False
            entry[1] = self.clock()
            return True

    def lock_drop(self, path: str, token: str) -> None:
        with self._guard:
            entry: list[Any] | None = self.locks.get(path)
            if entry is not None and entry[0] == token:
                del self.locks[path]


def epoch_of(record: dict[str, Any] | None) -> int:
    value: Any = (record or {}).get("epoch", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def require_epoch(epoch: Any, stored: int) -> int:
    """The caller's epoch, or EpochRequired when it was not given (None, a bool, a non-int) and StaleEpoch when older."""
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        raise EpochRequired("an epoch is required to change a lease; pass the one you hold (0 for a first lease)")
    if epoch < stored:
        raise StaleEpoch(f"stale epoch {epoch} is older than the stored lease epoch {stored}; the lease is unchanged")
    return epoch


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


# --- G-23: one event shape ---------------------------------------------------------------------------------------
NO_SCOPE: Final[str] = "-"  # the run or lane field of an event that belongs to no particular run or lane
EVENT_KEYS: Final[tuple[str, ...]] = ("v", "ts", "run", "lane", "kind", "id")
GENERATED_PREFIX: Final[str] = "u-"  # ids made by make_event; they identify nothing, so they are never deduped


def event_id(*parts: object) -> str:
    """A stable id from the parts that identify an event, so writing it twice is recognised: same parts, same id."""
    joined: str = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode(ENCODING)).hexdigest()[:16]


def scope_of(value: Any, parse: Callable[[Any], Any]) -> str:
    return NO_SCOPE if value in (None, "", NO_SCOPE) else str(parse(value))


def make_event(kind: str, *, run: Any = None, lane: Any = None, id: str | None = None, ts: int | None = None,
               **fields: Any) -> dict[str, Any]:
    """An event row: {v, ts, run, lane, kind, id} plus the caller's fields. The six keys cannot be overridden by fields.
    `run` and `lane` are validated (InvalidId) or "-" for none. Without `id` the event gets a unique `u-` one and is never
    treated as a duplicate; pass `event_id(...)` of what identifies it to make writing it twice a no-op."""
    return {**fields, "v": RECORD_VERSION, "ts": int(time.time()) if ts is None else ts,
            "run": scope_of(run, Stamp.parse), "lane": scope_of(lane, LaneId.parse), "kind": kind,
            "id": id or GENERATED_PREFIX + uuid.uuid4().hex}


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

    def update_record(self, path: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Read-merge-write one record under its lock, so concurrent writers never lose each other's fields."""
        with self.store.lock(path):
            return self.merge_record(path, changes)

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

    def append_event(self, path: str, event: dict[str, Any]) -> bool:
        """Append one event row (a single O_APPEND write). False when an event with the same caller-chosen id is already
        there. Only caller-chosen ids are checked (under the file's lock); generated ones (prefix `u-`) skip the read, so
        busy ledgers stay cheap and never block."""
        row: dict[str, Any] = stamped(event)
        line: str = json.dumps(row, sort_keys=True) + "\n"
        if str(row.get("id", GENERATED_PREFIX)).startswith(GENERATED_PREFIX):
            self.store.append_text(path, line)
            return True
        with self.store.lock(path):
            if any(existing.get("id") == row["id"] for existing in self.read_rows(path)):
                return False
            self.store.append_text(path, line)
            return True

    def forget_event(self, path: str, event_id: str) -> None:
        """Drop the rows with this id (under the file's lock), so a write that failed after its dedupe row went in can be retried."""
        with self.store.lock(path):
            kept: list[str] = [line for line in (self.store.read_text(path) or "").splitlines()
                               if (parse_object(line) or {}).get("id") != event_id]
            self.store.write_text(path, "".join(line + "\n" for line in kept))

    def events(self, path: str, kind: str | None = None, lane: str | None = None) -> list[dict[str, Any]]:
        return [row for row in self.read_rows(path)
                if (kind is None or row.get("kind") == kind) and (lane is None or row.get("lane") == lane)]

    def lease(self, stamp: object, lane: object) -> dict[str, Any] | None:
        return self.read_record(lane_rel(stamp, lane, LEASE_NAME))

    def acquire_lease(self, stamp: object, lane: object, *, epoch: int,
                      fields: dict[str, Any] | None = None) -> dict[str, Any]:
        """Take or renew a lane's lease under its lock. `epoch` is the caller's view (0 for the first lease) and is
        mandatory: an older one raises StaleEpoch, an unreadable stored lease is never overwritten."""
        path: str = lane_rel(stamp, lane, LEASE_NAME)
        require_epoch(epoch, 0)
        with self.store.lock(path):
            raw: str | None = self.store.read_text(path)
            previous: dict[str, Any] | None = self.read_record(path)
            if raw is not None and previous is None:
                raise StateError(f"unreadable lease at {path}; refusing to overwrite")
            stored: int = epoch_of(previous)
            require_epoch(epoch, stored)
            record: dict[str, Any] = {**(fields or {}), "stamp": str(Stamp.coerce(stamp)), "lane": str(LaneId.coerce(lane)),
                                      "status": "active", "created": int(self.store.clock()), "epoch": stored + 1}
            self.write_record(path, record)
            return self.read_record(path) or record

    def release_lease(self, stamp: object, lane: object, *, epoch: int) -> dict[str, Any]:
        path: str = lane_rel(stamp, lane, LEASE_NAME)
        require_epoch(epoch, 0)
        with self.store.lock(path):
            record: dict[str, Any] | None = self.read_record(path)
            if record is None:
                raise StateError(f"no lease at {path}")
            require_epoch(epoch, epoch_of(record))
            closed: dict[str, Any] = {**record, "status": "closed", "released": int(self.store.clock())}
            self.write_record(path, closed)
            return closed

    def sendback(self, stamp: object, lane: object, reason: str, limit: int = MAX_SEND_BACKS) -> int | None:
        """Write the next send-back note and return its number, or None when `limit` are used. The counter is the
        exclusive create of the file, so racing callers never share a number."""
        name: str = str(LaneId.coerce(lane))
        for number in range(1, limit + 1):
            path: str = lane_rel(stamp, lane, SEND_BACK_FILE.format(n=number))
            if self.store.create_exclusive(path, f"# Send-back {number} for lane {name}\n\n{reason}\n"):
                return number
        return None

    def status(self, stamp: object, lane: object) -> dict[str, Any] | None:
        return self.read_record(lane_rel(stamp, lane, STATUS_NAME))

    def runs(self) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p in self.store.dirs(RUNS_REL)]

    def lanes(self, stamp: object) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p in self.store.dirs(run_rel(stamp))]


def append_event_at(path: Path | str, event: dict[str, Any]) -> bool:
    """append_event for a plain filesystem path (a ledger a script was handed on its command line)."""
    target: Path = Path(path)
    return State(FileStore(target.parent)).append_event(target.name, event)


def forget_event_at(path: Path | str, event_id: str) -> None:
    """forget_event for a plain filesystem path; the counterpart of append_event_at for a write that then failed."""
    target: Path = Path(path)
    State(FileStore(target.parent)).forget_event(target.name, event_id)


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
