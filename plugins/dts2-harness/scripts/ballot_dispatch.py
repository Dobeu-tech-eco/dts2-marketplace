#!/usr/bin/env python3
"""Ballot provenance (G-68): a script, not the head's say-so, performs each council seat dispatch.

`dispatch` runs one seat through `model_call.invoke` (so it shares the global call limit), writes the ballot file and, beside
it, `<ballot>.dispatch.json` holding the argv, the model, the session id and the SHA-256 of the ballot text. `council.py tally`
refuses a ballot with no record, an incomplete record, or text that no longer matches its hash.

Claude seats run with `--json-schema` (the answer is a typed verdict object, turned into the strict `VOTE:` ballot here) and
`--restricted` (no command-running tools). Other providers answer in the ballot format and keep their own sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_call import invoke, parse_result  # noqa: E402
from proc import binary  # noqa: E402
from son_launch import provider_env  # noqa: E402

RECORD_SUFFIX: Final[str] = ".dispatch.json"
TIMEOUT_S: Final[float] = 900.0
BRIEF_HEADING: Final[str] = "## Dissent brief"
VERDICTS: Final[tuple[str, ...]] = ("APPROVE", "REJECT")
REQUIRED_FIELDS: Final[tuple[str, ...]] = ("argv", "model", "sha256")
BALLOT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object", "additionalProperties": False, "required": ["verdict", "reasons"],
    "properties": {"verdict": {"enum": list(VERDICTS)}, "reasons": {"type": "string"}, "dissent_brief": {"type": "string"}},
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_path(ballot: Path) -> Path:
    """`<seat>.md` -> `<seat>.md.dispatch.json` (never matches a `*.md` glob, so a dossier does not read it)."""
    return ballot.with_name(ballot.name + RECORD_SUFFIX)


def write_record(ballot: Path, argv: list[str], model: str, session_id: str | None) -> dict[str, Any]:
    """Write the dispatch record for the ballot text now on disk."""
    record: dict[str, Any] = {"argv": argv, "model": model, "session_id": session_id,
                              "sha256": sha256_text(ballot.read_text(encoding="utf-8"))}
    record_path(ballot).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def provenance_problem(ballot: Path) -> str | None:
    """Why this ballot has no valid dispatch record, or None."""
    path: Path = record_path(ballot)
    try:
        record: Any = json.loads(path.read_text(encoding="utf-8"))
        text: str = ballot.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return f"{ballot.name}: no readable dispatch record ({path.name})"
    if not isinstance(record, dict) or any(not record.get(k) for k in REQUIRED_FIELDS):
        return f"{ballot.name}: dispatch record lacks {', '.join(REQUIRED_FIELDS)}"
    if record["sha256"] != sha256_text(text):
        return f"{ballot.name}: the ballot changed after its dispatch (sha256 mismatch)"
    return None


def claude_argv(model: str) -> list[str]:
    """A Claude council seat: typed output and no command-running tools; the prompt arrives on stdin."""
    return [*binary("DTS2_CLAUDE_BIN", "claude"), "-p", "--model", model, "--output-format", "json",
            "--json-schema", json.dumps(BALLOT_SCHEMA, separators=(",", ":")), "--restricted"]


def ballot_from_structured(stdout: str) -> str | None:
    """The strict ballot text for a Claude seat's JSON answer, or None when it does not carry a valid verdict object."""
    try:
        data: Any = json.loads(stdout)
    except ValueError:
        return None
    body: Any = data.get("structured_output") if isinstance(data, dict) else None
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if not isinstance(body, dict) or body.get("verdict") not in VERDICTS or not isinstance(body.get("reasons"), str):
        return None
    brief: Any = body.get("dissent_brief")
    tail: str = f"\n\n{BRIEF_HEADING}\n\n{brief.strip()}\n" if isinstance(brief, str) and brief.strip() else "\n"
    return f"VOTE: {body['verdict']}\n\n{body['reasons'].strip()}{tail}"


def dispatch_seat(seat: str, argv: list[str], model: str, prompt: str, out_dir: Path, claude: bool,
                  cwd: Path | None = None) -> dict[str, Any]:
    """Run one seat and write `<seat>.md` plus its dispatch record. A failed or unreadable answer writes nothing."""
    root: Path = cwd or Path.cwd()
    env: dict[str, str] = provider_env(dict(os.environ), claude=claude)
    call: dict[str, Any] = invoke(argv, root, TIMEOUT_S, f"council-{seat}", env=env, stdin_text=prompt)
    if call["code"] != 0:
        return {"ok": False, "seat": seat, "reason": f"dispatch exited {call['code']}"}
    text: str | None = ballot_from_structured(call["stdout"]) if claude else call["stdout"]
    if not text:
        return {"ok": False, "seat": seat, "reason": "the answer carries no ballot"}
    ballot: Path = out_dir / f"{seat}.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    ballot.write_text(text, encoding="utf-8")
    parsed: dict[str, Any] | None = parse_result(call["stdout"]) if claude else None
    record: dict[str, Any] = write_record(ballot, argv, model, parsed["session_id"] if parsed else None)
    return {"ok": True, "seat": seat, "ballot": str(ballot), "sha256": record["sha256"], "session_id": record["session_id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    dis = sub.add_parser("dispatch", help="run one seat and record its provenance")
    dis.add_argument("--seat", required=True)
    dis.add_argument("--model", required=True)
    dis.add_argument("--prompt-file", required=True)
    dis.add_argument("--out-dir", required=True)
    dis.add_argument("--provider", default="claude", help="claude, or the argv words after `--` for another provider")
    dis.add_argument("command", nargs="*", help="argv for a non-Claude provider (after --)")
    args = parser.parse_args(argv)
    prompt: str = Path(args.prompt_file).read_text(encoding="utf-8")
    is_claude: bool = args.provider == "claude"
    words: list[str] = claude_argv(args.model) if is_claude else args.command
    if not words:
        print(json.dumps({"ok": False, "reason": "no command given for a non-Claude seat"}))
        return 2
    result: dict[str, Any] = dispatch_seat(args.seat, words, args.model, prompt, Path(args.out_dir), is_claude)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
