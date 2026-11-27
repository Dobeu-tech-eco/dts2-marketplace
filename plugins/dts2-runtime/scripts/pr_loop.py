#!/usr/bin/env python3
"""PR-end completeness loop: re-run the missing-items check against one PR's scope and gate the PR body on it.

Subcommands:
  check --base REF [--head REF] [--file-items]   print the "## Loop gate" markdown block for the PR body; with --file-items each
                                                 newly missing item is filed in .harness/action-items.md (never dropped)
  verify-body PATH                               exit 0 when PATH holds the Loop gate headings, each with text (HTML comments
                                                 do not count) and no failing line ("Missing: ..." or "not yet fixed or filed"); else 1

Global: --repo ROOT (default .). Read-only except --file-items. Stdlib only."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _load  # noqa: E402
import gap_research  # noqa: E402
import state_io  # noqa: E402

PLUGIN: Final[str] = "plugins/dts2-runtime/"
MANIFEST: Final[str] = PLUGIN + ".claude-plugin/plugin.json"
CHANGELOG: Final[str] = PLUGIN + "CHANGELOG.md"
UNSHIPPED: Final[tuple[str, ...]] = (PLUGIN + "tests/", PLUGIN + "changelog.d/")
ROADMAP_FILES: Final[tuple[str, ...]] = (state_io.END_STATE_REL, gap_research.ROADMAP_VIEW_REL)
PASS_REL: Final[str] = gap_research.PASS_REL
GAPS_REL: Final[str] = gap_research.LEDGER_REL
OPEN_GAP: Final[tuple[str, ...]] = ("proposed", "escalated")
ITEMS_GROUP: Final[str] = "Decisions"  # action-items.py has no "Loop gate" group; rows carry the prefix instead
ITEM_PREFIX: Final[str] = "[Loop gate]"
HEADINGS: Final[tuple[str, ...]] = ("## Loop gate", "### Setup gap pass", "### PR-end check")
NOT_APPLICABLE: Final[str] = "Not applicable: this PR does not change the roadmap scope."
MISSING_PASS: Final[str] = "Missing: run gap_research.py pass before requesting merge."
NOTHING: Final[str] = "Nothing newly missing."
UNFIXED: Final[str] = "not yet fixed or filed"
MARKER: Final[re.Pattern[str]] = re.compile(r"\b(" + "TO" + "DO|FIX" + "ME|X" + r"XX)\b")
ANY_HEADING: Final[re.Pattern[str]] = re.compile(r"^#{1,6} +\S")
HTML_COMMENT: Final[re.Pattern[str]] = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)  # an unclosed comment hides the rest
LEVEL_TWO: Final[re.Pattern[str]] = re.compile(r"^## ", re.MULTILINE)


def git(repo: Path, *args: str) -> str:
    done: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout


def show(repo: Path, ref: str, path: str) -> str:
    try:
        return git(repo, "show", f"{ref}:{path}")
    except RuntimeError:
        return ""


def changed_files(repo: Path, base: str, head: str, added_only: bool = False) -> list[str]:
    args: list[str] = ["diff", "-z", "--name-only"]
    if added_only:
        args.append("--diff-filter=A")
    return [path for path in git(repo, *args, f"{base}...{head}").split("\0") if path]


def area(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "(root)"


def scope_lines(changed: list[str]) -> list[str]:
    groups: dict[str, int] = {}
    for path in changed:
        groups[area(path)] = groups.get(area(path), 0) + 1
    if not groups:
        return ["Scope: no changed files."]
    parts: str = ", ".join(f"{name} ({count})" for name, count in sorted(groups.items()))
    return [f"Scope: {len(changed)} changed files in {parts}."]


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def open_gap_rows(repo: Path) -> list[dict[str, Any]]:
    try:
        lines: list[str] = (repo / GAPS_REL).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == "gap" and row.get("status") in OPEN_GAP:
            rows.append(row)
    return rows


def roadmap_touched(changed: list[str]) -> bool:
    return any(path in ROADMAP_FILES for path in changed)


def current_key(repo: Path) -> str | None:
    try:
        text: str = (repo / state_io.END_STATE_REL).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return gap_research.scope_key(text)


def setup_section(repo: Path, changed: list[str]) -> list[str]:
    data: dict[str, Any] | None = read_json(repo / PASS_REL)
    if data is None:
        return [MISSING_PASS if roadmap_touched(changed) else NOT_APPLICABLE]
    current: str | None = current_key(repo)
    if current is not None and data.get("key") != current:
        return [f"Stale: gap pass ran for {data.get('key')}, scope is now {current}; re-run gap_research.py pass.",
                MISSING_PASS]
    counts: dict[str, Any] = data.get("counts") or {}
    tally: str = ", ".join(f"{name} {counts[name]}" for name in sorted(counts)) or "none"
    lines: list[str] = [
        f"Gap pass ran {data.get('ran')} for scope {data.get('key')}: {data.get('found', 0)} new, by category {tally}."
    ]
    rows: list[dict[str, Any]] = open_gap_rows(repo)
    if not rows:
        return lines + ["No open gaps: every gap has a disposition."]
    return lines + [f"Open gaps ({len(rows)}):"] + [
        f"- {row.get('id')} [{row.get('category')}] {row.get('text')}" for row in rows
    ]


def runtime_changed(changed: list[str]) -> bool:
    return any(p.startswith(PLUGIN) and not p.startswith(UNSHIPPED) for p in changed)


def test_mentions(repo: Path, changed: list[str], script: str) -> bool:
    name: str = Path(script).name
    stem: str = Path(script).stem
    tests: list[Path] = sorted((repo / PLUGIN / "tests").glob("*.py"))
    tests += [repo / p for p in changed if p.startswith(PLUGIN + "tests/")]
    for path in tests:
        try:
            text: str = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if name in text or stem in text:
            return True
    return False


def untested_scripts(repo: Path, changed: list[str]) -> list[str]:
    prefix: str = PLUGIN + "scripts/"
    scripts: list[str] = [p for p in changed if p.startswith(prefix) and p.endswith(".py") and "/" not in p[len(prefix):]]
    return [
        f"{p} changed with no test that names it"
        for p in scripts
        if (repo / p).exists() and not test_mentions(repo, changed, p)
    ]


def missing_changelog(repo: Path, changed: list[str], head: str) -> list[str]:
    if not runtime_changed(changed):
        return []
    try:
        version: str = str(json.loads(show(repo, head, MANIFEST)).get("version", ""))
    except ValueError:
        version = ""
    heading: re.Pattern[str] = re.compile(rf"^## \[{re.escape(version)}\]", re.MULTILINE)
    if version and heading.search(show(repo, head, CHANGELOG)):
        return []
    return [f"runtime change with no CHANGELOG entry for version {version or '(unreadable)'}"]


def added_markers(repo: Path, base: str, head: str) -> list[str]:
    diff: str = git(repo, "diff", "-U0", f"{base}...{head}")
    found: list[str] = []
    current: str = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and current and not current.startswith(PLUGIN + "tests/") and MARKER.search(line):
            found.append(f"marker line added in {current}: {line[1:].strip()[:100]}")
    return found


def new_names(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    for path in changed_files(repo, base, head, added_only=True):
        parts: list[str] = path.split("/")
        if path.startswith(PLUGIN + "skills/") and parts[-1] == "SKILL.md" and len(parts) == 5:
            names.append((path, parts[3]))
        elif path.startswith(PLUGIN + "scripts/") and path.endswith(".py") and len(parts) == 4:
            names.append((path, parts[-1]))
    return names


def is_doc(path: str) -> bool:
    name: str = Path(path).name
    if not name.endswith(".md"):
        return False
    return name.upper().startswith("README") or ("/" + path).find("/docs/") >= 0


def doc_text(repo: Path, head: str) -> str:
    paths: list[str] = git(repo, "ls-tree", "-r", "--name-only", head).split("\n")
    return "\n".join(show(repo, head, p) for p in paths if p and is_doc(p))


def undocumented(repo: Path, base: str, head: str) -> list[str]:
    names: list[tuple[str, str]] = new_names(repo, base, head)
    if not names:
        return []
    text: str = doc_text(repo, head)
    return [f"{path} is not mentioned in any README or docs page" for path, name in names if name not in text]


def find_items(repo: Path, base: str, head: str, changed: list[str]) -> list[str]:
    return (
        untested_scripts(repo, changed)
        + missing_changelog(repo, changed, head)
        + added_markers(repo, base, head)
        + undocumented(repo, base, head)
    )


def file_item(repo: Path, text: str) -> str:
    script: Path = Path(__file__).resolve().parent / "action-items.py"
    done: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", str(script), str(repo), "add", ITEMS_GROUP, f"{ITEM_PREFIX} {text}"],
        capture_output=True, text=True, check=False,
    )
    try:
        reply: dict[str, Any] = json.loads(done.stdout)
    except ValueError:
        reply = {}
    if done.returncode != 0 or "id" not in reply:
        raise RuntimeError(f"could not file action item: {done.stdout.strip() or done.stderr.strip()}")
    return str(reply["id"])


def filed_items(repo: Path) -> set[str]:
    """Normalised text of the open action items. Only open items are checked, so an item marked done can be filed again."""
    script: Path = Path(__file__).resolve().parent / "action-items.py"
    done: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", str(script), str(repo), "list"], capture_output=True, text=True, check=False
    )
    try:
        listing: Any = json.loads(done.stdout)
    except ValueError:
        listing = None
    items: Any = listing.get("items") if isinstance(listing, dict) else None
    if done.returncode != 0 or not isinstance(items, list):
        raise RuntimeError(f"could not read action items: {done.stdout.strip() or done.stderr.strip()}")
    clean_text = _load.load("action-items").clean_text
    return {clean_text(str(row.get("item"))) for row in items if isinstance(row, dict)}


def end_section(repo: Path, base: str, head: str, changed: list[str], file_items: bool) -> list[str]:
    lines: list[str] = scope_lines(changed)
    items: list[str] = find_items(repo, base, head, changed)
    if not items:
        return lines + [NOTHING]
    out: list[str] = lines + [f"Newly missing ({len(items)}):"]
    already: set[str] = filed_items(repo) if file_items else set()
    clean_text = _load.load("action-items").clean_text
    for item in items:
        status: str = UNFIXED
        if file_items:
            status = "already filed" if clean_text(f"{ITEM_PREFIX} {item}") in already else f"filed as {file_item(repo, item)}"
        out.append(f"- {item} ({status})")
    return out


def render(repo: Path, base: str, head: str, file_items: bool) -> str:
    changed: list[str] = changed_files(repo, base, head)
    parts: list[str] = [HEADINGS[0], "", HEADINGS[1], "", *setup_section(repo, changed), ""]
    parts += [HEADINGS[2], "", *end_section(repo, base, head, changed, file_items), ""]
    return "\n".join(parts)


def section_text(lines: list[str], at: int, to_end: bool) -> bool:
    """True when non-empty text follows line `at`: up to the next heading, or (to_end) any text after it."""
    for line in lines[at + 1:]:
        if ANY_HEADING.match(line):
            if to_end:
                continue
            return False
        if line.strip():
            return True
    return False


def missing_headings(text: str) -> list[str]:
    """Headings of the Loop gate block that are absent or have no text under them (HTML comments are not text)."""
    lines: list[str] = HTML_COMMENT.sub("", text).splitlines()
    missing: list[str] = []
    for heading in HEADINGS:
        at: int | None = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
        if at is None or not section_text(lines, at, to_end=heading == HEADINGS[0]):
            missing.append(heading)
    return missing


def gate_block(text: str) -> str:
    """The text from the "## Loop gate" heading to the next level-2 heading or the end; empty when there is no such heading."""
    start: re.Match[str] | None = re.search(rf"^{re.escape(HEADINGS[0])}[ \t]*$", text, re.MULTILINE)
    if start is None:
        return ""
    after: re.Match[str] | None = LEVEL_TWO.search(text, start.end())
    return text[start.start():after.start() if after else len(text)]


def body_problems(text: str) -> list[str]:
    """Why a PR body fails the Loop gate: missing or empty headings, a missing gap pass, or an unfixed item. Empty when it passes."""
    problems: list[str] = [f"{heading} (absent or empty)" for heading in missing_headings(text)]
    visible: str = gate_block(HTML_COMMENT.sub("", text))
    if MISSING_PASS in visible:
        problems.append(f'the gap pass is missing ("{MISSING_PASS}")')
    if UNFIXED in visible:
        problems.append(f'an item is "{UNFIXED}"')
    return problems


def verify_body(path: Path) -> int:
    try:
        text: str = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    problems: list[str] = body_problems(text)
    if problems:
        print("PR body fails the Loop gate: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    check: argparse.ArgumentParser = sub.add_parser("check")
    check.add_argument("--base", required=True)
    check.add_argument("--head", default="HEAD")
    check.add_argument("--file-items", action="store_true")
    sub.add_parser("verify-body").add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    if args.command == "verify-body":
        return verify_body(Path(args.path))
    try:
        sys.stdout.write(render(Path(args.repo), args.base, args.head, args.file_items))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
