#!/usr/bin/env python3
"""Detect how a repo deploys, by file presence only. Never runs the check command."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

PROVIDER_FILES: Final[tuple[tuple[str, tuple[str, ...], str | None], ...]] = (
    ("vercel", ("vercel.json", ".vercel/project.json"), "vercel ls --prod"),
    ("cloudflare", ("wrangler.toml", "wrangler.jsonc", "wrangler.json"), "wrangler deployments list"),
    ("netlify", ("netlify.toml",), "netlify status"),
    ("fly", ("fly.toml",), "fly status"),
    ("render", ("render.yaml",), None),
    ("firebase", ("firebase.json",), "firebase hosting:channel:list"),
)
DEPLOY_COMMANDS: Final[dict[str, str]] = {
    "vercel": "vercel --prod",
    "cloudflare": "wrangler deploy",
    "netlify": "netlify deploy --prod",
    "fly": "fly deploy",
    "github-workflow": "gh workflow run <file>",
}
PRODUCTION_PLANS: Final[dict[str, list[str]]] = {
    "nextjs": ["vercel", "cloudflare-pages"],
    "react": ["vercel", "cloudflare-pages"],
    "static": ["vercel", "cloudflare-pages"],
    "node-api": ["fly", "render"],
    "python-api": ["fly", "render"],
    "docker": ["fly", "render"],
    "supabase": ["vercel"],
    "workers": ["cloudflare"],
}
WORKFLOW_GLOBS: Final[tuple[str, ...]] = ("*.yml", "*.yaml")
WORKFLOW_DIR: Final[str] = ".github/workflows"
WORKFLOW_CHECK: Final[str] = "gh run list --workflow {name} --limit 1"
END_STATE_PATH: Final[str] = ".harness/end-state.md"
URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?:-\s*)?productionUrl:\s*(\S+)\s*$", re.MULTILINE)
NULL_VALUES: Final[frozenset[str]] = frozenset({"null", "none", "<url|null>", ""})


def result(provider: str, evidence: list[str], url: str | None, command: str | None) -> dict[str, Any]:
    return {"provider": provider, "evidence": evidence, "productionUrl": url, "checkCommand": command}


def read_production_url(repo: Path) -> str | None:
    path: Path = repo / END_STATE_PATH
    if not path.is_file():
        return None
    match: re.Match[str] | None = URL_PATTERN.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None or match.group(1).lower() in NULL_VALUES:
        return None
    return match.group(1)


def find_provider(repo: Path) -> tuple[str, list[str], str | None] | None:
    for provider, names, command in PROVIDER_FILES:
        found: list[str] = [name for name in names if (repo / name).is_file()]
        if found:
            return provider, found, command
    return None


def find_workflow(repo: Path) -> tuple[list[str], str] | None:
    workflow_dir: Path = repo / WORKFLOW_DIR
    for path in sorted(p for glob in WORKFLOW_GLOBS for p in workflow_dir.glob(glob)):
        if "deploy" in path.read_text(encoding="utf-8", errors="replace").lower():
            return [f"{WORKFLOW_DIR}/{path.name}"], WORKFLOW_CHECK.format(name=path.name)
    return None


def detect(repo: Path) -> dict[str, Any]:
    url: str | None = read_production_url(repo)
    provider = find_provider(repo)
    if provider is not None:
        return result(provider[0], provider[1], url, provider[2])
    workflow = find_workflow(repo)
    if workflow is not None:
        return result("github-workflow", workflow[0], url, workflow[1])
    return result("none", [], url, None)


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root to inspect")
    args: argparse.Namespace = parser.parse_args()
    json.dump(detect(Path(args.repo)), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
