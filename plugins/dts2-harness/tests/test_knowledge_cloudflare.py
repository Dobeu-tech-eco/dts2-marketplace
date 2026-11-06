"""Tests for scripts/knowledge_cloudflare.py against a local fake of the Worker REST API."""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Final, Iterator
from unittest import mock

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import knowledge_cloudflare as kc  # noqa: E402

TOKEN: Final[str] = "test-bearer-value-123"
OLD: Final[str] = "2026-11-01T00:00:00Z"
NEW: Final[str] = "2026-11-05T00:00:00Z"


class FakeWorker(BaseHTTPRequestHandler):
    entries: dict[str, dict[str, Any]] = {}

    def log_message(self, *args: Any) -> None:
        return

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"error": "unauthorized"})
        path = self.path.split("?", 1)[0]
        if path == "/api/meta":
            return self._send(200, {"backend": "cloudflare-d1", "owner": "acme"})
        if path == "/api/entries" and method == "GET":
            return self._send(200, {"entries": list(self.entries.values())})
        key = path.removeprefix("/api/entries/")
        if method == "PUT":
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.entries[key] = body
            return self._send(200, body)
        if key not in self.entries:
            return self._send(404, {"error": "no entry"})
        if method == "DELETE":
            del self.entries[key]
            return self._send(200, {"deleted": key})
        return self._send(200, self.entries[key])

    def do_GET(self) -> None:
        self._handle("GET")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


def entry(key: str, value: str, updated: str, kind: str = "preference") -> dict[str, Any]:
    return {"key": key, "kind": kind, "value": value, "aliases": [], "tags": [], "updated": updated, "by": "laptop"}


@contextlib.contextmanager
def serve() -> Iterator[str]:
    FakeWorker.entries = {}
    server = HTTPServer(("127.0.0.1", 0), FakeWorker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.url = stack.enter_context(serve())
        self.tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.backend = kc.CloudflareBackend(self.url, TOKEN)

    def test_rejects_missing_or_wrong_token(self) -> None:
        for token in ("", "wrong"):
            with self.assertRaises(kc.BackendError) as ctx:
                kc.CloudflareBackend(self.url, token).list()
            self.assertIn("401", str(ctx.exception))

    def test_put_get_list_delete(self) -> None:
        self.backend.put(entry("agents.standard", "6 agents", NEW))
        self.assertEqual(self.backend.get("agents.standard")["value"], "6 agents")
        self.assertEqual([e["key"] for e in self.backend.list()], ["agents.standard"])
        self.assertIsNone(self.backend.get("missing"))
        self.assertTrue(self.backend.delete("agents.standard"))
        self.assertFalse(self.backend.delete("agents.standard"))
        self.assertEqual(self.backend.list(), [])

    def test_meta_and_describe_hide_token(self) -> None:
        self.assertEqual(self.backend.meta()["owner"], "acme")
        described = self.backend.describe()
        self.assertEqual(described["backend"], "cloudflare")
        self.assertTrue(described["token_set"])
        self.assertNotIn(TOKEN, json.dumps(described))

    def test_sync_pulls_new_remote_entries(self) -> None:
        FakeWorker.entries["style"] = entry("style", "terse", NEW, kind="term")
        self.assertEqual(self.backend.sync(self.tmp), 1)
        parsed = kc.parse_entry((self.tmp / "entries" / "term" / "style.md").read_text())
        self.assertEqual(parsed["value"], "terse")
        self.assertEqual(parsed["updated"], NEW)

    def test_sync_newer_wins_in_both_directions(self) -> None:
        FakeWorker.entries["remote.wins"] = entry("remote.wins", "remote new", NEW)
        FakeWorker.entries["local.wins"] = entry("local.wins", "remote old", OLD)
        FakeWorker.entries["tie"] = entry("tie", "remote tie", NEW)
        kc.write_local(self.tmp, entry("remote.wins", "local old", OLD), None)
        kc.write_local(self.tmp, entry("local.wins", "local new", NEW), None)
        kc.write_local(self.tmp, entry("tie", "local tie", NEW), None)
        kc.write_local(self.tmp, entry("only.local", "fresh", NEW), None)
        self.assertEqual(self.backend.sync(self.tmp), 3)
        local = kc.read_local(self.tmp)
        self.assertEqual(local["remote.wins"][0]["value"], "remote new")
        self.assertEqual(local["tie"][0]["value"], "local tie")
        self.assertEqual(FakeWorker.entries["local.wins"]["value"], "local new")
        self.assertEqual(FakeWorker.entries["only.local"]["value"], "fresh")
        self.assertEqual(FakeWorker.entries["tie"]["value"], "remote tie")

    def test_sync_moves_entry_when_remote_kind_changes(self) -> None:
        kc.write_local(self.tmp, entry("shift", "v", OLD, kind="preference"), None)
        FakeWorker.entries["shift"] = entry("shift", "v", NEW, kind="term")
        self.backend.sync(self.tmp)
        self.assertFalse((self.tmp / "entries" / "preference" / "shift.md").exists())
        self.assertTrue((self.tmp / "entries" / "term" / "shift.md").exists())

    def test_sync_ignores_invalid_remote_keys(self) -> None:
        FakeWorker.entries["bad"] = entry("../escape", "x", NEW)
        self.assertEqual(self.backend.sync(self.tmp), 0)
        self.assertFalse((self.tmp.parent / "escape.md").exists())

    def test_token_never_written_to_store(self) -> None:
        FakeWorker.entries["a"] = entry("a", "alpha", NEW)
        kc.write_local(self.tmp, entry("b", "beta", NEW), None)
        self.backend.sync(self.tmp)
        for path in self.tmp.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN, path.read_text())


class CliTest(unittest.TestCase):
    def test_requires_token_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(kc.main(["--url", "http://127.0.0.1:1", "ping"]), kc.EXIT_BAD_INPUT)

    def test_pull_and_unreachable(self) -> None:
        with serve() as url, tempfile.TemporaryDirectory() as tmp:
            FakeWorker.entries["a"] = entry("a", "alpha", NEW)
            with mock.patch.dict(os.environ, {kc.ENV_TOKEN: TOKEN}):
                self.assertEqual(kc.main(["--url", url, "pull", tmp]), kc.EXIT_OK)
            self.assertTrue((Path(tmp) / "entries" / "preference" / "a.md").exists())
            self.assertEqual(os.listdir(tmp), ["entries"])
        with mock.patch.dict(os.environ, {kc.ENV_TOKEN: TOKEN}):
            self.assertEqual(kc.main(["--url", "http://127.0.0.1:1", "ping"]), kc.EXIT_UNREACHABLE)


if __name__ == "__main__":
    unittest.main()
