#!/usr/bin/env python3
"""PostToolUse PR-receipt hook body (hooks/pr-receipt.sh passes the payload on stdin after its cheap prefilter).

On `gh pr create|edit` (or `gh api .../pulls -X POST`) make sure the PR body has a change receipt and the repo's PR template
has the section. Never blocks: every failure goes to stderr and the exit code is 0. DTS2_GH_BIN overrides the gh binary.
The `git push` is the plugin's one deliberate push, limited to the PR's own head branch, and only with
pr_receipt_template_push: true outside son mode."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import pr_payload  # noqa: E402
import state_io  # noqa: E402

PLUGIN_DIR: Final[Path] = SCRIPT_DIR.parent
RECEIPT_MARKER: Final[str] = "## Change receipt"
ORG_TEMPLATE_PATH: Final[str] = ".github/pull_request_template.md"
ORG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
ORG_LINE: Final[re.Pattern[str]] = re.compile(r"^org:[ \t\r\n\f\v]*([^ \t\r\n\f\v#]*)")
LOCAL_TEMPLATE: Final[str] = ".github/pull_request_template.md"
COMMIT_MESSAGE: Final[str] = "chore: add change receipt to PR template"
STAMP_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{8}-[0-9]{1,6}$")  # same shape as state_ids.STAMP_PATTERN
BRANCH_STAMP_RE: Final[re.Pattern[str]] = re.compile(r"^dts2/([0-9]{8}-[0-9]{1,6})/")
VIEW_FIELDS: Final[str] = "number,body,headRefName,isCrossRepository,headRepositoryOwner,baseRepository"
ENCODING: Final[str] = "utf-8"
ERRORS: Final[str] = "surrogateescape"
RECEIPT_TEMPLATE: Final[Path] = PLUGIN_DIR / "templates" / "receipt.md"
PR_TEMPLATE: Final[Path] = PLUGIN_DIR / "templates" / "pr-template.md"
SETTINGS_KEY: Final[str] = "pr_receipt_template_push"


def warn(message: str) -> None:
    print(f"dts2-harness pr-receipt: {message}", file=sys.stderr)


def gh_bin() -> str:
    return os.environ.get("DTS2_GH_BIN") or "gh"


def tmp_dir() -> str:
    return os.environ.get("TMPDIR") or "/tmp"


def read(path: Path | str) -> str:
    return Path(path).read_text(encoding=ENCODING, errors=ERRORS)


def branch_receipt(branch: str) -> Path | None:
    """The receipt for a dts2/<stamp>/... branch: plain, ship-<stamp> or lane folder."""
    match = BRANCH_STAMP_RE.match(branch)
    if not match:
        return None
    stamp: str = match.group(1)
    runs: Path = Path(state_io.RUNS_REL)
    lane: str = branch.rsplit("/lane-", 1)[1] if "/lane-" in branch else ""
    candidates: list[Path] = ([runs / stamp / lane / "receipt.md"] if lane else [])
    candidates += [runs / stamp / "receipt.md", runs / f"ship-{stamp}" / "receipt.md"]
    return next((c for c in candidates if c.is_file()), None)


def newest_receipt() -> Path | None:
    """Newest run folder holding a receipt: stamped runs (and ship-<stamp>) first, any other name only when none is stamped."""
    runs: Path = Path(state_io.RUNS_REL)
    best_key: str = ""
    best: Path | None = None
    folders: list[Path] = sorted(p for p in runs.glob("*") if p.is_dir()) if runs.is_dir() else []
    for folder in folders:
        if not (folder / "receipt.md").is_file():
            continue
        name: str = folder.name.removeprefix("ship-")
        key: str = ("1" if STAMP_RE.match(name) else "0") + name
        if not best_key or key > best_key:
            best_key, best = key, folder / "receipt.md"
    return best


def fallback_receipt() -> str:
    """Template receipt with the tests table replaced by "not recorded"."""
    try:
        lines: list[str] = read(RECEIPT_TEMPLATE).splitlines()
    except OSError:
        return ""
    out: list[str] = []
    skip: bool = False
    for line in lines:
        if line.startswith("### Tests run"):
            out += [line, "", "not recorded", ""]
            skip = True
            continue
        if line.startswith("### "):
            skip = False
        if not skip:
            out.append(line)
    return "".join(f"{line}\n" for line in out)


def build_receipt(branch: str) -> str:
    found: Path | None = branch_receipt(branch) or newest_receipt()
    return read(found) if found else fallback_receipt()


def add_receipt_to_pr(number: str, body: str, branch: str) -> None:
    text: str = pr_payload.body_with_receipt(body, build_receipt(branch))
    try:
        handle, name = tempfile.mkstemp(prefix="dts2-pr-body.", dir=tmp_dir())
    except OSError:
        warn("cannot create temp file")
        return
    try:
        with os.fdopen(handle, "w", encoding=ENCODING, errors=ERRORS) as stream:
            stream.write(text)
        done = subprocess.run([gh_bin(), "pr", "edit", number, "--body-file", name], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, check=False)
        if done.returncode != 0:
            warn(f"gh pr edit failed for PR #{number}")
    finally:
        Path(name).unlink(missing_ok=True)


def resolve_org() -> str:
    """Org that owns the shared `.github` repo: DTS2_PR_ORG, then `org:` in the harness config, then the current repo's owner."""
    org: str = os.environ.get("DTS2_PR_ORG", "")
    config: Path = Path(state_io.CONFIG_REL)
    if not org and config.is_file():
        for line in read(config).splitlines():
            match = ORG_LINE.match(line)
            if match:
                org = match.group(1)
                break
    if not org:
        try:
            done = subprocess.run([gh_bin(), "repo", "view", "--json", "owner", "--jq", ".owner.login"], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, errors=ERRORS, check=False)
            lines: list[str] = done.stdout.splitlines()
            org = lines[0] if lines else ""
        except OSError:
            org = ""
    return org if ORG_PATTERN.match(org) else ""


def org_has_receipt(session: str) -> bool:
    """Caches only a definitive answer: the template exists (yes/no section) or the API said 404."""
    org: str = resolve_org()
    if not org:
        return False
    cache: Path = Path(tmp_dir()) / f"dts2-org-template.{org}.{session}.cache"
    if cache.is_file():
        return read(cache).rstrip("\n") == "yes"
    try:
        done = subprocess.run([gh_bin(), "api", f"repos/{org}/.github/contents/{ORG_TEMPLATE_PATH}", "-H",
                               "Accept: application/vnd.github.raw"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              errors=ERRORS, check=False)
    except OSError:
        return False
    answer: str = ""
    found: bool = False
    if done.returncode == 0:
        found = RECEIPT_MARKER in done.stdout
        answer = "yes" if found else "no"
    elif re.search(r"not found|404", done.stderr, re.IGNORECASE):
        answer = "no"
    if answer:
        try:
            cache.write_text(answer + "\n", encoding=ENCODING)
        except OSError:
            pass
    return found


def repo_has_receipt() -> bool:
    path: Path = Path(LOCAL_TEMPLATE)
    return path.is_file() and RECEIPT_MARKER in read(path)


def write_template() -> None:
    target: Path = Path(LOCAL_TEMPLATE)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        addition: str = "\n" + read(RECEIPT_TEMPLATE)
        with target.open("a", encoding=ENCODING, errors=ERRORS) as stream:
            stream.write(addition)
    else:
        shutil.copyfile(PR_TEMPLATE, target)


def template_push_enabled() -> bool:
    if os.environ.get("DTS2_SON") or os.environ.get("DTS2_SON_BRANCH_PREFIX"):
        return False
    from lanes.planner import read_setting  # noqa: PLC0415 - only the push path needs it
    return read_setting(Path.cwd(), SETTINGS_KEY, "false") == "true"


def can_push_branch(branch: str, cross: str) -> bool:
    if not branch or cross == "true":
        return False
    done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)
    return done.stdout.rstrip("\n") == branch


def git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], stdin=subprocess.DEVNULL, check=False).returncode == 0


def ensure_template(session: str, branch: str, cross: str) -> None:
    if repo_has_receipt() or org_has_receipt(session):
        return
    try:
        write_template()
    except OSError:
        warn(f"cannot write {LOCAL_TEMPLATE}")
        return
    if not git_ok("add", LOCAL_TEMPLATE):
        warn("git add failed")
        return
    if not can_push_branch(branch, cross):
        print(f"pr-receipt: PR template staged; commit and push it to {branch or 'the PR branch'} yourself "
              "(branch mismatch or fork PR)", file=sys.stderr)
        return
    if not template_push_enabled():
        print("pr-receipt: PR template staged; commit and push it yourself "
              "(set pr_receipt_template_push: true to let the hook do it)", file=sys.stderr)
        return
    if not git_ok("commit", "-q", "-m", COMMIT_MESSAGE, "--", LOCAL_TEMPLATE):
        warn("git commit failed")
        return
    if not git_ok("push", "-q", "origin", f"HEAD:refs/heads/{branch}"):
        warn(f"git push origin {branch} failed")


def main() -> None:
    payload: str = sys.stdin.read()
    data = pr_payload.load(payload)
    parsed = pr_payload.parse_payload(data) or pr_payload.parse_api_payload(data)
    if parsed is None:
        return
    session, selector = parsed
    gh: str = gh_bin()
    if shutil.which(gh) is None:
        warn(f"gh not found ({gh}); skipping")
        return
    cmd: list[str] = [gh, "pr", "view", *([selector] if selector else []), "--json", VIEW_FIELDS]
    done = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, errors=ERRORS, check=False)
    if done.returncode != 0:
        warn("gh pr view failed")
        return
    fields = pr_payload.view_fields(pr_payload.load(done.stdout))
    if fields is None:
        warn("could not parse gh pr view output; leaving PR untouched")
        return
    body: str = fields["body"].rstrip("\n")
    if RECEIPT_MARKER not in body:
        add_receipt_to_pr(fields["number"], body, fields["branch"])
    ensure_template(session, fields["branch"], fields["cross"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - the hook never blocks a tool call
        warn(f"unexpected error: {error}")
    sys.exit(0)
