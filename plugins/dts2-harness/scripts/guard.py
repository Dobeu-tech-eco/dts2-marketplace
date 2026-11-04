#!/usr/bin/env python3
"""PreToolUse guards, run as `guard.py --mode son|merge` with the hook payload on stdin.

son: the deny list for a headless son (A8): pushes outside the lane's own branch, merges, non-GET `gh api`, repo deletes,
git config escapes (`git -c`, `core.hooksPath`, `GIT_EXTERNAL_DIFF`), reads of ssh keys, `.env*` and cloud credentials,
and writes to `.claude/`, `.mcp.json` and `.git/hooks`.
merge: the plugin-wide gate (Q-15, G-18): a force-push is always refused; `gh pr merge` into, and `git push` to, a
protected branch is refused unless a lane's merge-go.md names the exact head and the base commit it was cleared against.

A denial is printed as the documented PreToolUse JSON and exits 0; anything the guard cannot parse is allowed through only
when it is not a command the guard watches (fail closed for the watched commands)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from son_launch import merge_config  # noqa: E402
from state_io import append_text  # noqa: E402

LOG_NAME: Final[str] = ".harness/merge-guard.log"
RUNS_DIR: Final[str] = ".harness/runs"
MERGE_GO_NAME: Final[str] = "merge-go.md"
HEAD_LINE: Final[re.Pattern[str]] = re.compile(r"^Verified head:\s*([0-9a-f]{7,40})\s*$", re.M)
BASE_LINE: Final[re.Pattern[str]] = re.compile(r"^Base:\s*(\S+)\s+([0-9a-f]{7,40})\s*$", re.M)
PROTECTED_BRANCHES: Final[frozenset[str]] = frozenset({"main", "master"})
SEGMENT_SPLIT: Final[re.Pattern[str]] = re.compile(r"&&|\|\||(?<![&>])&(?![&>])|[;|\n]")
WRAPPERS: Final[frozenset[str]] = frozenset({"env", "sudo", "command", "exec", "timeout", "time", "nice", "nohup", "stdbuf",
                                             "builtin", "xargs"})
SHELLS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
WATCHED: Final[re.Pattern[str]] = re.compile(r"\b(push|merge|mergePullRequest)\b")
SHELL_C: Final[re.Pattern[str]] = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
FLAG_WITH_VALUE: Final[frozenset[str]] = frozenset({"-s", "-k", "-n", "-o", "-e", "-i", "-u", "-g", "-C", "-I", "-L", "-P",
                                                    "--signal", "--kill-after", "--adjustment", "--unset", "--chdir"})
DURATION: Final[re.Pattern[str]] = re.compile(r"^\d+(\.\d+)?[smhd]?$")
MAX_DEPTH: Final[int] = 4
GH_GLOBAL_VALUE: Final[frozenset[str]] = frozenset({"-R", "--repo", "--hostname"})
MERGE_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email",
                                                      "--match-head-commit", "-R", "--repo"})
PR_URL: Final[re.Pattern[str]] = re.compile(r"^https://[^\s]+/pull/\d+$")
API_MERGE_PATH: Final[re.Pattern[str]] = re.compile(r"/pulls/(\d+)/merge/?$")
SAFE_SRC: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_./@~^][A-Za-z0-9._/@~^-]*$")
GIT_TIMEOUT_S: Final[int] = 20
FORCE_FLAGS: Final[frozenset[str]] = frozenset({"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror",
                                                "--delete", "-d", "--prune", "--all"})
SECRET_DIRS: Final[frozenset[str]] = frozenset({".ssh", ".aws", ".azure", ".kube", ".gnupg", ".docker"})
SECRET_FILES: Final[frozenset[str]] = frozenset({".netrc", "credentials.json", "application_default_credentials.json",
                                                 "id_rsa", "id_ed25519", "id_ecdsa"})
ENV_OK: Final[frozenset[str]] = frozenset({".env.example", ".env.sample", ".env.template", ".env.dist"})
WRITE_COMMANDS: Final[frozenset[str]] = frozenset({"tee", "cp", "mv", "rm", "sed", "ln", "chmod", "install", "touch",
                                                   "truncate", "dd", "perl", "python", "python3", "node", "ruby"})
WRITE_TOOLS: Final[frozenset[str]] = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})
READ_TOOLS: Final[frozenset[str]] = frozenset({"Read", "Glob", "Grep"})
PATH_KEYS: Final[tuple[str, ...]] = ("file_path", "path", "notebook_path")
GH_BODY_FLAGS: Final[frozenset[str]] = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})
GH_METHOD_FLAGS: Final[frozenset[str]] = frozenset({"-X", "--method"})
CONFIG_ESCAPES: Final[tuple[str, ...]] = ("core.hookspath", "git_external_diff")
SAFE_REF: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._/@-]+$")


def binary(name: str, default: str) -> list[str]:
    value: str = os.environ.get(name, default)
    return [sys.executable, value] if value.endswith(".py") else [value]


def run(cmd: list[str], cwd: Path) -> str | None:
    """stdout of a command, or None on any failure (the callers fail closed)."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def substitutions(text: str) -> list[str]:
    """Inner texts of `$(...)` (balanced) and backtick pairs, so commands hidden in them are checked too."""
    found: list[str] = []
    pos: int = 0
    while (start := text.find("$(", pos)) != -1:
        depth, k = 1, start + 2
        while k < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[k], 0)
            k += 1
        found.append(text[start + 2:k - 1 if depth == 0 else k])
        pos = start + 2
    found += re.findall(r"`([^`]*)`", text)
    return found


def strip_wrappers(words: list[str]) -> list[str]:
    """Drop env assignments and the wrappers Claude Code strips (`timeout N`, `time`, `nice`, `nohup`, `stdbuf`, `builtin`,
    bare `xargs`) and their flags, leaving the command that actually runs."""
    while words:
        head: str = Path(words[0]).name
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        elif head in WRAPPERS:
            words = words[1:]
            while words and (words[0].startswith("-") or (head in ("timeout", "nice") and DURATION.match(words[0]))
                             or (head == "env" and "=" in words[0])):
                words = words[2:] if words[0] in FLAG_WITH_VALUE else words[1:]
        else:
            break
    return words


def segments(command: str, _depth: int = 0) -> list[list[str]]:
    """Each simple command of a shell line as its words: split on `;`, `&&`, `||`, `|`, `&` and newlines, with leading
    `(` / `{` and wrappers stripped, and the text of `bash -c`, `sh -c`, `eval`, `$(...)` and backticks checked too. A
    segment that does not parse becomes its raw words, so it is still checked. See `parse_failed` for the fail-closed case."""
    found: list[list[str]] = []
    if _depth > MAX_DEPTH:
        return found
    for inner in substitutions(command):
        found += segments(inner, _depth + 1)
    for part in SEGMENT_SPLIT.split(command):
        part = part.strip().lstrip("({ \t").rstrip(")} \t")
        try:
            words: list[str] = shlex.split(part)
        except ValueError:
            words = part.split()
        words = strip_wrappers(words)
        if not words:
            continue
        found.append(words)
        head: str = Path(words[0]).name
        if head == "eval":
            found += segments(" ".join(words[1:]), _depth + 1)
        elif head in SHELLS:
            flags = [i for i, w in enumerate(words[1:], 1) if SHELL_C.match(w)]
            if flags and flags[0] + 1 < len(words):
                found += segments(words[flags[0] + 1], _depth + 1)
    return found


def parse_failed(command: str) -> bool:
    """True when a line names a watched word (push, merge) but a part of it cannot be parsed, or nesting runs too deep."""
    if not WATCHED.search(command):
        return False
    return unparsable(command, 0)


def unparsable(command: str, depth: int) -> bool:
    if depth > MAX_DEPTH:
        return True
    for inner in substitutions(command):
        if unparsable(inner, depth + 1):
            return True
    for part in SEGMENT_SPLIT.split(command):
        part = part.strip().lstrip("({ \t").rstrip(")} \t")
        try:
            shlex.split(part)
        except ValueError:
            return True
    return False


def norm_path(raw: str) -> list[str]:
    expanded: str = os.path.expanduser(raw).replace("\\", "/")
    return [p for p in PurePosixPath(os.path.normpath(expanded)).parts if p not in ("/", ".")]


def is_secret_path(raw: str) -> bool:
    parts: list[str] = norm_path(raw)
    if not parts:
        return False
    name: str = parts[-1]
    if any(p in SECRET_DIRS for p in parts) or name in SECRET_FILES:
        return True
    if ".config" in parts and "gcloud" in parts[parts.index(".config"):]:
        return True
    return (name == ".env" or name.startswith(".env.")) and name not in ENV_OK


def is_protected_write(raw: str) -> bool:
    parts: list[str] = norm_path(raw)
    if ".claude" in parts or (parts and parts[-1] in (".mcp.json", MERGE_GO_NAME)):
        return True
    return any(parts[i] == ".git" and parts[i + 1] == "hooks" for i in range(len(parts) - 1))


def looks_like_path(word: str) -> bool:
    return not word.startswith("-") or "=" in word


def path_words(words: list[str]) -> list[str]:
    """Words that can name a path, including the value after `--flag=`, `>` and `>>`."""
    found: list[str] = []
    for word in words:
        value: str = word.split("=", 1)[1] if word.startswith("--") and "=" in word else word
        found += [piece.lstrip("&") for piece in re.split(r"[<>]+", value)]
    return [w for w in found if w]


def gh_words(words: list[str]) -> tuple[list[str], str]:
    """(the words after `gh` with its global flags skipped, the --repo value). `gh -R o/r pr merge 3` is `pr merge 3`."""
    rest: list[str] = words[1:]
    repo: str = ""
    while rest and rest[0].startswith("-"):
        flag: str = rest[0].split("=", 1)[0]
        if flag in GH_GLOBAL_VALUE:
            value: str = rest[0].split("=", 1)[1] if "=" in rest[0] else (rest[1] if len(rest) > 1 else "")
            repo = value if flag in ("-R", "--repo") else repo
            rest = rest[1:] if "=" in rest[0] else rest[2:]
        else:
            rest = rest[1:]
    return rest, repo


def gh_api_denial(words: list[str]) -> str | None:
    method: str = "GET"
    for i, word in enumerate(words):
        if word in GH_METHOD_FLAGS and i + 1 < len(words):
            method = words[i + 1].upper()
        elif word.startswith("--method="):
            method = word.split("=", 1)[1].upper()
        elif word.startswith("-X") and len(word) > 2:
            method = word[2:].upper()
        elif word in GH_BODY_FLAGS and method == "GET":
            method = "POST"
    return None if method == "GET" else f"gh api with method {method} is denied for a son"


def git_subcommand(words: list[str]) -> tuple[str | None, list[str], bool]:
    """(subcommand, its arguments, whether a global -c / --config-env came before it)."""
    config: bool = False
    i: int = 1
    while i < len(words):
        word: str = words[i]
        if word == "-c" or word.startswith("--config-env"):
            config = True
        if word in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
            continue
        if word.startswith("-"):
            i += 1
            continue
        return word, words[i + 1:], config
    return None, [], config


def is_force(args: list[str]) -> bool:
    return any(a in FORCE_FLAGS or a.startswith(("--force", "--delete")) or (a.startswith("+") and len(a) > 1)
               or (a.startswith(":") and len(a) > 1) or re.match(r"^-[a-z]*f[a-z]*$", a) is not None for a in args)


def push_targets(args: list[str]) -> list[str]:
    """Destination branch names named on a `git push` line (the refspec's right side)."""
    plain: list[str] = [a for a in args if not a.startswith("-")]
    specs: list[str] = plain[1:]
    return [s.split(":", 1)[-1].removeprefix("refs/heads/") for s in specs]


def son_bash_denial(words: list[str], prefix: str) -> str | None:
    head: str = Path(words[0]).name
    if head == "git":
        sub, args, config = git_subcommand(words)
        if config:
            return "git -c / --config-env can switch hooks or external tools on and is denied for a son"
        if sub == "push":
            if is_force(args):
                return "a son never force-pushes or deletes remote refs"
            targets: list[str] = push_targets(args)
            if not prefix or not targets or any(not own_branch(t, prefix) for t in targets):
                return f"a son may push only its own lane branch ({prefix or 'none set'}*)"
    if head == "gh":
        rest, _repo = gh_words(words)
        if rest[:2] == ["pr", "merge"]:
            return "a son never merges; the head merges after merge-go"
        if rest[:2] == ["repo", "delete"]:
            return "gh repo delete is denied"
        if rest[:1] == ["api"]:
            return gh_api_denial(rest[1:])
    if head == "python3" or head == "python":
        lanes_cmd = " ".join(words[1:])
        if re.search(r"lanes\.py.*\b(merge-go|merge-target)\b", lanes_cmd):
            return "merge-go and merge-target are the head's alone"
    return None


def own_branch(target: str, prefix: str) -> bool:
    """The lane's own branch or one of its builder branches (`<prefix>-b1`), never a sibling lane that shares the prefix."""
    return target == prefix or target.startswith(prefix + "-")


def son_path_denial(tool: str, tool_input: dict[str, Any], command: str, prefix: str) -> str | None:
    lowered: str = command.lower()
    if any(token in lowered for token in CONFIG_ESCAPES):
        return "core.hooksPath and GIT_EXTERNAL_DIFF are denied for a son"
    paths: list[str] = [str(tool_input[k]) for k in PATH_KEYS if isinstance(tool_input.get(k), str)]
    if tool in READ_TOOLS | WRITE_TOOLS and any(is_secret_path(p) for p in paths):
        return "reading credentials (ssh keys, .env files, cloud credential paths) is denied for a son"
    if tool in WRITE_TOOLS and any(is_protected_write(p) for p in paths):
        return "writing .claude/, .mcp.json, merge-go.md or .git/hooks is denied for a son"
    for words in segments(command) if tool == "Bash" else []:
        flat: list[str] = path_words(words)
        if any(is_secret_path(w) for w in flat if looks_like_path(w)):
            return "reading credentials (ssh keys, .env files, cloud credential paths) is denied for a son"
        writes: bool = Path(words[0]).name in WRITE_COMMANDS or any(">" in w for w in words)
        if writes and any(is_protected_write(w) for w in flat if looks_like_path(w)):
            return "writing .claude/, .mcp.json, merge-go.md or .git/hooks is denied for a son"
    return None


def son_denial(payload: dict[str, Any], prefix: str) -> str | None:
    tool: str = str(payload.get("tool_name", ""))
    tool_input: Any = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command: str = str(tool_input.get("command", "")) if tool == "Bash" else ""
    reason: str | None = son_path_denial(tool, tool_input, command, prefix)
    if reason is not None:
        return reason
    if tool == "Bash" and parse_failed(command):
        return "a command naming push or merge could not be parsed, so the guard denies it"
    for words in segments(command):
        reason = son_bash_denial(words, prefix)
        if reason is not None:
            return reason
    return None


def grants(cwd: Path) -> list[dict[str, str]]:
    """Every merge-go.md under the runs dir as {head, base_ref, base_sha}."""
    found: list[dict[str, str]] = []
    for path in sorted((cwd / RUNS_DIR).glob(f"*/*/{MERGE_GO_NAME}")):
        try:
            text: str = path.read_text(encoding="utf-8")
        except OSError:
            continue
        head, base = HEAD_LINE.search(text), BASE_LINE.search(text)
        if head and base:
            found.append({"head": head.group(1), "base_ref": base.group(1), "base_sha": base.group(2)})
    return found


def authorized(cwd: Path, head: str | None, branch: str) -> str | None:
    """None when a merge-go names this head and the base commit still at the tip of `branch`; else why not."""
    if not head:
        return "the head commit cannot be read, so no merge-go can be matched"
    tip: str | None = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", f"refs/remotes/origin/{branch}"], cwd)
    for grant in grants(cwd):
        if not head.startswith(grant["head"]) and not grant["head"].startswith(head):
            continue
        if grant["base_ref"] != branch:
            continue
        if tip is None:
            return f"cannot read origin/{branch}, so the approved base {grant['base_sha'][:10]} cannot be checked"
        if tip.startswith(grant["base_sha"]) or grant["base_sha"].startswith(tip):
            return None
        return (f"origin/{branch} moved from the approved base {grant['base_sha'][:10]} to {tip[:10]}; "
                "rebase, re-verify and ask the head for a new merge-go")
    return f"no merge-go.md names head {head[:10]} for {branch}; the head grants it with lanes.py merge-go"


def pr_facts(selector: str, cwd: Path, repo: str = "") -> tuple[str | None, str | None]:
    """(base branch, head sha) of the PR a `gh pr merge` names; (None, None) when gh cannot say."""
    cmd: list[str] = [*binary("DTS2_GH_BIN", "gh"), "pr", "view", *([selector] if selector else []),
                      *(["--repo", repo] if repo else []), "--json", "baseRefName,headRefOid"]
    raw: str | None = run(cmd, cwd)
    try:
        data: Any = json.loads(raw) if raw else {}
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    base, head = data.get("baseRefName"), data.get("headRefOid")
    return (base if isinstance(base, str) else None, head if isinstance(head, str) else None)


def merge_selector(args: list[str]) -> str | None:
    """The PR a `gh pr merge` names: "" for the current branch's PR (no positional), a number, branch or PR URL, or None when
    a positional argument exists but is not safe (the caller fails closed instead of guessing)."""
    plain: list[str] = []
    skip: bool = False
    for arg in args:
        if skip:
            skip = False
        elif arg in MERGE_VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-"):
            plain.append(arg)
    if not plain:
        return ""
    return plain[0] if SAFE_REF.match(plain[0]) or PR_URL.match(plain[0]) else None


def protected_branches(cwd: Path) -> set[str]:
    """main, master, the configured default branch, every `Base:` branch in a grant, and (once a lanes run exists) the
    configured and recorded merge target, so the base check also covers the default `dev` target of a run."""
    config: dict[str, str] = merge_config(cwd)
    found: set[str] = {*PROTECTED_BRANCHES, config["default_branch"], *(g["base_ref"] for g in grants(cwd))}
    runs: Path = cwd / RUNS_DIR
    if any(runs.glob("*/*/status.json")) or any(runs.glob("*/*/merge-go.md")):
        found.add(config["target"])
    for path in runs.glob("*/merge-target.txt"):
        try:
            target: str = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if SAFE_REF.match(target):
            found.add(target)
    return found


def gate_pr(selector: str, repo: str, cwd: Path) -> str | None:
    base, sha = pr_facts(selector, cwd, repo)
    if base is None:
        return "cannot tell which branch this PR merges into; the merge gate fails closed"
    if base not in protected_branches(cwd):
        return None
    return authorized(cwd, sha, base)


def api_merge_denial(rest: list[str], cwd: Path) -> str | None:
    """`gh api` calls that merge: a non-GET on .../pulls/<n>/merge is gated like `gh pr merge <n>`; a graphql
    mergePullRequest cannot be matched to a PR and is denied."""
    text: str = " ".join(rest)
    if "mergePullRequest" in text or "enablePullRequestAutoMerge" in text:
        return "a graphql merge cannot be matched to a merge-go; use `gh pr merge` so the guard can check it"
    method: str = gh_api_denial(rest[1:]) or ""
    found = API_MERGE_PATH.search(next((w for w in rest[1:] if "/pulls/" in w), ""))
    if found and method:
        return gate_pr(found.group(1), "", cwd)
    return None


def git_ref_sha(ref: str, cwd: Path) -> str | None:
    if not SAFE_SRC.match(ref):
        return None
    out: str | None = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", f"{ref}^{{commit}}"], cwd)
    return out or None


def push_refspecs(args: list[str], current: str) -> list[tuple[str, str]]:
    """(source ref, destination branch) for each refspec of a push; no refspec pushes the current branch, and a bare
    name pushes the same name."""
    plain: list[str] = [a for a in args if not a.startswith("-")]
    specs: list[str] = plain[1:] or [current]
    pairs: list[tuple[str, str]] = []
    for spec in specs:
        src, _, dst = spec.lstrip("+").partition(":")
        dst = (dst or src).removeprefix("refs/heads/")
        pairs.append((src, current if dst == "HEAD" else dst))
    return pairs


def push_denial(args: list[str], cwd: Path) -> str | None:
    if is_force(args):
        return "force-push is refused; open a normal commit instead"
    current: str = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", "--abbrev-ref", "HEAD"], cwd) or ""
    if not current and not [a for a in args if not a.startswith("-")][1:]:
        return "cannot tell which branch this push sends; the merge gate fails closed"
    protected: set[str] = protected_branches(cwd)
    for src, dst in push_refspecs(args, current):
        if dst not in protected:
            continue
        reason: str | None = authorized(cwd, git_ref_sha(src or "HEAD", cwd), dst)
        if reason is not None:
            return reason
    return None


def merge_bash_denial(words: list[str], cwd: Path) -> str | None:
    head: str = Path(words[0]).name
    if head == "gh":
        rest, repo = gh_words(words)
        if rest[:2] == ["pr", "merge"]:
            selector: str | None = merge_selector(rest[2:])
            if selector is None:
                return "the PR argument of this merge is not a number, branch or PR URL; the merge gate fails closed"
            return gate_pr(selector, repo, cwd)
        if rest[:1] == ["api"]:
            return api_merge_denial(rest, cwd)
        return None
    if head == "git":
        sub, args, _ = git_subcommand(words)
        return push_denial(args, cwd) if sub == "push" else None
    return None


def merge_denial(payload: dict[str, Any], cwd: Path) -> str | None:
    tool_input: Any = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return None
    command: str = str(tool_input.get("command", ""))
    if parse_failed(command):
        return "a command naming push or merge could not be parsed, so the merge gate denies it"
    for words in segments(command):
        reason: str | None = merge_bash_denial(words, cwd)
        if reason is not None:
            return reason
    return None


def deny_output(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": f"dts2-harness guard: {reason}"}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("son", "merge"), required=True)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()
    try:
        payload: Any = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd: Path = Path(args.cwd)
    reason: str | None = (son_denial(payload, os.environ.get("DTS2_SON_BRANCH_PREFIX", "")) if args.mode == "son"
                          else merge_denial(payload, cwd))
    if reason is not None:
        print(deny_output(reason))
        if args.mode == "merge":
            command: str = str((payload.get("tool_input") or {}).get("command", ""))[:300]
            append_text(cwd / LOG_NAME, json.dumps({"event": "denied", "reason": reason, "command": command}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
