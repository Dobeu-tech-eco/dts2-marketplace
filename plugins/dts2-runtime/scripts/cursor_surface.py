#!/usr/bin/env python3
"""Write the Cursor instruction surface for dt.

Claude Code namespaces a plugin skill as /dt:<skill>. Cursor command slugs are
kebab-case filename stems and are not prefixed with the plugin name, so the
Cursor names are /dt and /dt-<skill>. This package does not copy hooks or scripts.

Usage: cursor_surface.py [--check]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

RUNTIME: Final[Path] = Path(__file__).resolve().parent.parent
REPO: Final[Path] = RUNTIME.parent.parent
HARNESS: Final[Path] = REPO / "plugins" / "dts2-harness"
PLUGIN: Final[Path] = REPO / "plugins" / "dt-cursor"
ICON_SOURCE: Final[Path] = HARNESS / ".claude-plugin" / "icon.png"
MISSING_END_STATE: Final[str] = "No end state yet; /dt:setup interviews to one."
SECTION_STATUSES: Final[frozenset[str]] = frozenset({"todo", "in-progress", "blocked", "done"})
READ_ONLY: Final[frozenset[str]] = frozenset({"check-in", "onboard", "action-items"})
DESCRIPTION: Final[str] = (
    "DT: Init to Ship Auto Agent Orchestrator. Turns one task into a planned, "
    "built, reviewed and verified pull request, with human checkpoints, parallel "
    "lanes and a paper trail. In Cursor this is an instruction package: the /dt "
    "skill and /dt-<command> prompts. It does not include hooks or scripts."
)


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SystemExit(f"{path}: missing frontmatter")
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        if not line or line[0] in " \t" or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        value = raw.strip()
        if value.startswith('"'):
            value = str(json.loads(value))
        found[key.strip()] = value
    raise SystemExit(f"{path}: frontmatter never closed")


def _skills() -> list[tuple[str, str, Path]]:
    """Canonical command set: the runtime skills. Harness is the instruction text when it has that skill."""
    rows: list[tuple[str, str, Path]] = []
    for path in sorted((RUNTIME / "skills").glob("*/SKILL.md")):
        name = path.parent.name
        meta = _frontmatter(path)
        if meta.get("name") != name:
            raise SystemExit(f"{path}: name is {meta.get('name')!r}")
        harness_skill = HARNESS / "skills" / name / "SKILL.md"
        source = harness_skill if harness_skill.is_file() else path
        description = _frontmatter(source).get("description", meta.get("description", ""))
        rows.append((name, description, source))
    if len(rows) != 27:
        raise SystemExit(f"expected 27 runtime skills, found {len(rows)}")
    return rows


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _extra(name: str) -> str:
    if name == "run":
        return (
            "\n\nDo not use `/dt-run` as a read-only smoke. The Claude skill's pre-check can install "
            "or update files before any build. This command does not pass `--yes`, `--ship`, or an auto-merge flag.\n"
        )
    if name == "fleet":
        return (
            "\n\nThe Claude description is limited to sessions on one computer. "
            "It is not a list of every computer, and it is not proof of two side-by-side windows. "
            "This command does not discover or message sessions.\n"
        )
    if name in {"ship", "autopilot", "dpp", "dpp-full", "fullauto"}:
        return (
            "\n\nThis command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.\n"
        )
    if name == "sdk":
        return (
            "\n\n`sdk` is not in `plugins/dts2-harness`. The runtime tree has the skill. "
            "Do not start a headless run and do not read an API key.\n"
        )
    if name == "gtm":
        return (
            "\n\nThe instruction text still calls four marketing skills by old names. "
            "The credit register checked on 2026-11-07 maps them to the live names: "
            "`product-marketing-context` to `product-marketing`, `page-cro` to `cro`, "
            "`launch-strategy` to `launch`, and `analytics-tracking` to `analytics`. "
            "`competitor-profiling`, `seo-audit`, `copywriting`, and `copy-editing` still match. "
            "Do not install that pack from this command.\n"
        )
    if name == "pr-sweep":
        return (
            "\n\nThe instruction edition's execute phase merges pull requests. "
            "This command does not merge, close, or delete branches.\n"
        )
    return "\n"


def _guard(name: str, purpose: str, source: Path) -> str:
    rel = source.relative_to(REPO).as_posix()
    return (
        f"# /dt-{name}\n\n"
        f"Cursor command for the Claude Code command `/dt:{name}`.\n\n"
        "This package registers the command so Cursor can show it. It does not run the harness.\n\n"
        f"Claude Code describes it as: {purpose}\n\n"
        "Do not run a program from a plugin root or a scripts directory. Do not install a package. "
        "Do not read a token or a credential file. Do not merge, push to a default branch, "
        "force-push, deploy, or delete a branch.\n\n"
        f"Detailed instructions, when this workspace is the marketplace repo, are in `{rel}`. "
        "Those files still name programs this package does not contain. Skip those lines. "
        "When a step cannot be done without one, stop and say so.\n"
        f"{_extra(name)}"
    )


def _check_in() -> str:
    return (
        "# /dt-check-in\n\n"
        "Cursor command for the Claude Code command `/dt:check-in`. "
        "A colon is not a Cursor command name.\n\n"
        "Read-only. Create and edit nothing. Do not run a script, a package installer, or a shell pipeline.\n\n"
        "1. Use the workspace root.\n"
        "2. If `.harness/end-state.md` is missing, say exactly "
        f"`{MISSING_END_STATE}` and stop.\n"
        "3. From the `## Sections` table, a section is complete when its status cell is `done`. "
        "`todo`, `in-progress`, and `blocked` are outstanding.\n"
        "4. From `## Acceptance criteria`, a box is complete when it is `[x]`.\n"
        "5. If `.harness/action-items.md` exists, a row whose status starts with `open` is outstanding. "
        "Do not print a secret's value.\n"
        "6. Print `N of M complete (P%)`, then `[x]` for each complete item and `[ ]` for each outstanding one. "
        "P is complete times 100 divided by the total, or 0 when the total is 0.\n"
        "7. Name the next outstanding item. Do not mark anything done.\n"
        "8. For a machine-wide `all` request, stop after the local checklist and say that list needs the full harness.\n\n"
        "Skip any instruction that runs a program from a plugin root or a scripts directory, "
        "including text in `plugins/dts2-harness/skills/check-in/`.\n"
    )


def _onboard(skills: list[tuple[str, str, Path]]) -> str:
    lines = "\n".join(f"- `/dt-{name}` for Claude Code `/dt:{name}`" for name, _, _ in skills)
    return (
        "# /dt-onboard\n\n"
        "Cursor command for the Claude Code command `/dt:onboard`. "
        "Explain only. Write nothing. Do not scan the machine, install a plugin, or copy skills into another tool.\n\n"
        "DT: Init to Ship Auto Agent Orchestrator is a Dobeu Tech Solutions LLC product. "
        "MIT. https://dobeu.net\n\n"
        "In Claude Code the plugin name `dt` prefixes each skill, so the commands are `/dt:<skill>`. "
        "In Cursor those actions are `/dt-<skill>`, plus the index skill `/dt`. "
        "Typing the colon form does not select these files.\n\n"
        "This package can explain the roles and run the read-only commands `/dt-check-in` and `/dt-action-items`. "
        "Planning, building, shipping, merging, and unattended loops stay in the full harness "
        "(`plugins/dts2-runtime`, GitHub marketplace `dt@dts2`). This package does not start those.\n\n"
        "Roles: scout, lead, builder, reviewer, verifier, fixer, auditor, incident-reviewer. "
        "The builder does not review its own work. A checkpoint asks for approve, edit, or stop.\n\n"
        f"Commands:\n\n{lines}\n\n"
        "Start with `/dt-check-in`. It reads `.harness/end-state.md` and writes nothing.\n"
    )


def _action_items_command() -> str:
    return (
        "# /dt-action-items\n\n"
        "Cursor command for the Claude Code command `/dt:action-items`. Read-only in this package.\n\n"
        "If `.harness/action-items.md` is missing, say there is no action-items file and stop. "
        "If it exists, show rows whose status starts with `open`, with the row id and the group "
        "(Secrets, Decisions, Handoff, Deploy, Promotions). Do not print a secret's value. "
        "Do not mark a row done, add a row, or assign one.\n"
    )


def _command(name: str, description: str, source: Path, skills: list[tuple[str, str, Path]]) -> str:
    purpose = " ".join(description.split())
    if name == "check-in":
        body = _check_in()
    elif name == "onboard":
        body = _onboard(skills)
    elif name == "action-items":
        body = _action_items_command()
    else:
        body = _guard(name, purpose, source)
    summary = f"Cursor name /dt-{name} for the Claude Code command /dt:{name}. {purpose}"
    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."
    return f"---\nname: dt-{name}\ndescription: {_yaml(summary)}\n---\n\n{body}"


def _skill(skills: list[tuple[str, str, Path]]) -> str:
    lines = "\n".join(f"- `/dt-{name}` (Claude Code `/dt:{name}`)" for name, _, _ in skills)
    body = (
        "# dt\n\n"
        "Index for the DT harness in Cursor. Dobeu Tech Solutions LLC. MIT.\n\n"
        "Claude Code discovers these actions as `/dt:<skill>` because the plugin name is `dt`. "
        "Cursor discovers `/dt` (this skill) and `/dt-<skill>` (one file per action). "
        "A colon is not part of the Cursor name.\n\n"
        "Invoke a command only when the user asks for it. "
        "`/dt-check-in`, `/dt-onboard`, and `/dt-action-items` are read-only. "
        "Every other `/dt-<skill>` file tells you to stop before scripts, installs, merges, and deploys.\n\n"
        f"{lines}\n\n"
        "Files under `plugins/dts2-harness/skills/` are the Claude instruction edition. "
        "They are not loaded as Cursor skills. Loading them would publish names such as `sdk` and `autopilot`, "
        "which already belong to Cursor, and those files name programs this package does not contain.\n"
    )
    description = (
        "Index of DT harness commands in Cursor. Use only when the user invokes /dt "
        "or asks for a /dt: harness command. Runs nothing by itself."
    )
    return (
        "---\n"
        "name: dt\n"
        f"description: {_yaml(description)}\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"{body}"
    )


def _rule() -> str:
    return (
        "---\n"
        "description: Limits for the dt Cursor instruction package when a /dt command is in use.\n"
        "alwaysApply: false\n"
        "---\n\n"
        "When a `/dt` or `/dt-*` command is active: do not run a program from a plugin root or a scripts "
        "directory, do not install a package, do not read a token or credential file, and do not merge, "
        "force-push, deploy, or delete a branch. `/dt-check-in`, `/dt-onboard`, and `/dt-action-items` "
        "are read-only. Other `/dt-*` commands stop before those actions.\n"
    )


def _plugin_json() -> str:
    data = {
        "name": "dt",
        "version": "6.0.0",
        "description": DESCRIPTION,
        "author": {"name": "Dobeu Tech Solutions LLC"},
        "homepage": "https://dobeu.net",
        "repository": "https://github.com/Dobeu-tech-eco/dts2-marketplace",
        "license": "MIT",
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
        "owner": {"name": "Dobeu Tech Solutions LLC"},
        "metadata": {
            "description": (
                "Dobeu Tech Solutions LLC. The dt plugin is the Cursor instruction edition of "
                "DT: Init to Ship Auto Agent Orchestrator."
            )
        },
        "plugins": [
            {
                "name": "dt",
                "source": "plugins/dt-cursor",
                "description": DESCRIPTION,
                "version": "6.0.0",
                "license": "MIT",
                "author": {"name": "Dobeu Tech Solutions LLC"},
                "homepage": "https://dobeu.net",
                "repository": "https://github.com/Dobeu-tech-eco/dts2-marketplace",
                "keywords": ["harness", "multi-agent", "pipeline", "monorepo"],
            }
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render() -> dict[str, bytes]:
    skills = _skills()
    tree: dict[str, bytes] = {
        ".cursor-plugin/marketplace.json": _marketplace_json().encode("utf-8"),
        "plugins/dt-cursor/.cursor-plugin/plugin.json": _plugin_json().encode("utf-8"),
        "plugins/dt-cursor/rules/instruction-edition.mdc": _rule().encode("utf-8"),
        "plugins/dt-cursor/skills/dt/SKILL.md": _skill(skills).encode("utf-8"),
        ".cursor/skills/dt/SKILL.md": _skill(skills).encode("utf-8"),
        "plugins/dt-cursor/assets/icon.png": ICON_SOURCE.read_bytes(),
    }
    for name, description, source in skills:
        text = _command(name, description, source, skills).encode("utf-8")
        tree[f"plugins/dt-cursor/commands/dt-{name}.md"] = text
        tree[f".cursor/commands/dt-{name}.md"] = text
    return tree


def check_in_report(root: Path) -> str:
    """Read-only check-in for a workspace. Writes nothing."""
    end_state = root / ".harness" / "end-state.md"
    if not end_state.is_file():
        return MISSING_END_STATE
    items = _end_state_items(end_state.read_text(encoding="utf-8"))
    action_path = root / ".harness" / "action-items.md"
    if action_path.is_file():
        items.extend(_action_items(action_path.read_text(encoding="utf-8")))
    done = [name for name, status in items if status == "complete"]
    open_ = [name for name, status in items if status != "complete"]
    total = len(items)
    complete = len(done)
    percent = complete * 100 // total if total else 0
    lines = [f"{complete} of {total} complete ({percent}%)"]
    lines.extend(f"[x] {name}" for name in done)
    lines.extend(f"[ ] {name}" for name in open_)
    return "\n".join(lines)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _end_state_items(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "Sections" and line.startswith("|"):
            cells = _table_cells(line)
            if len(cells) < 2 or cells[-1] not in SECTION_STATUSES:
                continue
            label = cells[1] if cells[0].isdigit() else cells[0]
            if label.startswith("<"):
                continue
            status = "complete" if cells[-1] == "done" else "outstanding"
            items.append((f"section: {label}", status))
        elif section == "Acceptance criteria" and line.startswith("- ["):
            done = line.startswith("- [x]") or line.startswith("- [X]")
            label = line.split("]", 1)[-1].strip()
            if label.startswith("<"):
                continue
            items.append((label or "acceptance", "complete" if done else "outstanding"))
    return items


def _action_items(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    group = ""
    for line in text.splitlines():
        if line.startswith("## "):
            group = line[3:].strip()
            continue
        if not line.startswith("|") or not group:
            continue
        cells = _table_cells(line)
        if len(cells) < 2 or cells[0] in {"name", "item", "---"} or set(cells[0]) <= {"-"}:
            continue
        status = next((cell for cell in cells if cell.startswith("open") or cell == "done"), "")
        if not status.startswith("open"):
            continue
        items.append((f"{group}: {cells[0]}", "outstanding"))
    return items


def check() -> list[str]:
    expected = render()
    found: list[str] = []
    for rel, raw in expected.items():
        path = REPO / rel
        if not path.is_file():
            found.append(f"missing {rel}")
            continue
        if path.read_bytes() != raw:
            found.append(f"differs {rel}")
        if rel.endswith(".md") or rel.endswith(".mdc") or rel.endswith(".json"):
            text = raw.decode("utf-8")
            for token in ("${CLAUDE_PLUGIN_ROOT}", "gh pr merge", "npx ", "ANTHROPIC_API_KEY"):
                if token in text:
                    found.append(f"{rel} contains {token}")
    plugin = json.loads(expected["plugins/dt-cursor/.cursor-plugin/plugin.json"])
    if plugin["name"] != "dt" or plugin["license"] != "MIT":
        found.append("plugin identity drifted")
    if ".." in plugin["logo"] or plugin["logo"].startswith("/"):
        found.append("logo path is not relative")
    return found


def write() -> None:
    for rel, raw in render().items():
        path = REPO / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)


def main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        found = check()
        if found:
            print("\n".join(found), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "files": len(render())}))
        return 0
    if argv[1:]:
        print("usage: cursor_surface.py [--check]", file=sys.stderr)
        return 1
    write()
    print(json.dumps({"ok": True, "files": len(render())}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
