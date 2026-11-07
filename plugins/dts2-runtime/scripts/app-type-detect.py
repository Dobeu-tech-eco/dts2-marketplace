#!/usr/bin/env python3
"""Detect what kind of app a repo is (web-app, api, cli, library, static-site) by file presence, and print the
production-readiness rows that apply to it. Reads files only; never runs anything from the repo."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

WEB_APP: Final[str] = "web-app"
API: Final[str] = "api"
CLI: Final[str] = "cli"
LIBRARY: Final[str] = "library"
STATIC_SITE: Final[str] = "static-site"
UNKNOWN: Final[str] = "unknown"
APP_TYPES: Final[tuple[str, ...]] = (WEB_APP, API, CLI, LIBRARY, STATIC_SITE)

GATE: Final[str] = "gate"
REPORT: Final[str] = "report"
STATUS_TODO: Final[str] = "todo"
STATUS_NA: Final[str] = "n/a"
ALL_TYPES: Final[tuple[str, ...]] = APP_TYPES
SERVICES: Final[tuple[str, ...]] = (WEB_APP, API)
HOSTED: Final[tuple[str, ...]] = (WEB_APP, API, STATIC_SITE)
SITES: Final[tuple[str, ...]] = (WEB_APP, STATIC_SITE)

# (row id, kind, evidence the verifier looks for, app types it applies to). Gate rows must be done or n/a before
# `done`; report rows are listed with whatever value exists and never block.
READINESS_ROWS: Final[tuple[tuple[str, str, str, tuple[str, ...]], ...]] = (
    ("ci", GATE, ".github/workflows/ci.yml", ALL_TYPES),
    ("release", GATE, "semver tag and changelog entry", ALL_TYPES),
    ("install-docs", GATE, "install, usage and exit codes in the README", (CLI, LIBRARY)),
    ("package-metadata", GATE, "name, version, license and entry point in the manifest", (CLI, LIBRARY)),
    ("runbook", GATE, "RUNBOOK.md", SERVICES),
    ("error-tracking", GATE, "ops/monitoring.md names the tool and where the DSN lives", SERVICES),
    ("uptime-check", GATE, "ops/monitoring.md names one check on a key route", HOSTED),
    ("alert-route", GATE, "ops/monitoring.md names who is paged and how", SERVICES),
    ("backups", GATE, "ops/backups.md schedule", SERVICES),
    ("restore-test", GATE, "ops/backups.md dated restore test", SERVICES),
    ("migration-safety", GATE, "expand/contract plan for schema changes", SERVICES),
    ("credential-handoff", GATE, "ops/credential-handoff.md", SERVICES),
    ("rollback", GATE, "ops/rollback.md", HOSTED),
    ("post-deploy-watch", GATE, "ops/rollback.md watch window", HOSTED),
    ("promotion", GATE, "ops/release.md preview, staging, production", HOSTED),
    ("feature-flag-hook", GATE, "ops/release.md flag hook for risky work", SERVICES),
    ("coverage", REPORT, "coverage percentage", (WEB_APP, API, CLI, LIBRARY)),
    ("a11y-axe", REPORT, "axe violations count", SITES),
    ("lighthouse", REPORT, "Lighthouse scores", SITES),
    ("sast-semgrep", REPORT, "semgrep findings count", ALL_TYPES),
    ("license-check", REPORT, "dependency license summary", ALL_TYPES),
    ("sbom", REPORT, "SBOM file path", ALL_TYPES),
    ("stride", REPORT, "STRIDE notes", SERVICES),
)

WEB_FRAMEWORKS: Final[frozenset[str]] = frozenset({
    "next", "react", "react-dom", "vue", "nuxt", "svelte", "@sveltejs/kit", "@remix-run/react", "solid-js",
    "@angular/core", "preact", "astro",
})
STATIC_GENERATORS: Final[frozenset[str]] = frozenset({
    "@11ty/eleventy", "vitepress", "@docusaurus/core", "gatsby", "hexo", "docsify-cli",
})
NODE_API: Final[frozenset[str]] = frozenset({
    "express", "fastify", "koa", "hono", "@nestjs/core", "@hapi/hapi", "restify", "@trpc/server",
})
PY_WEB: Final[tuple[str, ...]] = ("django",)
PY_API: Final[tuple[str, ...]] = ("fastapi", "flask", "starlette", "aiohttp", "sanic", "litestar", "tornado")
RUST_API: Final[tuple[str, ...]] = ("axum", "actix-web", "rocket", "warp", "poem")
GO_API: Final[tuple[str, ...]] = (
    "http.ListenAndServe", "http.HandleFunc", "http.NewServeMux", "gin-gonic/gin", "labstack/echo", "go-chi/chi", "gofiber/fiber",
    "http.Server{", "gorilla/mux", "julienschmidt/httprouter", "grpc.NewServer(")
STATIC_FILES: Final[tuple[str, ...]] = ("mkdocs.yml", "_config.yml", "hugo.toml", "hugo.yaml", "config.toml")
MAX_READ: Final[int] = 1_000_000


def read(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_READ).decode("utf-8", errors="replace")
    except OSError:
        return ""


def verdict(app_type: str, evidence: list[str]) -> dict[str, Any]:
    return {"appType": app_type, "evidence": evidence}


def node_dependencies(manifest: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section: Any = manifest.get(key)
        if isinstance(section, dict):
            names.update(str(name) for name in section)
    return names


def detect_node(repo: Path) -> dict[str, Any] | None:
    text: str = read(repo / "package.json")
    if not text:
        return None
    try:
        manifest: Any = json.loads(text)
    except ValueError:
        return None
    if not isinstance(manifest, dict):
        return None
    deps: set[str] = node_dependencies(manifest)
    runtime: Any = manifest.get("dependencies")
    runtime_names: set[str] = set(runtime) if isinstance(runtime, dict) else set()
    packaged: bool = bool(manifest.get("main") or manifest.get("exports") or manifest.get("module"))
    if packaged and not manifest.get("bin") and not deps & STATIC_GENERATORS:
        framework: set[str] = deps & (WEB_FRAMEWORKS | NODE_API)
        if framework and not framework & runtime_names:
            return verdict(LIBRARY, ["package.json main/exports; framework only in peer/dev deps"])
    for names, app_type in ((STATIC_GENERATORS, STATIC_SITE), (WEB_FRAMEWORKS, WEB_APP), (NODE_API, API)):
        hit: list[str] = sorted(deps & names)
        if hit:
            return verdict(app_type, [f"package.json dependency {hit[0]}"])
    if manifest.get("bin"):
        return verdict(CLI, ["package.json bin"])
    if manifest.get("main") or manifest.get("exports") or manifest.get("module"):
        return verdict(LIBRARY, ["package.json main/exports"])
    return None


def detect_python(repo: Path) -> dict[str, Any] | None:
    text: str = (read(repo / "pyproject.toml") + "\n" + read(repo / "requirements.txt")).lower()
    if not text.strip():
        return None
    for name in PY_WEB:
        if re.search(rf"(?<![\w-]){name}(?![\w-])", text):
            return verdict(WEB_APP, [f"python dependency {name}"])
    for name in PY_API:
        if re.search(rf"(?<![\w-]){name}(?![\w-])", text):
            return verdict(API, [f"python dependency {name}"])
    if re.search(r"^\[(project|tool\.poetry)\.scripts\]", text, re.MULTILINE):
        return verdict(CLI, ["pyproject scripts table"])
    if (repo / "pyproject.toml").is_file():
        return verdict(LIBRARY, ["pyproject.toml without scripts or web framework"])
    return None


def detect_rust(repo: Path) -> dict[str, Any] | None:
    text: str = read(repo / "Cargo.toml")
    if not text:
        return None
    for name in RUST_API:
        if re.search(rf"^{re.escape(name)}\s*=", text, re.MULTILINE):
            return verdict(API, [f"Cargo dependency {name}"])
    if (repo / "src" / "main.rs").is_file() or "[[bin]]" in text:
        return verdict(CLI, ["Cargo binary target"])
    return verdict(LIBRARY, ["Cargo crate without binary target"])


def detect_go(repo: Path) -> dict[str, Any] | None:
    mod: str = read(repo / "go.mod")
    if not mod:
        return None
    files: list[Path] = sorted(repo.glob("*.go"))
    if (repo / "cmd").is_dir():
        files += sorted((repo / "cmd").glob("*/*.go"))
    sources: str = "\n".join(read(path) for path in files)
    mod_lines: str = "\n".join(line for line in mod.splitlines() if "// indirect" not in line)
    for name in GO_API:
        if name in sources or name in mod_lines:
            return verdict(API, [f"go import {name}"])
    if re.search(r"^package main\b", sources, re.MULTILINE):
        return verdict(CLI, ["go main package"])
    return verdict(LIBRARY, ["go module without main package"])


def detect_static(repo: Path) -> dict[str, Any] | None:
    found: list[str] = [name for name in STATIC_FILES if (repo / name).is_file()]
    if found:
        return verdict(STATIC_SITE, [found[0]])
    if (repo / "index.html").is_file() or (repo / "public" / "index.html").is_file():
        return verdict(STATIC_SITE, ["index.html without a package manifest"])
    return None


def detect_type(repo: Path) -> dict[str, Any]:
    for probe in (detect_node, detect_python, detect_rust, detect_go, detect_static):
        found: dict[str, Any] | None = probe(repo)
        if found is not None:
            return found
    return verdict(UNKNOWN, [])


def rows_for(app_type: str) -> list[dict[str, str]]:
    """Every readiness row, with status `todo` when it applies to the type and `n/a` when it does not.
    An unknown type marks everything `todo` so nothing is silently skipped."""
    rows: list[dict[str, str]] = []
    for row_id, kind, evidence, applies in READINESS_ROWS:
        applicable: bool = app_type == UNKNOWN or app_type in applies
        rows.append({"row": row_id, "kind": kind, "evidence": evidence, "status": STATUS_TODO if applicable else STATUS_NA})
    return rows


def render_table(rows: list[dict[str, str]]) -> str:
    lines: list[str] = ["| row | kind | evidence | status |", "|---|---|---|---|"]
    lines += [f"| {r['row']} | {r['kind']} | {r['evidence']} | {r['status']} |" for r in rows]
    return "\n".join(lines) + "\n"


def detect(repo: Path, override: str | None = None) -> dict[str, Any]:
    found: dict[str, Any] = detect_type(repo)
    if override is not None:
        found = verdict(override, ["set by the user"])
    rows: list[dict[str, str]] = rows_for(found["appType"])
    found["gates"] = [r["row"] for r in rows if r["kind"] == GATE and r["status"] == STATUS_TODO]
    found["reportOnly"] = [r["row"] for r in rows if r["kind"] == REPORT and r["status"] == STATUS_TODO]
    found["rows"] = rows
    return found


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root to inspect")
    parser.add_argument("--type", choices=APP_TYPES, default=None, help="use this type instead of detecting it")
    parser.add_argument("--table", action="store_true", help="print the readiness table as markdown instead of JSON")
    args: argparse.Namespace = parser.parse_args()
    result: dict[str, Any] = detect(Path(args.repo), args.type)
    if args.table:
        sys.stdout.write(render_table(result["rows"]))
        return 0
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
