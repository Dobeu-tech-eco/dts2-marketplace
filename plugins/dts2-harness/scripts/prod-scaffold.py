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
YAML_NULLS: Final[frozenset[str]] = frozenset({"~", "null", "Null", "NULL"})
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


def _scalar(raw: str) -> str | None:
    """Parse one YAML scalar: double-quoted (JSON escapes), single-quoted ('' escape) or plain."""
    raw = raw.strip()
    if raw.startswith('"'):
        index: int = 1
        while index < len(raw):
            if raw[index] == "\\":
                index += 2
                continue
            if raw[index] == '"':
                break
            index += 1
        else:
            return None
        rest: str = raw[index + 1:]
        if rest.strip() and not re.match(r"^\s+#", rest):
            return None
        try:
            decoded: Any = json.loads(raw[: index + 1])
        except ValueError:
            return None
        return decoded if isinstance(decoded, str) else None
    if raw.startswith("'"):
        index = 1
        while index < len(raw):
            if raw[index] == "'":
                if raw[index + 1:index + 2] == "'":
                    index += 2
                    continue
                break
            index += 1
        else:
            return None
        rest = raw[index + 1:]
        if rest.strip() and not re.match(r"^\s+#", rest):
            return None
        return raw[1:index].replace("''", "'")
    if raw.startswith("#"):
        return ""
    plain: str = re.sub(r"\s+#.*$", "", raw).strip()
    return "" if plain in YAML_NULLS else plain


def read_commands(repo: Path, dropped: list[dict[str, str]] | None = None) -> dict[str, str]:
    """Pull the `commands:` block out of config.yaml without a YAML library. Empty values are dropped;
    unsafe ones are dropped and reported through `dropped`."""
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
        raw: str = match.group(2).strip()
        if raw[:1] in ("'", '"'):
            parsed: str | None = _scalar(raw)
            if parsed is None:
                if dropped is not None:
                    dropped.append({"key": match.group(1), "reason": "could not parse quoted value; not copied into ci.yml"})
                continue
            value: str = parsed
        else:
            if re.match(r"^[|>][-+0-9]*$", raw) or raw[:1] in ("&", "*", "!"):
                if dropped is not None:
                    dropped.append({"key": match.group(1), "reason": "unsupported YAML form (block scalar, anchor, alias or tag); not copied into ci.yml"})
                continue
            value = _scalar(raw) or ""
        if not value:
            continue
        if UNSAFE_COMMAND.search(value):
            if dropped is not None:
                dropped.append({"key": match.group(1), "reason": "contains `${{` or a newline; not copied into ci.yml"})
            continue
        found[match.group(1)] = value
    return found


def step(name: str, command: str) -> str:
    return f"      - name: {name}\n        run: {json.dumps(command)}"


def steps_block(repo: Path, dropped: list[dict[str, str]] | None = None) -> str:
    commands: dict[str, str] = read_commands(repo, dropped)
    steps: list[str] = [step(key, commands[key]) for key in COMMAND_KEYS if key in commands]
    steps.append(step("repo checks", f"if [ -f {CHECKS_PATH} ]; then bash {CHECKS_PATH}; fi"))
    return "\n".join(steps)


def render_ci(repo: Path, stack: str, dropped: list[dict[str, str]] | None = None) -> str:
    text: str = (TEMPLATES / "ci.yml").read_text(encoding="utf-8")
    setup: str = setup_block(repo, stack)
    text = text.replace("{{SETUP}}\n", setup + "\n" if setup else "")
    return text.replace("{{STEPS}}", steps_block(repo, dropped))


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
    dropped: list[dict[str, str]] = []
    stack: str = detect_stack(repo)
    if with_ci:
        write_new(repo, CI_PATH, render_ci(repo, stack, dropped), written, skipped)
    for source, target, types in OPS_FILES:
        if app_type == "unknown" or app_type in types:
            write_new(repo, target, (TEMPLATES / source).read_text(encoding="utf-8"), written, skipped)
    return {"appType": app_type, "stack": stack, "written": written, "skipped": skipped, "dropped": dropped}


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
