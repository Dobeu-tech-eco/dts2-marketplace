#!/usr/bin/env python3
"""Declarative policy gate (G-70): one JSON file (`templates/policy.json`) evaluated by `hooks/policy-gate.sh` for the head and
for every son.

Per-agent rules (batch D): when `DTS2_AGENT` names a roster agent, a tool call is also refused if its task class (the
`taskClasses` table: `gh pr merge` is `merge`, `vercel deploy` is `deploy`, an Edit is `build`) is denied by that agent's rules
(`scripts/agent_rules.py`), if a `read_only` agent edits, or if a path (a file tool's `file_path`, a Bash word) matches
`paths_deny`. That only adds to the tables below, and without `DTS2_AGENT` nothing changes.

Three tables: `deny` (always refused: force-push, `--admin`, deploy CLIs, `gh secret`, `vercel env`, a bare `env`, repo
deletes), `require_approval` (`gh pr merge` and a push to the default branch pass only when `approvals.is_human_approved`
holds the PR number or branch; a direct `gh pr merge <n> --squash --match-head-commit <sha>` also passes under the standing grant
`merge_policy: ["auto-when-green"]` when the sha is the one `lanes.py merge-go-step` recorded and is the live PR head, the PR touches no
`auto_merge_never_paths` file and every required check of the base branch is green on that head. `--auto` is always refused: GitHub native
auto-merge is never armed, so every merge runs through the merge mutex) and `scanner_required` (staging everything in an unattended run needs a secret scanner; its
absence is red). The command is normalised before it is matched: `bash -lc "..."`, `eval`, `$(...)`, `env -i`, `command`,
`sudo`, `npx` / `pnpm dlx` runners, `git -C dir`, `;` `&&` `|` chains and quoted words all reduce to the command that runs.
The tokenizer is `guard.py`'s, not a copy. A line that hides its command word behind a shell expansion is refused when it names
a policy tool (fail closed). Denials are printed as PreToolUse JSON and exit 0."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_rules  # noqa: E402
import approvals  # noqa: E402
import guard  # noqa: E402
import state_io  # noqa: E402
from state_io import append_text, rel  # noqa: E402

POLICY_PATH: Final[Path] = Path(__file__).resolve().parent.parent / "templates" / "policy.json"
LOG_REL: Final[str] = rel("policy-gate.log")
MAX_DEPTH: Final[int] = 4
MIN_ABBREV: Final[int] = 5
RUNNERS: Final[frozenset[str]] = frozenset({"npx", "pnpx", "bunx"})
PACKAGE_MANAGERS: Final[frozenset[str]] = frozenset({"pnpm", "yarn", "npm", "bun"})
RUNNER_VERBS: Final[frozenset[str]] = frozenset({"dlx", "exec", "x"})
ALIASES: Final[dict[str, str]] = {"flyctl": "fly", "ntl": "netlify"}
TEXT_HEADS: Final[frozenset[str]] = frozenset({"echo", "printf", "grep", "egrep", "fgrep", "rg", "man", "cat", "less", "head", "tail",
                                               "which", "type", "diff", "wc", "git", "gh"})
ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
UNATTENDED_VARS: Final[tuple[str, ...]] = ("DTS2_SON", "DTS2_UNATTENDED")
TRUE_WORDS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
SCANNERS: Final[tuple[tuple[str, str], ...]] = (("DTS2_GITLEAKS_BIN", "gitleaks"), ("DTS2_TRUFFLEHOG_BIN", "trufflehog"))
PR_NUMBER: Final[re.Pattern[str]] = re.compile(r"^(?:\d+|https://[^\s]+/pull/(\d+))$")
HEAD_SHA: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{7,40}$")
REPO_FROM_URL: Final[re.Pattern[str]] = re.compile(r"^https://[^/\s]+/([^/\s]+/[^/\s]+)/pull/\d+")
MAX_LISTED_FILES: Final[int] = 100  # gh lists at most this many changed files; a full list may be cut short
HIDDEN_WORDS: Final[tuple[str, ...]] = ("push", "merge", "deploy", "publish", "secret")
WRITE_TOOLS: Final[frozenset[str]] = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
PATH_KEYS: Final[tuple[str, ...]] = ("file_path", "notebook_path", "path")
POLICY_TOOLS: Final[frozenset[str]] = frozenset({"git", "gh", "vercel", "wrangler", "fly", "flyctl", "netlify", "ntl", "supabase",
                                                 "env", "printenv"})


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """The policy table; a missing or damaged file raises, so the hook can say so (it never silently allows)."""
    data: Any = json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("policy.json must hold an object")
    return data


def unattended() -> bool:
    """A son, or a run the person marked unattended (`DTS2_UNATTENDED=1`)."""
    return any(os.environ.get(name, "").lower() in TRUE_WORDS or (name == "DTS2_SON" and bool(os.environ.get(name)))
               for name in UNATTENDED_VARS)


def scanner_available() -> bool:
    """True when gitleaks or trufflehog is reachable (the same lookup `checks.py` uses: `DTS2_*_BIN`, then PATH)."""
    return any(os.environ.get(env) or shutil.which(tool) for env, tool in SCANNERS)


def secret_scan_red() -> bool:
    """Unattended without a secret scanner is red: nothing may stage everything or commit on its own."""
    return unattended() and not scanner_available()


def skip_flags(words: list[str], start: int, valued: bool = True, env: bool = False) -> int:
    """Index of the first word after the flags that begin at `start`. `valued` lets a flag take the next word as its value (the
    guard's table, or env's own `-u`, `-C`, `-S`); `env` flags like `-i` never do."""
    index: int = start
    while index < len(words) and (words[index].startswith("-") or guard.DURATION.match(words[index])):
        if env and words[index].startswith("-"):
            index += guard.env_flag_width(words[index])
            continue
        index += 2 if valued and words[index] in guard.FLAG_WITH_VALUE else 1
    return index


def peel(words: list[str], valued: bool) -> list[str]:
    """The command behind assignments and wrappers (`env -i`, `sudo`, `command`, `timeout 5` ...). Unlike the guard's stripper,
    `env -i gh ...` keeps `gh`; `valued` decides whether another wrapper's flag swallows the next word."""
    words = guard.strip_reserved(words)
    while words:
        name: str = Path(words[0]).name
        if ASSIGNMENT.match(words[0]):
            words = words[1:]
        elif name in guard.WRAPPERS:
            words = words[skip_flags(words, 1, valued, env=name == "env"):]
        else:
            break
        words = guard.strip_reserved(words)
    return words


def bare_env(words: list[str]) -> bool:
    """True when the command, behind any wrappers, is `env` / `printenv` with no operand (it prints the whole environment)."""
    return any(bare_env_variant(words, valued) for valued in (True, False))


def bare_env_variant(words: list[str], valued: bool) -> bool:
    index: int = 0
    while index < len(words):
        word: str = words[index]
        name: str = Path(word).name
        if ASSIGNMENT.match(word):
            index += 1
        elif name in ("env", "printenv"):
            rest: list[str] = words[skip_flags(words, index + 1, valued, env=name == "env"):]
            operands: list[str] = [w for w in rest if not ASSIGNMENT.match(w)] if name == "env" else [w for w in rest if not w.startswith("-")]
            return not operands
        elif name in guard.WRAPPERS:
            index = skip_flags(words, index + 1, valued)
        else:
            return False
    return False


def unwrap_runner(words: list[str]) -> list[str]:
    """`npx vercel deploy`, `pnpm dlx wrangler deploy`, `npm exec -- fly deploy` run the tool that follows."""
    if not words:
        return words
    head: str = Path(words[0]).name
    if head in RUNNERS:
        return words[skip_flags(words, 1):]
    if head in PACKAGE_MANAGERS and len(words) > 1 and words[1] in RUNNER_VERBS:
        rest: list[str] = words[2:]
        return rest[skip_flags(rest, 0):] if rest and rest[0] != "--" else rest[1:]
    return words


def split_segments(command: str) -> list[str]:
    """Split a shell line on `;` `&&` `||` `|` `&` and newlines that sit outside quotes, so `bash -c "a; b"` stays one part."""
    parts: list[str] = []
    current: list[str] = []
    quote: str = ""
    index: int = 0
    while index < len(command):
        char: str = command[index]
        if quote:
            if quote == '"' and char == "\\" and index + 1 < len(command):
                current.append(command[index:index + 2])
                index += 2
                continue
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "\\" and index + 1 < len(command):
            current.append(char)
            index += 1
            char = command[index]
        elif char in ";|&\n":
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def expand(command: str, depth: int = 0) -> list[list[str]]:
    """Every simple command the line can run, as raw words with wrappers still in place and again unwrapped, descending into
    `$(...)`, backticks, `eval`, `bash -c` and quoted multi-word arguments of other commands."""
    found: list[list[str]] = []
    if depth > MAX_DEPTH:
        return found
    command = guard.mask_literals(guard.join_continuations(command))  # '$(x)' in single quotes is text, not an expansion
    for inner in guard.substitutions(command):
        found += expand(inner, depth + 1)
    for part in split_segments(command):
        try:
            words, _ = guard.tokenize(guard.cleaned(part))
        except ValueError:
            words = guard.cleaned(part).split()
        words = guard.strip_reserved(words)
        if not words:
            continue
        found.append(words)
        found += nested([guard.unmask_literals(w) for w in words], depth)
        for valued in (True, False):
            inner_words: list[str] = unwrap_runner(peel(words, valued))
            if inner_words and inner_words != words:
                found.append(inner_words)
                found += nested([guard.unmask_literals(w) for w in inner_words], depth)
    return found


def nested(words: list[str], depth: int) -> list[list[str]]:
    """Commands carried inside this command's arguments: `eval ...`, `sh -c "..."`, and a quoted multi-word argument of a
    command that is not a text printer or git/gh itself (`ssh host 'git push -f'`)."""
    head: str = Path(words[0]).name
    if head == "eval":
        return expand(" ".join(words[1:]), depth + 1)
    if head in guard.SHELLS:
        flags: list[int] = [i for i, w in enumerate(words[1:], 1) if guard.SHELL_C.match(w)]
        return expand(words[flags[0] + 1], depth + 1) if flags and flags[0] + 1 < len(words) else []
    if head in TEXT_HEADS:
        return []
    found: list[list[str]] = []
    for word in words[1:]:
        if re.search(r"\s", word) and any(re.search(rf"\b{tool}\b", word) for tool in POLICY_TOOLS):
            found += expand(word, depth + 1)
    return found


def tool_view(words: list[str]) -> tuple[str, list[str], list[str]] | None:
    """(tool name, positional words, flag words) for a command; git and gh skip their global options first."""
    words = unwrap_runner(words)
    if not words:
        return None
    name: str = ALIASES.get(Path(words[0]).name, Path(words[0]).name)
    if name == "git":
        sub, args, _ = guard.git_subcommand(words)
        if sub is None:
            return name, [], []
        return name, [sub, *[a for a in args if not a.startswith("-")]], [a for a in args if a.startswith("-")]
    rest: list[str] = guard.gh_words(words)[0] if name == "gh" else words[1:]
    return name, [w for w in rest if not w.startswith("-")], [w for w in rest if w.startswith("-")]


def sub_slack(words: list[str]) -> int:
    """How far from the front a sub-command may start: git and gh already skip their global options, so it starts first; any other
    tool may put value-taking flags before it (`vercel --token x --scope y env`), so each leading `--name value` buys one position."""
    words = unwrap_runner(words)
    if not words or ALIASES.get(Path(words[0]).name, Path(words[0]).name) in ("git", "gh"):
        return 0
    slack: int = 0
    i: int = 1
    while i < len(words) and words[i].startswith("-"):
        has_value: bool = "=" not in words[i] and i + 1 < len(words) and not words[i + 1].startswith("-")
        slack += has_value
        i += 2 if has_value else 1
    return slack


def has_sequence(positionals: list[str], sub: list[str], slack: int = 0) -> bool:
    """True when `sub` sits at the sub-command position (the first `slack + 1` places), not in a later option value or operand."""
    size: int = len(sub)
    return any(positionals[i:i + size] == sub for i in range(min(slack + 1, len(positionals) - size + 1)))


def flag_hit(flag: str, rule: dict[str, Any]) -> bool:
    base: str = flag.split("=", 1)[0]
    if base in rule.get("flags", []):
        return True
    if rule.get("abbrev") and base.startswith("--") and len(base) >= MIN_ABBREV:
        return any(listed.startswith("--") and (listed.startswith(base) or base.startswith(listed)) for listed in rule.get("flags", []))
    shorts: list[str] = rule.get("short_flags", [])
    return bool(shorts) and re.match(r"^-[A-Za-z]+$", flag) is not None and any(letter in flag[1:] for letter in shorts)


def rule_matches(rule: dict[str, Any], words: list[str]) -> bool:
    """True when `words` run a command this rule names, with its sub-command words and one of its flags (when it lists any)."""
    view = tool_view(words)
    if view is None or view[0] not in rule.get("cmd", []):
        return False
    _, positionals, flags = view
    if rule.get("sub") and not has_sequence(positionals, rule["sub"], sub_slack(words)):
        return False
    if not (rule.get("flags") or rule.get("short_flags") or rule.get("plus_refspec")):
        return True
    if any(flag_hit(flag, rule) for flag in flags):
        return True
    return bool(rule.get("plus_refspec")) and any(p.startswith("+") and len(p) > 1 for p in positionals[1:])


def expansion_hides_flags(rule: dict[str, Any], words: list[str]) -> bool:
    """A flag-checked rule for a command whose arguments hold a `$` cannot be judged; refuse it (fail closed). A rule with a
    `sub` only judges commands that run that sub-command; a flag-only rule judges every command of its tool."""
    view = tool_view(words)
    if view is None or view[0] not in rule.get("cmd", []) or not (rule.get("flags") or rule.get("short_flags")):
        return False
    _, positionals, flags = view
    skip: int = len(rule["sub"]) if rule.get("sub") else 0
    if skip and not has_sequence(positionals, rule["sub"], sub_slack(words)):
        return False
    return any(arg.startswith(("$", "`")) for arg in positionals[skip:]) or any("$" in flag or "`" in flag for flag in flags)


def deny_reason(policy: dict[str, Any], command: str) -> str | None:
    """The first `deny` rule the command breaks, as `<id>: <reason>`."""
    lines: list[list[str]] = expand(command)
    for words in lines:
        if bare_env(words):
            rule: dict[str, Any] = next(r for r in policy.get("deny", []) if r.get("bare_cmd"))
            return f"{rule['id']}: {rule['reason']}"
    for rule in policy.get("deny", []):
        if rule.get("bare_cmd"):
            continue
        for words in lines:
            if rule_matches(rule, words) or expansion_hides_flags(rule, words):
                return f"{rule['id']}: {rule['reason']}"
    return hidden_command_denial(policy, command, lines)


def hidden_command_denial(policy: dict[str, Any], command: str, lines: list[list[str]]) -> str | None:
    """The command word comes from an expansion on a line that names a policy tool: the gate cannot see what runs."""
    named: bool = any(re.search(rf"\b{word}\b", command, re.I) for word in (*(POLICY_TOOLS - {"env"}), *HIDDEN_WORDS))
    if named and any(words[0].startswith(("$", "`")) for words in lines):
        return "hidden-command: the command word comes from a shell expansion on a line naming a policy tool"
    return None


def pr_key(args: list[str]) -> str | None:
    """The PR number a `gh pr merge` names; None for the current-branch form or a branch name (the person approves numbers)."""
    selector: str | None = guard.merge_selector(args)
    match = PR_NUMBER.match(selector or "")
    return (match.group(1) or match.group(0)) if match else None


def default_branches(cwd: Path) -> set[str]:
    return {*guard.PROTECTED_BRANCHES, guard.merge_config(cwd)["default_branch"]}


def push_branches(args: list[str], cwd: Path) -> list[str]:
    """Default-branch destinations of a push: the refspec destinations, or the current branch when none is named."""
    current: str = guard.run([*guard.binary("DTS2_GIT_BIN", "git"), "rev-parse", "--abbrev-ref", "HEAD"], cwd) or ""
    targets: list[str] = [dst for _, dst in guard.push_refspecs(args, current)]
    return [dst for dst in targets if dst in default_branches(cwd) or not dst]


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A path glob as a regex: `**/` any directories (or none), `**` anything, `*` and `?` stay inside one path part."""
    out: list[str] = []
    i: int = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            out.append("[^/]*" if pattern[i] == "*" else "[^/]" if pattern[i] == "?" else re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def never_path_hit(policy: dict[str, Any], paths: list[str]) -> str | None:
    """The first changed path that matches an `auto_merge_never_paths` glob."""
    patterns: list[re.Pattern[str]] = [glob_regex(str(p)) for p in policy.get("auto_merge_never_paths", [])]
    return next((path for path in paths if any(p.match(path) for p in patterns)), None)


def merge_flag_value(merge_args: list[str], flag: str) -> str | None:
    """The value of `--flag value` or `--flag=value` among a merge command's arguments."""
    for i, arg in enumerate(merge_args):
        if arg == flag and i + 1 < len(merge_args):
            return merge_args[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return None


def gh_json(args: list[str], cwd: Path) -> Any:
    """Parsed JSON printed by `gh <args>` (DTS2_GH_BIN honoured); None when gh fails or prints something else."""
    raw: str | None = guard.run([*guard.binary("DTS2_GH_BIN", "gh"), *args], cwd)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


GREEN_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success", "neutral", "skipped"})


def required_check_names(base: str, repo: str, cwd: Path) -> list[str]:
    """Names of the status checks the base branch requires (branch protection `contexts` and `checks[].context`, plus
    `required_status_checks` ruleset parameters); empty when there are none or they cannot be read."""
    slug: str = repo or "{owner}/{repo}"
    names: list[str] = []
    protection: Any = gh_json(["api", f"repos/{slug}/branches/{base}/protection/required_status_checks"], cwd)
    if isinstance(protection, dict):
        names += [str(c) for c in protection.get("contexts") or []]
        names += [str(c["context"]) for c in protection.get("checks") or [] if isinstance(c, dict) and c.get("context")]
    rules: Any = gh_json(["api", f"repos/{slug}/rules/branches/{base}"], cwd)
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
                params: Any = rule.get("parameters")
                items: Any = params.get("required_status_checks") if isinstance(params, dict) else None
                names += [str(c["context"]) for c in items or [] if isinstance(c, dict) and c.get("context")]
    return list(dict.fromkeys(names))


def required_checks_refusal(base: str, repo: str, head: str, cwd: Path) -> str | None:
    """None when the base requires status checks and every one is green on `head`; else why not. Fails closed on any
    lookup error."""
    names: list[str] = required_check_names(base, repo, cwd)
    if not names:
        return (f"{base} has no required status checks (or they cannot be read), so a direct merge would skip CI; add a GitHub "
                "ruleset or branch protection on the base that requires the test and lint checks")
    slug: str = repo or "{owner}/{repo}"
    runs: Any = gh_json(["api", f"repos/{slug}/commits/{head}/check-runs?per_page=100"], cwd)
    status: Any = gh_json(["api", f"repos/{slug}/commits/{head}/status"], cwd)
    if not isinstance(runs, dict) or not isinstance(runs.get("check_runs"), list) or not isinstance(status, dict) \
            or not isinstance(status.get("statuses"), list):
        return f"cannot read the checks on {head[:10]} from gh, so the merge fails closed; retry, or add the PR under dts2_approvals.merge"
    for name in names:
        # Every result reported under the name must be green: a passing namesake never masks a pending or failing one.
        results: list[bool] = [r.get("conclusion") in GREEN_CONCLUSIONS for r in runs["check_runs"]
                               if isinstance(r, dict) and str(r.get("name")) == name]
        results += [s.get("state") == "success" for s in status["statuses"] if isinstance(s, dict) and str(s.get("context")) == name]
        if not results or not all(results):
            return f"required check {name} is not green: wait for {name} on {head[:10]}, then merge again"
    return None


def has_flag(args: list[str], flag: str) -> bool:
    """True when `flag` appears bare or in its `--flag=value` form (gh accepts `--auto=true`)."""
    return any(a == flag or a.startswith(flag + "=") for a in args)


def standing_merge_refusal(policy: dict[str, Any], rule: dict[str, Any], words: list[str], cwd: Path) -> str | None:
    """None when this `gh pr merge` may pass under the standing grant (see the module docstring); else the reason, which says
    what to do. A merge without the grant keeps the rule's own per-PR message."""
    if not approvals.standing_auto_merge(cwd):
        return str(rule["reason"])
    rest, repo = guard.gh_words(unwrap_runner(words))
    merge_args: list[str] = rest[rest.index("merge") + 1:] if "merge" in rest else []
    repo = repo or guard.repo_flag(merge_args)
    if has_flag(merge_args, "--admin"):
        return "--admin skips branch protection and is denied"
    if has_flag(merge_args, "--auto"):
        return "native auto-merge is never armed; merge directly with --match-head-commit <sha> after the required checks are green"
    sha: str = (merge_flag_value(merge_args, "--match-head-commit") or "").lower()
    if not HEAD_SHA.match(sha):
        return "a merge under the standing grant needs `--match-head-commit <sha>` (the PR head that `lanes.py merge-go-step` recorded) so a later push cannot ride along"
    key: str | None = pr_key(merge_args)
    if not key:
        return "a merge under the standing grant names the PR by number or URL (`gh pr merge <n> --squash --match-head-commit <sha>`), not by branch or the current branch"
    url = REPO_FROM_URL.match(guard.merge_selector(merge_args) or "")
    repo = repo or (url.group(1) if url else "")
    if not any(sha.startswith(g["head"].lower()) or g["head"].lower().startswith(sha) for g in guard.grants(cwd)):
        return (f"no merge-go grant records head {sha[:10]}; run `python3 -I \"${{CLAUDE_PLUGIN_ROOT}}/scripts/lanes.py\" merge-go-step <stamp> "
                f"--step <step> --head <sha>` for the PR head first")
    facts: Any = gh_json(["pr", "view", key, *(["--repo", repo] if repo else []), "--json", "baseRefName,headRefOid,files"], cwd)
    if not isinstance(facts, dict) or not isinstance(facts.get("baseRefName"), str) or not isinstance(facts.get("files"), list):
        return f"cannot read PR {key} (base, head and changed files) from gh, so the merge fails closed; retry, or add {key} under dts2_approvals.merge"
    head: str = str(facts.get("headRefOid") or "").lower()
    if not head or not (head.startswith(sha) or sha.startswith(head)):
        return f"PR {key} head is {head[:10] or 'unknown'}, not the pinned {sha[:10]}; the head moved, so fetch and run merge-go-step again"
    files: list[Any] = facts["files"]
    if len(files) >= MAX_LISTED_FILES:
        return f"PR {key} lists {len(files)} changed files, which may be cut short, so its paths cannot be checked; merge it with a per-PR approval"
    hit: str | None = never_path_hit(policy, [str(f.get("path", "")) if isinstance(f, dict) else "" for f in files])
    if hit is not None:
        return f"PR {key} touches {hit}, a path the standing grant never covers (auto_merge_never_paths); the person approves it per PR under dts2_approvals.merge"
    return required_checks_refusal(facts["baseRefName"], repo, head, cwd)


def approval_reason(policy: dict[str, Any], words: list[str], cwd: Path) -> str | None:
    for rule in policy.get("require_approval", []):
        if not rule_matches(rule, words):
            continue
        view = tool_view(words)
        if view is None:
            continue
        keys: list[str] = approval_keys(rule, words, view, cwd)
        if keys and all(approvals.is_human_approved(rule["kind"], key, cwd) for key in keys):
            continue
        if not keys and rule["key"] == "branch":
            continue
        if rule["key"] == "pr":
            refusal: str | None = standing_merge_refusal(policy, rule, words, cwd)
            if refusal is None:
                continue
            return f"{rule['id']}: {refusal}"
        return f"{rule['id']}: {rule['reason']}"
    return None


def approval_keys(rule: dict[str, Any], words: list[str], view: tuple[str, list[str], list[str]], cwd: Path) -> list[str]:
    """The approval keys this command needs (empty: it needs none, or for a PR merge, names no PR number)."""
    if rule["key"] == "pr":
        unwrapped: list[str] = unwrap_runner(words)
        rest: list[str] = guard.gh_words(unwrapped)[0]
        merge_args: list[str] = rest[rest.index("merge") + 1:] if "merge" in rest else []
        key: str | None = pr_key(merge_args)
        return [key] if key else ["?"]
    return push_branches(guard.git_subcommand(unwrap_runner(words))[1], cwd)


def approval_denial(policy: dict[str, Any], command: str, cwd: Path) -> str | None:
    for words in expand(command):
        reason: str | None = approval_reason(policy, words, cwd)
        if reason is not None:
            return reason
    return None


def scanner_denial(policy: dict[str, Any], command: str) -> str | None:
    if not secret_scan_red():
        return None
    for rule in policy.get("scanner_required", []):
        for words in expand(command):
            view = tool_view(words)
            if view is None or not rule_matches({**rule, "flags": [], "short_flags": []}, words):
                continue
            if any(flag in rule.get("flags", []) for flag in view[2]) or any(p in rule.get("operands", []) for p in view[1][1:]):
                return f"{rule['id']}: {rule['reason']}"
    return None


def bash_denial(payload: dict[str, Any], cwd: Path, policy: dict[str, Any]) -> str | None:
    """The reason the global tables refuse this Bash payload, or None (any other tool passes)."""
    tool_input: Any = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return None
    command: str = str(tool_input.get("command", ""))
    return deny_reason(policy, command) or approval_denial(policy, command, cwd) or scanner_denial(policy, command)


def tool_path(payload: dict[str, Any], key: str) -> str:
    tool_input: Any = payload.get("tool_input")
    value: Any = tool_input.get(key) if isinstance(tool_input, dict) else None
    return value if isinstance(value, str) else ""


def relative_path(path: str, cwd: Path) -> str:
    """`path` relative to the repo when it sits inside it, so `paths_deny` globs written for the repo match absolute paths."""
    try:
        return str(Path(path).resolve().relative_to(cwd.resolve())) if Path(path).is_absolute() else path
    except (ValueError, OSError):
        return path


def call_paths(payload: dict[str, Any], lines: list[list[str]], cwd: Path) -> list[str]:
    """Paths a call touches: a file tool's path fields, or every word (and `--flag=value` value) of a Bash command."""
    found: list[str] = [tool_path(payload, key) for key in PATH_KEYS]
    for words in lines:
        for word in words:
            found.append(word.split("=", 1)[1] if word.startswith("-") and "=" in word else "" if word.startswith("-") else word)
    return [relative_path(path, cwd) for path in found if path]


def docs_write(spec: dict[str, Any], path: str) -> bool:
    return agent_rules.path_denied(path, spec.get("docs_paths", [])) is not None


def call_classes(payload: dict[str, Any], table: dict[str, Any], lines: list[list[str]], cwd: Path) -> list[str]:
    """Task classes this call belongs to, by the `taskClasses` table: file tools by name (a write to a docs path is `docs`,
    not `build`), Bash by the same cmd / sub / flags rules the deny table uses."""
    tool: Any = payload.get("tool_name")
    classes: dict[str, Any] = table.get("taskClasses") or {}
    found: list[str] = [name for name in agent_rules.TASK_CLASSES if tool in (classes.get(name) or {}).get("tools", [])]
    if tool in WRITE_TOOLS and "build" in found and docs_write(classes.get("docs") or {}, relative_path(tool_path(payload, "file_path") or tool_path(payload, "notebook_path"), cwd)):
        found = ["docs" if name == "build" else name for name in found]
    if tool == "Bash":
        found += [name for name in agent_rules.TASK_CLASSES
                  if any(rule_matches(rule, words) for rule in (classes.get(name) or {}).get("rules", []) for words in lines)]
    return list(dict.fromkeys(found))


def agent_profile_auth(agent: str, cwd: Path) -> str | None:
    from profiles import Profiles  # noqa: PLC0415 - only a rules-limited agent needs the profiles
    profile: dict[str, Any] = Profiles.load(project=cwd).get(agent) or {}
    return profile.get("auth") if isinstance(profile.get("auth"), str) else None


def agent_denial(payload: dict[str, Any], cwd: Path, policy: dict[str, Any], agent: str) -> str | None:
    """The reason the rules of agent `agent` refuse this tool call, or None. An agent with no rules is not restricted."""
    config: Path = cwd / state_io.CONFIG_REL
    if agent_rules.entry_for(agent, config) is None:
        return None
    rules: dict[str, Any] = agent_rules.agent_rules(agent, config, agent_profile_auth(agent, cwd))
    if not rules:
        return None
    command: str = guard.command_of(payload)
    lines: list[list[str]] = expand(command) if payload.get("tool_name") == "Bash" else []
    if rules.get("read_only") is True and payload.get("tool_name") in WRITE_TOOLS:
        return f"agent-rules: {agent} is read-only and may not use {payload['tool_name']}"
    for task in call_classes(payload, policy, lines, cwd):
        allowed, why = agent_rules.permits(rules, task_class=task)
        if not allowed:
            return f"agent-rules: {agent}: {why}"
    allowed, why = agent_rules.permits(rules, paths=call_paths(payload, lines, cwd))
    return None if allowed else f"agent-rules: {agent}: {why}"


def decide(payload: dict[str, Any], cwd: Path, policy: dict[str, Any] | None = None) -> str | None:
    """The reason to refuse this PreToolUse payload, or None. The global tables apply to Bash; the calling agent's own rules
    (`DTS2_AGENT`) then apply to every guarded tool, on top of them."""
    agent: str = os.environ.get(agent_rules.AGENT_VAR, "")
    if payload.get("tool_name") != "Bash" and not agent:
        return None
    table: dict[str, Any] = policy if policy is not None else load_policy()
    return bash_denial(payload, cwd, table) or (agent_denial(payload, cwd, table, agent) if agent else None)


def deny_output(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": f"dts2-harness policy: {reason}"}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()
    try:
        payload: Any = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd: Path = Path(args.cwd)
    try:
        reason: str | None = decide(payload, cwd)
    except Exception as exc:  # noqa: BLE001 - a crash must not let a command naming a policy tool through silently
        named: bool = any(re.search(rf"\b{tool}\b", guard.command_of(payload)) for tool in POLICY_TOOLS)
        limited: bool = bool(os.environ.get(agent_rules.AGENT_VAR))  # a rules-limited agent fails closed on every tool
        reason = (f"the policy gate failed ({type(exc).__name__}) on a command naming a policy tool" if named
                  else f"the policy gate failed ({type(exc).__name__}) for a rules-limited agent" if limited else None)
    if reason is not None:
        print(deny_output(reason))
        command: str = guard.command_of(payload)[:300]
        append_text(cwd / LOG_REL, json.dumps({"event": "denied", "reason": reason, "command": command}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
