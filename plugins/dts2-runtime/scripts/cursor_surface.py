#!/usr/bin/env python3
"""Build the Cursor dt package from the instruction-edition skills.

Each Claude skill becomes skills/dt-<name>/ inside plugins/dt-cursor, with script
calls pointed at scripts/dt_gate.py. Command files carry the same procedure.
The marketplace entry keeps only the keys the official schema allows.

Usage: cursor_surface.py [--check]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

RUNTIME: Final[Path] = Path(__file__).resolve().parent.parent
REPO: Final[Path] = RUNTIME.parent.parent
HARNESS: Final[Path] = REPO / "plugins" / "dts2-harness"
ICON_SOURCE: Final[Path] = HARNESS / ".claude-plugin" / "icon.png"
METADATA: Final[dict[str, Any]] = json.loads(
    (RUNTIME / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
)
PUBLISHER: Final[str] = METADATA["author"]["name"]
DESCRIPTION: Final[str] = (
    "DT: Init to Ship Auto Agent Orchestrator. Turns one task into a planned, "
    "built, reviewed and verified pull request, with human checkpoints, parallel "
    "lanes and a paper trail. Cursor runs the procedure through scripts/dt_gate.py. "
    "Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls "
    "stay unexecuted."
)
DISPLAY_NAME: Final[str] = "DT: Init to Ship Auto Agent Orchestrator"
BANNER: Final[str] = (
    "> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. "
    "Do not read tokens or credential files. Do not merge, broadcast, install hooks, "
    "or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.\n"
)
DIRECTORY_BANNER: Final[str] = (
    "> Directory edition: do not run bundled scripts or hooks, a package launcher, "
    "or a download piped into a shell. Do not read tokens or credential files from the machine. "
    "Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.\n"
)
SCRIPT_CALL: Final[re.Pattern[str]] = re.compile(
    r"""python3(?: -I)? (?:"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([A-Za-z0-9_.-]+\.py)"|"\$CLAUDE_PLUGIN_ROOT/scripts/([A-Za-z0-9_.-]+\.py)")"""
)
BARE_SCRIPT: Final[re.Pattern[str]] = re.compile(
    r"""\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([A-Za-z0-9_.-]+\.py)"""
)
PREFACE: Final[str] = (
    "## Cursor procedure\n\n"
    "Find the plugin root: the nearest ancestor of this file that contains "
    "`.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.\n\n"
    "Run `python3 \"$PLUGIN/scripts/dt_gate.py\"` for every gate. "
    "Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. "
    "Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise "
    "blocker for that one step: record it and do not imitate the script. "
    "The interview, `approve`, and `scaffold` still run.\n\n"
    "`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same "
    "name as a kind is not authorization. `approve` records the sha256 of the file "
    "the user accepted, and later gates require that digest.\n\n"
    "Phase files for this command are in `$PLUGIN/skills/{folder}/`.\n\n"
    "Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls "
    "are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.\n\n"
)
DISCIPLINE: Final[str] = """# Harness discipline

Copied into `.harness/discipline.md` by `dt_gate.py scaffold`.

1. Define done before planning. The plan file needs an outcome and a check.
2. End with a receipt. This package writes no pull request by itself.
3. Stop when `.harness/STOP` exists. The runtime text caps fix rounds at five and also sends rounds 1-3 to one model tier. This package does not switch models. Record each fix round in `.harness/state.md` and stop after five.
4. Do not merge, force-push, or deploy. `dt_gate.py blocked --action merge` does not run a merge.
5. Do not read credential files or `.env`.
6. Do not edit `AGENTS.md` or `CLAUDE.md` from scaffold.
7. Approvals bind to the sha256 of the accepted file. Editing the file after approval requires a new approval.
"""


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    found: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line[0] in " \t" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        item = value.strip()
        if item.startswith('"'):
            item = str(json.loads(item))
        found[key.strip()] = item
    return found, body


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def rewrite(text: str) -> str:
    """Point Claude script calls at the Cursor gate and drop the colon command form."""
    text = text.replace(DIRECTORY_BANNER, BANNER)

    def _call(match: re.Match[str]) -> str:
        script = next(group for group in match.groups() if group)
        return f'python3 "$PLUGIN/scripts/dt_gate.py" bridge {script}'

    text = SCRIPT_CALL.sub(_call, text)
    text = BARE_SCRIPT.sub(lambda match: f'"$PLUGIN/scripts/dt_gate.py" bridge {match.group(1)}', text)
    text = text.replace("${CLAUDE_PLUGIN_ROOT}/templates/", "$PLUGIN/templates/")
    text = text.replace("${CLAUDE_PLUGIN_ROOT}", "$PLUGIN")
    text = text.replace("$CLAUDE_PLUGIN_ROOT", "$PLUGIN")
    text = text.replace("/dt:", "/dt-")
    text = text.replace(
        "Part 2 never starts until the user approves the end state, unless `--scaffold-only` was given.",
        "Part 2 never starts until `dt_gate.py approve` records the sha256 of `.harness/end-state.md`. The gate rejects `--scaffold-only`.",
    )
    text = text.replace(
        "Never scaffold before the end state is approved, unless `--scaffold-only` was given.",
        "Never scaffold before `dt_gate.py scaffold` accepts the matching approval. The gate rejects `--scaffold-only`.",
    )
    text = text.replace(
        "Skip Part 1 files with `--scaffold-only`.",
        "Do not skip Part 1. The gate rejects `--scaffold-only`.",
    )
    text = text.replace(
        "`--scaffold-only` → skip Part 1 and run Part 2 directly. Leave any existing `.harness/end-state.md` as it is.",
        "`--scaffold-only` is rejected. Set `status: approved`, then run `dt_gate.py approve` and `dt_gate.py scaffold`.",
    )
    text = text.replace(
        "or the user passed `--scaffold-only`",
        "and `dt_gate.py scaffold` accepts the matching approval digest",
    )
    text = text.replace("gh pr merge", 'python3 "$PLUGIN/scripts/dt_gate.py" blocked --action merge')
    text = text.replace(
        "9. Create `AGENTS.md` if absent and append this line once if it is not already there:",
        "9. Do not create or edit `AGENTS.md` or `CLAUDE.md`. Leave their bytes unchanged. "
        "The Claude edition appended a pointer and this package does not:",
    )
    text = text.replace(
        "It writes each distinct `rulesFile` (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, ...) when absent;",
        "Do not write `CLAUDE.md` or `AGENTS.md`. The Claude script writes each distinct `rulesFile` when absent;",
    )
    return text


def _skill_dirs() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in sorted((HARNESS / "skills").iterdir()):
        if (path / "SKILL.md").is_file():
            found.append((path.name, path))
    sdk = RUNTIME / "skills" / "sdk"
    if not any(name == "sdk" for name, _ in found):
        found.append(("sdk", sdk))
    found.sort(key=lambda item: item[0])
    if len(found) != 28:
        raise SystemExit(f"expected 28 skill directories, found {len(found)}")
    return found


def _skill_markdown(name: str, source: Path) -> tuple[str, str]:
    skill = source / "SKILL.md"
    meta, body = _frontmatter(skill.read_text(encoding="utf-8"))
    description = rewrite(meta.get("description", ""))
    body = PREFACE.format(folder=f"dt-{name}") + rewrite(body)
    front = (
        "---\n"
        f"name: dt-{name}\n"
        f"description: {_yaml(description)}\n"
        "disable-model-invocation: true\n"
        "---\n\n"
    )
    return front + body, description


def _command(name: str, procedure: str, description: str) -> str:
    summary = f"Run the /dt-{name} procedure shipped in this plugin. {description}"
    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."
    return f"---\nname: dt-{name}\ndescription: {_yaml(summary)}\n---\n\n{procedure}"


def _index(names: list[str]) -> str:
    lines = "\n".join(f"- `/dt-{name}`" for name in names)
    description = (
        "Run a DT harness command in Cursor. Use when the user invokes /dt or names a "
        "/dt-<command> procedure. Setup scaffolds only after an end-state approval. "
        "Run stops at the plan and ship gates."
    )
    body = (
        "# dt\n\n"
        f"{DISPLAY_NAME}. {PUBLISHER}. {METADATA['license']}.\n\n"
        "Invoke the matching skill. Each one is a procedure, not an index entry.\n\n"
        f"{lines}\n\n"
        "Start with `/dt-setup` when `.harness/end-state.md` is missing. "
        "`/dt-check-in` only reads. `/dt-run` plans and builds only after `dt_gate.py` "
        "accepts the approvals. Merges, fleet broadcast, hook install, the headless SDK, "
        "and paid provider calls stay unexecuted.\n"
    )
    return (
        "---\n"
        "name: dt\n"
        f"description: {_yaml(description)}\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"{body}"
    )


def _plugin_json() -> str:
    data = {
        "name": "dt",
        "displayName": DISPLAY_NAME,
        "version": "6.0.0",
        "description": DESCRIPTION,
        "author": {"name": PUBLISHER},
        "homepage": METADATA["homepage"],
        "repository": METADATA["repository"],
        "license": METADATA["license"],
        "keywords": ["harness", "multi-agent", "pipeline", "monorepo"],
        "logo": "assets/icon.png",
        "skills": "skills",
        "commands": "commands",
        "rules": "rules",
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _marketplace_json() -> str:
    data = {
        "name": "dts2",
        "owner": {"name": PUBLISHER},
        "metadata": {
            "description": f"{PUBLISHER} Cursor plugins.",
        },
        "plugins": [
            {
                "name": "dt",
                "source": "plugins/dt-cursor",
                "description": DESCRIPTION,
            }
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _rule() -> str:
    return (
        "---\n"
        "description: Optional dt gate reminder. alwaysApply is false, so Cursor does not attach this rule to every chat.\n"
        "alwaysApply: false\n"
        "---\n\n"
        "Use this rule only when the user invokes a /dt command. The enforcement is "
        "`scripts/dt_gate.py`, not this text. Do not treat `--yes`, `--ship`, or a JSON key "
        "as approval. Do not merge, broadcast, install hooks, run the headless SDK, or spend a provider API.\n"
    )


def render() -> dict[str, bytes]:
    tree: dict[str, bytes] = {
        ".cursor-plugin/marketplace.json": _marketplace_json().encode("utf-8"),
        "plugins/dt-cursor/.cursor-plugin/plugin.json": _plugin_json().encode("utf-8"),
        "plugins/dt-cursor/rules/instruction-edition.mdc": _rule().encode("utf-8"),
        "plugins/dt-cursor/assets/icon.png": ICON_SOURCE.read_bytes(),
        "plugins/dt-cursor/templates/discipline.md": DISCIPLINE.encode("utf-8"),
        "plugins/dt-cursor/templates/state.md": (HARNESS / "templates" / "state.md").read_bytes(),
        "plugins/dt-cursor/templates/keep.yaml": (HARNESS / "templates" / "keep.yaml").read_bytes(),
        "plugins/dt-cursor/templates/loop-experiment.example.json": (
            HARNESS / "templates" / "loop-experiment.example.json"
        ).read_bytes(),
        ".cursor/templates/loop-experiment.example.json": (
            HARNESS / "templates" / "loop-experiment.example.json"
        ).read_bytes(),
    }
    names: list[str] = []
    for name, source in _skill_dirs():
        names.append(name)
        procedure, description = _skill_markdown(name, source)
        tree[f"plugins/dt-cursor/skills/dt-{name}/SKILL.md"] = procedure.encode("utf-8")
        tree[f".cursor/skills/dt-{name}/SKILL.md"] = procedure.encode("utf-8")
        command = _command(name, procedure.split("\n---\n", 1)[-1].lstrip("\n"), description).encode("utf-8")
        # _command expects the body. procedure includes frontmatter. Split carefully.
        tree[f"plugins/dt-cursor/commands/dt-{name}.md"] = command
        tree[f".cursor/commands/dt-{name}.md"] = command
        for extra in sorted(source.glob("*.md")):
            if extra.name == "SKILL.md":
                continue
            rewritten = rewrite(extra.read_text(encoding="utf-8")).encode("utf-8")
            tree[f"plugins/dt-cursor/skills/dt-{name}/{extra.name}"] = rewritten
            tree[f".cursor/skills/dt-{name}/{extra.name}"] = rewritten
    index = _index(names).encode("utf-8")
    tree["plugins/dt-cursor/skills/dt/SKILL.md"] = index
    tree[".cursor/skills/dt/SKILL.md"] = index
    return tree


def _command_bytes(name: str, procedure: str, description: str) -> bytes:
    body = procedure.split("---\n", 2)[-1].lstrip("\n")
    return _command(name, body, description).encode("utf-8")


def render_fixed() -> dict[str, bytes]:
    """render() builds command bytes with a bad split. This pass rewrites those keys."""
    tree = render()
    for name, source in _skill_dirs():
        procedure, description = _skill_markdown(name, source)
        command = _command_bytes(name, procedure, description)
        tree[f"plugins/dt-cursor/commands/dt-{name}.md"] = command
        tree[f".cursor/commands/dt-{name}.md"] = command
    return tree


def check() -> list[str]:
    expected = render_fixed()
    found: list[str] = []
    for rel, raw in expected.items():
        path = REPO / rel
        if not path.is_file() or path.read_bytes() != raw:
            found.append(f"differs {rel}" if path.is_file() else f"missing {rel}")
            continue
        if rel.endswith((".md", ".mdc", ".json", ".yaml")):
            text = raw.decode("utf-8")
            for token in ("CLAUDE_PLUGIN_ROOT", "gh pr merge", "does not run the harness", "npx "):
                if token in text:
                    found.append(f"{rel} contains {token}")
    plugin = json.loads(expected["plugins/dt-cursor/.cursor-plugin/plugin.json"])
    if plugin.get("displayName") != DISPLAY_NAME:
        found.append("displayName missing")
    entry = json.loads(expected[".cursor-plugin/marketplace.json"])["plugins"][0]
    extra = set(entry) - {"name", "source", "description", "minClientVersions"}
    if extra:
        found.append("marketplace entry has " + ",".join(sorted(extra)))
    gate = REPO / "plugins" / "dt-cursor" / "scripts" / "dt_gate.py"
    if not gate.is_file():
        found.append("missing scripts/dt_gate.py")
    return found


def write() -> None:
    for rel, raw in render_fixed().items():
        path = REPO / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)


def main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        found = check()
        if found:
            print("\n".join(found[:40]), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "files": len(render_fixed())}))
        return 0
    if argv[1:]:
        print("usage: cursor_surface.py [--check]", file=sys.stderr)
        return 1
    write()
    print(json.dumps({"ok": True, "files": len(render_fixed())}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
