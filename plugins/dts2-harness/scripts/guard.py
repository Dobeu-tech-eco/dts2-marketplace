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
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from son_launch import merge_config  # noqa: E402
from state_io import MERGE_GUARD_LOG_REL, RUNS_REL, append_text  # noqa: E402

LOG_NAME: Final[str] = MERGE_GUARD_LOG_REL
RUNS_DIR: Final[str] = RUNS_REL
MERGE_GO_NAME: Final[str] = "merge-go.md"
HEAD_LINE: Final[re.Pattern[str]] = re.compile(r"^Verified head:\s*([0-9a-f]{7,40})\s*$", re.M)
BASE_LINE: Final[re.Pattern[str]] = re.compile(r"^Base:\s*(\S+)\s+([0-9a-f]{7,40})\s*$", re.M)
PROTECTED_BRANCHES: Final[frozenset[str]] = frozenset({"main", "master"})
SEGMENT_SPLIT: Final[re.Pattern[str]] = re.compile(r"&&|\|\||(?<![&>])&(?![&>])|[;|\n]")
WRAPPERS: Final[frozenset[str]] = frozenset({"env", "sudo", "command", "exec", "timeout", "time", "nice", "nohup", "stdbuf",
                                             "builtin", "xargs"})
SHELLS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
WATCHED: Final[re.Pattern[str]] = re.compile(r"\b(push|merge|mergePullRequest)\b")
RESERVED: Final[frozenset[str]] = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "in",
                                             "case", "esac", "select", "!", "{", "}", "function"})  # `time` is a wrapper
DEF_OPEN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:+-]*\(\)\{?$")
GLOB_CHARS: Final[frozenset[str]] = frozenset("{}*?[")
GH_API_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-f", "-F", "-H", "-X", "-q", "-t", "-p", "--field", "--raw-field", "--header",
                                                       "--method", "--jq", "--template", "--input", "--hostname", "--cache",
                                                       "--preview"})
GIT_BUILTINS: Final[frozenset[str]] = frozenset("""add am annotate apply archive bisect blame branch bundle cat-file checkout
cherry cherry-pick clean clone commit config count-objects describe diff difftool fetch filter-branch for-each-ref format-patch
fsck gc grep hash-object help init log ls-files ls-remote ls-tree maintenance merge merge-base merge-file merge-tree mergetool
mv name-rev notes pull push range-diff read-tree rebase reflog remote repack replace request-pull reset restore rev-list
rev-parse revert rm send-email shortlog show show-branch show-ref sparse-checkout stash status submodule switch symbolic-ref tag
update-index update-ref var verify-commit verify-tag version whatchanged worktree write-tree""".split())
PROTECTED_API: Final[tuple[str, ...]] = ("/merges", "/git/refs", "/branches/", "/contents/")
SHELL_C: Final[re.Pattern[str]] = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
FLAG_WITH_VALUE: Final[frozenset[str]] = frozenset({"-s", "-k", "-n", "-o", "-e", "-i", "-u", "-g", "-C", "-I", "-L", "-P",
                                                    "--signal", "--kill-after", "--adjustment", "--unset", "--chdir"})
ENV_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-u", "-C", "-S", "--unset", "--chdir", "--split-string"})  # env's own; `-i` takes none
DURATION: Final[re.Pattern[str]] = re.compile(r"^\d+(\.\d+)?[smhd]?$")
MAX_DEPTH: Final[int] = 4
GH_GLOBAL_VALUE: Final[frozenset[str]] = frozenset({"-R", "--repo", "--hostname"})
MERGE_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email",
                                                      "--match-head-commit", "-R", "--repo"})
PR_URL: Final[re.Pattern[str]] = re.compile(r"^https://[^\s]+/pull/\d+$")
API_MERGE_PATH: Final[re.Pattern[str]] = re.compile(r"/pulls/(\d+)/merge/?(?:[?#].*)?$")
API_REPO_PATH: Final[re.Pattern[str]] = re.compile(r"(?:^|/)repos/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/pulls/")
API_FILE_FIELD: Final[re.Pattern[str]] = re.compile(r"^[^=\s]+=@")
GRANT_COMMANDS: Final[frozenset[str]] = frozenset({"merge-go", "merge-go-step", "merge-target", "gc-restore"})
BODY_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email"})
STATUS_NAME: Final[str] = "status.json"
PENDING_NAME: Final[str] = "merge-pending.txt"
DONE_PHASE: Final[str] = "done"
SAFE_SRC: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_./@~^][A-Za-z0-9._/@~^-]*$")
GIT_TIMEOUT_S: Final[int] = 10
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


def join_continuations(text: str) -> str:
    """Remove backslash-newline pairs outside single quotes, the way the shell joins a continued line."""
    out: list[str] = []
    quote: str = ""
    i: int = 0
    while i < len(text):
        c: str = text[i]
        if quote == "'":
            quote = "" if c == "'" else quote
        elif c == "\\" and i + 1 < len(text):
            if text[i + 1] == "\n":
                i += 2
                continue
            out.append(c)
            i += 1
            c = text[i]
        elif c in "'\"":
            quote = c if quote != c else ""
        out.append(c)
        i += 1
    return "".join(out)


def watched(command: str) -> bool:
    """True when a line names push / merge, also through a continuation, quote or backslash split (`pu""sh`, `mer\\ge`)."""
    joined: str = join_continuations(command)
    return WATCHED.search(joined) is not None or WATCHED.search(re.sub(r"[\\'\"]", "", joined)) is not None


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


def strip_wrappers(words: list[str], seen: list[str] | None = None) -> list[str]:
    """Drop env assignments and the wrappers Claude Code strips (`timeout N`, `time`, `nice`, `nohup`, `stdbuf`, `builtin`,
    bare `xargs`) and their flags, leaving the command that actually runs. The wrapper names dropped are appended to `seen`."""
    while words:
        head: str = Path(words[0]).name
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        elif head in WRAPPERS:
            if seen is not None:
                seen.append(head)
            words = words[1:]
            while words and (words[0].startswith("-") or (head in ("timeout", "nice") and DURATION.match(words[0]))
                             or (head == "env" and "=" in words[0])):
                value_flags: frozenset[str] = ENV_VALUE_FLAGS if head == "env" else FLAG_WITH_VALUE
                words = words[2:] if words[0] in value_flags else words[1:]
        else:
            break
    return words


def strip_reserved(words: list[str]) -> list[str]:
    """Drop shell reserved words, function definitions (`f()`, `f(){`, `function f`) and case-arm patterns (`x)`) from the front
    of a simple command, so `then git push` and `! git push` are seen as `git push`."""
    while words:
        head: str = words[0]
        if head in ("for", "select", "case"):
            if head == "case" and "in" in words[2:3]:
                words = words[3:]
                continue
            return []  # a loop header or a case subject: a word list, not a command
        if head == "function":
            words = words[2:]
        elif head in RESERVED:
            words = words[1:]
        elif DEF_OPEN.match(head):
            words = words[1:]
        elif len(words) > 1 and words[1].startswith("()"):
            words = words[2:] if words[1] == "()" or words[1] == "(){" else words[1:]
        elif ")" in head and not head.startswith(("$", "`")):
            rest: str = head.split(")", 1)[1]
            words = ([rest] if rest else []) + words[1:]
        else:
            break
    return words


def strip_leading(words: list[str], seen: list[str] | None = None) -> list[str]:
    """Reserved words, definitions and wrappers, repeated until the command word is stable."""
    while True:
        after: list[str] = strip_wrappers(strip_reserved(words), seen)
        if after == words:
            return after
        words = after


def read_word(text: str, start: int) -> tuple[str, int]:
    """One shell word from `start`, honouring quotes and backslashes; stops at unquoted whitespace, `<` or `>`.
    Raises ValueError on an unbalanced quote."""
    chars: list[str] = []
    quote: str = ""
    i: int = start
    while i < len(text):
        c: str = text[i]
        if quote:
            if c == quote:
                quote = ""
            elif quote == '"' and c == "\\" and i + 1 < len(text) and text[i + 1] in '"\\$`':
                i += 1
                chars.append(text[i])
            else:
                chars.append(c)
        elif c in "'\"":
            quote = c
        elif c == "\\" and i + 1 < len(text):
            i += 1
            chars.append(text[i])
        elif c.isspace() or c in "<>":
            break
        else:
            chars.append(c)
        i += 1
    if quote:
        raise ValueError("unbalanced quote")
    return "".join(chars), i


def tokenize(part: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(words, redirects) of one simple command. A redirect operator (`>`, `>>`, `2>`, `&>`, `>&`, `<`, `<<`) and its target
    are not words, even when glued to the neighbouring word (`git push origin main>/dev/null`); they come back as
    (operator, target) so a caller can still check what is written or read. Raises ValueError on an unbalanced quote."""
    words: list[str] = []
    redirects: list[tuple[str, str]] = []
    i: int = 0
    while i < len(part):
        if part[i].isspace():
            i += 1
        elif part[i] in "<>":
            j: int = i
            while j < len(part) and part[j] in "<>&":
                j += 1
            op: str = part[i:j]
            while j < len(part) and part[j].isspace():
                j += 1
            target, i = read_word(part, j)
            redirects.append((op, target))
        else:
            word, i = read_word(part, i)
            if i < len(part) and part[i] in "<>" and (word.isdigit() or word == "&"):
                continue  # an fd number or `&` glued to its operator (`2>`, `&>`) belongs to the redirect
            words.append(word)
    return words, redirects


def cleaned(part: str) -> str:
    return part.strip().lstrip("({ \t").rstrip(")} \t")


def parts_of(command: str, depth: int, notes: list[str] | None = None) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """Each simple command of a shell line as (words, redirects), with reserved words and wrappers stripped and the text of
    `bash -c`, `sh -c`, `eval`, `$(...)` and backticks checked too. A part that does not tokenize falls back to a plain
    whitespace split. A part that is only redirects comes back with no words. Wrapper names dropped go into `notes`."""
    found: list[tuple[list[str], list[tuple[str, str]]]] = []
    if depth > MAX_DEPTH:
        return found
    command = join_continuations(command)
    for inner in substitutions(command):
        found += parts_of(inner, depth + 1, notes)
    for part in SEGMENT_SPLIT.split(command):
        try:
            words, redirects = tokenize(cleaned(part))
        except ValueError:
            words, redirects = cleaned(part).split(), []
        words = strip_leading(words, notes)
        if not words:
            if redirects:
                found.append(([], redirects))
            continue
        found.append((words, redirects))
        head: str = Path(words[0]).name
        if head == "eval":
            found += parts_of(" ".join(words[1:]), depth + 1, notes)
        elif head in SHELLS:
            flags = [i for i, w in enumerate(words[1:], 1) if SHELL_C.match(w)]
            if flags and flags[0] + 1 < len(words):
                found += parts_of(words[flags[0] + 1], depth + 1, notes)
    return found


def segments(command: str) -> list[list[str]]:
    """The words of each simple command of a shell line (redirects removed): split on `;`, `&&`, `||`, `|`, `&` and
    newlines, with leading `(` / `{` and wrappers stripped. See `parse_failed` for the fail-closed case."""
    return [words for words, _ in parts_of(command, 0) if words]


def parse_failed(command: str) -> bool:
    """True when a line names a watched word (push, merge) but a part of it cannot be parsed, or nesting runs too deep."""
    if not watched(command):
        return False
    return unparsable(command, 0)


def unparsable(command: str, depth: int) -> bool:
    if depth > MAX_DEPTH:
        return True
    command = join_continuations(command)
    for inner in substitutions(command):
        if unparsable(inner, depth + 1):
            return True
    for part in SEGMENT_SPLIT.split(command):
        try:
            tokenize(cleaned(part))
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
        if word == "-c" or word.startswith("--config-env") or (word.startswith("-c") and not word.startswith("--")):
            config = True
        if word in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
            continue
        if word.startswith("-"):
            i += 1
            continue
        return word, words[i + 1:], config
    return None, [], config


def git_alias_config(words: list[str]) -> bool:
    """True when a global `-c alias.*=...` or `--config-env` precedes the git subcommand (an alias can hide a push)."""
    i: int = 1
    while i < len(words) and words[i].startswith("-"):
        word: str = words[i]
        if word.startswith("--config-env"):
            return True
        value: str = words[i + 1] if word == "-c" and i + 1 < len(words) else (word[2:] if word.startswith("-c") else "")
        if value.lower().startswith("alias."):
            return True
        i += 2 if word in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") else 1
    return False


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
    for i, word in enumerate(words):
        if Path(word).name == "lanes.py" and any(w in GRANT_COMMANDS for w in words[i + 1:]):
            return "merge-go, merge-target and gc-restore are the head's alone"
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
    for words, redirects in parts_of(command, 0) if tool == "Bash" else []:
        flat: list[str] = [*path_words(words), *(t for _op, t in redirects if t)]
        if any(is_secret_path(w) for w in flat if looks_like_path(w)):
            return "reading credentials (ssh keys, .env files, cloud credential paths) is denied for a son"
        writes: bool = bool(words) and Path(words[0]).name in WRITE_COMMANDS
        written: list[str] = [*(flat if writes else []), *(t for op, t in redirects if ">" in op and t)]
        if any(is_protected_write(w) for w in written if looks_like_path(w)):
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
    if tool == "Bash":
        reason = hidden_tool_denial(command)
        if reason is not None:
            return reason
    for words in segments(command):
        reason = son_bash_denial(words, prefix)
        if reason is not None:
            return reason
    return None


def grants(cwd: Path, stamp: str = "*") -> list[dict[str, str]]:
    """Every merge-go.md under the runs dir (one stamp when given) as {head, base_ref, base_sha}."""
    found: list[dict[str, str]] = []
    for path in sorted((cwd / RUNS_DIR).glob(f"{stamp}/*/{MERGE_GO_NAME}")):
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


def run_state(stamp_dir: Path) -> str:
    """`active` while a lanes run in this stamp still has work to merge, `finished` once it has none, `unknown` when the
    stamp holds no run state at all. merge-pending.txt (the lanes not yet merged, written by lanes.py) decides when it exists;
    otherwise any lane status.json that is not `done` keeps the run active."""
    try:
        return "active" if (stamp_dir / PENDING_NAME).read_text(encoding="utf-8").strip() else "finished"
    except OSError:
        pass
    phases: list[str] = []
    for path in stamp_dir.glob(f"*/{STATUS_NAME}"):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        phases.append(str(data.get("status", "")) if isinstance(data, dict) else "")
    if not phases:
        return "unknown"
    return "finished" if all(p == DONE_PHASE for p in phases) else "active"


def protected_branches(cwd: Path) -> set[str]:
    """main, master and the configured default branch always. The configured `merge.target` (default `dev`) and every
    `Base:` branch of a grant only while a lanes run is active; a target recorded by `lanes.py merge-target` until its run
    is finished. A run that merged everything, and the files it left behind, protect nothing."""
    config: dict[str, str] = merge_config(cwd)
    found: set[str] = {*PROTECTED_BRANCHES, config["default_branch"]}
    runs: Path = cwd / RUNS_DIR
    states: dict[Path, str] = {d: run_state(d) for d in sorted(runs.glob("*")) if d.is_dir()}
    if "active" in states.values():
        found.add(config["target"])
    for stamp_dir, state in states.items():
        if state == "active":
            found |= {g["base_ref"] for g in grants(cwd, stamp_dir.name)}
        target_file: Path = stamp_dir / "merge-target.txt"
        try:
            target: str = target_file.read_text(encoding="utf-8").strip() if state != "finished" else ""
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


def api_fields(args: list[str]) -> dict[str, str]:
    """`key=value` fields of a gh api call (-f, -F, --field, --raw-field, also glued or `--flag=`)."""
    fields: dict[str, str] = {}
    for i, arg in enumerate(args):
        raw: str = ""
        if arg in ("-f", "-F", "--field", "--raw-field") and i + 1 < len(args):
            raw = args[i + 1]
        elif arg.startswith(("--field=", "--raw-field=")):
            raw = arg.split("=", 1)[1]
        elif arg.startswith(("-f", "-F")) and not arg.startswith("--") and len(arg) > 2:
            raw = arg[2:]
        key, sep, value = raw.partition("=")
        if sep:
            fields[key] = value
    return fields


def api_endpoint(args: list[str]) -> str:
    """The first positional argument of a gh api call (the endpoint), skipping flag values."""
    skip: bool = False
    for arg in args:
        if skip:
            skip = False
        elif arg in GH_API_VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-"):
            return arg
    return ""


def api_write_denial(args: list[str], protected: set[str]) -> str | None:
    """Non-GET gh api calls that move a protected branch without a pull request: `/merges`, `/git/refs`,
    `/branches/<protected>/` and `/contents/` (which writes to the default branch unless `branch=` names another)."""
    endpoint: str = api_endpoint(args).split("?", 1)[0].lower().rstrip("/")
    if not any(marker.rstrip("/") in endpoint for marker in PROTECTED_API):
        return None
    fields: dict[str, str] = api_fields(args)
    if any(a == "--input" or a.startswith("--input=") for a in args):
        return "a gh api write whose body is read from a file or stdin cannot be inspected, so the merge gate denies it"

    def branch(name: str) -> str:
        return name.removeprefix("refs/heads/").strip()

    if endpoint.endswith("/merges"):
        base: str = branch(fields.get("base", ""))
        return None if base and base not in protected else "a gh api merge into a protected branch bypasses the merge gate; use `gh pr merge`"
    if "/git/refs" in endpoint:
        ref: str = branch(fields.get("ref", "")) or branch(endpoint.split("/git/refs", 1)[1].lstrip("/").removeprefix("heads/"))
        if not ref or ref in protected:
            return "a gh api write to git refs on a protected branch bypasses the merge gate"
        return None
    if "/branches/" in endpoint:
        name: str = endpoint.split("/branches/", 1)[1].split("/", 1)[0]
        return "a gh api write to a protected branch bypasses the merge gate" if name in protected else None
    if "/contents" not in endpoint:
        return None
    target: str = branch(fields.get("branch", ""))
    if not target or target in protected:
        return "a gh api contents write to a protected branch bypasses the merge gate"
    return None


def api_merge_denial(rest: list[str], cwd: Path) -> str | None:
    """`gh api` calls that merge: a non-GET on .../pulls/<n>/merge is gated like `gh pr merge <n>` (in the repo the path
    names); a graphql mergePullRequest cannot be matched to a PR and is denied, and so is any graphql call whose query
    text sits in a file or stdin (`-F query=@file`, `--input`), which the guard cannot read. A non-GET to `/merges`, `/git/refs`,
    `/branches/<protected>/` or `/contents/` aimed at a protected branch is denied, and so is a glob or brace in the endpoint."""
    text: str = " ".join(rest)
    if "mergePullRequest" in text or "enablePullRequestAutoMerge" in text:
        return "a graphql merge cannot be matched to a merge-go; use `gh pr merge` so the guard can check it"
    args: list[str] = rest[1:]
    if "graphql" in args and any(
            API_FILE_FIELD.match(a) or a == "--input" or a.startswith("--input=") for a in args):
        return "a graphql query read from a file or stdin cannot be inspected, so the merge gate denies it"
    method: str = gh_api_denial(args) or ""
    endpoint: str = next((w for w in args if "/pulls/" in w), "")
    found = API_MERGE_PATH.search(endpoint)
    if found and method:
        owner = API_REPO_PATH.search(endpoint)
        return gate_pr(found.group(1), f"{owner.group(1)}/{owner.group(2)}" if owner else "", cwd)
    if method:
        if has_glob([api_endpoint(args).split("?", 1)[0]]):
            return "a glob or brace in a gh api endpoint hides the target; the merge gate fails closed"
        return api_write_denial(args, protected_branches(cwd))
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


def repo_flag(args: list[str]) -> str:
    """The `-R` / `--repo` / `--repo=` value among a subcommand's own arguments."""
    for i, arg in enumerate(args):
        if arg in ("-R", "--repo") and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--repo="):
            return arg.split("=", 1)[1]
    return ""


def has_expansion(args: list[str], skip_values: frozenset[str] = frozenset()) -> bool:
    """True when an argument holds a `$`, so the real value (a branch, a PR number, an endpoint) is not what the guard sees.
    The values of the flags in `skip_values` (free text such as a merge body) are not looked at."""
    skip: bool = False
    for arg in args:
        if skip:
            skip = False
        elif arg in skip_values:
            skip = True
        elif arg.split("=", 1)[0] in skip_values and "=" in arg:
            continue
        elif "$" in arg:
            return True
    return False


def has_glob(args: list[str]) -> bool:
    """True when an argument holds a glob or brace character, so the real destination is not what the guard sees."""
    return any(GLOB_CHARS & set(arg) for arg in args)


def is_tool_word(word: str) -> bool:
    return word in ("git", "gh") or (word.startswith(("/", "./", "../", "~")) and Path(word).name in ("git", "gh"))


def hidden_tool_denial(command: str) -> str | None:
    """Deny a `git` / `gh` word that is not the command word of its segment on a line naming push or merge (`ssh h git push`,
    a construct this parser does not understand), and `xargs` standing in front of such a command."""
    if not watched(command):
        return None
    notes: list[str] = []
    for words, _ in parts_of(command, 0, notes):
        if any(is_tool_word(w) for w in words[1:]):
            return "git or gh appears after another command word on a line naming push or merge; the guard cannot see what runs"
    if "xargs" in notes:
        return "xargs in front of a push or merge hides the arguments; the guard denies it"
    return None


def merge_bash_denial(words: list[str], cwd: Path, line_watched: bool = False) -> str | None:
    head: str = Path(words[0]).name
    if head == "gh":
        rest, repo = gh_words(words)
        if rest[:2] == ["pr", "merge"]:
            if has_expansion(rest[2:], BODY_VALUE_FLAGS):
                return "a shell expansion in a merge command hides the PR; write the number out, the merge gate fails closed"
            if has_glob([a for a in rest[2:] if not a.startswith("-")]):
                return "a glob or brace in a merge command hides the PR; the merge gate fails closed"
            selector: str | None = merge_selector(rest[2:])
            if selector is None:
                return "the PR argument of this merge is not a number, branch or PR URL; the merge gate fails closed"
            return gate_pr(selector, repo_flag(rest[2:]) or repo, cwd)
        if rest[:1] == ["api"]:
            if has_expansion(rest[1:]):
                return "a shell expansion in a gh api call hides the endpoint; the merge gate fails closed"
            if has_glob([api_endpoint(rest[1:]).split("?", 1)[0]]):
                return "a glob or brace in a gh api endpoint hides the target; the merge gate fails closed"
            return api_merge_denial(rest, cwd)
        return None
    if head == "git":
        sub, args, _ = git_subcommand(words)
        if git_alias_config(words):
            return "git -c alias.* / --config-env can define an alias that hides a push or merge; the merge gate denies it"
        if line_watched and sub is not None and sub not in GIT_BUILTINS:
            return f"git {sub} is not a built-in subcommand and may be an alias for push or merge; the merge gate denies it"
        if sub != "push":
            return None
        if has_expansion(args):
            return "a shell expansion in a push hides the destination branch; the merge gate fails closed"
        if has_glob([a for a in args if not a.startswith("-")]):
            return "a glob or brace in a push hides the destination branch; the merge gate fails closed"
        return push_denial(args, cwd)
    return None


def merge_denial(payload: dict[str, Any], cwd: Path) -> str | None:
    tool_input: Any = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return None
    command: str = str(tool_input.get("command", ""))
    if parse_failed(command):
        return "a command naming push or merge could not be parsed, so the merge gate denies it"
    reason: str | None = hidden_tool_denial(command)
    if reason is not None:
        return reason
    line_watched: bool = watched(command)
    for words in segments(command):
        if "$" in words[0] and line_watched:
            return "the command name comes from a shell expansion on a line naming push or merge; the merge gate denies it"
        reason = merge_bash_denial(words, cwd, line_watched)
        if reason is not None:
            return reason
    return None


def deny_output(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": f"dts2-harness guard: {reason}"}})


def decide(payload: dict[str, Any], mode: str, cwd: Path) -> str | None:
    return son_denial(payload, os.environ.get("DTS2_SON_BRANCH_PREFIX", "")) if mode == "son" else merge_denial(payload, cwd)


def command_of(payload: dict[str, Any]) -> str:
    tool_input: Any = payload.get("tool_input")
    return str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("son", "merge"), required=True)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()
    raw: str = sys.stdin.read()
    try:
        payload: Any = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd: Path = Path(args.cwd)
    try:
        reason: str | None = decide(payload, args.mode, cwd)
    except Exception as exc:  # noqa: BLE001 - an uncaught error exits non-zero, which lets the call through
        reason = f"the guard failed ({type(exc).__name__}) on a command naming push or merge" if watched(command_of(payload)) else None
    if reason is not None:
        print(deny_output(reason))
        if args.mode == "merge":
            command: str = command_of(payload)[:300]
            append_text(cwd / LOG_NAME, json.dumps({"event": "denied", "reason": reason, "command": command}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
