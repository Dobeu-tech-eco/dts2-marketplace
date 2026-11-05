#!/usr/bin/env bash
# dts2 optional hook: PreToolUse (Bash). Denies obviously destructive shell commands.
# Fails open (exit 0) when python3 is missing or the input cannot be read.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat)"

read -r -d '' PY <<'PYEOF' || true
import json
import re
import shlex
import sys

DANGEROUS = {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "${HOME}/", "${HOME}/*",
             ".", "./", "./*", "..", "*"}


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def flags_and_args(tokens):
    flags, args = [], []
    for token in tokens:
        (flags if token.startswith("-") and token != "-" else args).append(token)
    return flags, args


def has_short(flags, letters):
    return any(f.startswith("-") and not f.startswith("--") and any(c in f for c in letters) for f in flags)


try:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
if not isinstance(command, str) or not command:
    sys.exit(0)

if re.search(r"\b(curl|wget)\b[^|;&\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", command):
    deny("Piping a download into a shell is blocked by the dts2 command-guard hook.")
if re.search(r"\bgit\s+(-\S+\s+)*reset\b[^;&|\n]*--hard", command):
    deny("git reset --hard is blocked by the dts2 command-guard hook; it discards work.")
if re.search(r"\bmkfs(\.\w+)?\b", command):
    deny("mkfs is blocked by the dts2 command-guard hook.")
if re.search(r"\bdd\b[^;&|\n]*\bof=/dev/", command):
    deny("Writing to a device with dd is blocked by the dts2 command-guard hook.")

for segment in re.split(r"[;&|\n]+", command):
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    while tokens and tokens[0] in ("sudo", "command", "env"):
        tokens = tokens[1:]
    if not tokens:
        continue
    name, rest = tokens[0].rsplit("/", 1)[-1], tokens[1:]
    flags, args = flags_and_args(rest)
    if name == "rm":
        recursive = has_short(flags, "rR") or "--recursive" in flags
        force = has_short(flags, "f") or "--force" in flags
        if recursive and force and any(a in DANGEROUS for a in args):
            deny("rm -rf on a root, home or current-directory target is blocked by the dts2 command-guard hook.")
    elif name == "git" and rest[:1] == ["clean"]:
        flags, _ = flags_and_args(rest[1:])
        dry = has_short(flags, "n") or "--dry-run" in flags
        force = has_short(flags, "f") or "--force" in flags
        if force and has_short(flags, "dx") and not dry:
            deny("git clean -fd/-fx is blocked by the dts2 command-guard hook; it deletes untracked files.")
    elif name == "chmod":
        recursive = has_short(flags, "R") or "--recursive" in flags
        if recursive and any(a in ("777", "0777") for a in args):
            deny("chmod -R 777 is blocked by the dts2 command-guard hook.")
PYEOF

printf '%s' "$input" | python3 -I -c "$PY" 2>/dev/null
exit 0
