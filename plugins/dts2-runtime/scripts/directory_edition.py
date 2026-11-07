#!/usr/bin/env python3
"""Build the Claude directory listing at plugins/dts2-harness from this harness.

The directory accepts hooks, scripts, and extra frontmatter only from a Verified
organization. This writes an instruction edition: Markdown, text, JSON, YAML, and
the listing icon. The marketplace install stays plugins/dts2-runtime.

Usage: directory_edition.py [--check]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

RUNTIME: Final[Path] = Path(__file__).resolve().parent.parent
REPO: Final[Path] = RUNTIME.parent.parent
DEST: Final[Path] = REPO / "plugins" / "dts2-harness"
DIRECTORY_VERSION: Final[str] = "6.0.0"
SKIP_DIRS: Final[frozenset[str]] = frozenset({
    "scripts", "hooks", "tests", "evals", "sdk", "__pycache__", ".ruff_cache", ".git",
})
SKIP_FILES: Final[frozenset[str]] = frozenset({
    "ruff.toml", "pytest.ini", "requirements.txt", "requirements-dev.txt", "wrangler.toml",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "uv.toml", "uv.lock", ".npmrc", "bunfig.toml", "hooks.json",
})
ALLOWED_SUFFIXES: Final[frozenset[str]] = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
})
BARE_NAMES: Final[frozenset[str]] = frozenset({"LICENSE", "README", ".gitignore"})
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"})
SKILL_KEYS: Final[frozenset[str]] = frozenset({
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
    "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "model", "effort", "context", "agent",
})
AGENT_KEYS: Final[frozenset[str]] = frozenset({
    "name", "description", "model", "effort", "maxTurns", "tools", "disallowedTools",
    "skills", "memory", "background", "omitClaudeMd", "isolation", "color",
})
TEXT_LIMIT: Final[int] = 256 * 1024
FILE_LIMIT: Final[int] = 512
NOTE: Final[str] = (
    "> Directory edition: do not run bundled scripts or hooks, a package launcher, "
    "or a download piped into a shell. Do not read tokens or credential files from the machine. "
    "Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.\n"
)
REPLACEMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("`GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`", "`a GitHub token` or the SSH agent socket"),
    ("curl -fsSL https://composio.dev/install | sh", "Composio's install documentation at https://composio.dev"),
    ("read the key from the environment", "ask the user for the key"),
    ("read a key from an environment variable", "ask the user for the key"),
    ("npx skills update", "a bulk skill update"),
    ("npx skills add", "the publisher's installer for"),
    ("npx skills", "the publisher's skill installer"),
    ("npx wrangler", "wrangler"),
    ("npx playwright", "playwright"),
    ("npx -p typescript@5 tsc", "tsc"),
    ("npx ", "a package launcher "),
    ("npx", "a package launcher"),
    ("bunx", "a package launcher"),
    ("pnpm dlx", "a package launcher"),
    ("yarn dlx", "a package launcher"),
    ("uvx", "a package launcher"),
    ("pipx", "a package launcher"),
    ("uv run", "a locked project run"),
    ("curl -fsSL", "the publisher's install documentation"),
    ("| sh", ""),
    ("| bash", ""),
    ("ANTHROPIC_API_KEY", "the API key the user provides when asked"),
    ("GITHUB_TOKEN", "the GitHub token"),
    ("GH_TOKEN", "the GitHub token"),
    ("CODEX_API_KEY", "the Codex API key"),
    ("XAI_API_KEY", "the xAI API key"),
    ("KNOWLEDGE_TOKEN", "the knowledge token"),
    ("SSH_AUTH_SOCK", "the SSH agent socket"),
)
BANNED: Final[tuple[str, ...]] = (
    "npx", "bunx", "uvx", "pipx", "pnpm dlx", "yarn dlx", "curl -fsSL", "| sh", "| bash", "#!",
    "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "CODEX_API_KEY", "XAI_API_KEY",
    "KNOWLEDGE_TOKEN", "SSH_AUTH_SOCK",
)
DIRECTORY_SECTION: Final[str] = """## Directory edition

This folder is the instruction edition published to the Claude plugin directory. It contains skills, roles, and documents. It does not contain hooks or scripts. The directory accepts those only from a Verified organization.

Follow each skill with Claude's own tools. When a step names a file under `scripts/` or `hooks/`, do the work the step describes and write the files it names. Ask the user for a missing token or key. Do not read one from the machine, and do not download a program and run it.

The full harness installs from GitHub. The commands are in Install below.

"""
REQUIREMENTS_FROM: Final[str] = """## Requirements

- Claude Code with plugin support.
- Python 3.10 or newer (`python3`, `python`, or `py -3`). The scripts use only the standard library.
- `git` (2.38 or newer) and bash for the hooks. On Windows, Git Bash works, and Claude Code already uses it.
- The `gh` CLI, signed in, for anything that opens or sweeps pull requests (`ship`, `pr-sweep`, `dpp`, `autopilot`).
- Linux, macOS, WSL or Docker for parallel runs. On native Windows `dpp` parks with the reason `windows-native` (see [docs/RUNTIMES.md](docs/RUNTIMES.md)).
- Optional: `claude-agent-sdk` for the headless runner. Optional: the command-line tools for other AI providers (`codex`, `gemini`, `grok`, `opencode`, `copilot`, `muse`) if you want them on the roster. `autopilot` votes across three providers, so it needs three installed and signed in.

To check all of this on your machine, run `python3 scripts/doctor.py` from the plugin folder, or `make doctor` in a clone of the marketplace repo.
"""
REQUIREMENTS_TO: Final[str] = """## Requirements

- Claude Code, Cowork, or Claude.
- `git` (2.38 or newer) for skills that commit and open pull requests.
- The `gh` CLI, signed in, for skills that open or sweep pull requests.

This edition does not include Python scripts or shell hooks. The full harness, which needs Python 3.10 or newer and bash, installs from the GitHub marketplace named dts2.
"""
CHANGELOG_ENTRY: Final[str] = """## [6.0.0]

_Released 2026-11-07_

Directory edition for the Claude plugin directory. Skills, roles, and documents only. Hooks and scripts stay in the GitHub marketplace install (`plugins/dts2-runtime`), because an unverified organization cannot publish them.

"""


def _rel(path: Path) -> str:
    return path.relative_to(RUNTIME).as_posix()


def _kept(path: Path) -> bool:
    rel = _rel(path)
    parts = rel.split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return False
    if path.name in SKIP_FILES:
        return False
    if path.name in BARE_NAMES or path.suffix.lower() in ALLOWED_SUFFIXES:
        return True
    return False


def _filter_frontmatter(frontmatter: str, allowed: frozenset[str]) -> str:
    kept: list[str] = []
    skipping = False
    for line in frontmatter.splitlines():
        if line and line[0] not in " \t":
            key = line.split(":", 1)[0].strip()
            skipping = key not in allowed
        if not skipping:
            kept.append(line)
    body = "\n".join(kept).strip("\n")
    return body


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    return text[4:end], text[end + 4:]


def _insert_note(text: str) -> str:
    if NOTE.strip() in text:
        return text
    split = _split_frontmatter(text)
    if split is None:
        return NOTE + "\n" + text
    frontmatter, rest = split
    rest = rest.lstrip("\n")
    closing = f"---\n{frontmatter}\n---\n\n{NOTE}\n{rest}"
    return closing


def _component_keys(rel: str) -> frozenset[str] | None:
    parts = rel.split("/")
    if parts[0] == "skills" and rel.endswith("/SKILL.md"):
        return SKILL_KEYS
    if parts[0] == "agents" and rel.endswith(".md"):
        return AGENT_KEYS
    if parts[0] == "commands" and rel.endswith(".md"):
        return SKILL_KEYS
    return None


def _rewrite_markdown(rel: str, text: str) -> str:
    keys = _component_keys(rel)
    split = _split_frontmatter(text)
    if keys is not None and split is not None:
        frontmatter, rest = split
        filtered = _filter_frontmatter(frontmatter, keys)
        text = f"---\n{filtered}\n---\n{rest}" if filtered else rest.lstrip("\n")
    elif keys is None and split is not None:
        frontmatter, rest = split
        text = (
            "# Settings\n\nThese values are documentation in this edition.\n\n"
            f"```yaml\n{frontmatter.strip()}\n```\n{rest}"
        )
    if rel.startswith("skills/") or rel.startswith("agents/"):
        text = _insert_note(text)
    if rel == "README.md":
        if "## Directory edition" not in text:
            author_heading = "## From " + "Jere" + "my\n"
            text = text.replace(author_heading, DIRECTORY_SECTION + author_heading, 1)
        text = text.replace("## Install\n\n", "## Install\n\nThe commands below install the full harness from GitHub. Adding this plugin from the Claude directory installs the instruction edition.\n\n", 1)
        if REQUIREMENTS_FROM not in text:
            raise SystemExit("README requirements block changed; update directory_edition.py")
        text = text.replace(REQUIREMENTS_FROM, REQUIREMENTS_TO, 1)
    if rel == "CHANGELOG.md" and "## [6.0.0]" not in text:
        text = text.replace("## [5.1.1]\n", CHANGELOG_ENTRY + "## [5.1.1]\n", 1)
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _rewrite_manifest(text: str) -> str:
    data = json.loads(text)
    data["version"] = DIRECTORY_VERSION
    data["description"] = (
        "Instruction edition of the init-to-ship orchestrator. Skills and roles Claude follows "
        "with its own tools. The full harness, with hooks and scripts, installs from the GitHub marketplace dts2."
    )
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render() -> dict[str, bytes]:
    tree: dict[str, bytes] = {}
    for path in sorted(RUNTIME.rglob("*")):
        if not path.is_file() or not _kept(path):
            continue
        rel = _rel(path)
        raw = path.read_bytes()
        if path.suffix.lower() in IMAGE_SUFFIXES:
            tree[rel] = raw
            continue
        text = raw.decode("utf-8")
        if rel == ".claude-plugin/plugin.json":
            text = _rewrite_manifest(text)
        elif path.suffix.lower() in {".md", ".txt", ".yaml", ".yml", ".json"} or path.name in BARE_NAMES:
            if path.suffix.lower() == ".md":
                text = _rewrite_markdown(rel, text)
            else:
                for old, new in REPLACEMENTS:
                    text = text.replace(old, new)
        if "\0" in text:
            raise SystemExit(f"NUL byte in {rel}")
        tree[rel] = text.encode("utf-8")
    return tree


def policy(tree: dict[str, bytes]) -> list[str]:
    found: list[str] = []
    if len(tree) > FILE_LIMIT:
        found.append(f"{len(tree)} files exceeds {FILE_LIMIT}")
    if "hooks/hooks.json" in tree or any(rel.split("/")[0] == "hooks" for rel in tree):
        found.append("hooks shipped")
    manifest = json.loads(tree[".claude-plugin/plugin.json"].decode("utf-8"))
    if manifest.get("version") != DIRECTORY_VERSION:
        found.append(f"version is {manifest.get('version')}")
    if "hooks" in manifest:
        found.append("plugin.json declares hooks")
    for rel, raw in tree.items():
        name = rel.rsplit("/", 1)[-1]
        suffix = Path(name).suffix.lower()
        if name not in BARE_NAMES and suffix not in ALLOWED_SUFFIXES:
            found.append(f"disallowed file {rel}")
            continue
        if suffix in IMAGE_SUFFIXES:
            continue
        if len(raw) > TEXT_LIMIT:
            found.append(f"{rel} is {len(raw)} bytes")
        if raw.startswith(b"#!") or b"\0" in raw:
            found.append(f"shebang or NUL in {rel}")
        text = raw.decode("utf-8")
        for token in BANNED:
            if token in text:
                found.append(f"{rel} contains {token}")
                break
        split = _split_frontmatter(text)
        if split is None:
            continue
        allowed = _component_keys(rel)
        if allowed is None:
            found.append(f"frontmatter outside a skill, agent, or command: {rel}")
            continue
        for line in split[0].splitlines():
            if line and line[0] not in " \t":
                key = line.split(":", 1)[0].strip()
                if key not in allowed:
                    found.append(f"{rel} frontmatter key {key}")
    return found


def _read_dest() -> dict[str, bytes]:
    if not DEST.is_dir():
        return {}
    found: dict[str, bytes] = {}
    for path in DEST.rglob("*"):
        if path.is_file():
            found[path.relative_to(DEST).as_posix()] = path.read_bytes()
    return found


def check() -> list[str]:
    expected = render()
    actual = _read_dest()
    found = policy(expected)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        found.append("missing " + ", ".join(missing[:8]))
    if extra:
        found.append("extra " + ", ".join(extra[:8]))
    for rel, raw in expected.items():
        if actual.get(rel) not in (None, raw) and rel not in missing:
            found.append(f"differs {rel}")
    return found


def write() -> None:
    tree = render()
    found = policy(tree)
    if found:
        raise SystemExit("directory edition refused:\n" + "\n".join(found))
    DEST.mkdir(parents=True, exist_ok=True)
    for path in sorted(DEST.rglob("*"), reverse=True):
        rel = path.relative_to(DEST).as_posix()
        if path.is_file() and rel not in tree:
            path.unlink()
    for rel, raw in tree.items():
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != raw:
            target.write_bytes(raw)
    for path in sorted(DEST.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        found = check()
        if found:
            print("\n".join(found), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "version": DIRECTORY_VERSION}))
        return 0
    if argv[1:]:
        print("usage: directory_edition.py [--check]", file=sys.stderr)
        return 1
    write()
    print(json.dumps({"ok": True, "version": DIRECTORY_VERSION, "files": len(render())}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
