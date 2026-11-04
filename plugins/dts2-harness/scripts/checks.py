#!/usr/bin/env python3
"""Deterministic checks that run before any model vote, and the run ledger they write.

Subcommands print one JSON object each:
  run       --stamp S [--cwd DIR] [--base REF]
                                    run test, typecheck, lint, secret scan and scope check; one ledger line each.
                                    The scope check covers committed, uncommitted and untracked files since the base:
                                    --base, else the run's recorded `.harness/runs/<stamp>/base`, else origin's default branch
  gate      --stamp S               may the vote start? red checks mean a fix round with zero votes
  summary   --stamp S               one markdown table built from the ledger, for the lead's brief and the PR receipt
  env-missing --stamp S NAME ...    record env var NAMES that are missing (never values)
  scout-check FILE                  an evidence file must hold no verdict token
The ledger is .harness/runs/<stamp>/ledger.jsonl: one JSON object per line, kind `check`, `env` or `ballot`."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import atomic_write  # noqa: E402

RUNS_DIR: Final[str] = ".harness/runs"
LEDGER_NAME: Final[str] = "ledger.jsonl"
CHECKS_DIR: Final[str] = "checks"
CONFIG_PATH: Final[str] = ".harness/config.yaml"
COMMAND_CHECKS: Final[tuple[str, ...]] = ("test", "typecheck", "lint")
EXPECTED_CHECKS: Final[tuple[str, ...]] = (*COMMAND_CHECKS, "secret-scan", "scope-check")
BASE_NAME: Final[str] = "base"
DEFAULT_BASES: Final[tuple[str, ...]] = ("origin/HEAD", "origin/main", "origin/master")
PASS: Final[str] = "pass"
FAIL: Final[str] = "fail"
SKIP: Final[str] = "skip"
TIMEOUT_S: Final[int] = 900
GIT_TIMEOUT_S: Final[int] = 30
REDACTED: Final[str] = "<redacted>"
ENV_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]*$")
KEY_SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)
ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"""\b([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Za-z0-9_]*)["']?[ \t]*[=:][ \t]*("[^"]*"|'[^']*'|\S+)""", re.IGNORECASE)
BEARER: Final[re.Pattern[str]] = re.compile(r"\bBearer[ \t]+\S+", re.IGNORECASE)
URL_USERINFO: Final[re.Pattern[str]] = re.compile(r"(://[^/\s:@]+:)[^@\s]+@")
VERDICT_TOKEN: Final[re.Pattern[str]] = re.compile(r"\b(VERIFIED|BLOCKED|APPROVE|REJECT)\b|^#+\s*Verdict", re.MULTILINE)


def redact(text: str) -> str:
    """Remove anything key-shaped or assigned to a secret-looking name before it reaches a log or the ledger."""
    cleaned: str = ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    cleaned = BEARER.sub(f"Bearer {REDACTED}", cleaned)
    cleaned = URL_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}@", cleaned)
    for shape in KEY_SHAPES:
        cleaned = shape.sub(REDACTED, cleaned)
    return cleaned


def binary(env_name: str, default: str) -> list[str] | None:
    value: str | None = os.environ.get(env_name) or shutil.which(default)
    if not value:
        return None
    return [sys.executable, value] if value.endswith(".py") else [value]


def run_dir(cwd: Path, stamp: str) -> Path:
    return cwd / RUNS_DIR / stamp


def ledger_path(cwd: Path, stamp: str) -> Path:
    return run_dir(cwd, stamp) / LEDGER_NAME


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def append_ledger(path: Path, record: dict[str, Any]) -> None:
    """Append one line. The whole file is rewritten through atomic_write so a crash never leaves a torn line."""
    existing: str = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, existing + json.dumps(record, sort_keys=True) + "\n")


def latest_checks(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The newest `check` record per check name, so a re-run after a fix replaces the red one."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("kind") == "check" and isinstance(record.get("name"), str):
            latest[record["name"]] = record
    return latest


def red_checks(records: list[dict[str, Any]]) -> list[str]:
    return sorted(name for name, rec in latest_checks(records).items() if rec.get("status") == FAIL)


def inline_list(value: str) -> list[str] | None:
    """Read a one-line flow list such as [".env", "secrets/**"]; None when the text is not one."""
    if not (value.startswith("[") and value.endswith("]")):
        return None
    return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]


def parse_config(text: str) -> dict[str, Any]:
    """Read the `commands:` block (key: value) and the `do_not_touch:` list (block or inline) from .harness/config.yaml.

    `unreadable` is true when `do_not_touch` has a value this parser cannot read, so the scope check fails closed."""
    commands: dict[str, str] = {}
    forbidden: list[str] = []
    unreadable: bool = False
    block: str = ""
    for raw in text.splitlines():
        line: str = raw.rstrip()
        if line and not line.startswith((" ", "\t", "-")):
            block, _, rest = line.partition(":")
            block = block.strip()
            value: str = rest.split(" #", 1)[0].strip()
            if block == "do_not_touch" and value and not value.startswith("#"):
                items: list[str] | None = inline_list(value)
                if items is None:
                    unreadable = True
                else:
                    forbidden += items
            continue
        body: str = line.strip()
        if block == "commands" and ":" in body:
            key, value = body.split(":", 1)
            commands[key.strip()] = value.strip().strip("\"'")
        elif block == "do_not_touch" and body.startswith("- "):
            forbidden.append(body[2:].strip().strip("\"'"))
    return {"commands": commands, "do_not_touch": forbidden, "unreadable": unreadable}


def load_config(cwd: Path) -> dict[str, Any]:
    path: Path = cwd / CONFIG_PATH
    return parse_config(path.read_text(encoding="utf-8")) if path.is_file() else {"commands": {}, "do_not_touch": [], "unreadable": False}


def finish(name: str, status: str, started: float, log: Path, output: str, cwd: Path) -> dict[str, Any]:
    log.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(log, redact(output))
    return {"kind": "check", "name": name, "status": status, "duration_ms": int((time.monotonic() - started) * 1000),
            "log_path": str(log.relative_to(cwd)) if log.is_relative_to(cwd) else str(log)}


def run_command(name: str, command: str, cwd: Path, log: Path) -> dict[str, Any]:
    started: float = time.monotonic()
    if not command:
        return finish(name, SKIP, started, log, f"no `{name}` command configured\n", cwd)
    try:
        done = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return finish(name, FAIL, started, log, f"timed out after {TIMEOUT_S}s\n", cwd)
    except OSError as error:
        return finish(name, FAIL, started, log, f"could not start: {error}\n", cwd)
    return finish(name, PASS if done.returncode == 0 else FAIL, started, log, done.stdout + done.stderr, cwd)


def trufflehog_report(stdout: str) -> str:
    """Detector, file and line per finding. The raw secret fields are never copied."""
    lines: list[str] = []
    unparsed: int = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            finding: Any = json.loads(line)
        except ValueError:
            unparsed += 1
            continue
        if not isinstance(finding, dict):
            unparsed += 1
            continue
        where: dict[str, Any] = {}
        data: Any = (finding.get("SourceMetadata") or {}).get("Data") or {}
        for source in data.values() if isinstance(data, dict) else []:
            if isinstance(source, dict):
                where = source
                break
        lines.append(f"finding: detector={finding.get('DetectorName')} file={where.get('file')} line={where.get('line')}\n")
    if unparsed:
        lines.append(f"{unparsed} output lines were not parsed and are not logged\n")
    return "".join(lines)


def secret_scan(cwd: Path, log: Path) -> dict[str, Any]:
    started: float = time.monotonic()
    for env_name, tool, args in (("DTS2_GITLEAKS_BIN", "gitleaks", ["detect", "--no-git", "--redact", "-s", str(cwd)]),
                                 ("DTS2_TRUFFLEHOG_BIN", "trufflehog", ["filesystem", str(cwd), "--json", "--fail", "--no-update"])):
        cmd: list[str] | None = binary(env_name, tool)
        if cmd is None:
            continue
        try:
            done = subprocess.run(cmd + args, cwd=str(cwd), capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return finish("secret-scan", FAIL, started, log, f"{tool} did not finish: {error}\n", cwd)
        status: str = PASS if done.returncode == 0 else FAIL
        if tool == "trufflehog":
            return finish("secret-scan", status, started, log, f"trufflehog exit {done.returncode}\n" + trufflehog_report(done.stdout), cwd)
        return finish("secret-scan", status, started, log, done.stdout + done.stderr, cwd)
    return finish("secret-scan", SKIP, started, log, "warning: neither gitleaks nor trufflehog is installed; secret scan skipped\n", cwd)


def git_lines(cwd: Path, *args: str) -> list[str] | None:
    cmd: list[str] = (binary("DTS2_GIT_BIN", "git") or ["git"]) + list(args)
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [line.strip() for line in done.stdout.splitlines() if line.strip()] if done.returncode == 0 else None


def resolve_base(cwd: Path, stamp: str, base: str | None) -> str | None:
    """The ref the run started from: --base, else the run's recorded base, else origin's default branch."""
    if base:
        return base
    recorded: Path = run_dir(cwd, stamp) / BASE_NAME
    if recorded.is_file() and recorded.read_text(encoding="utf-8").strip():
        return recorded.read_text(encoding="utf-8").strip().splitlines()[0]
    for candidate in DEFAULT_BASES:
        if git_lines(cwd, "rev-parse", "--verify", "--quiet", candidate) is not None:
            return candidate
    return None


def changed_files(cwd: Path, base: str | None) -> list[str] | None:
    """Union of committed (since the merge-base), uncommitted and untracked files; None when any part cannot be listed."""
    if not base:
        return None
    parts: list[list[str] | None] = [git_lines(cwd, "diff", "--name-only", f"{base}...HEAD"), git_lines(cwd, "diff", "--name-only", "HEAD"),
                                     git_lines(cwd, "ls-files", "--others", "--exclude-standard")]
    if any(part is None for part in parts):
        return None
    return sorted({f for part in parts for f in part or []})


def scope_check(cwd: Path, forbidden: list[str], log: Path, base: str | None = None, unreadable: bool = False) -> dict[str, Any]:
    started: float = time.monotonic()
    if unreadable:
        return finish("scope-check", FAIL, started, log, "do_not_touch has a value this parser cannot read; use a block list or a one-line [a, b] list\n", cwd)
    files: list[str] | None = changed_files(cwd, base)
    if files is None:
        if forbidden:
            return finish("scope-check", FAIL, started, log, "could not list changed files (pass --base <ref> or record the base); do_not_touch is set, so this fails closed\n", cwd)
        return finish("scope-check", SKIP, started, log, "could not list changed files; nothing is protected, scope check skipped\n", cwd)
    hits: list[str] = [f for f in files if any(fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(Path(f).name, pat) for pat in forbidden)]
    body: str = "".join(f"touches do_not_touch: {f}\n" for f in hits) or f"{len(files)} changed files, none protected\n"
    return finish("scope-check", FAIL if hits else PASS, started, log, body, cwd)


def run_checks(cwd: Path, stamp: str, base: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = load_config(cwd)
    logs: Path = run_dir(cwd, stamp) / CHECKS_DIR
    results: list[dict[str, Any]] = [run_command(n, config["commands"].get(n, ""), cwd, logs / f"{n}.log") for n in COMMAND_CHECKS]
    results.append(secret_scan(cwd, logs / "secret-scan.log"))
    results.append(scope_check(cwd, config["do_not_touch"], logs / "scope-check.log", resolve_base(cwd, stamp, base), config["unreadable"]))
    path: Path = ledger_path(cwd, stamp)
    for record in results:
        append_ledger(path, record)
    return gate(read_ledger(path)) | {"checks": results, "ledger": str(path)}


def gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = latest_checks(records)
    red: list[str] = red_checks(records)
    missing: list[str] = [name for name in EXPECTED_CHECKS if name not in latest]
    if red:
        return {"ok": False, "votes_allowed": False, "red": red, "missing": missing, "action": "fix",
                "reason": f"red checks: {', '.join(red)}; fix round with zero votes"}
    if missing:
        reason: str = ("no deterministic check results on record; run them before any vote" if not latest
                       else f"missing checks: {', '.join(missing)}; run all five before any vote")
        return {"ok": False, "votes_allowed": False, "red": [], "missing": missing, "action": "run-checks", "reason": reason}
    return {"ok": True, "votes_allowed": True, "red": [], "missing": [], "action": "vote",
            "reason": "every deterministic check is green or skipped"}


def summary(records: list[dict[str, Any]]) -> str:
    lines: list[str] = ["| check | status | ms | log |", "| --- | --- | --- | --- |"]
    for name, rec in sorted(latest_checks(records).items()):
        lines.append(f"| {name} | {rec.get('status')} | {rec.get('duration_ms')} | {rec.get('log_path')} |")
    missing: list[str] = sorted({n for r in records if r.get("kind") == "env" for n in r.get("missing", [])})
    if missing:
        lines += ["", f"Missing env vars (names only): {', '.join(missing)}"]
    return "\n".join(lines) + "\n"


def record_missing_env(path: Path, names: list[str]) -> dict[str, Any]:
    """Keep only well-formed variable names; a `NAME=value` argument loses its value, anything else is dropped."""
    clean: list[str] = sorted({n.split("=", 1)[0] for n in names if ENV_NAME.match(n.split("=", 1)[0])})
    append_ledger(path, {"kind": "env", "missing": clean})
    return {"ok": True, "missing": clean, "dropped": len(names) - len(clean)}


def scout_check(path: Path) -> dict[str, Any]:
    tokens: list[str] = sorted({m.group(0).strip() for m in VERDICT_TOKEN.finditer(path.read_text(encoding="utf-8"))})
    return {"ok": not tokens, "tokens": tokens,
            "reason": "evidence only" if not tokens else "scout output carries a verdict token; the verifier alone decides"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("run", "gate", "summary", "env-missing"):
        p = sub.add_parser(name)
        p.add_argument("--stamp", required=True)
        p.add_argument("--cwd", default=".")
        if name == "run":
            p.add_argument("--base", default=None, help="ref the run started from; default the recorded base or origin's default branch")
        if name == "env-missing":
            p.add_argument("names", nargs="+")
    sub.add_parser("scout-check").add_argument("file")
    args = parser.parse_args()
    if args.cmd == "scout-check":
        result: dict[str, Any] = scout_check(Path(args.file))
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    cwd: Path = Path(args.cwd)
    path: Path = ledger_path(cwd, args.stamp)
    if args.cmd == "run":
        result = run_checks(cwd, args.stamp, args.base)
    elif args.cmd == "gate":
        result = gate(read_ledger(path))
    elif args.cmd == "summary":
        result = {"ok": True, "markdown": summary(read_ledger(path))}
    else:
        result = record_missing_env(path, args.names)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
