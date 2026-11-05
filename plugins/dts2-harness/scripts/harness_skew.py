"""Harness version checks that read state only: live lane leases (G-76), son-versus-head plugin version skew (G-76) and the
marketplace repo named by the plugin itself (G-77, so no org string is hard-coded in a script)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proc  # noqa: E402
import state_io  # noqa: E402
from lanes.common import lease_live  # noqa: E402
from lanes.leases import read_lease  # noqa: E402

PLUGIN_JSON_REL: Final[tuple[str, ...]] = (".claude-plugin", "plugin.json")
REASON_SKEW: Final[str] = "version-skew"  # the same park reason as a claude CLI skew (lanes.common.REASON_SKEW)
MARKETPLACE_ENV: Final[str] = "DTS2_MARKETPLACE_REPO"
GITHUB_REPO: Final[re.Pattern[str]] = re.compile(r"github\.com[:/]([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*?)(?:\.git)?/?$", re.ASCII)
OWNER_REPO: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*", re.ASCII)
GIT_TIMEOUT_S: Final[int] = 10


def live_leases(repo: Path, now: int) -> list[str]:
    """`<stamp>/<lane>` of every live lease under the repo's runs folder. Read-only: nothing is renewed or closed."""
    runs: Path = repo / state_io.RUNS_REL
    held: list[str] = []
    for path in sorted(runs.glob(f"*/*/{state_io.LEASE_NAME}")):
        if lease_live(read_lease(path), now):
            held.append(f"{path.parent.parent.name}/{path.parent.name}")
    return held


def plugin_version(root: Path) -> str | None:
    try:
        data: Any = json.loads(root.joinpath(*PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version: Any = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) and version else None


def skew_problem(head_root: Path, son_root: Path) -> str | None:
    """A reason string when the son's plugin.json version differs from the head's, else None. An unreadable version on
    either side is a mismatch too: a son that cannot prove its version does not run."""
    head, son = plugin_version(head_root), plugin_version(son_root)
    if head is None or son is None:
        return f"plugin.json version unreadable (head {head or 'unknown'}, son {son or 'unknown'})"
    if head != son:
        return f"son harness is {son}, the head is {head}"
    return None


def repo_from_url(url: str) -> str | None:
    match = GITHUB_REPO.search(url.strip())
    return match.group(1) if match else None


def marketplace_repo(plugin_root: Path) -> str | None:
    """owner/repo of the marketplace: the env override, else the `repository` field of the plugin's own plugin.json, else
    the plugin checkout's `git remote get-url origin`. None when none of them names a GitHub repo."""
    override: str = os.environ.get(MARKETPLACE_ENV, "").strip()
    if override and OWNER_REPO.fullmatch(override):
        return override
    try:
        data: Any = json.loads(plugin_root.joinpath(*PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    named: str | None = repo_from_url(str(data.get("repository", ""))) if isinstance(data, dict) else None
    if named:
        return named
    code, out = proc.run([*proc.binary("DTS2_GIT_BIN", "git"), "-C", str(plugin_root), "remote", "get-url", "origin"], plugin_root, timeout_s=GIT_TIMEOUT_S)
    return repo_from_url(out) if code == 0 else None
