#!/usr/bin/env python3
"""List, recommend and add optional Claude Code hooks to a user's settings; merges only, never overwrites."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TEMPLATE_DIR: Final[Path] = PLUGIN_ROOT / "templates" / "hooks"
HOOKS_JSON: Final[Path] = PLUGIN_ROOT / "hooks" / "hooks.json"
HOOK_SCRIPT: Final[re.Pattern[str]] = re.compile(r"hooks/([\w-]+)\.sh")
SCRIPT_SUBDIR: Final[str] = "hooks/dts2"
TEST_COMMAND_FILE: Final[str] = "test-command"
NPM_DEFAULT_TEST: Final[str] = 'echo "Error: no test specified" && exit 1'
SCOPES: Final[tuple[str, ...]] = ("project", "local", "user")
# id, event, matcher (None when the event has none), timeout, summary, why it is recommended.
CATALOG: Final[tuple[dict[str, Any], ...]] = (
    {"id": "command-guard", "event": "PreToolUse", "matcher": "Bash", "timeout": 10,
     "summary": "Deny destructive shell commands (rm -rf on root or home, git reset --hard, curl piped to sh).",
     "why": "A cheap safety net against the worst one-line mistakes."},
    {"id": "auto-format", "event": "PostToolUse", "matcher": "Edit|Write|MultiEdit", "timeout": 30,
     "summary": "Run the project formatter on each file Claude edits.",
     "why": "Keeps edits formatted without a manual step."},
    {"id": "test-on-stop", "event": "Stop", "matcher": None, "timeout": 300,
     "summary": "Run the project test command when Claude stops; block the stop if tests fail.",
     "why": "Catches broken tests before Claude calls the work done."},
    {"id": "notify", "event": "Notification", "matcher": None, "timeout": 10,
     "summary": "Show a desktop notification when Claude needs your attention.",
     "why": "Lets you leave a long run and come back when it asks."},
    {"id": "merge-on-green", "event": "Stop", "matcher": None, "timeout": 30,
     "summary": "Report whether the open PR for this branch has green checks; never merges.",
     "why": "Shows when a pull request is ready to merge."},
)
CATALOG_BY_ID: Final[dict[str, dict[str, Any]]] = {entry["id"]: entry for entry in CATALOG}


class SetupError(Exception):
    """A refusal: nothing was written."""


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in ("id", "event", "matcher", "timeout", "summary")}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def read_json_object(path: Path) -> dict[str, Any]:
    """The parsed settings object; an absent file is an empty one; anything else unusable raises."""
    if not path.exists():
        return {}
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SetupError(f"{path} is not valid JSON ({error}); nothing was changed") from error
    if not isinstance(parsed, dict):
        raise SetupError(f"{path} is not a JSON object; nothing was changed")
    return parsed


def settings_path(scope: str, cwd: Path, home: Path) -> Path:
    if scope == "user":
        return home / ".claude" / "settings.json"
    name = "settings.json" if scope == "project" else "settings.local.json"
    return cwd / ".claude" / name


def script_dir(scope: str, cwd: Path, home: Path) -> Path:
    base: Path = home if scope == "user" else cwd
    return base / ".claude" / SCRIPT_SUBDIR


def hook_command(hook_id: str, scope: str) -> str:
    root: str = "$HOME" if scope == "user" else "$CLAUDE_PROJECT_DIR"
    return f'bash "{root}/.claude/{SCRIPT_SUBDIR}/{hook_id}.sh"'


def commands_in(settings: dict[str, Any]) -> list[str]:
    """Every hook command string in a settings object; tolerant of odd shapes."""
    found: list[str] = []
    hooks: Any = settings.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for groups in hooks.values():
        for group in groups if isinstance(groups, list) else []:
            inner: Any = group.get("hooks") if isinstance(group, dict) else None
            for hook in inner if isinstance(inner, list) else []:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    found.append(hook["command"])
    return found


def count_commands(path: Path) -> int:
    try:
        return len(commands_in(read_json_object(path)))
    except SetupError:
        return 0


def builtin_hooks() -> list[str]:
    try:
        hooks: Any = json.loads(HOOKS_JSON.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, json.JSONDecodeError):
        return []
    labels: list[str] = []
    for event, groups in hooks.items():
        for group in groups:
            matcher: str = group.get("matcher", "")
            for hook in group.get("hooks", []):
                found = HOOK_SCRIPT.search(hook.get("command", ""))
                if found:
                    where: str = f"{event} {matcher}".strip()
                    labels.append(f"{found.group(1)} ({where})")
    return list(dict.fromkeys(labels))


def package_json(cwd: Path) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(read_text(cwd / "package.json"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def detect_formatters(cwd: Path) -> str | None:
    names: list[str] = []
    package: dict[str, Any] = package_json(cwd)
    deps: dict[str, Any] = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    for dep, label in (("@biomejs/biome", "biome"), ("prettier", "prettier")):
        if dep in deps:
            names.append(label)
    if (cwd / "ruff.toml").is_file() or "ruff" in read_text(cwd / "pyproject.toml"):
        names.append("ruff")
    if (cwd / "go.mod").is_file():
        names.append("gofmt")
    if (cwd / "Cargo.toml").is_file():
        names.append("rustfmt")
    return ", ".join(names) or None


def detect_test_command(cwd: Path) -> str | None:
    scripts: Any = package_json(cwd).get("scripts")
    test: Any = scripts.get("test") if isinstance(scripts, dict) else None
    if isinstance(test, str) and test.strip() and test.strip() != NPM_DEFAULT_TEST:
        return "npm test"
    if (cwd / "go.mod").is_file():
        return "go test ./..."
    if (cwd / "Cargo.toml").is_file():
        return "cargo test"
    tests_dir: Path = cwd / "tests"
    has_tests: bool = tests_dir.is_dir() and any(tests_dir.glob("test_*.py"))
    pytest_named: bool = "pytest" in read_text(cwd / "pyproject.toml")
    if pytest_named:
        return "python3 -m pytest -q"
    return "python3 -m unittest discover -s tests" if has_tests else None


def has_github_remote(cwd: Path) -> bool:
    if not (cwd / ".git").exists():
        return False
    try:
        out: str = subprocess.run(["git", "remote", "-v"], cwd=str(cwd), capture_output=True, text=True,
                                  timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    return "github.com" in out or "github.com" in read_text(cwd / ".git" / "config")


def detection(cwd: Path) -> dict[str, str | None]:
    """Per hook id: what was detected (a string) or None when the hook is not recommended on detection alone."""
    return {
        "command-guard": "always",
        "notify": "always",
        "auto-format": detect_formatters(cwd),
        "test-on-stop": detect_test_command(cwd),
        "merge-on-green": "github.com remote" if has_github_remote(cwd) else None,
    }


def recommend(cwd: Path, home: Path) -> dict[str, Any]:
    project: Path = settings_path("project", cwd, home)
    try:
        present: set[str] = set(commands_in(read_json_object(project)))
    except SetupError:
        present = set()
    found: dict[str, str | None] = detection(cwd)
    recommended: list[dict[str, Any]] = []
    for entry in CATALOG:
        detected: str | None = found[entry["id"]]
        if detected is None:
            continue
        recommended.append({
            "id": entry["id"], "event": entry["event"], "matcher": entry["matcher"], "why": entry["why"],
            "detected": None if detected == "always" else detected,
            "already_present": hook_command(entry["id"], "project") in present,
        })
    return {
        "builtin": builtin_hooks(),
        "existing": {"project": count_commands(project),
                     "local": count_commands(settings_path("local", cwd, home)),
                     "user": count_commands(settings_path("user", cwd, home))},
        "recommended": recommended,
    }


def new_group(entry: dict[str, Any], command: str) -> dict[str, Any]:
    group: dict[str, Any] = {}
    if entry["matcher"]:
        group["matcher"] = entry["matcher"]
    group["hooks"] = [{"type": "command", "command": command, "timeout": entry["timeout"]}]
    return group


def add_group(settings: dict[str, Any], entry: dict[str, Any], command: str) -> None:
    hooks: Any = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SetupError("settings 'hooks' is not an object; nothing was changed")
    groups: Any = hooks.setdefault(entry["event"], [])
    if not isinstance(groups, list):
        raise SetupError(f"settings hooks.{entry['event']} is not a list; nothing was changed")
    groups.append(new_group(entry, command))


def backup_path(path: Path) -> Path:
    stamp: str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate: Path = path.with_name(f"{path.name}.bak-{stamp}")
    counter: int = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
        counter += 1
    return candidate


def script_conflict(source: Path, dest: Path) -> bool:
    return dest.exists() and dest.read_bytes() != source.read_bytes()


def apply(ids: list[str], scope: str, cwd: Path, home: Path, dry_run: bool) -> dict[str, Any]:
    unknown: list[str] = [hook_id for hook_id in ids if hook_id not in CATALOG_BY_ID]
    if unknown:
        raise SetupError(f"unknown hook id(s): {', '.join(unknown)}; run 'list' for the catalog")
    target: Path = settings_path(scope, cwd, home)
    settings: dict[str, Any] = read_json_object(target)
    existing: set[str] = set(commands_in(settings))
    dest_dir: Path = script_dir(scope, cwd, home)
    added: list[str] = []
    skipped: list[dict[str, str]] = []
    copy_plan: list[tuple[Path, Path]] = []
    for hook_id in dict.fromkeys(ids):
        entry: dict[str, Any] = CATALOG_BY_ID[hook_id]
        command: str = hook_command(hook_id, scope)
        source: Path = TEMPLATE_DIR / f"{hook_id}.sh"
        dest: Path = dest_dir / f"{hook_id}.sh"
        if command in existing:
            skipped.append({"id": hook_id, "reason": "already present"})
        elif not source.is_file():
            skipped.append({"id": hook_id, "reason": "template script missing"})
        elif script_conflict(source, dest):
            skipped.append({"id": hook_id, "reason": f"{dest} already exists and differs; not overwritten"})
        else:
            add_group(settings, entry, command)
            copy_plan.append((source, dest))
            existing.add(command)
            added.append(hook_id)
    backup: Path | None = backup_path(target) if added and target.exists() else None
    copied: list[str] = [str(dest) for _, dest in copy_plan if not dest.exists()]
    if not dry_run and added:
        write_all(target, settings, backup, copy_plan, detect_test_command(cwd) if "test-on-stop" in added else None,
                  dest_dir)
    return {"settings": str(target), "added": added, "skipped": skipped, "copied": copied,
            "backup": str(backup) if backup else None, "dry_run": dry_run}


def write_all(target: Path, settings: dict[str, Any], backup: Path | None, copy_plan: list[tuple[Path, Path]],
              test_command: str | None, dest_dir: Path) -> None:
    if backup is not None:
        shutil.copy2(target, backup)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for source, dest in copy_plan:
        if not dest.exists():
            shutil.copyfile(source, dest)
        dest.chmod(0o755)
    if test_command:
        (dest_dir / TEST_COMMAND_FILE).write_text(test_command + "\n", encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print the hook catalog")
    for name in ("recommend", "apply"):
        child = sub.add_parser(name)
        child.add_argument("--cwd", default=None, help="project directory (default: current)")
        child.add_argument("--home", default=None, help="home directory (default: the user's home)")
        if name == "apply":
            child.add_argument("--ids", required=True, help="comma-separated hook ids")
            child.add_argument("--scope", choices=SCOPES, default="project")
            child.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "list":
        print(json.dumps([public_entry(entry) for entry in CATALOG], indent=2))
        return 0
    cwd: Path = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    home: Path = Path(args.home).resolve() if args.home else Path.home()
    try:
        if args.command == "recommend":
            result: dict[str, Any] = recommend(cwd, home)
        else:
            ids: list[str] = [part.strip() for part in args.ids.split(",") if part.strip()]
            result = apply(ids, args.scope, cwd, home, args.dry_run)
    except SetupError as error:
        print(f"hooks-setup error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
