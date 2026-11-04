#!/usr/bin/env python3
"""Pre-run check: harness version, plugin marketplaces, and every companion and keep-list skill.

Report mode (default) changes nothing. `--fix` installs missing skills, removes retired ones whose
provenance is confirmed, updates the rest, refreshes marketplaces, and starts a harness upgrade when
a newer version is published. A skill gone upstream is never replaced automatically: `--fix` lists
ranked candidates and `--swap OLD=REF` (after the user says yes) installs one. Never pushes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Final

SCRIPTS: Final[Path] = Path(__file__).resolve().parent
PLUGIN_ROOT: Final[Path] = SCRIPTS.parent
MATTPOCOCK: Final[str] = "https://github.com/mattpocock/skills --skill"
COMPANIONS: Final[dict[str, str]] = {
    "grill-me": f"{MATTPOCOCK} grill-me",
    "improve-codebase-architecture": f"{MATTPOCOCK} improve-codebase-architecture",
    "writing-for-agents": f"{MATTPOCOCK} writing-for-agents",
    "pr": f"{MATTPOCOCK} pr",
    "resolve-merge-conflicts": "warpdotdev/common-skills@resolve-merge-conflicts",
    "diagnosing-bugs": f"{MATTPOCOCK} diagnosing-bugs",
    "ask-matt": f"{MATTPOCOCK} ask-matt",
    "research": f"{MATTPOCOCK} research",
    "loop-me": f"{MATTPOCOCK} loop-me",
    "setup-pre-commit": f"{MATTPOCOCK} setup-pre-commit",
    "code-review": f"{MATTPOCOCK} code-review",
}
# name -> the only source it is removed from; a same-named skill from anywhere else is left alone.
RETIRED: Final[dict[str, str]] = {
    "resolving-merge-conflicts": "mattpocock/skills",
    "request-refactor-plan": "mattpocock/skills",
    "diagnose": "mattpocock/skills",
}
# Windows silently drops the symlink a bare install makes, so Claude Code never sees the skill.
INSTALL_FLAGS: Final[tuple[str, ...]] = ("-a", "claude-code", "--copy", "-y")
HARNESS_PLUGIN: Final[str] = "dts2-harness@dts2"
TIMEOUT_S: Final[int] = 120
TIMED_OUT: Final[int] = 124
NOT_FOUND: Final[int] = 127
CANDIDATES_SHOWN: Final[int] = 3
# On Windows npx is npx.cmd, run through cmd.exe, which interprets & | > even in list-form argv,
# so every value that reaches a command line must match one of these first.
SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][\w.-]{0,99}", re.ASCII)
SAFE_REF: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"https://github\.com/([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*) --skill ([A-Za-z0-9][\w.-]*)", re.ASCII),
    re.compile(r"([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)@([A-Za-z0-9][\w.-]*)", re.ASCII),
)
SAFE_PLUGIN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][\w.-]*@[A-Za-z0-9][\w.-]*", re.ASCII)
SAFE_TREE_PATH: Final[re.Pattern[str]] = re.compile(r"[\w.-]+(?:/[\w.-]+)*/SKILL\.md", re.ASCII)
FIND_HITS_EXAMINED: Final[int] = 8
# The freshness sweep (npx update, gone-upstream checks, marketplace + harness-version refresh) makes
# serial network calls, so it runs at most once a day; this marker holds the date it last ran. The
# cheap work (are the skills on disk, install any that are missing, act on a detected upgrade) runs
# every call regardless.
DAILY_MARKER: Final[str] = ".skills-checked"


def checked_today(repo: Path) -> bool:
    marker: Path = repo / ".harness" / DAILY_MARKER
    try:
        return marker.read_text(encoding="utf-8").strip() == date.today().isoformat()
    except OSError:
        return False


def mark_checked(repo: Path) -> None:
    marker: Path = repo / ".harness" / DAILY_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(date.today().isoformat() + "\n", encoding="utf-8")
FIND_LINE: Final[re.Pattern[str]] = re.compile(r"^([\w.-]+/[\w.-]+)@([\w.-]+)\s+([\d.]+)([KkMm]?) installs")
LIST_LINE: Final[re.Pattern[str]] = re.compile(r"^\S\s{4}([\w.-]+)\s*$")
ANSI: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def load_upgrade_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("upgrade_check", SCRIPTS / "upgrade-check.py")
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binary(name: str, default: str) -> list[str]:
    value: str = os.environ.get(name, default)
    if value.endswith(".py"):
        return [sys.executable, value]
    # Windows ships npx as npx.cmd; subprocess only finds it through PATHEXT via which().
    return [shutil.which(value) or value]


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return TIMED_OUT, "timed out"
    except OSError as exc:
        return NOT_FOUND, str(exc)
    return done.returncode, ANSI.sub("", (done.stdout or "") + (done.stderr or ""))


def npx(*args: str) -> list[str]:
    return [*binary("DTS2_NPX_BIN", "npx"), "-y", "skills", *args]


def parse_ref(ref: str) -> tuple[str, str] | None:
    """(owner/repo, skill) for an allowlisted ref, else None. Nothing else ever reaches a command line."""
    for pattern in SAFE_REF:
        m = pattern.fullmatch(ref.strip())
        if m:
            return m.group(1), m.group(2)
    return None


def ref_args(ref: str) -> list[str]:
    parsed = parse_ref(ref)
    assert parsed is not None
    return ref.split()


# --- keep.yaml (line based, no yaml dependency) --------------------------------------------

def strip_comment(value: str) -> str:
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def read_keep(repo: Path) -> dict[str, Any]:
    path: Path = repo / ".harness" / "keep.yaml"
    skills: list[dict[str, str]] = []
    plugins: list[str] = []
    swapped: list[str] = []
    if not path.is_file():
        return {"skills": skills, "plugins": plugins, "swapped": swapped}
    section: str = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#") or not raw.strip():
            continue
        line: str = strip_comment(raw) if raw[:1] != " " else raw.rstrip()
        if raw[:1] not in (" ", "\t") and line.endswith(":"):
            section = line[:-1].strip()
            continue
        item: str = raw.strip()
        if section == "plugins" and item.startswith("- "):
            plugins.append(strip_comment(item[2:]))
        elif section == "skills" and item.startswith("- name:"):
            skills.append({"name": strip_comment(item.split(":", 1)[1]), "source": ""})
            m = re.search(r"#\s*swapped from ([\w.-]+)", item)
            if m:
                swapped.append(m.group(1))
        elif section == "skills" and item.startswith("source:") and skills:
            skills[-1]["source"] = strip_comment(item.split(":", 1)[1])
    return {"skills": skills, "plugins": plugins, "swapped": swapped}


def swap_keep_entry(repo: Path, old: str, new: str, ref: str) -> None:
    """Replace the `old` entry (or append one) so a setup re-run keeps the replacement."""
    path: Path = repo / ".harness" / "keep.yaml"
    text: str = path.read_bytes().decode("utf-8") if path.is_file() else "skills:\n"
    newline: str = "\r\n" if "\r\n" in text else "\n"
    lines: list[str] = text.splitlines()
    entry_re = re.compile(rf"^(\s*)-\s*name:\s*{re.escape(old)}\s*(#.*)?$")
    skills_key = re.compile(r"^skills:\s*(#.*)?$")
    note: str = f"# swapped from {old} {date.today().isoformat()} (gone upstream)"
    out: list[str] = []
    replaced, skipping = False, False
    for line in lines:
        m = entry_re.match(line)
        if m and not replaced:
            indent: str = m.group(1)
            out.extend([f"{indent}- name: {new}  {note}", f"{indent}  source: npx skills add {ref}",
                        f"{indent}  serves: harness"])
            replaced, skipping = True, True
            continue
        if skipping and line.strip().startswith(("source:", "serves:")):
            continue
        skipping = False
        out.append(line)
    if not replaced:
        if not any(skills_key.match(line) for line in out):
            out.append("skills:")
        at: int = next(i for i, line in enumerate(out) if skills_key.match(line)) + 1
        out[at:at] = [f"  - name: {new}  {note}", f"    source: npx skills add {ref}", "    serves: harness"]
    tmp: Path = path.with_suffix(".yaml.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(newline.join(out) + newline, encoding="utf-8", newline="")
    os.replace(tmp, path)


# --- upstream lookups -----------------------------------------------------------------------

_TREES: dict[str, list[str] | None] = {}
_LISTED: dict[str, set[str] | None] = {}


def repo_tree(repo_id: str, cwd: Path) -> list[str] | None:
    """Every path in the repo, or None when GitHub did not answer or the tree is truncated."""
    if repo_id not in _TREES:
        code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/{repo_id}/git/trees/HEAD?recursive=1",
                         "--jq", ".truncated, .tree[].path"], cwd)
        lines: list[str] = out.splitlines()
        _TREES[repo_id] = lines[1:] if code == 0 and lines and lines[0] == "false" else None
    return _TREES[repo_id]


def listed_names(repo_id: str, cwd: Path) -> set[str] | None:
    """Frontmatter skill names the skills CLI finds in a repo; folder names can differ from them."""
    if repo_id not in _LISTED:
        code, out = run(npx("add", repo_id, "--list"), cwd)
        names: set[str] = {m.group(1) for m in (LIST_LINE.match(line) for line in out.splitlines()) if m}
        _LISTED[repo_id] = names if code == 0 and names else None
    return _LISTED[repo_id]


_FRONTMATTER: dict[str, set[str] | None] = {}
FRONTMATTER_CAP: Final[int] = 80
NAME_LINE: Final[re.Pattern[str]] = re.compile(r"^name:\s*['\"]?([\w.-]+)", re.M)


def frontmatter_names(repo_id: str, cwd: Path) -> set[str] | None:
    """Skill names read from every SKILL.md in the repo; the slow path when the CLI listing is unusable."""
    if repo_id in _FRONTMATTER:
        return _FRONTMATTER[repo_id]
    tree = repo_tree(repo_id, cwd)
    paths: list[str] = [p for p in (tree or []) if p.endswith("SKILL.md")]
    names: set[str] | None = set()
    if tree is None or len(paths) > FRONTMATTER_CAP:
        names = None
    else:
        for path in paths:
            if not SAFE_TREE_PATH.fullmatch(path):
                continue  # a tree path is third-party data; an odd name is skipped, never run
            code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/{repo_id}/contents/{path}",
                             "-H", "Accept: application/vnd.github.raw"], cwd)
            if code != 0:
                names = None
                break
            m = NAME_LINE.search(out)
            names.add(m.group(1) if m else Path(path).parent.name)
    _FRONTMATTER[repo_id] = names
    return names


def exists_upstream(ref: str, cwd: Path) -> bool | None:
    """True when any source shows the skill; False only from a complete name list; None means unknown (never gone)."""
    parsed = parse_ref(ref)
    if parsed is None:
        return None
    repo_id, name = parsed
    tree = repo_tree(repo_id, cwd)
    if tree is None:
        return None
    if any(p == f"{name}/SKILL.md" or p.endswith(f"/{name}/SKILL.md") for p in tree):
        return True
    names = listed_names(repo_id, cwd)
    if names is not None and name in names:
        return True
    # A partial or failed listing (fewer names than SKILL.md files) cannot prove absence: read the files.
    if names is None or len(names) < sum(1 for p in tree if p.endswith("SKILL.md")):
        names = frontmatter_names(repo_id, cwd)
        if names is None:
            return None
    return name in names


def install_count(number: str, unit: str) -> float:
    return float(number) * {"k": 1e3, "m": 1e6}.get(unit.lower(), 1.0)


def swap_candidates(name: str, gone_ref: str, cwd: Path) -> list[dict[str, Any]]:
    """Live alternatives ranked by installs, the gone skill's own repo included (renames live there)."""
    code, out = run(npx("find", name.replace("-", " ")), cwd)
    if code != 0 and not out:
        return []
    seen: dict[str, float] = {}
    for line in out.splitlines():
        m = FIND_LINE.match(line.strip())
        if m:
            seen.setdefault(f"{m.group(1)}@{m.group(2)}", install_count(m.group(3), m.group(4)))
    gone = parse_ref(gone_ref)
    ranked: list[dict[str, Any]] = []
    top: list[tuple[str, float]] = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:FIND_HITS_EXAMINED]
    for candidate, installs in top:
        parsed = parse_ref(candidate)
        if parsed is None or (gone and parsed == gone):
            continue
        if exists_upstream(candidate, cwd) is True:
            ranked.append({"ref": candidate, "name": parsed[1], "installs": int(installs)})
        if len(ranked) == CANDIDATES_SHOWN:
            break
    return ranked


# --- skills ---------------------------------------------------------------------------------

def installed(repo: Path, name: str, home: Path) -> str:
    """`claude` when Claude Code can see it, `agents-only` when only the cross-agent copy exists, else `missing`."""
    for base in (repo / ".claude" / "skills", home / ".claude" / "skills"):
        if (base / name / "SKILL.md").is_file():
            return "claude"
    for base in (repo / ".agents" / "skills", home / ".agents" / "skills"):
        if (base / name / "SKILL.md").is_file():
            return "agents-only"
    return "missing"


def lock_source(repo: Path, name: str) -> str | None:
    path: Path = repo / "skills-lock.json"
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return str(data["skills"][name]["source"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ref_from_source(source: str) -> str | None:
    """`npx skills add <ref> [flags]` -> `<ref>`; None for plugin/synced or an unsafe value."""
    text: str = strip_comment(source)
    if not text.startswith("npx skills add "):
        return None
    tokens: list[str] = text[len("npx skills add "):].split()
    kept: list[str] = []
    skip_next: bool = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in ("-a", "--agent"):
            skip_next = True
            continue
        if token in ("--copy", "-y", "--yes", "-g", "--global", "-p", "--project"):
            continue
        kept.append(token)
    ref: str = " ".join(kept)
    return ref if parse_ref(ref) else None


def wanted_skills(repo: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    keep: dict[str, Any] = read_keep(repo)
    entries: dict[str, dict[str, Any]] = {n: {"name": n, "ref": r, "origin": "companion"}
                                          for n, r in COMPANIONS.items() if n not in keep["swapped"]}
    for item in keep["skills"]:
        name, source = item["name"], item["source"]
        if name in RETIRED or name in entries:
            continue
        if not SAFE_NAME.fullmatch(name):
            report["rejected"].append({"name": name[:60], "reason": "unsafe skill name"})
            continue
        if not source.startswith("npx skills add "):
            continue  # plugin- or synced-provided
        ref = ref_from_source(source)
        if ref is None:
            report["rejected"].append({"name": name, "reason": "source is not an allowlisted ref"})
            continue
        entries[name] = {"name": name, "ref": ref, "origin": "keep"}
    return list(entries.values())


def new_report() -> dict[str, Any]:
    return {"freshness": "fast", "installed": [], "missing": [], "retired_removed": [], "retired_kept": [],
            "swapped": [], "gone": [], "failed": [], "rejected": [], "updated": None, "npx": "ok",
            "lesson_candidates": []}


def do_swap(repo: Path, home: Path, old: str, ref: str, report: dict[str, Any]) -> None:
    parsed = parse_ref(ref)
    if not SAFE_NAME.fullmatch(old) or parsed is None:
        report["rejected"].append({"name": old[:60], "reason": "unsafe --swap value"})
        return
    if exists_upstream(ref, repo) is not True:
        report["failed"].append({"name": old, "output": f"{ref} not confirmed upstream; not installed"})
        return
    new_name: str = parsed[1]
    code, out = run(npx("add", *ref_args(ref), *INSTALL_FLAGS), repo)
    if code != 0 or installed(repo, new_name, home) != "claude":
        report["failed"].append({"name": old, "output": out[-400:]})
        return
    swap_keep_entry(repo, old, new_name, ref)
    if installed(repo, old, home) != "missing" and new_name != old:
        run(npx("remove", old, "-y"), repo)
    report["swapped"].append({"from": old, "to": new_name, "source": ref})
    if old in COMPANIONS:
        report["lesson_candidates"].append(
            f"harness: companion `{old}` is gone upstream; replaced with `{new_name}` (`npx skills add {ref}`). "
            "Update discipline.md, the run skill and COMPANIONS in skills-check.py to the new name.")


def check_skills(repo: Path, home: Path, fix: bool, daily: bool, verify_upstream: bool,
                 swaps: list[str]) -> dict[str, Any]:
    """Every call: presence check, install the missing, apply explicit swaps. Daily only: remove
    retired skills, detect gone-upstream ones, and `npx skills update` the rest."""
    report: dict[str, Any] = new_report()
    report["freshness"] = "full" if daily else "fast"
    for spec in swaps:
        old, _, ref = spec.partition("=")
        do_swap(repo, home, old.strip(), ref.strip(), report)
    if daily:
        for name, origin in RETIRED.items():
            if installed(repo, name, home) == "missing":
                continue
            source = lock_source(repo, name)
            if source != origin:
                report["retired_kept"].append({"name": name, "source": source or "unknown"})
            elif fix:
                code, _ = run(npx("remove", name, "-y"), repo)
                (report["retired_removed"] if code == 0 else report["failed"]).append(name)
            else:
                report["missing"].append({"name": name, "action": "remove (retired)"})
    for entry in wanted_skills(repo, report):
        name, ref = entry["name"], entry["ref"]
        state: str = installed(repo, name, home)
        if daily and verify_upstream and state != "claude" and exists_upstream(ref, repo) is False:
            report["gone"].append({"name": name, "ref": ref, "installed": state,
                                   "candidates": swap_candidates(name, ref, repo) if fix else []})
            continue
        if state == "claude":
            report["installed"].append(name)
            continue
        if not fix:
            report["missing"].append({"name": name, "action": f"npx skills add {ref} {' '.join(INSTALL_FLAGS)}",
                                      "state": state})
            continue
        if report["npx"] != "ok":
            report["failed"].append({"name": name, "output": f"npx {report['npx']}"})
            continue
        code, out = run(npx("add", *ref_args(ref), *INSTALL_FLAGS), repo)
        if code == NOT_FOUND:
            report["npx"] = "unavailable"
        elif code == TIMED_OUT:
            report["npx"] = "timed out"
        if installed(repo, name, home) == "claude":
            report["installed"].append(name)
        else:
            report["failed"].append({"name": name, "output": out[-400:]})
    if daily and fix and report["npx"] == "ok":
        _, out = run(npx("update", "-p", "-y"), repo)
        lower: str = out.lower()
        # The Windows CLI can end on a libuv assertion after a clean update, and an upstream skill with
        # bad YAML prints a "⚠ Skipped … parse error" warning; judge by the result line, and count a
        # failure only from a marker at column 0 (never from a warning or a quoted error string).
        good: bool = "up to date" in lower or bool(re.search(r"\bupdated \d+", lower))
        bad: bool = bool(re.search(r"^(✗|×|error:|fatal:)", out, re.M | re.I))
        report["updated"] = good and not bad
    return report


# --- marketplaces and harness version -------------------------------------------------------

def marketplaces(plugins: list[str]) -> list[str]:
    names: list[str] = [p.split("@", 1)[1] for p in [HARNESS_PLUGIN, *plugins] if SAFE_PLUGIN.fullmatch(p)]
    return list(dict.fromkeys(names))


def published_version(home: Path, cwd: Path, allow_remote: bool) -> str | None:
    local: Path = home / ".claude" / "plugins" / "marketplaces" / "dts2" / "plugins" / "dts2-harness" / ".claude-plugin" / "plugin.json"
    if local.is_file():
        try:
            return str(json.loads(local.read_text(encoding="utf-8"))["version"])
        except (ValueError, KeyError):
            pass
    if not allow_remote:
        return None  # the local marketplace clone is the cheap, every-call source
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api",
                     "repos/Dobeu-tech-eco/dts2-marketplace/contents/plugins/dts2-harness/.claude-plugin/plugin.json",
                     "-H", "Accept: application/vnd.github.raw"], cwd)
    if code != 0:
        return None
    try:
        return str(json.loads(out)["version"])
    except (ValueError, KeyError):
        return None


def check_harness(repo: Path, home: Path, plugin_root: Path, fix: bool, daily: bool) -> dict[str, Any]:
    upgrade = load_upgrade_check()
    plugin_json: Path = plugin_root / ".claude-plugin" / "plugin.json"
    installed_v: str = upgrade.read_version(plugin_json)
    marker: Path = repo / ".harness" / "upgrade-from.txt"
    result: dict[str, Any] = {"installed": installed_v, "published": None, "upgrade_available": False,
                              "upgrade_started": False, "upgrade_failed": None, "resume_upgrade": None,
                              "marketplaces": {}, "plugins_updated": [], "restart_required": False}
    if marker.is_file():
        result["resume_upgrade"] = upgrade.check(marker, plugin_json)
        return result
    plugins: list[str] = [p for p in read_keep(repo)["plugins"] if SAFE_PLUGIN.fullmatch(p)]
    claude = binary("DTS2_CLAUDE_BIN", "claude")
    # Daily: refresh the marketplace clones so the version read below sees a newly-published harness.
    if fix and daily:
        for name in marketplaces(plugins):
            code, _ = run([*claude, "plugin", "marketplace", "update", name], repo)
            result["marketplaces"][name] = "updated" if code == 0 else "failed"
    # The local clone is read every call (cheap); the gh fallback is a daily-only network call.
    published = published_version(home, repo, allow_remote=daily)
    result["published"] = published
    result["upgrade_available"] = published is not None and upgrade.ordering(installed_v, published) < 0
    if not fix:
        return result
    if result["upgrade_available"]:
        run([sys.executable, str(SCRIPTS / "handoff-write.py"), str(repo)], repo)
        code, out = run([*claude, "plugin", "update", HARNESS_PLUGIN], repo)
        if code == 0:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(installed_v + "\n", encoding="utf-8")
            result["upgrade_started"] = True
        else:
            result["upgrade_failed"] = out[-400:] or f"exit {code}"
    if daily and not result["upgrade_started"]:
        for plugin in (p for p in plugins if p != HARNESS_PLUGIN):
            code, out = run([*claude, "plugin", "update", plugin], repo)
            if code == 0 and "already" not in out.lower():
                result["plugins_updated"].append(plugin)
    result["restart_required"] = result["upgrade_started"] or bool(result["plugins_updated"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--fix", action="store_true", help="install, update, refresh and upgrade")
    parser.add_argument("--swap", action="append", default=[], metavar="OLD=REF",
                        help="replace a gone skill with REF; only after the user said yes")
    parser.add_argument("--no-upstream", action="store_true", help="skip the gone-upstream check")
    parser.add_argument("--force-full", action="store_true",
                        help="run the freshness sweep now even if it already ran today")
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT)))
    args = parser.parse_args()
    repo, home, root = Path(args.repo).resolve(), Path(args.home), Path(args.plugin_root)
    # The expensive freshness sweep runs the first time each day (or on demand); the rest of the day is
    # a cheap presence check that still installs anything missing and acts on a detected upgrade.
    daily: bool = args.force_full or not checked_today(repo)
    harness: dict[str, Any] = check_harness(repo, home, root, args.fix, daily)
    skills: dict[str, Any] = {} if harness["upgrade_started"] else \
        check_skills(repo, home, args.fix, daily, not args.no_upstream, args.swap)
    # Record the sweep only when it actually completed on disk — not when an upgrade cut it short, and
    # not when npx was missing so nothing could be refreshed.
    if args.fix and daily and not harness["upgrade_started"] and skills.get("npx") == "ok":
        mark_checked(repo)
    print(json.dumps({"harness": harness, "skills": skills}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
