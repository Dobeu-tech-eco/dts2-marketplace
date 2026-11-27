#!/usr/bin/env python3
"""The approval channel (G-63, ruling Q11).

An approval is a key in `.claude/settings.local.json`. A model cannot edit that file directly (every son launch denies Edit and
Write on it, and the sandbox lists it under denyWrite; the head's own instructions say never to edit it). The person edits the
file, or `grant()` in this script writes it for one of the entry points below:

    {"dts2_approvals": {"merge": ["42"], "recorded_yes": ["step-3"], "lane_override": ["lane-a"], "merge_policy": ["auto-when-green"]}}

`merge_policy: ["auto-when-green"]` is a standing grant: the policy gate then lets a direct `gh pr merge <n> --merge --match-head-commit <sha>`
through without a per-PR entry once the required checks are green (see policy_gate.py for the conditions).
A `roadmap` entry is the 12-character scope key printed by `roadmap.py status`. No lock, by any route below, is granted until
the setup gap pass has run for that key and no gap is open (`gap_research.py <repo> pass`; see `gap_research.lock_block`).
Two ways in, both on the person's own input:
- In Claude Code, the owner says it in chat, in their own words ("lock it in", "approve the roadmap", or `lock roadmap <key>`).
  The UserPromptSubmit hook (`hooks/roadmap-lock.sh`) runs only on typed text and calls `grant`; the model never writes the file.
- In any other harness or model (Codex, T3 Code, Cursor), the owner runs `approvals.py lock-roadmap` in their own terminal.
  It asks for a yes on the terminal itself, and refuses when no terminal is attached.
- An agent may run `approvals.py lock-roadmap <key>` itself once agents from two different providers have signed the same
  key with `approvals.py sign-roadmap <key>`. No prompt is shown, and the log records the lock as `agent:<name>`.
  `--skip-review <reason>` (the owner said to skip the review or not to wait) and `--single-provider <reason>` (only one
  provider is available) lock on one sign-off or none, and the log records which override was used.
  This is a workflow gate for cooperating agents, not a defense against a hostile local process.

`is_human_approved(kind, key)` reads only that file. Nothing an agent writes anywhere else counts, and `record_actor` only logs
who asked (`agent:<session_id>` or `human`), so the log shows when an agent claimed an approval it did not hold."""
from __future__ import annotations

import argparse
import json
import io
import os
import re
import tempfile
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

MARKER_REL: Final[str] = ".claude/settings.local.json"
APPROVALS_KEY: Final[str] = "dts2_approvals"
KINDS: Final[tuple[str, ...]] = ("recorded_yes", "unsafe_no_sandbox", "blocked_pr_done", "lane_override", "merge", "merge_policy", "roadmap")
MERGE_POLICY_KIND: Final[str] = "merge_policy"
AUTO_WHEN_GREEN: Final[str] = "auto-when-green"
ACTOR_HUMAN: Final[str] = "human"
ACTOR_AGENT_PREFIX: Final[str] = "agent:"
SESSION_VAR: Final[str] = "CLAUDE_CODE_SESSION_ID"
UNKNOWN_SESSION: Final[str] = "unknown"
LOG_REL: Final[str] = state_io.rel("approvals.log")
LOG_HEADER: Final[str] = "# Approval requests: time | kind | key | actor | approved\n"


class ApprovalError(ValueError):
    """An unknown approval kind."""


def human_marker_path(repo: Path | None = None) -> Path:
    """The one file whose contents count as a human approval."""
    return Path(repo if repo is not None else Path.cwd()) / MARKER_REL


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ApprovalError(f"unknown approval kind {kind!r}; use one of {', '.join(KINDS)}")
    return kind


def read_approvals(repo: Path | None = None) -> dict[str, list[str]]:
    """The `dts2_approvals` table; an unreadable file, a missing key or a wrong shape is an empty table (fail closed)."""
    try:
        data: Any = json.loads(human_marker_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    table: Any = data.get(APPROVALS_KEY) if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {str(kind): [str(k) for k in keys] for kind, keys in table.items() if isinstance(keys, list)}


def is_human_approved(kind: str, key: str, repo: Path | None = None) -> bool:
    """True only when the person listed `key` under `kind` in `.claude/settings.local.json`."""
    check_kind(kind)
    return str(key) in read_approvals(repo).get(kind, [])


def standing_auto_merge(repo: Path | None = None) -> bool:
    """True when the person's standing grant `"merge_policy": ["auto-when-green"]` is in the human file. It lets the agent merge
    directly, pinned to one exact head sha, once the required checks are green (GitHub auto-merge is never armed)."""
    return is_human_approved(MERGE_POLICY_KIND, AUTO_WHEN_GREEN, repo)


def actor_label(session_id: str | None = None) -> str:
    """`agent:<session_id>` for a model session, `human` when the caller is the person's own shell (no session variable)."""
    session: str | None = session_id if session_id is not None else os.environ.get(SESSION_VAR)
    return f"{ACTOR_AGENT_PREFIX}{session or UNKNOWN_SESSION}" if session or os.environ.get("DTS2_SON") else ACTOR_HUMAN


def record_actor(kind: str, key: str, actor: str, repo: Path | None = None) -> Path:
    """Log who asked for this approval and whether the channel held it at that moment. Never grants anything."""
    check_kind(kind)
    root: Path = Path(repo if repo is not None else Path.cwd())
    line: str = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} | {kind} | {key} | {actor} | {is_human_approved(kind, key, root)}\n"
    return state_io.append_text(root / LOG_REL, line, header=LOG_HEADER)


def deny_rules() -> list[str]:
    """Permission rules that keep the model away from the channel (used in the son `--settings` permissions.deny)."""
    return [f"Edit({MARKER_REL})", f"Write({MARKER_REL})", f"MultiEdit({MARKER_REL})", f"NotebookEdit({MARKER_REL})"]


LOCK_PHRASE: Final[re.Pattern[str]] = re.compile(r"^lock roadmap ([0-9a-f]{12})$", re.IGNORECASE)
KEY_IN_TEXT: Final[re.Pattern[str]] = re.compile(r"\b([0-9a-f]{12})\b", re.IGNORECASE)
LOCK_INTENT: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\block(?:ed)?\s+(?:it\s+|that\s+|this\s+)?in\b"),
    re.compile(r"\block(?:ed)?\s+(?:the\s+|that\s+|this\s+)?roadmap\b"),
    re.compile(r"\broadmap\s+(?:is\s+)?(?:locked|approved)\b"),
    re.compile(r"\bapprove(?:d)?\s+(?:the\s+|that\s+|this\s+)?roadmap\b"),
)
NOT_LOCK: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\w+n'?t|do\s+not|not|never|no|nah|nope|wait|hold|stop|cancel|unlock|later|until|before|if|when|unless|after|once|"
    r"yet|tomorrow|tonight|next|soon|maybe|otherwise|won|should|could|would|can|how|what|why)\b"
)
APOSTROPHES: Final[dict[int, str]] = {0x2018: "'", 0x2019: "'", 0x02BC: "'", 0x0060: "'"}

INTENT_MAX_WORDS: Final[int] = 16
BACKUP_SUFFIX: Final[str] = ".bak"


def grant(repo: Path, kind: str, key: str, agent_lock: bool = False) -> bool:
    """Append `key` under `kind` in the human file. The UserPromptSubmit hook calls this on text the person typed, and
    `lock_roadmap` calls it with `agent_lock=True` for an agent that passed the matching roadmap key.
    Refused (False, nothing written) inside a son launch (`DTS2_SON` set) unless `agent_lock`, or when the existing file
    is not a JSON object."""
    check_kind(kind)
    if os.environ.get("DTS2_SON") and not agent_lock:
        return False
    path: Path = human_marker_path(repo)
    data: dict[str, Any] = {}
    existed: bool = path.is_file()
    if existed:
        try:
            loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(loaded, dict):
            return False
        data = loaded
    table: Any = data.get(APPROVALS_KEY)
    if not isinstance(table, dict):
        table = {}
    keys: Any = table.get(kind)
    keys = [str(k) for k in keys] if isinstance(keys, list) else []
    if str(key) not in keys:
        keys.append(str(key))
    table[kind] = keys
    data[APPROVALS_KEY] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        path.with_name(path.name + BACKUP_SUFFIX).write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".approvals-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return False
    record_actor(kind, str(key), ACTOR_HUMAN, repo)
    return True


def lock_intent(prompt: str) -> tuple[bool, str | None]:
    """(is a lock, typed key or None) for one typed prompt. A lock is the exact `lock roadmap <key>`, or a short message in the
    owner's own words that says to lock or approve the roadmap ("lock it in", "approved, lock the roadmap"). A question, a
    negation or a condition ("don't lock it in yet", "lock it in if the tests pass?") is never a lock. A bare "yes" is not one."""
    text: str = prompt.strip()
    exact = LOCK_PHRASE.match(text)
    if exact is not None:
        return True, exact.group(1).lower()
    if "\n" in text or "`" in text or '"' in text:
        return False, None
    lowered: str = unicodedata.normalize("NFKC", text).translate(APOSTROPHES).lower()
    if not lowered.isascii() or "?" in lowered or len(lowered.split()) > INTENT_MAX_WORDS or NOT_LOCK.search(lowered):
        return False, None
    if re.search(r"(?<![a-z])'\s*lock|lock[^']*'(?![a-z])", lowered):
        return False, None
    if not any(pattern.search(lowered) for pattern in LOCK_INTENT):
        return False, None
    keys: list[str] = [k.lower() for k in KEY_IN_TEXT.findall(lowered)]
    return True, keys[0] if keys else None


def grant_from_prompt(raw: str, repo: Path) -> str:
    """The context line for one UserPromptSubmit payload: empty unless the typed prompt is a lock (see `lock_intent`).
    A lock without a key applies only while the current roadmap is waiting for approval; a typed key must match it."""
    try:
        payload: Any = json.loads(raw)
    except ValueError:
        return ""
    prompt: Any = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str):
        return ""
    is_lock, typed = lock_intent(prompt)
    if not is_lock:
        return ""
    import roadmap  # noqa: PLC0415 (roadmap imports this module)
    info: dict[str, Any] = roadmap.status(repo)
    current: str | None = info["key"]
    if typed is None:
        if current is None or info["approved"]:
            return ""
        typed = current
    if current != typed:
        return f"dt: roadmap key {typed} does not match the current roadmap {current}; nothing locked"
    if not info["approved"]:
        import gap_research  # noqa: PLC0415 (gap_research imports roadmap, which imports this module)
        blocked: str | None = gap_research.lock_block(Path(repo), typed)
        if blocked is not None:
            return f"{blocked}; nothing locked"
    if not grant(repo, roadmap.APPROVAL_KIND, typed):
        return f"dt: roadmap {typed} was not locked (the approvals file could not be written)"
    return f"dt: roadmap {typed} locked by the owner"


def open_terminal() -> Any:
    """The controlling terminal for reading and writing, or None when none is attached (a model's shell, CI, a pipe)."""
    try:
        raw: io.FileIO = io.FileIO("/dev/tty", "r+")
    except OSError:
        return None
    # A terminal is not seekable, so a plain open(..., "r+") in text mode fails; pair the raw stream instead.
    return io.TextIOWrapper(io.BufferedRWPair(raw, raw), encoding="utf-8", line_buffering=True)


AGENT_PROCESSES: frozenset[str] = frozenset({"claude", "codex", "gemini", "cursor-agent", "aider", "opencode", "goose", "amp", "antigravity", "grok", "muse"})
AGENT_ENV: tuple[str, ...] = ("CLAUDECODE", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "GEMINI_CLI")
MAX_ANCESTORS: int = 64


def agent_ancestor() -> str | None:
    """The name of an agent CLI this process runs under (by environment marker or /proc ancestry), or None.
    A command an agent runs is its child; the owner's own shell is the agent's parent, never its child."""
    for name in AGENT_ENV:
        if os.environ.get(name):
            return name
    pid: int = os.getppid()
    for _ in range(MAX_ANCESTORS):
        if pid <= 1:
            return None
        try:
            stat: str = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        comm: str = stat[stat.index("(") + 1 : stat.rindex(")")]
        if comm.lower() in AGENT_PROCESSES:
            return comm
        pid = int(stat[stat.rindex(")") + 2 :].split()[1])
    return None


PROVIDERS: Final[frozenset[str]] = frozenset({"claude", "codex", "cursor", "antigravity", "grok", "muse", "gemini", "aider", "opencode", "goose", "amp"})
PROVIDER_OF: Final[dict[str, str]] = {
    "claudecode": "claude", "codex_sandbox": "codex", "codex_sandbox_network_disabled": "codex", "gemini_cli": "gemini",
    "cursor-agent": "cursor", "son": "claude",
}
SIGNOFF_REL: Final[str] = state_io.rel("roadmap-signoffs.jsonl")
REQUIRED_PROVIDERS: Final[int] = 2
OVERRIDES: Final[tuple[str, ...]] = ("skip-review", "single-provider")


def provider_name(agent: str | None) -> str | None:
    """The provider an agent name belongs to, or None when it is not a known provider (unknown callers are refused)."""
    if not agent:
        return None
    name: str = agent.strip().lower()
    name = PROVIDER_OF.get(name, name)
    return name if name in PROVIDERS else None


def signoffs(repo: Path, key: str) -> list[str]:
    """The distinct providers that signed roadmap `key`, in the order they first signed."""
    path: Path = Path(repo) / SIGNOFF_REL
    seen: list[str] = []
    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return seen
    for line in lines:
        try:
            record: Any = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("key") != key:
            continue
        provider: str | None = provider_name(str(record.get("provider", "")))
        if provider is not None and provider not in seen:
            seen.append(provider)
    return seen


def sign_roadmap(repo: Path, key: str, provider: str | None = None, note: str = "") -> tuple[int, str]:
    """(exit code, message) for `approvals.py sign-roadmap <key>`: one agent's review sign-off on the current roadmap.
    The provider is the one given or, failing that, the agent this process runs under; an unknown provider is refused."""
    import roadmap  # noqa: PLC0415 (roadmap imports this module)
    current: str | None = roadmap.status(repo)["key"]
    if current is None:
        return 1, "dt: the roadmap has no scope to sign"
    if key.lower() != current:
        return 1, f"dt: roadmap key {key.lower()} does not match the current roadmap {current}; nothing signed"
    detected: str | None = "son" if os.environ.get("DTS2_SON") else agent_ancestor()
    name: str | None = provider_name(provider) if provider else provider_name(detected)
    if name is None:
        return 2, f"dt: unknown provider ({provider or detected or 'none detected'}); pass --provider one of {', '.join(sorted(PROVIDERS))}"
    record: dict[str, str] = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "key": current, "provider": name,
                              "actor": detected or "unknown", "note": note}
    state_io.append_text(Path(repo) / SIGNOFF_REL, json.dumps(record) + "\n")
    signed: list[str] = signoffs(repo, current)
    return 0, f"dt: roadmap {current} signed by {name} ({len(signed)}/{REQUIRED_PROVIDERS} providers: {', '.join(signed)})"


def lock_roadmap(repo: Path, key: str | None = None, terminal: Any = None, override: tuple[str, str] | None = None) -> tuple[int, str]:
    """(exit code, message) for `approvals.py lock-roadmap`, in any harness.
    The owner runs it in their own terminal and types yes. An agent launch (a son, or a process under an agent CLI) may
    run it too, with no prompt, when the roadmap has a scope, the agent passes the current roadmap key, two providers
    have signed that key (or an override with a reason is given), and the roadmap is not locked yet; the lock is logged
    as `agent:<name>`. Refused with exit code 4, for the owner and an agent alike, until the setup gap pass has run for this
    key and every gap it found is resolved or rejected (`gap_research.lock_block`). Refused when a given key does not match, when an agent gives no key or lacks the sign-offs, when
    no terminal is attached for the owner, or without the owner's typed yes."""
    agent: str | None = "son" if os.environ.get("DTS2_SON") else (agent_ancestor() if terminal is None else None)
    import roadmap  # noqa: PLC0415 (roadmap imports this module)
    info: dict[str, Any] = roadmap.status(repo)
    current: str | None = info["key"]
    if current is None:
        return 1, "dt: the roadmap has no scope to approve"
    if key is not None and key.lower() != current:
        return 1, f"dt: roadmap key {key.lower()} does not match the current roadmap {current}; nothing locked"
    if info["approved"]:
        return 0, f"dt: roadmap {current} is already locked"
    import gap_research  # noqa: PLC0415 (gap_research imports roadmap, which imports this module)
    blocked: str | None = gap_research.lock_block(Path(repo), current)
    if blocked is not None:
        return 4, f"{blocked}; nothing locked"
    if agent is not None:
        return agent_lock_roadmap(repo, current, key, agent, override)
    tty: Any = terminal if terminal is not None else open_terminal()
    if tty is None:
        return 2, "dt: lock-roadmap needs your own terminal (no terminal is attached); nothing locked"
    try:
        signed: list[str] = signoffs(repo, current)
        tty.write(f"Lock roadmap {current} ({info['sections']} sections, signed by {', '.join(signed) or 'no agent yet'})? Type yes: ")
        tty.flush()
        answer: str = tty.readline().strip().lower()
    finally:
        if terminal is None:
            tty.close()
    if answer not in ("y", "yes"):
        return 1, f"dt: roadmap {current} not locked"
    if not grant(repo, roadmap.APPROVAL_KIND, current):
        return 1, f"dt: roadmap {current} was not locked (the approvals file could not be written)"
    return 0, f"dt: roadmap {current} locked by the owner"


def agent_lock_roadmap(repo: Path, current: str, key: str | None, agent: str, override: tuple[str, str] | None = None) -> tuple[int, str]:
    """Lock for an agent launch: it must name the current roadmap key, so it locks the scope it read and nothing newer,
    and agents from two different providers must have signed that key, unless an override with a reason is given."""
    import roadmap  # noqa: PLC0415 (roadmap imports this module)
    if key is None:
        return 2, f"dt: an agent ({agent}) must pass the roadmap key: approvals.py lock-roadmap {current}; nothing locked"
    actor: str = f"agent:{agent}"
    if override is not None:
        mode, reason = override
        if mode not in OVERRIDES or not reason.strip():
            return 2, f"dt: an override needs one of {', '.join(OVERRIDES)} and a reason; nothing locked"
        actor = f"agent:{agent} override:{mode} ({reason.strip()})"
    else:
        signed: list[str] = signoffs(repo, current)
        if len(signed) < REQUIRED_PROVIDERS:
            return 3, (f"dt: roadmap {current} needs sign-offs from {REQUIRED_PROVIDERS} different providers "
                       f"(has {len(signed)}: {', '.join(signed) or 'none'}); run approvals.py sign-roadmap {current} from another provider; nothing locked")
    if not grant(repo, roadmap.APPROVAL_KIND, current, agent_lock=True):
        return 1, f"dt: roadmap {current} was not locked (the approvals file could not be written)"
    record_actor(roadmap.APPROVAL_KIND, current, actor, repo)
    return 0, f"dt: roadmap {current} locked by an agent ({agent})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="exit 0 when the person approved <kind> <key>, 1 otherwise; logs the asker")
    chk.add_argument("kind")
    chk.add_argument("key")
    chk.add_argument("--session", default=None)
    sub.add_parser("path")
    sub.add_parser("grant-from-prompt", help="read a UserPromptSubmit payload on stdin; a typed lock (\"lock it in\") locks the roadmap")
    lock = sub.add_parser("lock-roadmap", help="lock the current roadmap in any harness; the owner types yes, an agent passes the roadmap key")
    lock.add_argument("key", nargs="?", default=None)
    skip = lock.add_mutually_exclusive_group()
    skip.add_argument("--skip-review", metavar="REASON", default=None, help="the owner said to skip the second review or not to wait")
    skip.add_argument("--single-provider", metavar="REASON", default=None, help="only one agent provider is available")
    sign = sub.add_parser("sign-roadmap", help="record this agent's review sign-off on the current roadmap key")
    sign.add_argument("key")
    sign.add_argument("--provider", default=None, help=f"one of {', '.join(sorted(PROVIDERS))}; detected when omitted")
    sign.add_argument("--note", default="")
    args = parser.parse_args(argv)
    repo: Path = Path(args.repo)
    if args.cmd == "sign-roadmap":
        code, message = sign_roadmap(repo, args.key, args.provider, args.note)
        print(message)
        return code
    if args.cmd == "lock-roadmap":
        override: tuple[str, str] | None = None
        if args.skip_review is not None:
            override = ("skip-review", args.skip_review)
        elif args.single_provider is not None:
            override = ("single-provider", args.single_provider)
        code, message = lock_roadmap(repo, args.key, override=override)
        print(message)
        return code
    if args.cmd == "grant-from-prompt":
        try:
            line: str = grant_from_prompt(sys.stdin.read(), repo)
        except Exception:  # noqa: BLE001 (a hook must fail open)
            return 0
        if line:
            print(line)
        return 0
    if args.cmd == "path":
        print(human_marker_path(repo))
        return 0
    try:
        record_actor(args.kind, args.key, actor_label(args.session), repo)
        approved: bool = is_human_approved(args.kind, args.key, repo)
    except ApprovalError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps({"kind": args.kind, "key": args.key, "approved": approved}))
    return 0 if approved else 1


if __name__ == "__main__":
    sys.exit(main())
