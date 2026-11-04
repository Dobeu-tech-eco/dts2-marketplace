#!/usr/bin/env python3
"""Write the production scaffolding for a target app: a CI workflow built from .harness/config.yaml and
.harness/checks.sh, plus the runbook and ops notes that apply to the app type. Never overwrites a file."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

TEMPLATES: Final[Path] = Path(__file__).resolve().parent.parent / "templates"
CI_PATH: Final[str] = ".github/workflows/ci.yml"
CHECKS_PATH: Final[str] = ".harness/checks.sh"
CONFIG_PATH: Final[str] = ".harness/config.yaml"
COMMAND_KEYS: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "build")
SERVICES: Final[frozenset[str]] = frozenset({"web-app", "api"})
HOSTED: Final[frozenset[str]] = frozenset({"web-app", "api", "static-site"})
# template file -> (repo path, app types that get it)
OPS_FILES: Final[tuple[tuple[str, str, frozenset[str]], ...]] = (
    ("RUNBOOK.md", "RUNBOOK.md", SERVICES),
    ("ops/monitoring.md", "ops/monitoring.md", HOSTED),
    ("ops/backups.md", "ops/backups.md", SERVICES),
    ("ops/credential-handoff.md", "ops/credential-handoff.md", SERVICES),
    ("ops/rollback.md", "ops/rollback.md", HOSTED),
    ("ops/release.md", "ops/release.md", frozenset({"web-app", "api", "static-site", "cli", "library"})),
)
COMMAND_LINE: Final[re.Pattern[str]] = re.compile(r"^\s{2,}([a-z_]+):\s*(.*?)\s*$")
UNSAFE_COMMAND: Final[re.Pattern[str]] = re.compile(r"\$\{\{|[\r\n]")
SETUP_STEPS: Final[dict[str, str]] = {
    "node": (
        "      - uses: actions/setup-node@v4\n        with:\n          node-version: lts/*\n"
        "      - run: {install}\n"
    ),
    "python": (
        "      - uses: actions/setup-python@v5\n        with:\n          python-version: \"3.12\"\n"
        "      - run: {install}\n"
    ),
    "go": "      - uses: actions/setup-go@v5\n        with:\n          go-version-file: go.mod\n",
    "rust": "      - uses: dtolnay/rust-toolchain@stable\n",
    "none": "",
}


def detect_stack(repo: Path) -> str:
    for name, stack in (("package.json", "node"), ("pyproject.toml", "python"), ("requirements.txt", "python"),
                        ("go.mod", "go"), ("Cargo.toml", "rust")):
        if (repo / name).is_file():
            return stack
    return "none"


def node_install(repo: Path) -> str:
    if (repo / "pnpm-lock.yaml").is_file():
        return "corepack enable && pnpm install --frozen-lockfile"
    if (repo / "yarn.lock").is_file():
        return "corepack enable && yarn install --frozen-lockfile"
    if (repo / "package-lock.json").is_file():
        return "npm ci"
    return "npm install"


def python_install(repo: Path) -> str:
    if (repo / "requirements.txt").is_file():
        return "python -m pip install -r requirements.txt"
    return "python -m pip install -e ."


def setup_block(repo: Path, stack: str) -> str:
    if stack == "node":
        return SETUP_STEPS[stack].format(install=json.dumps(node_install(repo))).rstrip("\n")
    if stack == "python":
        return SETUP_STEPS[stack].format(install=json.dumps(python_install(repo))).rstrip("\n")
    return SETUP_STEPS.get(stack, "").rstrip("\n")


def read_commands(repo: Path) -> dict[str, str]:
    """Pull the `commands:` block out of config.yaml without a YAML library. Empty values are dropped."""
    path: Path = repo / CONFIG_PATH
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    inside: bool = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^commands:\s*$", line):
            inside = True
            continue
        if inside and line and not line[0].isspace():
            break
        match = COMMAND_LINE.match(line) if inside else None
        if match is None or match.group(1) not in COMMAND_KEYS:
            continue
        value: str = match.group(2).strip().strip("'\"")
        if value and value != "null" and not UNSAFE_COMMAND.search(value):
            found[match.group(1)] = value
    return found


def step(name: str, command: str) -> str:
    return f"      - name: {name}\n        run: {json.dumps(command)}"


def steps_block(repo: Path) -> str:
    commands: dict[str, str] = read_commands(repo)
    steps: list[str] = [step(key, commands[key]) for key in COMMAND_KEYS if key in commands]
    steps.append(step("repo checks", f"if [ -f {CHECKS_PATH} ]; then bash {CHECKS_PATH}; fi"))
    return "\n".join(steps)


def render_ci(repo: Path, stack: str) -> str:
    text: str = (TEMPLATES / "ci.yml").read_text(encoding="utf-8")
    setup: str = setup_block(repo, stack)
    text = text.replace("{{SETUP}}\n", setup + "\n" if setup else "")
    return text.replace("{{STEPS}}", steps_block(repo))


def write_new(repo: Path, rel: str, text: str, written: list[str], skipped: list[str]) -> None:
    target: Path = repo / rel
    if target.exists():
        skipped.append(rel)
        return
    atomic_write(target, text)
    written.append(rel)


def scaffold(repo: Path, app_type: str, *, with_ci: bool = True) -> dict[str, Any]:
    written: list[str] = []
    skipped: list[str] = []
    stack: str = detect_stack(repo)
    if with_ci:
        write_new(repo, CI_PATH, render_ci(repo, stack), written, skipped)
    for source, target, types in OPS_FILES:
        if app_type == "unknown" or app_type in types:
            write_new(repo, target, (TEMPLATES / source).read_text(encoding="utf-8"), written, skipped)
    return {"appType": app_type, "stack": stack, "written": written, "skipped": skipped}


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="repo root")
    parser.add_argument("--app-type", required=True, choices=["web-app", "api", "cli", "library", "static-site", "unknown"])
    parser.add_argument("--no-ci", action="store_true", help="skip .github/workflows/ci.yml")
    args: argparse.Namespace = parser.parse_args()
    repo: Path = Path(args.repo)
    if not repo.is_dir():
        sys.stderr.write(f"not a directory: {repo}\n")
        return 2
    json.dump(scaffold(repo, args.app_type, with_ci=not args.no_ci), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
