#!/usr/bin/env python3
"""Pre-run check: harness version, plugin marketplaces, and every companion and keep-list skill.

Report mode (default) changes nothing. `--fix` installs missing skills, removes retired ones whose
provenance is confirmed, updates the rest, refreshes marketplaces, and starts a harness upgrade when
a newer version is published. A skill gone upstream is never replaced automatically: `--fix` lists
ranked candidates and `--swap OLD=REF` (after the user says yes) installs one. Never pushes, and never
deletes or overwrites a git-tracked file: tracked skills are skipped and reported in `tracked_skipped`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402
import skill_pins as pins  # noqa: E402
import proc  # noqa: E402
import _load  # noqa: E402
import state_io  # noqa: E402
import harness_skew  # noqa: E402

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
HARNESS_PLUGIN: Final[str] = "dt@dts2"
TIMEOUT_S: Final[int] = 120
# G-76: the `skills` npm CLI is pinned. A moving `latest` could change flags or lock-file shape under a run; raise this
# constant in a reviewed commit, with the tests, when a newer CLI is wanted.
SKILLS_CLI_VERSION: Final[str] = "1.7.6"
TIMED_OUT: Final[int] = 124
NOT_FOUND: Final[int] = 127
RUNNER: proc.Runner | None = None  # tests set a proc.FakeRunner; None starts real processes
CANDIDATES_SHOWN: Final[int] = 3
# On Windows npx is npx.cmd, run through cmd.exe, which interprets & | > even in list-form argv,
# so every value that reaches a command line must match one of these first.
SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][\w.-]{0,99}", re.ASCII)
SAFE_REF: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"https://github\.com/([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)(?:/tree/[0-9a-f]{40})? --skill ([A-Za-z0-9][\w.-]*)", re.ASCII),
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
    marker: Path = state_io.harness_path(repo, DAILY_MARKER)
    try:
        return marker.read_text(encoding="utf-8").strip() == date.today().isoformat()
    except OSError:
        return False


def mark_checked(repo: Path) -> None:
    marker: Path = state_io.harness_path(repo, DAILY_MARKER)
    atomic_write(marker, date.today().isoformat() + "\n")
FIND_LINE: Final[re.Pattern[str]] = re.compile(r"^([\w.-]+/[\w.-]+)@([\w.-]+)\s+([\d.]+)([KkMm]?) installs")
LIST_LINE: Final[re.Pattern[str]] = re.compile(r"^\S\s{4}([\w.-]+)\s*$")
ANSI: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def load_upgrade_check() -> ModuleType:
    return _load.load("upgrade-check")


def binary(name: str, default: str) -> list[str]:
    return proc.binary(name, default)


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    return proc.run(cmd, cwd, timeout_s=TIMEOUT_S, runner=RUNNER, strip_ansi=True, merge_stderr=True,
                    timeout_code=TIMED_OUT)


def npx(*args: str) -> list[str]:
    return [*binary("DTS2_NPX_BIN", "npx"), "--yes", f"skills@{SKILLS_CLI_VERSION}", *args]


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
    path: Path = state_io.harness_path(repo, "keep.yaml")
    return parse_keep(path.read_text(encoding="utf-8") if path.is_file() else "")


def parse_keep(text: str) -> dict[str, Any]:
    skills: list[dict[str, str]] = []
    plugins: list[str] = []
    swapped: list[str] = []
    section: str = ""
    for raw in text.splitlines():
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
        elif section == "skills" and item.startswith("pin:") and skills:
            skills[-1]["pin"] = strip_comment(item.split(":", 1)[1])
    return {"skills": skills, "plugins": plugins, "swapped": swapped}


def swap_keep_entry(repo: Path, old: str, new: str, ref: str) -> None:
    """Replace the `old` entry (or append one) so a setup re-run keeps the replacement."""
    path: Path = state_io.harness_path(repo, "keep.yaml")
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
    atomic_write(path, newline.join(out) + newline, newline="")


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


# --- git-tracked skill files ----------------------------------------------------------------
# A repo can commit skill files (e.g. a vendored .claude/skills/stripe-*). The skills CLI treats every
# project skill as its own to rewrite, and `npx skills update` once deleted committed Stripe skill files.
# So no step here may delete or overwrite a git-tracked file: removals of a tracked skill are skipped,
# and every other mutating npx call runs under a snapshot that puts tracked files back byte-for-byte
# (and drops files the CLI added inside a tracked skill). Each skip is reported in `tracked_skipped`.
SKILL_ROOTS: Final[tuple[str, ...]] = (".claude/skills", ".agents/skills")
LOCK_FILE: Final[str] = "skills-lock.json"


def tracked_files(repo: Path, report: dict[str, Any]) -> list[str] | None:
    """Tracked paths under the skill roots (plus the lock file), relative to repo. None = cannot tell."""
    if "_tracked" in report:
        return report["_tracked"]
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "ls-files", "-z", "--", *SKILL_ROOTS, LOCK_FILE], repo)
    paths: list[str] | None
    if code == 0:
        paths, report["tracked_check"] = [p for p in out.split("\0") if p.strip()], "ok"
    elif any((d / ".git").exists() for d in (repo, *repo.parents)):
        paths, report["tracked_check"] = None, "unavailable"  # inside a git repo but git failed: fail closed
    else:
        paths, report["tracked_check"] = [], "no-git"
    report["_tracked"] = paths
    return paths


def skill_of(path: str) -> str | None:
    parts: list[str] = path.split("/")
    return parts[2] if len(parts) > 3 and "/".join(parts[:2]) in SKILL_ROOTS else None


def tracked_skills(repo: Path, report: dict[str, Any]) -> set[str] | None:
    paths = tracked_files(repo, report)
    return None if paths is None else {n for n in map(skill_of, paths) if n}


def is_tracked(repo: Path, report: dict[str, Any], name: str) -> bool:
    """True when the skill has a tracked file, or when tracked files cannot be listed (fail closed)."""
    names = tracked_skills(repo, report)
    return names is None or name in names


def note_skip(report: dict[str, Any], name: str, step: str, reverted: list[str]) -> None:
    report["tracked_skipped"].append({"name": name, "step": step, "reverted": reverted})


def skill_dir(repo: Path, rel: str) -> Path:
    return repo.joinpath(*rel.split("/")[:3])


def snapshot(repo: Path, paths: list[str]) -> dict[str, Any]:
    files: dict[str, tuple[bytes, int]] = {}
    for rel in paths:
        target: Path = repo / rel
        if target.is_file() and not target.is_symlink():
            files[rel] = (target.read_bytes(), target.stat().st_mode)
    dirs: set[Path] = {skill_dir(repo, rel) for rel in paths if skill_of(rel)}
    present: set[str] = {f.relative_to(repo).as_posix() for d in dirs if d.is_dir()
                         for f in d.rglob("*") if f.is_file() or f.is_symlink()}
    return {"files": files, "dirs": dirs, "present": present}


def restore(repo: Path, snap: dict[str, Any]) -> list[str]:
    """Put every snapshotted tracked file back; drop files the CLI added inside a tracked skill."""
    changed: list[str] = []
    for rel, (data, mode) in snap["files"].items():
        target: Path = repo / rel
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, mode)
        changed.append(rel)
    for d in snap["dirs"]:
        added: list[Path] = [f for f in d.rglob("*") if (f.is_file() or f.is_symlink())] if d.is_dir() else []
        for f in added:
            rel = f.relative_to(repo).as_posix()
            if rel not in snap["present"] and rel not in snap["files"]:
                f.unlink()
                changed.append(rel)
    return changed


def guarded_npx(repo: Path, report: dict[str, Any], step: str, cmd: list[str]) -> tuple[int, str]:
    """Run a mutating npx call; tracked files (skills and the lock file) come out exactly as they went in.

    Only a tracked skill the call actually touched is reported."""
    paths: list[str] = tracked_files(repo, report) or []
    snap = snapshot(repo, paths)
    code, out = run(cmd, repo)
    by_skill: dict[str, list[str]] = {}
    for rel in restore(repo, snap):
        by_skill.setdefault(skill_of(rel) or LOCK_FILE, []).append(rel)
    for name in sorted(set(by_skill) - {LOCK_FILE}):
        note_skip(report, name, step, sorted(by_skill.get(name, [])))
    if LOCK_FILE in by_skill:
        note_skip(report, LOCK_FILE, step, by_skill[LOCK_FILE])
    return code, out

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
    blocked: set[str] = set()
    for item in keep["skills"]:
        name, source = item["name"], item["source"]
        if name in blocked:
            continue
        if name in entries and item.get("pin") and not attach_pin(entries[name], item["pin"], report):
            blocked.add(name)  # a malformed pin never falls back to the unpinned upstream ref
            del entries[name]
            continue
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
        if item.get("pin") and not attach_pin(entries[name], item["pin"], report):
            blocked.add(name)
            del entries[name]
    return list(entries.values())


def attach_pin(entry: dict[str, Any], pin: str, report: dict[str, Any]) -> bool:
    """Record a keep.yaml pin on the skill entry. A value that is not a full commit SHA is rejected and
    the skill is left out entirely (fail closed): False tells the caller not to install or track it."""
    if pins.valid_pin(pin) and pins.pinned_ref(entry["ref"], pin) is not None:
        entry["pin"] = pin
        return True
    report["rejected"].append({"name": entry["name"],
                               "reason": "pin is not a 40-character commit SHA, or cannot be applied to this source; fix the pin in .harness/keep.yaml"})
    return False


def install_ref(entry: dict[str, Any]) -> str:
    """The ref to install: the exact pinned commit when keep.yaml pins the skill, else the plain ref."""
    return (pins.pinned_ref(entry["ref"], entry["pin"]) if entry.get("pin") else None) or entry["ref"]


def new_report() -> dict[str, Any]:
    return {"freshness": "fast", "installed": [], "missing": [], "retired_removed": [], "retired_kept": [],
            "swapped": [], "gone": [], "failed": [], "rejected": [], "updated": None, "npx": "ok",
            "lesson_candidates": [], "tracked_skipped": [], "tracked_check": None,
            "pinned": [], "proposals": [], "install_skipped": [], "update_skipped": None, "applied": []}


def do_swap(repo: Path, home: Path, old: str, ref: str, report: dict[str, Any]) -> None:
    parsed = parse_ref(ref)
    if not SAFE_NAME.fullmatch(old) or parsed is None:
        report["rejected"].append({"name": old[:60], "reason": "unsafe --swap value"})
        return
    if exists_upstream(ref, repo) is not True:
        report["failed"].append({"name": old, "output": f"{ref} not confirmed upstream; not installed"})
        return
    new_name: str = parsed[1]
    code, out = guarded_npx(repo, report, "swap-install", npx("add", *ref_args(ref), *INSTALL_FLAGS))
    if code != 0 or installed(repo, new_name, home) != "claude":
        report["failed"].append({"name": old, "output": out[-400:]})
        return
    swap_keep_entry(repo, old, new_name, ref)
    if installed(repo, old, home) != "missing" and new_name != old:
        if is_tracked(repo, report, old):
            note_skip(report, old, "swap-remove", [])
        else:
            run(npx("remove", old, "-y"), repo)
    report["swapped"].append({"from": old, "to": new_name, "source": ref})
    if old in COMPANIONS:
        report["lesson_candidates"].append(
            f"harness: companion `{old}` is gone upstream; replaced with `{new_name}` (`npx skills add {ref}`). "
            "Update discipline.md, the run skill and COMPANIONS in skills-check.py to the new name.")


def check_skills(repo: Path, home: Path, fix: bool, daily: bool, verify_upstream: bool,
                 swaps: list[str], applies: list[str] | None = None) -> dict[str, Any]:
    """Every call: presence check, install the missing, apply explicit swaps. Daily only: remove
    retired skills, detect gone-upstream ones, and write update proposals. Nothing is ever updated
    in bulk; an update lands only through an explicit --apply-update."""
    report: dict[str, Any] = new_report()
    report["freshness"] = "full" if daily else "fast"
    for spec in swaps:
        old, _, ref = spec.partition("=")
        do_swap(repo, home, old.strip(), ref.strip(), report)
    for spec in (applies or []) if fix else []:
        apply_update(repo, home, spec, report)
    if daily:
        for name, origin in RETIRED.items():
            if installed(repo, name, home) == "missing":
                continue
            source = lock_source(repo, name)
            if source != origin:
                report["retired_kept"].append({"name": name, "source": source or "unknown"})
            elif fix and is_tracked(repo, report, name):
                note_skip(report, name, "remove-retired", [])
            elif fix:
                code, _ = run(npx("remove", name, "-y"), repo)
                (report["retired_removed"] if code == 0 else report["failed"]).append(name)
            else:
                report["missing"].append({"name": name, "action": "remove (retired)"})
    wanted: list[dict[str, Any]] = wanted_skills(repo, report)
    report["pinned"] = [e["name"] for e in wanted if e.get("pin")]
    for entry in wanted:
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
        if tracked_files(repo, report) is None and (repo / ".claude" / "skills" / name).exists():
            note_skip(report, name, "install", [])  # cannot tell what is tracked; never write over it
            continue
        code, out = guarded_npx(repo, report, "install", npx("add", *ref_args(install_ref(entry)), *INSTALL_FLAGS))
        if code == NOT_FOUND:
            report["npx"] = "unavailable"
        elif code == TIMED_OUT:
            report["npx"] = "timed out"
        if installed(repo, name, home) == "claude":
            report["installed"].append(name)
        else:
            report["failed"].append({"name": name, "output": out[-400:]})
    if daily and verify_upstream:
        if pins.lock_fresh(repo):
            report["update_skipped"] = "skills-lock.json under 24h old"
        else:
            report["proposals"] = propose_updates(repo, wanted, write=fix)
    report.pop("_tracked", None)
    return report


def upstream_head(repo_id: str, cwd: Path) -> str | None:
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/{repo_id}/commits/HEAD",
                     "-H", "Accept: application/vnd.github.sha"], cwd)
    sha: str = out.strip()
    return sha if code == 0 and pins.valid_pin(sha) else None


def files_between(repo_id: str, base: str, head: str, cwd: Path) -> list[str] | None:
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/{repo_id}/compare/{base}...{head}",
                     "--jq", ".files[].filename"], cwd)
    return out.splitlines() if code == 0 else None


def propose_updates(repo: Path, wanted: list[dict[str, Any]], write: bool = True) -> list[dict[str, Any]]:
    """Daily sweep: list what changed upstream of each pin (or offer a first pin). With `write` (--fix) it
    stores them in the proposals file; check-only mode returns them and writes nothing. Nothing is
    installed and keep.yaml is untouched until an explicit --apply-update."""
    found = pins.build_proposals(wanted, lambda r: upstream_head(r, repo), lambda r, b, h: files_between(r, b, h, repo))
    target: Path = state_io.harness_path(repo, pins.PROPOSALS_FILE)
    if write and (found or target.is_file()):
        atomic_write(target, json.dumps(found, indent=2) + "\n")
    return found


def apply_update(repo: Path, home: Path, spec: str, report: dict[str, Any]) -> None:
    """Apply one approved proposal: NAME=SHA must match the stored proposal exactly."""
    name, _, sha = spec.partition("=")
    name, sha = name.strip(), sha.strip()
    target: Path = state_io.harness_path(repo, pins.PROPOSALS_FILE)
    try:
        stored: list[dict[str, Any]] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = []
    match = next((p for p in stored if isinstance(p, dict) and p.get("name") == name and p.get("upstream") == sha), None)
    entry = next((e for e in wanted_skills(repo, new_report()) if e["name"] == name), None)  # scratch report: rejections already counted
    if match is None or entry is None or not SAFE_NAME.fullmatch(name) or not pins.valid_pin(sha):
        report["rejected"].append({"name": name[:60], "reason": "--apply-update does not match a stored proposal"})
        return
    ref: str | None = pins.pinned_ref(entry["ref"], sha)
    if ref and tracked_files(repo, report) is None:  # git cannot say which files are tracked: fail closed
        note_skip(report, name, "apply-update", [])
        return
    code, out = guarded_npx(repo, report, "apply-update", npx("add", *ref_args(ref or ""), *INSTALL_FLAGS)) if ref else (1, "no ref")
    if any(k.get("step") == "apply-update" and k.get("name") == name and k.get("reverted")
           for k in report["tracked_skipped"]):  # the install was rolled back: nothing moved, so claim nothing
        report["rejected"].append({"name": name, "reason": "skill files are git-tracked; update them in a commit, not with --apply-update"})
        return
    if code != 0 or installed(repo, name, home) != "claude":
        report["failed"].append({"name": name, "output": out[-400:]})
        return
    keep: Path = state_io.harness_path(repo, "keep.yaml")
    text: str = keep.read_bytes().decode("utf-8") if keep.is_file() else ""
    updated: str = pins.set_pin_text(text, name, sha)
    if updated == text:  # a default companion with no keep entry yet: add one carrying the pin
        updated = pins.add_entry_text(text, name, entry["ref"], sha)
    written = next((e for e in parse_keep(updated)["skills"] if e["name"] == name), None)
    if written is None or written.get("pin") != sha:  # fail closed: never report a pin that is not in the file
        report["rejected"].append({"name": name, "reason": "could not set the pin in .harness/keep.yaml; edit it by hand"})
        return
    atomic_write(keep, updated, newline="")
    atomic_write(target, json.dumps([p for p in stored if p is not match], indent=2) + "\n")
    report["applied"].append({"name": name, "pin": sha})


# --- marketplaces and harness version -------------------------------------------------------

def marketplaces(plugins: list[str]) -> list[str]:
    names: list[str] = [p.split("@", 1)[1] for p in [HARNESS_PLUGIN, *plugins] if SAFE_PLUGIN.fullmatch(p)]
    return list(dict.fromkeys(names))


def published_version(home: Path, cwd: Path, allow_remote: bool, plugin_root: Path = PLUGIN_ROOT) -> str | None:
    local: Path = home / ".claude" / "plugins" / "marketplaces" / "dts2" / "plugins" / "dts2-harness" / ".claude-plugin" / "plugin.json"
    if local.is_file():
        try:
            return str(json.loads(local.read_text(encoding="utf-8"))["version"])
        except (ValueError, KeyError):
            pass
    if not allow_remote:
        return None  # the local marketplace clone is the cheap, every-call source
    source: str | None = harness_skew.marketplace_repo(plugin_root)  # G-77: named by the plugin, never hard-coded here
    if source is None:
        return None
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api",
                     f"repos/{source}/contents/plugins/dts2-harness/.claude-plugin/plugin.json",
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
    marker: Path = state_io.harness_path(repo, "upgrade-from.txt")
    result: dict[str, Any] = {"installed": installed_v, "published": None, "upgrade_available": False,
                              "upgrade_started": False, "upgrade_deferred": None, "upgrade_failed": None, "resume_upgrade": None,
                              "marketplaces": {}, "plugins_updated": [], "restart_required": False}
    if marker.is_file():
        result["resume_upgrade"] = upgrade.check(marker, plugin_json)
        return result
    # A keep list written before 5.0 still names the old plugin ids; they are the harness itself, not an extra plugin.
    plugins: list[str] = [p for p in read_keep(repo)["plugins"]
                          if SAFE_PLUGIN.fullmatch(p) and p not in state_io.LEGACY_HARNESS_PLUGINS]
    claude = binary("DTS2_CLAUDE_BIN", "claude")
    # Daily: refresh the marketplace clones so the version read below sees a newly-published harness.
    if fix and daily:
        for name in marketplaces(plugins):
            code, _ = run([*claude, "plugin", "marketplace", "update", name], repo)
            result["marketplaces"][name] = "updated" if code == 0 else "failed"
    # The local clone is read every call (cheap); the gh fallback is a daily-only network call.
    published = published_version(home, repo, allow_remote=daily, plugin_root=plugin_root)
    result["published"] = published
    result["upgrade_available"] = published is not None and upgrade.ordering(installed_v, published) < 0
    if not fix:
        return result
    held: list[str] = harness_skew.live_leases(repo, int(time.time()))
    if held:  # G-76: a plugin update swaps files under running sons; wait until no lane lease is live
        result["upgrade_deferred"] = f"live lane leases: {', '.join(held)}"
        return result
    if result["upgrade_available"]:
        run([sys.executable, str(SCRIPTS / "handoff-write.py"), str(repo)], repo)
        code, out = run([*claude, "plugin", "update", HARNESS_PLUGIN], repo)
        if code == 0:
            atomic_write(marker, installed_v + "\n")
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
    parser.add_argument("--apply-update", action="append", default=[], metavar="NAME=SHA",
                        help="apply one stored update proposal (after the user approved its diff)")
    parser.add_argument("--no-upstream", action="store_true", help="skip the gone-upstream check")
    parser.add_argument("--force-full", action="store_true",
                        help="run the freshness sweep now even if it already ran today")
    parser.add_argument("--son-root", default=None, metavar="PATH",
                        help="a son's plugin root; reports `skew` (park reason version-skew) when its version differs from the head's")
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT)))
    args = parser.parse_args()
    repo, home, root = Path(args.repo).resolve(), Path(args.home), Path(args.plugin_root)
    # The expensive freshness sweep runs the first time each day (or on demand); the rest of the day is
    # a cheap presence check that still installs anything missing and acts on a detected upgrade.
    daily: bool = args.force_full or not checked_today(repo)
    harness: dict[str, Any] = check_harness(repo, home, root, args.fix, daily)
    skills: dict[str, Any] = {} if harness["upgrade_started"] else \
        check_skills(repo, home, args.fix, daily, not args.no_upstream, args.swap, args.apply_update)
    # Record the sweep only when it actually completed on disk — not when an upgrade cut it short, and
    # not when npx was missing so nothing could be refreshed.
    if args.fix and daily and not harness["upgrade_started"] and skills.get("npx") == "ok":
        mark_checked(repo)
    out: dict[str, Any] = {"harness": harness, "skills": skills}
    if args.son_root:
        problem = harness_skew.skew_problem(root, Path(args.son_root))
        out["skew"] = {"ok": problem is None, "reason": None if problem is None else harness_skew.REASON_SKEW, "detail": problem}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
