#!/usr/bin/env python3
"""Personal cross-device knowledge store.

Standing preferences, glossary terms and cross-project learnings live as one Markdown file per entry
(`<store>/entries/<kind>/<key>.md`) in a folder that is usually a private git repository, so every device shares it.
The store is DTS2_KNOWLEDGE, else $DTS2_HOME/knowledge, else ~/.dts2/knowledge. Nothing reads it automatically:
only the user-invoked knowledge command and the setup interview (`context`) do. Secrets are refused on write.

Library: store_path / read_entries / write_entry / find_entry / check_secrets / build_context / sync.
CLI: python3 knowledge.py setup|join|init|set|get|find|list|rm|sync|status|context (see main)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

ENV_STORE: Final[str] = "DTS2_KNOWLEDGE"
ENV_HOME: Final[str] = "DTS2_HOME"
ENV_GIT: Final[str] = "DTS2_GIT_BIN"
ENV_PROFILE: Final[str] = "DTS2_KNOWLEDGE_PROFILE"
PROFILE_FILE: Final[str] = "knowledge.json"
MARKER_FILE: Final[str] = "store.json"
SCHEMA_VERSION: Final[int] = 1
BACKEND_GIT: Final[str] = "git"
BACKEND_FOLDER: Final[str] = "folder"
BACKEND_LOCAL: Final[str] = "local"
BACKEND_CLOUDFLARE: Final[str] = "cloudflare"
BACKEND_NAMES: Final[tuple[str, ...]] = (BACKEND_GIT, BACKEND_FOLDER, BACKEND_LOCAL, BACKEND_CLOUDFLARE)
ENV_CLOUDFLARE_TOKEN: Final[str] = "DTS2_KNOWLEDGE_TOKEN"
TOKEN_NOTE: Final[str] = f"note: set {ENV_CLOUDFLARE_TOKEN} in your environment before syncing (it is never stored)"
FOLDER_SYNC_NOTE: Final[str] = "folder is synced by your drive app"
LOCAL_SYNC_NOTE: Final[str] = "local store; nothing to sync"
DEFAULT_HOME_DIR: Final[str] = ".dts2"
STORE_DIR: Final[str] = "knowledge"
ENTRIES_DIR: Final[str] = "entries"
README_FILE: Final[str] = "README.md"
ENTRY_SUFFIX: Final[str] = ".md"
ENCODING: Final[str] = "utf-8"
FENCE: Final[str] = "---"
KINDS: Final[tuple[str, ...]] = ("preference", "term", "learning")
DEFAULT_KIND: Final[str] = "preference"
KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ISO_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
STAMP_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"
CONFLICT_MARK: Final[str] = ".conflict-"
MIN_TOKEN_CHARS: Final[int] = 3
LONG_TOKEN_CHARS: Final[int] = 32
DEFAULT_BRANCH: Final[str] = "main"
REMOTE: Final[str] = "origin"
FALLBACK_IDENTITY: Final[tuple[str, str]] = ("dts2-knowledge", "knowledge@localhost")
EXIT_OK: Final[int] = 0
EXIT_GIT: Final[int] = 1
EXIT_BAD_INPUT: Final[int] = 2
EXIT_NOT_FOUND: Final[int] = 3
SECRET_MESSAGE: Final[str] = "refused: looks like a secret; the knowledge store is for preferences and glossary only"
SECRET_NAME_WORDS: Final[tuple[str, ...]] = (
    "token", "password", "passwd", "secret", "api_key", "apikey", "api-key", "private_key", "private-key",
    "credential",
)
SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"github_pat_",
        r"xox[abprs]-",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN",
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.",
    )
)
README_TEXT: Final[str] = (
    "# Personal knowledge store\n\n"
    "One Markdown file per entry under `entries/<kind>/<key>.md`, kinds: preference, term, learning.\n"
    "Managed by `knowledge.py`; safe to edit by hand. Never put secrets here.\n"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(text: Any) -> datetime:
    """Stored timestamp as an aware datetime; anything unreadable sorts as the oldest possible."""
    oldest: datetime = datetime.min.replace(tzinfo=timezone.utc)
    if not isinstance(text, str):
        return oldest
    try:
        moment: datetime = datetime.strptime(text, ISO_FORMAT)
    except ValueError:
        return oldest
    return moment.replace(tzinfo=timezone.utc)


def short_host() -> str:
    return socket.gethostname().split(".")[0] or "unknown"


def profile_path() -> Path:
    explicit: str | None = os.environ.get(ENV_PROFILE)
    if explicit:
        return Path(explicit)
    home: str | None = os.environ.get(ENV_HOME)
    base: Path = Path(home) if home else Path.home() / DEFAULT_HOME_DIR
    return base / PROFILE_FILE


def load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        raw: Any = json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def load_profile() -> dict[str, Any] | None:
    """This device's profile, or None when absent or unreadable. Never raises."""
    profile: dict[str, Any] | None = load_json_file(profile_path())
    return profile if profile and profile.get("backend") in BACKEND_NAMES else None


def save_profile(owner: str, backend: str, store: Path, remote: str | None) -> dict[str, Any]:
    """Write the device profile. It holds locations only, never credentials."""
    profile: dict[str, Any] = {
        "schema": SCHEMA_VERSION, "owner": owner, "backend": backend, "store": str(store.resolve()),
        "remote": remote, "joined": to_iso(utc_now()),
    }
    atomic_write(profile_path(), json.dumps(profile, indent=2, sort_keys=True) + "\n")
    return profile


def store_path() -> Path:
    """DTS2_KNOWLEDGE, else the profile's store, else $DTS2_HOME/knowledge, else ~/.dts2/knowledge."""
    explicit: str | None = os.environ.get(ENV_STORE)
    if explicit:
        return Path(explicit)
    profile: dict[str, Any] | None = load_profile()
    if profile and isinstance(profile.get("store"), str) and profile["store"]:
        return Path(profile["store"])
    home: str | None = os.environ.get(ENV_HOME)
    base: Path = Path(home) if home else Path.home() / DEFAULT_HOME_DIR
    return base / STORE_DIR


def clean_key(key: str) -> str:
    lowered: str = str(key).strip().lower()
    if not KEY_PATTERN.match(lowered):
        raise ValueError(f"invalid key: {key!r} (lowercase letters, digits, . _ - ; max 64 chars)")
    return lowered


def check_secrets(key: str, aliases: list[str], value: str) -> None:
    """Raise ValueError when the key, an alias or the value looks like a credential."""
    for name in [key, *aliases]:
        lowered: str = name.lower()
        if any(word in lowered for word in SECRET_NAME_WORDS):
            raise ValueError(SECRET_MESSAGE)
    if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        raise ValueError(SECRET_MESSAGE)
    for token in value.split():
        if len(token) >= LONG_TOKEN_CHARS and re.search(r"[A-Za-z]", token) and re.search(r"\d", token):
            raise ValueError(SECRET_MESSAGE)


def atomic_write(target: Path, text: str) -> None:
    """Temp file in the same folder, fsync, os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=ENTRY_SUFFIX)
    try:
        with os.fdopen(descriptor, "w", encoding=ENCODING) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def render_entry(entry: dict[str, Any]) -> str:
    head: list[str] = [
        FENCE,
        f"key: {entry['key']}",
        f"kind: {entry['kind']}",
        f"aliases: {json.dumps(entry['aliases'], ensure_ascii=False)}",
        f"tags: {json.dumps(entry['tags'], ensure_ascii=False)}",
        f"updated: {entry['updated']}",
        f"by: {entry['by']}",
        FENCE,
    ]
    return "\n".join(head) + "\n" + entry["value"].strip() + "\n"


def parse_list(text: str) -> list[str]:
    try:
        parsed: Any = json.loads(text)
    except ValueError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def parse_entry(text: str, kind: str, key: str) -> dict[str, Any] | None:
    """An entry dict from file text, or None when the frontmatter is missing or unterminated."""
    lines: list[str] = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return None
    try:
        end: int = next(index for index in range(1, len(lines)) if lines[index].strip() == FENCE)
    except StopIteration:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        name, _, rest = line.partition(":")
        fields[name.strip()] = rest.strip()
    return {
        "key": fields.get("key") or key, "kind": fields.get("kind") or kind, "value": "\n".join(lines[end + 1:]).strip(),
        "aliases": parse_list(fields.get("aliases", "[]")), "tags": parse_list(fields.get("tags", "[]")),
        "updated": fields.get("updated", ""), "by": fields.get("by", ""),
    }


def entry_file(store: Path, kind: str, key: str) -> Path:
    return store / ENTRIES_DIR / kind / f"{key}{ENTRY_SUFFIX}"


def read_entries(store: Path, kind: str | None = None) -> list[dict[str, Any]]:
    """Every readable entry, sorted by kind then key. Conflict copies and unreadable files are skipped."""
    found: list[dict[str, Any]] = []
    for each_kind in ([kind] if kind else KINDS):
        for path in sorted((store / ENTRIES_DIR / each_kind).glob(f"*{ENTRY_SUFFIX}")):
            if not KEY_PATTERN.match(path.stem):
                continue
            try:
                entry = parse_entry(path.read_text(encoding=ENCODING), each_kind, path.stem)
            except (OSError, UnicodeDecodeError):
                continue
            if entry is not None:
                found.append(entry)
    return sorted(found, key=lambda item: (KINDS.index(item["kind"]) if item["kind"] in KINDS else len(KINDS), item["key"]))


def find_entry(store: Path, name: str) -> dict[str, Any] | None:
    """Exact key first, then a case-insensitive alias match across kinds."""
    entries: list[dict[str, Any]] = read_entries(store)
    lowered: str = name.strip().lower()
    for entry in entries:
        if entry["key"] == lowered:
            return entry
    for entry in entries:
        if any(alias.lower() == lowered for alias in entry["aliases"]):
            return entry
    return None


def write_entry(
    store: Path, key: str, value: str, kind: str, aliases: list[str], tags: list[str], by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate, refuse secrets, write atomically, and remove the same key from other kinds."""
    clean: str = key.strip()
    if not KEY_PATTERN.match(clean):
        raise ValueError(f"invalid key: {key!r} (lowercase letters, digits, . _ - ; max 64 chars)")
    if kind not in KINDS:
        raise ValueError(f"invalid kind: {kind!r} (one of {', '.join(KINDS)})")
    check_secrets(clean, aliases, value)
    entry: dict[str, Any] = {
        "key": clean, "kind": kind, "value": value.strip(), "aliases": aliases, "tags": tags,
        "updated": to_iso(now or utc_now()), "by": " ".join(by.split()) or short_host(),
    }
    atomic_write(entry_file(store, kind, clean), render_entry(entry))
    for other in KINDS:
        if other != kind:
            entry_file(store, other, clean).unlink(missing_ok=True)
    return entry


# ---------------------------------------------------------------- git

def git_bin() -> str:
    return os.environ.get(ENV_GIT) or "git"


def run_git(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git inside the store; never prompts, never raises on a non-zero exit (a missing binary reads as 127)."""
    env: dict[str, str] = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            [git_bin(), *args], cwd=str(store), capture_output=True, text=True, env=env, check=False,
        )
    except OSError as error:
        return subprocess.CompletedProcess(args=[git_bin(), *args], returncode=127, stdout="", stderr=str(error))


def identity_args(store: Path) -> list[str]:
    """Config overrides so commits work on a machine with no git identity and never wait on signing."""
    args: list[str] = ["-c", "commit.gpgsign=false"]
    name: str = run_git(store, "config", "user.name").stdout.strip()
    email: str = run_git(store, "config", "user.email").stdout.strip()
    if not name or not email:
        args += ["-c", f"user.name={FALLBACK_IDENTITY[0]}", "-c", f"user.email={FALLBACK_IDENTITY[1]}"]
    return args


def is_repo(store: Path) -> bool:
    return (store / ".git").exists() and run_git(store, "rev-parse", "--git-dir").returncode == 0


def remote_url(store: Path) -> str | None:
    if not is_repo(store):
        return None
    result = run_git(store, "remote", "get-url", REMOTE)
    return result.stdout.strip() or None if result.returncode == 0 else None


def current_branch(store: Path) -> str:
    result = run_git(store, "symbolic-ref", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else DEFAULT_BRANCH


def is_dirty(store: Path) -> bool:
    return is_repo(store) and bool(run_git(store, "status", "--porcelain").stdout.strip())


def commit_all(store: Path, message: str) -> bool:
    """Stage everything and commit when something changed. True when a commit was made."""
    if not is_dirty(store):
        return False
    run_git(store, "add", "-A")
    return run_git(store, *identity_args(store), "commit", "-m", message).returncode == 0


def entry_conflict_path(path: str) -> bool:
    parts: list[str] = path.split("/")
    return len(parts) >= 3 and parts[0] == ENTRIES_DIR and path.endswith(ENTRY_SUFFIX)


def resolve_conflict(store: Path, path: str, stamp: str) -> None:
    """Keep the side with the newer `updated`; save the other beside it as `<key>.conflict-<stamp>.md`."""
    sides: dict[str, str | None] = {}
    for label, stage in (("ours", ":2:"), ("theirs", ":3:")):
        shown = run_git(store, "show", f"{stage}{path}")
        sides[label] = shown.stdout if shown.returncode == 0 else None
    ours, theirs = sides["ours"], sides["theirs"]
    target: Path = store / path
    if ours is None or theirs is None:  # modify/delete: the surviving side wins, there is nothing to set aside
        survivor: str = ours if theirs is None else theirs  # type: ignore[assignment]
        atomic_write(target, survivor)
        run_git(store, "add", "--", path)
        return
    stem: str = Path(path).stem
    ours_entry = parse_entry(ours, "", stem)
    theirs_entry = parse_entry(theirs, "", stem)
    ours_time: datetime = parse_iso(ours_entry["updated"] if ours_entry else None)
    theirs_time: datetime = parse_iso(theirs_entry["updated"] if theirs_entry else None)
    winner, loser = (theirs, ours) if theirs_time > ours_time else (ours, theirs)
    atomic_write(target, winner)
    loser_path: Path = target.with_name(f"{stem}{CONFLICT_MARK}{stamp}{ENTRY_SUFFIX}")
    atomic_write(loser_path, loser)
    run_git(store, "add", "--", path, str(loser_path.relative_to(store)))


def resolve_merge(store: Path, host: str) -> tuple[bool, str]:
    """After a conflicted merge: resolve entry conflicts, or abort when anything else conflicts."""
    unmerged: list[str] = [
        line for line in run_git(store, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if line
    ]
    foreign: list[str] = [path for path in unmerged if not entry_conflict_path(path)]
    if foreign:
        run_git(store, "merge", "--abort")
        return False, f"merge aborted; conflicts outside entries need manual resolution: {', '.join(foreign)}"
    stamp: str = utc_now().strftime(STAMP_FORMAT)
    for path in unmerged:
        resolve_conflict(store, path, stamp)
    done = run_git(store, *identity_args(store), "commit", "--no-edit")
    if done.returncode != 0:
        return False, f"could not complete merge: {done.stderr.strip()}"
    return True, f"resolved {len(unmerged)} conflicting entr{'y' if len(unmerged) == 1 else 'ies'}"


def sync(store: Path) -> tuple[int, str]:
    """Commit, fetch, merge (newer entry wins), push. Returns (exit code, message)."""
    if not is_repo(store):
        return EXIT_OK, "not a git repository; nothing to sync (synced-folder mode)"
    host: str = short_host()
    commit_all(store, f"knowledge: sync from {host}")
    if remote_url(store) is None:
        return EXIT_OK, "no remote; committed locally"
    fetched = run_git(store, "fetch", REMOTE)
    if fetched.returncode != 0:
        return EXIT_GIT, f"fetch failed: {fetched.stderr.strip()}"
    branch: str = current_branch(store)
    notes: list[str] = []
    if run_git(store, "rev-parse", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{branch}").returncode == 0:
        merged = run_git(
            store, *identity_args(store), "merge", "--no-edit", "--allow-unrelated-histories", f"{REMOTE}/{branch}",
        )
        if merged.returncode != 0:
            ok, note = resolve_merge(store, host)
            if not ok:
                return EXIT_BAD_INPUT, note
            notes.append(note)
    pushed = run_git(store, "push", "-u", REMOTE, branch)
    if pushed.returncode != 0:
        return EXIT_GIT, f"push failed: {pushed.stderr.strip()}"
    notes.append(f"synced {branch} with {REMOTE}")
    return EXIT_OK, "; ".join(notes)


def init_store(store: Path, remote: str | None, clone: bool = True, use_git: bool = True) -> list[str]:
    """Create the store (idempotent). Returns human-readable notes about what happened."""
    notes: list[str] = []
    empty: bool = not store.exists() or not any(store.iterdir())
    if remote and empty and clone:
        store.parent.mkdir(parents=True, exist_ok=True)
        cloned = run_git(store.parent, "clone", remote, str(store))
        if cloned.returncode != 0:
            raise RuntimeError(f"clone failed: {cloned.stderr.strip()}")
        notes.append(f"cloned {remote}")
    store.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        (store / ENTRIES_DIR / kind).mkdir(parents=True, exist_ok=True)
    readme: Path = store / README_FILE
    if not readme.exists():
        atomic_write(readme, README_TEXT)
    if not use_git:
        return notes
    if not is_repo(store):
        if run_git(store, "init").returncode == 0:
            run_git(store, "symbolic-ref", "HEAD", f"refs/heads/{DEFAULT_BRANCH}")
            notes.append("initialised git repository")
        else:
            notes.append("git unavailable; using the folder without version control")
    if remote and is_repo(store) and not any("cloned" in note for note in notes):
        verb = "set-url" if remote_url(store) else "add"
        run_git(store, "remote", verb, REMOTE, remote)
        notes.append(f"remote {REMOTE} -> {remote}")
    return notes


# ---------------------------------------------------------------- backends

class Backend:
    """How a device keeps its store in step with the others. Subclasses set `name` and override `sync`."""

    name: str = ""

    def __init__(self, profile: dict[str, Any] | None = None) -> None:
        self.profile: dict[str, Any] = profile or {}

    def sync(self, store: Path) -> int:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "owner": self.profile.get("owner"), "remote": self.profile.get("remote")}


class GitBackend(Backend):
    name = BACKEND_GIT

    def sync(self, store: Path) -> int:
        code, message = sync(store)
        print(message, file=sys.stderr if code else sys.stdout)
        return code


class FolderBackend(Backend):
    name = BACKEND_FOLDER

    def sync(self, store: Path) -> int:
        print(FOLDER_SYNC_NOTE)
        return EXIT_OK


class LocalBackend(Backend):
    name = BACKEND_LOCAL

    def sync(self, store: Path) -> int:
        print(LOCAL_SYNC_NOTE)
        return EXIT_OK


class CloudflareSync(Backend):
    name = BACKEND_CLOUDFLARE

    def sync(self, store: Path) -> int:
        url: str | None = self.profile.get("remote")
        if not url:
            print("cloudflare backend has no url; run join --backend cloudflare --url URL", file=sys.stderr)
            return EXIT_BAD_INPUT
        if not os.environ.get(ENV_CLOUDFLARE_TOKEN):
            print(f"set {ENV_CLOUDFLARE_TOKEN} in the environment to sync with {url}", file=sys.stderr)
            return EXIT_BAD_INPUT
        import knowledge_cloudflare  # sibling module, loaded only when this backend is used

        try:
            changed: int = knowledge_cloudflare.CloudflareBackend.from_env(url).sync(store)
        except knowledge_cloudflare.BackendError as error:
            print(f"cloudflare sync failed: {error}", file=sys.stderr)
            return EXIT_GIT
        print(f"synced with {url}: {changed} entries changed")
        return EXIT_OK


BACKENDS: Final[dict[str, type[Backend]]] = {
    BACKEND_GIT: GitBackend, BACKEND_FOLDER: FolderBackend, BACKEND_LOCAL: LocalBackend,
    BACKEND_CLOUDFLARE: CloudflareSync,
}


def backend_for(profile: dict[str, Any] | None) -> Backend:
    """The backend the profile names; without a profile, git (which degrades to a note when not a repository)."""
    name: str = profile["backend"] if profile else BACKEND_GIT
    return BACKENDS[name](profile)


def read_marker(store: Path) -> dict[str, Any] | None:
    return load_json_file(store / MARKER_FILE)


def write_marker(store: Path, owner: str) -> None:
    marker: dict[str, Any] = {"schema": SCHEMA_VERSION, "owner": owner, "created": to_iso(utc_now())}
    atomic_write(store / MARKER_FILE, json.dumps(marker, indent=2, sort_keys=True) + "\n")


def write_readme(store: Path, owner: str) -> None:
    atomic_write(store / README_FILE, f"{README_TEXT}\nOwner: {owner}\n")


def create_store(
    store: Path, owner: str, backend: str, remote: str | None, adopt: bool = False,
) -> tuple[int, list[str]]:
    """Create a store for `backend` and tie this device to it. `adopt` (the init alias) clones an existing remote and
    keeps an existing marker and README; a brand-new setup never clones."""
    is_git: bool = backend == BACKEND_GIT
    notes: list[str] = init_store(store, remote if is_git else None, clone=adopt, use_git=is_git)
    if not adopt or read_marker(store) is None:
        write_marker(store, owner)
    if not adopt or "Owner:" not in (store / README_FILE).read_text(encoding=ENCODING):
        write_readme(store, owner)
    save_profile(owner, backend, store, remote if is_git or backend == BACKEND_CLOUDFLARE else None)
    code: int = EXIT_OK
    if is_git:
        commit_all(store, "knowledge: initial store")
        if remote:
            pushed = run_git(store, "push", "-u", REMOTE, current_branch(store))
            if pushed.returncode != 0:
                notes.append(f"push failed: {pushed.stderr.strip()}")
                code = EXIT_GIT
    return code, notes


def join_store(backend: str, remote: str | None, path: str | None) -> tuple[int, str]:
    """Tie this device to an existing store. Returns (exit code, message)."""
    store: Path = Path(path) if path else store_path()
    if backend == BACKEND_GIT:
        if not remote:
            raise ValueError("join --backend git needs --remote URL")
        if store.exists() and any(store.iterdir()):
            if not is_repo(store) or remote_url(store) != remote:
                raise ValueError(f"{store} already exists and is not a clone of {remote}")
        else:
            store.parent.mkdir(parents=True, exist_ok=True)
            cloned = run_git(store.parent, "clone", remote, str(store))
            if cloned.returncode != 0:
                return EXIT_GIT, f"clone failed: {cloned.stderr.strip()}"
    elif backend == BACKEND_CLOUDFLARE:
        if not remote:
            raise ValueError("join --backend cloudflare needs --url URL")
        store.mkdir(parents=True, exist_ok=True)
        if read_marker(store) is None:
            write_marker(store, default_owner())
    elif not path:
        raise ValueError("join --backend folder needs --path DIR")
    marker: dict[str, Any] | None = read_marker(store)
    if marker is None or not isinstance(marker.get("owner"), str):
        return EXIT_NOT_FOUND, f"no {MARKER_FILE} in {store}; run setup on the first device"
    save_profile(marker["owner"], backend, store, remote if backend in (BACKEND_GIT, BACKEND_CLOUDFLARE) else None)
    return EXIT_OK, f"this device is now tied to {marker['owner']}'s knowledge store"


# ---------------------------------------------------------------- context

def repo_haystack(repo: Path) -> str:
    """Lowercased repo directory name plus its origin URL (when it has one)."""
    resolved: Path = repo.resolve()
    url: str = ""
    if resolved.is_dir():
        result = run_git(resolved, "remote", "get-url", REMOTE)
        url = result.stdout.strip() if result.returncode == 0 else ""
    return f"{resolved.name} {url}".lower()


def term_tokens(entry: dict[str, Any]) -> list[str]:
    return [token.lower() for token in [entry["key"], *entry["aliases"], *entry["tags"]] if len(token) >= MIN_TOKEN_CHARS]


def repo_matches(terms: list[dict[str, Any]], repo: Path) -> list[str]:
    haystack: str = repo_haystack(repo)
    return [entry["key"] for entry in terms if any(token in haystack for token in term_tokens(entry))]


def build_context(store: Path, repo: Path) -> dict[str, Any]:
    if not store.is_dir():
        return {"store": None, "preferences": [], "terms": [], "repo_matches": []}
    terms: list[dict[str, Any]] = read_entries(store, "term")
    return {
        "store": str(store), "preferences": read_entries(store, "preference"), "terms": terms,
        "repo_matches": repo_matches(terms, repo),
    }


def format_context(context: dict[str, Any]) -> str:
    if context["store"] is None:
        return "Personal knowledge: no store found (run knowledge.py init to create one)."
    lines: list[str] = [f"Personal knowledge ({context['store']})"]
    for title, rows in (("Preferences", context["preferences"]), ("Terms", context["terms"])):
        lines.append(f"{title}:" + ("" if rows else " none"))
        lines.extend(f"- {row['key']}: {row['value']}" for row in rows)
    if context["repo_matches"]:
        lines.append("Matches this repo: " + ", ".join(context["repo_matches"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def print_json(payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True))


def entry_line(entry: dict[str, Any]) -> str:
    return f"{entry['kind']}/{entry['key']}: {entry['value']}"


def missing_store(store: Path) -> int:
    print(f"knowledge store not found at {store}; run knowledge.py init", file=sys.stderr)
    return EXIT_NOT_FOUND


def default_owner() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return short_host()


def report_created(store: Path, owner: str, backend: str, code: int, notes: list[str]) -> int:
    print(f"knowledge store ready at {store} (owner {owner}, backend {backend})")
    for note in notes:
        print(note, file=sys.stderr if code else sys.stdout)
    return code


def cmd_init(args: argparse.Namespace) -> int:
    """Alias of `setup --backend git` that adopts an existing store or remote and never refuses."""
    store: Path = store_path()
    owner: str = (load_profile() or {}).get("owner") or default_owner()
    try:
        code, notes = create_store(store, owner, BACKEND_GIT, args.remote, adopt=True)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return EXIT_GIT
    return report_created(store, owner, BACKEND_GIT, code, notes)


def cmd_setup(args: argparse.Namespace) -> int:
    if args.backend == BACKEND_FOLDER and not args.path:
        raise ValueError("setup --backend folder needs --path DIR")
    if args.backend == BACKEND_CLOUDFLARE:
        if not args.url:
            raise ValueError("setup --backend cloudflare needs --url URL")
        args.remote = args.url
    store: Path = Path(args.path) if args.path else store_path()
    if (store / MARKER_FILE).exists() and not args.force:
        print(f"refused: {store} already holds a store ({MARKER_FILE}); use --force to replace it", file=sys.stderr)
        return EXIT_BAD_INPUT
    owner: str = args.owner or default_owner()
    try:
        code, notes = create_store(store, owner, args.backend, args.remote)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return EXIT_GIT
    if args.backend == BACKEND_CLOUDFLARE and not os.environ.get(ENV_CLOUDFLARE_TOKEN):
        print(TOKEN_NOTE, file=sys.stderr)
    return report_created(store, owner, args.backend, code, notes)


def cmd_join(args: argparse.Namespace) -> int:
    remote: str | None = args.url if args.backend == BACKEND_CLOUDFLARE else args.remote
    code, message = join_store(args.backend, remote, args.path)
    print(message, file=sys.stderr if code else sys.stdout)
    if code == EXIT_OK and args.backend == BACKEND_CLOUDFLARE and not os.environ.get(ENV_CLOUDFLARE_TOKEN):
        print(TOKEN_NOTE, file=sys.stderr)
    return code


def cmd_set(args: argparse.Namespace) -> int:
    entry: dict[str, Any] = write_entry(
        store_path(), args.key, args.value, args.kind, args.alias, args.tag, args.by or short_host(),
    )
    print(f"saved {entry['kind']}/{entry['key']}")
    return EXIT_OK


def cmd_get(args: argparse.Namespace) -> int:
    store: Path = store_path()
    if not store.is_dir():
        return missing_store(store)
    entry: dict[str, Any] | None = find_entry(store, args.name)
    if entry is None:
        print(f"not found: {args.name}", file=sys.stderr)
        return EXIT_NOT_FOUND
    print_json(entry) if args.json else print(entry["value"])
    return EXIT_OK


def matches_text(entry: dict[str, Any], needle: str) -> bool:
    haystack: list[str] = [entry["key"], entry["value"], *entry["aliases"], *entry["tags"]]
    return any(needle in text.lower() for text in haystack)


def print_entries(entries: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        print_json(entries)
    else:
        for entry in entries:
            print(entry_line(entry))


def cmd_find(args: argparse.Namespace) -> int:
    store: Path = store_path()
    if not store.is_dir():
        return missing_store(store)
    needle: str = args.text.lower()
    print_entries([entry for entry in read_entries(store, args.kind) if matches_text(entry, needle)], args.json)
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    store: Path = store_path()
    if not store.is_dir():
        return missing_store(store)
    print_entries(read_entries(store, args.kind), args.json)
    return EXIT_OK


def cmd_rm(args: argparse.Namespace) -> int:
    store: Path = store_path()
    key: str = clean_key(args.key)
    removed: bool = False
    for kind in KINDS:
        path: Path = entry_file(store, kind, key)
        if path.exists():
            path.unlink()
            removed = True
    if not removed:
        print(f"not found: {key}", file=sys.stderr)
        return EXIT_NOT_FOUND
    print(f"removed {key}")
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    store: Path = store_path()
    if not store.is_dir():
        return missing_store(store)
    return backend_for(load_profile()).sync(store)


def conflict_count(store: Path) -> int:
    return sum(1 for kind in KINDS for _ in (store / ENTRIES_DIR / kind).glob(f"*{CONFLICT_MARK}*{ENTRY_SUFFIX}"))


def cmd_status(args: argparse.Namespace) -> int:
    store: Path = store_path()
    profile: dict[str, Any] | None = load_profile()
    exists: bool = store.is_dir()
    counts: dict[str, int] = {kind: len(read_entries(store, kind)) if exists else 0 for kind in KINDS}
    report: dict[str, Any] = {
        "store": str(store), "exists": exists, "counts": counts, "remote": remote_url(store) if exists else None,
        "dirty": is_dirty(store) if exists else False, "conflicts": conflict_count(store) if exists else 0,
        "url": (profile or {}).get("remote") if (profile or {}).get("backend") == BACKEND_CLOUDFLARE else None,
        "owner": (profile or {}).get("owner") or ((read_marker(store) or {}).get("owner") if exists else None),
        "backend": (profile or {}).get("backend") or (BACKEND_GIT if exists and is_repo(store) else BACKEND_LOCAL),
    }
    if args.json:
        print_json(report)
        return EXIT_OK
    print(f"store: {report['store']} ({'exists' if exists else 'missing'})")
    print("entries: " + ", ".join(f"{kind}={count}" for kind, count in counts.items()))
    print(f"owner: {report['owner'] or 'unknown'}; backend: {report['backend']}")
    print(f"remote: {report['remote'] or 'none'}")
    if report["backend"] == BACKEND_CLOUDFLARE:
        print(f"url: {report['url']}")
    print(f"uncommitted changes: {'yes' if report['dirty'] else 'no'}")
    if report["conflicts"]:
        print(f"conflict copies to review: {report['conflicts']}")
    return EXIT_OK


def cmd_context(args: argparse.Namespace) -> int:
    context: dict[str, Any] = build_context(store_path(), Path(args.repo) if args.repo else Path.cwd())
    print_json(context) if args.json else print(format_context(context))
    return EXIT_OK


def add_kind(parser: argparse.ArgumentParser, default: str | None) -> None:
    parser.add_argument("--kind", choices=KINDS, default=default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal cross-device knowledge store.")
    commands = parser.add_subparsers(dest="command", required=True)
    init_cmd = commands.add_parser("init", help="create the store (optionally clone or attach a remote)")
    init_cmd.add_argument("--remote", default=None)
    init_cmd.set_defaults(run=cmd_init)
    setup_cmd = commands.add_parser("setup", help="create a NEW store and tie this device to it")
    setup_cmd.add_argument("--owner", default=None)
    setup_cmd.add_argument("--backend", choices=BACKEND_NAMES, required=True)
    setup_cmd.add_argument("--remote", default=None)
    setup_cmd.add_argument("--path", default=None)
    setup_cmd.add_argument("--url", default=None, help="cloudflare backend: Worker URL")
    setup_cmd.add_argument("--force", action="store_true")
    setup_cmd.set_defaults(run=cmd_setup)
    join_cmd = commands.add_parser("join", help="tie this device to an EXISTING store")
    join_cmd.add_argument("--backend", choices=(BACKEND_GIT, BACKEND_FOLDER, BACKEND_CLOUDFLARE), required=True)
    join_cmd.add_argument("--remote", default=None)
    join_cmd.add_argument("--path", default=None)
    join_cmd.add_argument("--url", default=None, help="cloudflare backend: Worker URL")
    join_cmd.set_defaults(run=cmd_join)
    set_cmd = commands.add_parser("set", help="write or overwrite an entry")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    add_kind(set_cmd, DEFAULT_KIND)
    set_cmd.add_argument("--alias", action="append", default=[])
    set_cmd.add_argument("--tag", action="append", default=[])
    set_cmd.add_argument("--by", default=None)
    set_cmd.set_defaults(run=cmd_set)
    get_cmd = commands.add_parser("get", help="read one entry by key or alias")
    get_cmd.add_argument("name")
    get_cmd.add_argument("--json", action="store_true")
    get_cmd.set_defaults(run=cmd_get)
    find_cmd = commands.add_parser("find", help="substring search over key, aliases, tags and value")
    find_cmd.add_argument("text")
    add_kind(find_cmd, None)
    find_cmd.add_argument("--json", action="store_true")
    find_cmd.set_defaults(run=cmd_find)
    list_cmd = commands.add_parser("list", help="list entries")
    add_kind(list_cmd, None)
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(run=cmd_list)
    rm_cmd = commands.add_parser("rm", help="delete an entry")
    rm_cmd.add_argument("key")
    rm_cmd.set_defaults(run=cmd_rm)
    commands.add_parser("sync", help="commit, merge with the remote, push").set_defaults(run=cmd_sync)
    status_cmd = commands.add_parser("status", help="store location, counts, remote, dirty flag")
    status_cmd.add_argument("--json", action="store_true")
    status_cmd.set_defaults(run=cmd_status)
    context_cmd = commands.add_parser("context", help="preferences and terms for the setup interview")
    context_cmd.add_argument("--repo", default=None)
    context_cmd.add_argument("--json", action="store_true")
    context_cmd.set_defaults(run=cmd_context)
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        return int(args.run(args))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
