#!/usr/bin/env python3
"""Show and apply the unattended permission profile (templates/settings.unattended.json) to a project's Claude Code settings.

  diff     print what `apply` would add to the target settings file; writes nothing.
  apply    merge the profile in, append-only: lists and missing keys are added, an existing value is never changed. The old
           file is copied to <name>.bak-<stamp> first (the same contract as hooks-setup.py).
  status   print whether unattended mode is on (the `autonomy: unattended` setting or DTS2_UNATTENDED=1).

Also home of `is_unattended(cwd)`, which the PermissionDenied hook uses."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
from state_io import atomic_write  # noqa: E402

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "settings.unattended.json"
POLICY: Final[Path] = PLUGIN_ROOT / "templates" / "policy.json"
SCOPES: Final[tuple[str, ...]] = ("project", "local", "user")
LOCAL_SETTINGS: Final[str] = ".claude/dts2-harness.local.md"
AUTONOMY_KEY: Final[str] = "autonomy"
AUTONOMY_UNATTENDED: Final[str] = "unattended"
ENV_VAR: Final[str] = "DTS2_UNATTENDED"
TRUE_WORDS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
# Every policy.json deny rule id and the permission patterns that mirror it in the template. tests/test_unattended_profile.py
# fails when policy.json gains a rule id that is not listed here, or when a pattern here is missing from the template.
POLICY_MIRRORS: Final[dict[str, tuple[str, ...]]] = {
    "force-push": ("Bash(git push -f*)", "Bash(git push --force*)", "Bash(git push --mirror*)", "Bash(git push * -f*)",
                   "Bash(git push * --force*)", "Bash(git push * --mirror*)", "Bash(git push * +*)"),
    "admin-flag": ("Bash(gh --admin*)", "Bash(gh * --admin*)"),
    "deploy-vercel": ("Bash(vercel deploy*)",),
    "deploy-vercel-prod": ("Bash(vercel --prod*)", "Bash(vercel * --prod*)", "Bash(vercel --prebuilt*)", "Bash(vercel * --prebuilt*)"),
    "deploy-wrangler": ("Bash(wrangler deploy*)",),
    "deploy-wrangler-publish": ("Bash(wrangler publish*)",),
    "deploy-fly": ("Bash(fly deploy*)", "Bash(flyctl deploy*)"),
    "deploy-netlify": ("Bash(netlify deploy*)", "Bash(ntl deploy*)"),
    "deploy-supabase": ("Bash(supabase db push*)",),
    "gh-secret": ("Bash(gh secret*)",),
    "vercel-env": ("Bash(vercel env*)",),
    "gh-repo-delete": ("Bash(gh repo delete*)",),
    "env-dump": ("Bash(env)", "Bash(printenv)"),
}


class ProfileError(Exception):
    """A refusal: nothing was written."""


def load_json_object(path: Path, missing_ok: bool) -> dict[str, Any]:
    if not path.exists():
        if missing_ok:
            return {}
        raise ProfileError(f"{path} does not exist")
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProfileError(f"{path} is not valid JSON ({error}); nothing was changed") from error
    if not isinstance(parsed, dict):
        raise ProfileError(f"{path} is not a JSON object; nothing was changed")
    return parsed


def settings_path(scope: str, cwd: Path, home: Path) -> Path:
    if scope == "user":
        return home / ".claude" / "settings.json"
    return cwd / ".claude" / ("settings.json" if scope == "project" else "settings.local.json")


def merge(settings: dict[str, Any], profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(merged copy, changes). Lists gain the missing entries at the end; a scalar is set only when absent; a scalar that
    already differs is reported under `kept`, never changed. Objects merge key by key."""
    merged: dict[str, Any] = copy.deepcopy(settings)
    added: dict[str, list[str]] = {}
    kept: dict[str, Any] = {}

    def walk(target: dict[str, Any], source: dict[str, Any], trail: str) -> None:
        for key, value in source.items():
            where: str = f"{trail}.{key}" if trail else key
            if key not in target:
                target[key] = copy.deepcopy(value)
                added[where] = list(value) if isinstance(value, list) else [json.dumps(value)]
            elif isinstance(value, dict) and isinstance(target[key], dict):
                walk(target[key], value, where)
            elif isinstance(value, list) and isinstance(target[key], list):
                fresh: list[Any] = [item for item in value if item not in target[key]]
                if fresh:
                    target[key].extend(fresh)
                    added[where] = fresh
            elif target[key] != value:
                kept[where] = {"yours": target[key], "profile": value}

    walk(merged, profile, "")
    return merged, {"added": added, "kept": kept}


def backup_path(path: Path) -> Path:
    stamp: str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate: Path = path.with_name(f"{path.name}.bak-{stamp}")
    counter: int = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
        counter += 1
    return candidate


def plan(scope: str, cwd: Path, home: Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    target: Path = settings_path(scope, cwd, home)
    current: dict[str, Any] = load_json_object(target, missing_ok=True)
    merged, changes = merge(current, load_json_object(TEMPLATE, missing_ok=False))
    return target, current, merged, changes


def diff(scope: str, cwd: Path, home: Path) -> dict[str, Any]:
    target, _, _, changes = plan(scope, cwd, home)
    return {"settings": str(target), **changes, "changed": bool(changes["added"])}


def apply(scope: str, cwd: Path, home: Path, dry_run: bool) -> dict[str, Any]:
    target, _, merged, changes = plan(scope, cwd, home)
    backup: Path | None = backup_path(target) if changes["added"] and target.exists() else None
    if changes["added"] and not dry_run:
        if backup is not None:
            shutil.copy2(target, backup)
        atomic_write(target, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return {"settings": str(target), **changes, "changed": bool(changes["added"]), "dry_run": dry_run,
            "backup": str(backup) if backup else None,
            "next": f"set `{AUTONOMY_KEY}: {AUTONOMY_UNATTENDED}` in {LOCAL_SETTINGS} so the PermissionDenied hook parks the lane"}


def is_unattended(cwd: Path) -> bool:
    """True when `autonomy: unattended` is set in .claude/dts2-harness.local.md or DTS2_UNATTENDED is a true word."""
    if os.environ.get(ENV_VAR, "").strip().lower() in TRUE_WORDS:
        return True
    try:
        text: str = (cwd / LOCAL_SETTINGS).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return str(miniyaml.parse_frontmatter(text).get(AUTONOMY_KEY, "")).strip().lower() == AUTONOMY_UNATTENDED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("diff", "apply", "status"):
        child = sub.add_parser(name)
        child.add_argument("--cwd", default=None, help="project directory (default: current)")
        if name != "status":
            child.add_argument("--home", default=None, help="home directory (default: the user's home)")
            child.add_argument("--scope", choices=SCOPES, default="project")
        if name == "apply":
            child.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cwd: Path = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    if args.command == "status":
        print(json.dumps({"unattended": is_unattended(cwd)}))
        return 0
    home: Path = Path(args.home).resolve() if args.home else Path.home()
    try:
        result: dict[str, Any] = diff(args.scope, cwd, home) if args.command == "diff" else apply(args.scope, cwd, home, args.dry_run)
    except ProfileError as error:
        print(f"unattended error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
