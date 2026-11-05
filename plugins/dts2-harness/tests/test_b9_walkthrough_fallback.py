"""B10: the Playwright fallback for the post-merge walkthrough (scripts/walkthrough_fallback.py). Playwright itself is optional."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import walkthrough_fallback as wf  # noqa: E402

CLI: Final[Path] = SCRIPTS / "walkthrough_fallback.py"
ALLOW: Final[tuple[str, ...]] = ("app.example.com", "*.preview.example.com")
HAS_PLAYWRIGHT: Final[bool] = importlib.util.find_spec("playwright") is not None


class UrlTests(unittest.TestCase):
    def test_allowed_hosts(self) -> None:
        self.assertIsNone(wf.check_url("https://app.example.com/dashboard?x=1", ALLOW))
        self.assertIsNone(wf.check_url("http://pr-4.preview.example.com/", ALLOW))
        self.assertIsNone(wf.check_url("https://APP.example.com/", ALLOW))

    def test_refuses_file_and_other_schemes(self) -> None:
        for url in ("file:///etc/passwd", "file://app.example.com/x", "data:text/html,hi", "javascript:alert(1)",
                    "ftp://app.example.com/", "chrome://settings", "about:blank", "//app.example.com/x"):
            self.assertIsNotNone(wf.check_url(url, ALLOW), url)

    def test_refuses_hosts_off_the_allowlist(self) -> None:
        for url in ("https://evil.example.org/", "https://app.example.com.evil.org/", "https://preview.example.com/",
                    "https://example.com/", "http://127.0.0.1:8080/", "http://localhost/", "http://169.254.169.254/latest"):
            self.assertIsNotNone(wf.check_url(url, ALLOW), url)

    def test_refuses_credentials_in_the_url(self) -> None:
        self.assertIn("credentials", wf.check_url("https://user:pw@app.example.com/", ALLOW) or "")

    def test_empty_allowlist_refuses_everything(self) -> None:
        self.assertIsNotNone(wf.check_url("https://app.example.com/", ()))

    def test_localhost_only_when_listed(self) -> None:
        self.assertIsNone(wf.check_url("http://localhost:3000/", ("localhost",)))


class ConfigTests(unittest.TestCase):
    def test_allowlist_and_sandbox_come_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(wf.read_allowlist(repo), ())
            (repo / ".harness").mkdir()
            (repo / ".harness" / "config.yaml").write_text(
                "walkthrough:\n  allowed_hosts: app.example.com, *.preview.example.com  # prod and previews\n", encoding="utf-8")
            self.assertEqual(wf.read_allowlist(repo), ("app.example.com", "*.preview.example.com"))
            self.assertIsNone(wf.sandbox_problem(repo))
            (repo / ".harness" / "config.yaml").write_text("sandbox:\n  enabled: false\nwalkthrough:\n  allowed_hosts: a.com\n",
                                                          encoding="utf-8")
            self.assertIn("sandbox", wf.sandbox_problem(repo) or "")


def fake_driver(url: str, shot: Path, allow: tuple[str, ...]) -> dict[str, Any]:
    shot.write_bytes(b"\x89PNG fake")
    return {"status": 200, "title": "Fake", "blocked": []}


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / ".harness").mkdir(parents=True)
        self.out = Path(self.tmp.name) / "shots"
        self.addCleanup(self.tmp.cleanup)

    def config(self, text: str) -> None:
        (self.repo / ".harness" / "config.yaml").write_text(text, encoding="utf-8")

    def test_screenshots_are_saved_and_reported(self) -> None:
        self.config("walkthrough:\n  allowed_hosts: app.example.com\n")
        result = wf.run_walkthrough(self.repo, ["https://app.example.com/", "https://app.example.com/pricing"], self.out, driver=fake_driver)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["screens"]), 2)
        for screen in result["screens"]:
            self.assertTrue(Path(screen["file"]).is_file())
            self.assertTrue(Path(screen["file"]).name.endswith(".png"))
        section = wf.report_section(result)
        self.assertIn("![", section)
        self.assertIn(result["screens"][0]["file"], section)

    def test_sandbox_off_skips_without_touching_anything(self) -> None:
        self.config("sandbox:\n  enabled: false\nwalkthrough:\n  allowed_hosts: app.example.com\n")
        result = wf.run_walkthrough(self.repo, ["https://app.example.com/"], self.out, driver=fake_driver)
        self.assertFalse(result["ok"])
        self.assertIn("sandbox", result["skipped"])
        self.assertFalse(self.out.exists())

    def test_no_allowlist_skips(self) -> None:
        result = wf.run_walkthrough(self.repo, ["https://app.example.com/"], self.out, driver=fake_driver)
        self.assertFalse(result["ok"])
        self.assertIn("allowed_hosts", result["skipped"])

    def test_refused_urls_never_reach_the_driver(self) -> None:
        self.config("walkthrough:\n  allowed_hosts: app.example.com\n")
        seen: list[str] = []

        def spy(url: str, shot: Path, allow: tuple[str, ...]) -> dict[str, Any]:
            seen.append(url)
            return fake_driver(url, shot, allow)

        result = wf.run_walkthrough(self.repo, ["file:///etc/passwd", "https://app.example.com/", "https://evil.org/"], self.out, driver=spy)
        self.assertEqual(seen, ["https://app.example.com/"])
        self.assertEqual([r["url"] for r in result["refused"]], ["file:///etc/passwd", "https://evil.org/"])
        self.assertTrue(result["ok"])
        self.assertIn("refused", wf.report_section(result))

    def test_only_refused_urls_is_not_ok(self) -> None:
        self.config("walkthrough:\n  allowed_hosts: app.example.com\n")
        result = wf.run_walkthrough(self.repo, ["file:///etc/passwd"], self.out, driver=fake_driver)
        self.assertFalse(result["ok"])
        self.assertEqual(result["screens"], [])

    def test_a_driver_crash_is_reported_per_screen(self) -> None:
        self.config("walkthrough:\n  allowed_hosts: app.example.com\n")

        def boom(url: str, shot: Path, allow: tuple[str, ...]) -> dict[str, Any]:
            raise RuntimeError("navigation failed")

        result = wf.run_walkthrough(self.repo, ["https://app.example.com/"], self.out, driver=boom)
        self.assertFalse(result["ok"])
        self.assertIn("navigation failed", result["screens"][0]["error"])

    def test_missing_playwright_skips_cleanly(self) -> None:
        self.config("walkthrough:\n  allowed_hosts: app.example.com\n")
        original = wf.playwright_available
        wf.playwright_available = lambda: False  # type: ignore[assignment]
        try:
            result = wf.run_walkthrough(self.repo, ["https://app.example.com/"], self.out)
        finally:
            wf.playwright_available = original  # type: ignore[assignment]
        self.assertFalse(result["ok"])
        self.assertIn("playwright", result["skipped"].lower())

    def test_cli_skips_cleanly_without_config(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "--out", str(self.out),
                               "--url", "https://app.example.com/"], capture_output=True, text=True, check=False)
        out = json.loads(done.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("skipped", out)
        self.assertEqual(done.returncode, 2)


class Quiet(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html><title>Local</title><body><h1>hello</h1><img src='http://127.0.0.2:9/x.png'></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return


@unittest.skipUnless(HAS_PLAYWRIGHT, "playwright is not installed")
class PlaywrightTests(unittest.TestCase):
    def test_real_screenshot_and_off_allowlist_request_is_blocked(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "a.png"
            try:
                info = wf.playwright_driver(f"http://127.0.0.1:{server.server_port}/", shot, ("127.0.0.1",))
            except Exception as exc:  # browser binaries missing is an environment gap, not a failure
                self.skipTest(f"chromium unavailable: {exc}")
            self.assertTrue(shot.is_file())
            self.assertEqual(info["status"], 200)
            self.assertTrue(any("127.0.0.2" in b for b in info["blocked"]))


if __name__ == "__main__":
    unittest.main()
