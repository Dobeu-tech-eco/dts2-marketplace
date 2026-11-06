#!/usr/bin/env python3
"""Client for the Cloudflare-hosted personal knowledge store (templates/knowledge-cloudflare).

The bearer token comes only from the environment (DTS2_KNOWLEDGE_TOKEN) and is never written to disk. The store
directory uses the same entry-file layout as scripts/knowledge.py: <store>/entries/<kind>/<key>.md.

Library: CloudflareBackend (list / get / put / delete / context / meta / sync / describe).
CLI: python3 knowledge_cloudflare.py --url URL ping|list|pull STORE (manual testing)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

ENV_TOKEN: Final[str] = "DTS2_KNOWLEDGE_TOKEN"
ENCODING: Final[str] = "utf-8"
TIMEOUT_SECONDS: Final[float] = 20.0
KINDS: Final[tuple[str, ...]] = ("preference", "term", "learning")
KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
CONFLICT_MARK: Final[str] = ".conflict-"
FRONT_FENCE: Final[str] = "---"
EXIT_OK: Final[int] = 0
EXIT_BAD_INPUT: Final[int] = 2
EXIT_UNREACHABLE: Final[int] = 3
Entry = dict[str, Any]


class BackendError(Exception):
    """The remote store refused or could not answer a request."""


def now_stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_text(entry: Entry) -> str:
    """Serialize an entry to the front-matter file format shared with knowledge.py."""
    head = [
        FRONT_FENCE,
        f"key: {entry['key']}",
        f"kind: {entry['kind']}",
        f"aliases: {json.dumps(list(entry.get('aliases') or []), ensure_ascii=False)}",
        f"tags: {json.dumps(list(entry.get('tags') or []), ensure_ascii=False)}",
        f"updated: {entry['updated']}",
        f"by: {entry.get('by') or ''}",
        FRONT_FENCE,
    ]
    return "\n".join(head) + "\n" + str(entry["value"]).strip() + "\n"


def parse_entry(text: str) -> Entry | None:
    """Parse an entry file; None when it is not a valid entry."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONT_FENCE:
        return None
    try:
        end = lines.index(FRONT_FENCE, 1)
    except ValueError:
        return None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        name, sep, rest = line.partition(":")
        if sep:
            meta[name.strip()] = rest.strip()
    key, kind = meta.get("key", ""), meta.get("kind", "")
    if not KEY_PATTERN.match(key) or kind not in KINDS:
        return None
    return {
        "key": key,
        "kind": kind,
        "value": "\n".join(lines[end + 1:]).strip(),
        "aliases": _json_list(meta.get("aliases", "[]")),
        "tags": _json_list(meta.get("tags", "[]")),
        "updated": meta.get("updated", ""),
        "by": meta.get("by", ""),
    }


def _json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def read_local(store: Path) -> dict[str, tuple[Entry, Path]]:
    """Every valid local entry by key, with its file path. Conflict copies are ignored."""
    found: dict[str, tuple[Entry, Path]] = {}
    for kind in KINDS:
        for path in sorted((store / "entries" / kind).glob("*.md")):
            if CONFLICT_MARK in path.name:
                continue
            entry = parse_entry(path.read_text(encoding=ENCODING))
            if entry and entry["kind"] == kind and path.stem == entry["key"]:
                found[entry["key"]] = (entry, path)
    return found


def write_local(store: Path, entry: Entry, old_path: Path | None) -> None:
    target = store / "entries" / entry["kind"] / f"{entry['key']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry_text(entry), encoding=ENCODING)
    if old_path is not None and old_path != target and old_path.exists():
        old_path.unlink()


def clean_entry(raw: Any) -> Entry | None:
    """Validate an entry received from the remote; None when it must not be written locally."""
    if not isinstance(raw, dict):
        return None
    key, kind, value = raw.get("key"), raw.get("kind"), raw.get("value")
    if not isinstance(key, str) or not KEY_PATTERN.match(key) or kind not in KINDS or not isinstance(value, str):
        return None
    return {
        "key": key,
        "kind": kind,
        "value": value,
        "aliases": [str(x) for x in raw.get("aliases") or []],
        "tags": [str(x) for x in raw.get("tags") or []],
        "updated": str(raw.get("updated") or ""),
        "by": str(raw.get("by") or ""),
    }


class CloudflareBackend:
    name = "cloudflare"

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self._token = token

    @classmethod
    def from_env(cls, url: str) -> "CloudflareBackend":
        return cls(url, os.environ.get(ENV_TOKEN, ""))

    def _request(self, method: str, path: str, body: Entry | None = None) -> Any:
        data = json.dumps(body).encode(ENCODING) if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode(ENCODING) or "null")
        except urllib.error.HTTPError as err:
            raise BackendError(f"{method} {path}: HTTP {err.code} {_error_text(err)}") from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise BackendError(f"{method} {path}: {err}") from err

    def list(self, kind: str | None = None, q: str | None = None) -> list[Entry]:
        query = urllib.parse.urlencode({k: v for k, v in (("kind", kind), ("q", q)) if v})
        reply = self._request("GET", "/api/entries" + (f"?{query}" if query else ""))
        return [e for e in (clean_entry(raw) for raw in (reply or {}).get("entries", [])) if e]

    def get(self, key: str) -> Entry | None:
        try:
            return clean_entry(self._request("GET", "/api/entries/" + urllib.parse.quote(key, safe="")))
        except BackendError as err:
            if "HTTP 404" in str(err):
                return None
            raise

    def put(self, entry: Entry) -> Entry:
        path = "/api/entries/" + urllib.parse.quote(entry["key"], safe="")
        saved = clean_entry(self._request("PUT", path, entry))
        if saved is None:
            raise BackendError("PUT: malformed reply")
        return saved

    def delete(self, key: str) -> bool:
        try:
            self._request("DELETE", "/api/entries/" + urllib.parse.quote(key, safe=""))
        except BackendError as err:
            if "HTTP 404" in str(err):
                return False
            raise
        return True

    def context(self, repo: str) -> dict[str, Any]:
        reply = self._request("GET", "/api/context?" + urllib.parse.urlencode({"repo": repo}))
        return reply if isinstance(reply, dict) else {}

    def meta(self) -> dict[str, Any]:
        reply = self._request("GET", "/api/meta")
        return reply if isinstance(reply, dict) else {}

    def sync(self, store: Path) -> int:
        """Pull remote entries into the store, then push local ones that are newer. Newer `updated` wins.

        Returns how many entries changed (written locally plus sent to the remote). Deletions do not propagate."""
        remote = {e["key"]: e for e in self.list()}
        local = read_local(Path(store))
        changed = 0
        for key, theirs in remote.items():
            mine = local.get(key)
            if mine is None or theirs["updated"] > mine[0]["updated"]:
                write_local(Path(store), theirs, mine[1] if mine else None)
                changed += 1
        for key, (mine, _path) in local.items():
            theirs = remote.get(key)
            if theirs is None or mine["updated"] > theirs["updated"]:
                self.put(mine)
                changed += 1
        return changed

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "url": self.url, "token_set": bool(self._token), "token_env": ENV_TOKEN}


def _error_text(err: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(err.read().decode(ENCODING))
        return str(payload.get("error", "")) if isinstance(payload, dict) else ""
    except (ValueError, OSError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--url", required=True, help="Worker base URL, e.g. https://dts2-knowledge.acme.workers.dev")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping", help="check the URL and token")
    sub.add_parser("list", help="print remote entries as JSON")
    pull = sub.add_parser("pull", help="sync a local store directory with the remote")
    pull.add_argument("store", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not os.environ.get(ENV_TOKEN):
        print(f"set {ENV_TOKEN} in the environment first", file=sys.stderr)
        return EXIT_BAD_INPUT
    backend = CloudflareBackend.from_env(args.url)
    try:
        if args.command == "ping":
            print(json.dumps(backend.meta(), indent=2))
        elif args.command == "list":
            print(json.dumps(backend.list(), indent=2))
        else:
            print(f"synced {backend.sync(args.store)} entries")
    except BackendError as err:
        print(f"error: {err}", file=sys.stderr)
        return EXIT_UNREACHABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
