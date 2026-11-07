#!/usr/bin/env python3
"""Playwright fallback for the post-merge walkthrough (B10), used when no browser tool is available to the verifier.

It runs only with the sandbox on (`sandbox.enabled` is not false in .harness/config.yaml) and only against hosts listed in
`walkthrough: allowed_hosts:` (comma-separated; `*.example.com` matches subdomains, not the apex). A URL must be http or https
with no credentials: file://, data:, javascript: and the rest are refused, and every sub-request the page makes is checked
against the same allowlist and aborted when it is off it. A screenshot of each screen lands in --out and in the report section.
Playwright is optional: without it the run is skipped, never failed.

  walkthrough_fallback.py --out DIR --url URL [--url URL ...] [--cwd DIR]    prints one JSON object; exit 2 when not ok
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Final
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_call import read_block  # noqa: E402
from son_launch import sandbox_config  # noqa: E402

BLOCK: Final[str] = "walkthrough"
ALLOW_FIELD: Final[str] = "allowed_hosts"
SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
NAV_TIMEOUT_MS: Final[int] = 30_000
SECTION: Final[str] = "### Post-merge walkthrough (Playwright fallback)"
Driver = Callable[[str, Path, tuple[str, ...]], dict[str, Any]]


def read_allowlist(cwd: Path) -> tuple[str, ...]:
    raw: str = read_block(cwd, BLOCK).get(ALLOW_FIELD, "")
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def sandbox_problem(cwd: Path) -> str | None:
    return None if sandbox_config(cwd)["enabled"] else "sandbox is off (sandbox.enabled: false); the fallback runs only in sandbox mode"


def host_allowed(host: str, allow: tuple[str, ...]) -> bool:
    for entry in allow:
        if entry.startswith("*."):
            if host.endswith(entry[1:]) and host != entry[2:]:
                return True
        elif host == entry:
            return True
    return False


def check_url(url: str, allow: tuple[str, ...]) -> str | None:
    """None when the walkthrough may open `url`, else the reason it may not. Never opens anything."""
    try:
        parts = urlsplit(url.strip())
        host: str = (parts.hostname or "").lower()
    except ValueError:
        return "not a valid URL"
    if parts.scheme.lower() not in SCHEMES:
        return f"scheme {parts.scheme or '(none)'!r} is not allowed; only http and https"
    if "@" in parts.netloc:
        return "URL carries credentials"
    if not host_allowed(host, allow):
        return f"host {host or '(none)'} is not in walkthrough.allowed_hosts"
    return None


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def slug(url: str) -> str:
    parts = urlsplit(url)
    return re.sub(r"[^a-z0-9]+", "-", f"{parts.hostname}{parts.path}".lower()).strip("-")[:60] or "page"


def playwright_driver(url: str, shot: Path, allow: tuple[str, ...]) -> dict[str, Any]:
    """Open `url` in headless Chromium, abort every request off the allowlist, and save a full-page screenshot."""
    from playwright.sync_api import sync_playwright  # imported here: Playwright is optional
    blocked: list[str] = []

    def guard(route: Any) -> None:
        if check_url(route.request.url, allow) is None:
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False)
            context.route("**/*", guard)
            page = context.new_page()
            response = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
            page.screenshot(path=str(shot), full_page=True)
            return {"status": response.status if response else None, "title": page.title(), "blocked": blocked}
        finally:
            browser.close()


def run_walkthrough(cwd: Path, urls: list[str], out_dir: Path, driver: Driver | None = None) -> dict[str, Any]:
    problem: str | None = sandbox_problem(cwd)
    if problem:
        return {"ok": False, "skipped": problem, "screens": [], "refused": []}
    allow: tuple[str, ...] = read_allowlist(cwd)
    if not allow:
        return {"ok": False, "skipped": "no walkthrough.allowed_hosts in .harness/config.yaml", "screens": [], "refused": []}
    refused: list[dict[str, str]] = []
    wanted: list[str] = []
    for url in urls:
        why: str | None = check_url(url, allow)
        refused.append({"url": url, "problem": why}) if why else wanted.append(url)
    if not wanted:
        return {"ok": False, "screens": [], "refused": refused}
    use: Driver | None = driver
    if use is None:
        if not playwright_available():
            return {"ok": False, "skipped": "playwright is not installed (pip install playwright && playwright install chromium)",
                    "screens": [], "refused": refused}
        use = playwright_driver
    out_dir.mkdir(parents=True, exist_ok=True)
    screens: list[dict[str, Any]] = []
    for number, url in enumerate(wanted, 1):
        shot: Path = out_dir / f"fallback-{number:02d}-{slug(url)}.png"
        try:
            info: dict[str, Any] = use(url, shot, allow)
            screens.append({"url": url, "file": str(shot), "status": info.get("status"), "title": info.get("title"),
                            "blocked": info.get("blocked", [])})
        except Exception as exc:  # one broken screen must not hide the others
            screens.append({"url": url, "file": None, "error": str(exc)})
    ok: bool = all(s.get("file") and (s.get("status") or 200) < 400 for s in screens)
    return {"ok": ok, "screens": screens, "refused": refused}


def report_section(result: dict[str, Any]) -> str:
    """Markdown for the receipt: one screenshot per screen, what failed, what was refused or blocked."""
    if result.get("skipped"):
        return f"{SECTION}\n\n- skipped: {result['skipped']}\n"
    lines: list[str] = [SECTION, ""]
    for screen in result["screens"]:
        if screen.get("file"):
            lines += [f"- {screen['url']}: HTTP {screen.get('status')}, {screen.get('title') or 'untitled'}",
                      f"  ![{screen['url']}]({screen['file']})"]
            lines += [f"  - blocked request: {b}" for b in screen.get("blocked", [])]
        else:
            lines.append(f"- {screen['url']}: FAIL {screen.get('error')}")
    lines += [f"- refused {r['url']}: {r['problem']}" for r in result.get("refused", [])]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--url", action="append", default=[], required=True)
    args = parser.parse_args()
    result: dict[str, Any] = run_walkthrough(Path(args.cwd), args.url, Path(args.out))
    result["report"] = report_section(result)
    print(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
