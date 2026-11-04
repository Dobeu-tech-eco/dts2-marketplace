#!/usr/bin/env python3
"""Deterministic checks that run before any model vote, and the run ledger they write.

Subcommands print one JSON object each:
  run       --stamp S [--cwd DIR]   run test, typecheck, lint, secret scan and scope check; one ledger line each
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
ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Za-z0-9_]*)\s*[=:]\s*\S+",
                                                re.IGNORECASE)
VERDICT_TOKEN: Final[re.Pattern[str]] = re.compile(r"\b(VERIFIED|BLOCKED|APPROVE|REJECT)\b|^#+\s*Verdict", re.MULTILINE)


def redact(text: str) -> str:
    """Remove anything key-shaped or assigned to a secret-looking name before it reaches a log or the ledger."""
    cleaned: str = ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
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


def parse_config(text: str) -> dict[str, Any]:
    """Read the `commands:` block (key: value) and the `do_not_touch:` list from .harness/config.yaml."""
    commands: dict[str, str] = {}
    forbidden: list[str] = []
    block: str = ""
    for raw in text.splitlines():
        line: str = raw.rstrip()
        if line and not line.startswith((" ", "\t", "-")):
            block = line.split(":", 1)[0].strip()
            continue
        body: str = line.strip()
        if block == "commands" and ":" in body:
            key, value = body.split(":", 1)
            commands[key.strip()] = value.strip().strip("\"'")
        elif block == "do_not_touch" and body.startswith("- "):
            forbidden.append(body[2:].strip().strip("\"'"))
    return {"commands": commands, "do_not_touch": forbidden}


def load_config(cwd: Path) -> dict[str, Any]:
    path: Path = cwd / CONFIG_PATH
    return parse_config(path.read_text(encoding="utf-8")) if path.is_file() else {"commands": {}, "do_not_touch": []}


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


def secret_scan(cwd: Path, log: Path) -> dict[str, Any]:
    started: float = time.monotonic()
    for env_name, tool, args in (("DTS2_GITLEAKS_BIN", "gitleaks", ["detect", "--no-git", "--redact", "-s", str(cwd)]),
                                 ("DTS2_TRUFFLEHOG_BIN", "trufflehog", ["filesystem", str(cwd), "--fail", "--no-update"])):
        cmd: list[str] | None = binary(env_name, tool)
        if cmd is None:
            continue
        try:
            done = subprocess.run(cmd + args, cwd=str(cwd), capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return finish("secret-scan", FAIL, started, log, f"{tool} did not finish: {error}\n", cwd)
        return finish("secret-scan", PASS if done.returncode == 0 else FAIL, started, log, done.stdout + done.stderr, cwd)
    return finish("secret-scan", SKIP, started, log, "warning: neither gitleaks nor trufflehog is installed; secret scan skipped\n", cwd)


def changed_files(cwd: Path) -> list[str] | None:
    cmd: list[str] = (binary("DTS2_GIT_BIN", "git") or ["git"]) + ["diff", "--name-only", "HEAD"]
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [line.strip() for line in done.stdout.splitlines() if line.strip()] if done.returncode == 0 else None


def scope_check(cwd: Path, forbidden: list[str], log: Path) -> dict[str, Any]:
    started: float = time.monotonic()
    files: list[str] | None = changed_files(cwd)
    if files is None:
        return finish("scope-check", SKIP, started, log, "could not list changed files; scope check skipped\n", cwd)
    hits: list[str] = [f for f in files if any(fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(Path(f).name, pat) for pat in forbidden)]
    body: str = "".join(f"touches do_not_touch: {f}\n" for f in hits) or f"{len(files)} changed files, none protected\n"
    return finish("scope-check", FAIL if hits else PASS, started, log, body, cwd)


def run_checks(cwd: Path, stamp: str) -> dict[str, Any]:
    config: dict[str, Any] = load_config(cwd)
    logs: Path = run_dir(cwd, stamp) / CHECKS_DIR
    results: list[dict[str, Any]] = [run_command(n, config["commands"].get(n, ""), cwd, logs / f"{n}.log") for n in COMMAND_CHECKS]
    results.append(secret_scan(cwd, logs / "secret-scan.log"))
    results.append(scope_check(cwd, config["do_not_touch"], logs / "scope-check.log"))
    path: Path = ledger_path(cwd, stamp)
    for record in results:
        append_ledger(path, record)
    return gate(read_ledger(path)) | {"checks": results, "ledger": str(path)}


def gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    red: list[str] = red_checks(records)
    ran: int = len(latest_checks(records))
    if not ran:
        return {"ok": False, "votes_allowed": False, "red": [], "action": "run-checks",
                "reason": "no deterministic check results on record; run them before any vote"}
    if red:
        return {"ok": False, "votes_allowed": False, "red": red, "action": "fix",
                "reason": f"red checks: {', '.join(red)}; fix round with zero votes"}
    return {"ok": True, "votes_allowed": True, "red": [], "action": "vote", "reason": "every deterministic check is green or skipped"}


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
        result = run_checks(cwd, args.stamp)
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
