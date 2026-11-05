#!/usr/bin/env python3
"""G-87: a hash-chained journal and signed receipts, hashlib and hmac only.

Chain: each journal row is one JSON line `{"body": ..., "prev": <hash of the row before>, "hash": sha256(prev + canonical body)}`,
so editing, dropping or reordering a row breaks every hash after it. Signing: with a key, a row (and a receipt file) also gets
`sig` = HMAC-SHA256(key, hash). The key is held by the head in a file named by DTS2_PR_RECEIPT_KEY_FILE; the `DTS2_PR_`
prefix is denied to sons, so a son never sees the path, and the key file lives outside any son worktree. Without a key the
chain still detects accidental damage but not a forger who can rewrite the whole file.

Usage: receipts_sign.py append JOURNAL BODY_JSON | verify JOURNAL | sign FILE | check FILE SIG"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

KEY_FILE_VAR: Final[str] = "DTS2_PR_RECEIPT_KEY_FILE"
GENESIS: Final[str] = "0" * 64
EXIT_BAD: Final[int] = 1


class KeyUnreadable(Exception):
    """A key file is configured (DTS2_PR_RECEIPT_KEY_FILE is set) but cannot be read or is empty."""


def read_key(env: dict[str, str] | None = None) -> bytes | None:
    """The head's signing key; None only when no key file is configured (unsigned mode).
    Raises KeyUnreadable when one is configured but missing, unreadable or empty, so a broken key never falls back to unsigned."""
    path: str | None = (dict(os.environ) if env is None else env).get(KEY_FILE_VAR)
    if not path:
        return None
    try:
        key: bytes = Path(path).read_bytes().strip()
    except OSError as exc:
        raise KeyUnreadable(f"{KEY_FILE_VAR} names a key file that cannot be read: {exc.strerror or exc}") from exc
    if not key:
        raise KeyUnreadable(f"{KEY_FILE_VAR} names an empty key file")
    return key


def canonical(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def row_hash(prev: str, body: Any) -> str:
    return hashlib.sha256((prev + canonical(body)).encode("utf-8")).hexdigest()


def sign(digest: str, key: bytes) -> str:
    return hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row: Any = json.loads(line)
        except ValueError:
            row = {"corrupt": line}
        rows.append(row if isinstance(row, dict) else {"corrupt": line})
    return rows


def append(path: Path, body: Any, key: bytes | None = None) -> dict[str, Any]:
    """Add one row chained to the last; the row written."""
    rows: list[dict[str, Any]] = read_rows(path)
    prev: str = str(rows[-1].get("hash", GENESIS)) if rows else GENESIS
    row: dict[str, Any] = {"body": body, "prev": prev, "hash": row_hash(prev, body)}
    if key is not None:
        row["sig"] = sign(row["hash"], key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return row


def row_problem(row: dict[str, Any], prev: str, key: bytes | None) -> str | None:
    if "body" not in row or row.get("prev") != prev or row.get("hash") != row_hash(prev, row["body"]):
        return "hash chain broken"
    if key is not None and not hmac.compare_digest(str(row.get("sig", "")), sign(row["hash"], key)):
        return "signature missing or wrong"
    return None


def verify(path: Path, key: bytes | None = None) -> dict[str, Any]:
    """{ok, rows, broken_at, problem}. With a key every row must also carry a valid signature."""
    prev: str = GENESIS
    rows: list[dict[str, Any]] = read_rows(path)
    for index, row in enumerate(rows):
        problem: str | None = row_problem(row, prev, key)
        if problem:
            return {"ok": False, "rows": len(rows), "broken_at": index, "problem": problem}
        prev = str(row["hash"])
    return {"ok": True, "rows": len(rows), "broken_at": None, "problem": None}


def sign_file(path: Path, key: bytes) -> str:
    return sign(hashlib.sha256(path.read_bytes()).hexdigest(), key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    app_p = sub.add_parser("append")
    app_p.add_argument("journal")
    app_p.add_argument("body")
    sub.add_parser("verify").add_argument("journal")
    sub.add_parser("sign").add_argument("file")
    check_p = sub.add_parser("check")
    check_p.add_argument("file")
    check_p.add_argument("sig")
    args = parser.parse_args()
    try:
        key: bytes | None = read_key()
    except KeyUnreadable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD
    if args.command == "append":
        print(json.dumps(append(Path(args.journal), json.loads(args.body), key)))
        return 0
    if args.command == "verify":
        result: dict[str, Any] = verify(Path(args.journal), key)
        print(json.dumps(result))
        return 0 if result["ok"] else EXIT_BAD
    if key is None:
        print(f"no key: set {KEY_FILE_VAR} to the head's key file", file=sys.stderr)
        return EXIT_BAD
    if args.command == "sign":
        print(sign_file(Path(args.file), key))
        return 0
    good: bool = hmac.compare_digest(sign_file(Path(args.file), key), args.sig)
    print(json.dumps({"ok": good}))
    return 0 if good else EXIT_BAD


if __name__ == "__main__":
    sys.exit(main())
