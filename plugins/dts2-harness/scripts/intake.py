#!/usr/bin/env python3
"""Prompt intake queue: capture every prompt typed mid-run, classify it, and tell the agent how to fold it in.

Kinds: `fold` (add to the task ledger and keep working), `clarify` (may change direction: ask at the next safe point),
`steer` (explicit stop-and-redirect). Deterministic and stdlib only."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_io  # noqa: E402

FOLD: Final[str] = "fold"
CLARIFY: Final[str] = "clarify"
STEER: Final[str] = "steer"
KINDS: Final[tuple[str, ...]] = (FOLD, CLARIFY, STEER)
OPEN: Final[str] = "open"
SET: Final[str] = "set"
STEERED: Final[str] = "steered"
DONE: Final[str] = "done"
STATUSES: Final[tuple[str, ...]] = (OPEN, SET, STEERED, DONE)
RESOLVE_TARGETS: Final[tuple[str, ...]] = (FOLD, CLARIFY, STEER, DONE)

CLARITY_THRESHOLD: Final[int] = 60
QUESTION_BUDGET: Final[int] = 2
MAX_TEXT_CHARS: Final[int] = 4000
ASSUMPTION_CHARS: Final[int] = 160
SCORE_MAX: Final[int] = 100
SCORE_MIN: Final[int] = 0
SHORT_WORDS: Final[int] = 6
SHORT_PENALTY: Final[int] = 30
NO_NOUN_PENALTY: Final[int] = 20
NOUN_MIN_LETTERS: Final[int] = 5
VAGUE_LEAD_WORDS: Final[int] = 10
VAGUE_PENALTY: Final[int] = 25
QUESTION_PENALTY: Final[int] = 15
STEER_PREFIXES: Final[tuple[str, ...]] = ("/dts2:steer", "steer:")
SLASH: Final[str] = "/"
VAGUE_LEADS: Final[frozenset[str]] = frozenset({"it", "this", "that", "those"})
STOPWORDS: Final[frozenset[str]] = frozenset({
    "about", "after", "again", "also", "because", "before", "could", "doing", "every", "going", "should", "their",
    "there", "these", "thing", "things", "those", "through", "under", "where", "which", "while", "would", "other",
    "being", "still", "using", "really", "please"})
CLARIFY_WORDS: Final[tuple[str, ...]] = (
    "stop", "cancel", "instead", "scrap", "revert", "undo", "don't", "do not", "wrong approach", "change direction",
    "start over", "forget that")
CLARIFY_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w'])(?:" + "|".join(re.escape(w) for w in CLARIFY_WORDS) + r")(?![\w'])", re.I)
WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9']+")
DIRECTION_QUESTION: Final[str] = "Should this change the direction of the current work, or only add to it?"
QUESTION_TEMPLATES: Final[tuple[str, ...]] = (
    "What outcome do you want from this?",
    "Which part or file should it touch?",
    "How will we know it is done?")
ID_PREFIX: Final[str] = "in-"
HOOK_FIELD: Final[str] = "prompt"
SOURCES: Final[tuple[str, ...]] = ("hook", "cli")
EXIT_USAGE: Final[int] = 2
HOOK_LOCK_TRIES: Final[int] = 1
MD_HEADER: Final[str] = "# Intake queue\n\nGenerated from intake.jsonl by scripts/intake.py. Do not edit by hand.\n\n"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def words_of(text: str) -> list[str]:
    return WORD_RE.findall(text)


def strip_steer_prefix(text: str) -> str | None:
    """The text after a steer prefix, or None when the text is not a steer."""
    lowered: str = text.lower()
    for prefix in STEER_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return None


def classify(prompt: str) -> tuple[str, str] | None:
    """(kind, text) for a prompt, or None when nothing should be recorded."""
    text: str = (prompt or "").strip()
    if not text:
        return None
    steer_text: str | None = strip_steer_prefix(text)
    if steer_text is not None:
        return STEER, steer_text
    if text.startswith(SLASH):
        return None
    return (CLARIFY if CLARIFY_RE.search(text) else FOLD), text


def has_concrete_word(words: list[str]) -> bool:
    return any(len(w) >= NOUN_MIN_LETTERS and w.lower() not in STOPWORDS for w in words)


def clarity_score(text: str) -> int:
    words: list[str] = words_of(text)
    score: int = SCORE_MAX
    if len(words) < SHORT_WORDS:
        score -= SHORT_PENALTY
    if not has_concrete_word(words):
        score -= NO_NOUN_PENALTY
    if words and words[0].lower() in VAGUE_LEADS and len(words) < VAGUE_LEAD_WORDS:
        score -= VAGUE_PENALTY
    if text.rstrip().endswith("?"):
        score -= QUESTION_PENALTY
    return max(SCORE_MIN, min(SCORE_MAX, score))


def make_questions(kind: str, score: int, threshold: int, budget: int) -> list[str]:
    asked: list[str] = [DIRECTION_QUESTION] if kind == CLARIFY else []
    if score < threshold:
        asked += list(QUESTION_TEMPLATES)
    return asked[:budget]


def combined_text(item: dict[str, Any]) -> str:
    return " ".join([item["text"], *item.get("answers", [])])


def assumption_for(text: str) -> str:
    return f"Proceeding on best reading: {text[:ASSUMPTION_CHARS]}"


def build_record(item_id: str, kind: str, text: str, source: str, threshold: int, budget: int) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unknown intake kind: {kind!r}")
    text = text[:MAX_TEXT_CHARS]
    score: int = SCORE_MAX if kind == STEER else clarity_score(text)
    questions: list[str] = [] if kind == STEER else make_questions(kind, score, threshold, budget)
    if kind == STEER:
        status: str = STEERED
    elif kind == FOLD and score >= threshold:
        status = SET
    else:
        status = OPEN
    return {"id": item_id, "ts": now_iso(), "text": text, "kind": kind, "score": score, "questions": questions,
            "status": status, "assumption": None, "answers": [], "source": source}


def intake_path(root: Path) -> Path:
    return root / state_io.INTAKE_REL


def md_path(root: Path) -> Path:
    return root / state_io.INTAKE_MD_REL


def load_items(root: Path) -> list[dict[str, Any]]:
    path: Path = intake_path(root)
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding=state_io.ENCODING).splitlines():
        try:
            parsed: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "id" in parsed:
            items.append(parsed)
    return items


def save_items(root: Path, items: list[dict[str, Any]]) -> None:
    state_io.atomic_write(intake_path(root), "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items))
    render_md(root, items)


def render_md(root: Path, items: list[dict[str, Any]]) -> None:
    lines: list[str] = [f"- {i['id']} [{i['kind']}/{i['status']}] clarity {i['score']}/100: {i['text'][:200]!r}" for i in items]
    state_io.atomic_write(md_path(root), MD_HEADER + ("\n".join(lines) + "\n" if lines else "(empty)\n"))


def next_id(items: list[dict[str, Any]]) -> str:
    numbers: list[int] = [int(i["id"][len(ID_PREFIX):]) for i in items if re.fullmatch(rf"{ID_PREFIX}\d+", str(i["id"]))]
    return f"{ID_PREFIX}{max(numbers, default=0) + 1}"


def locked(root: Path, tries: int | None = None) -> Any:
    """The intake ledger lock. Not re-entrant: callers hold it once and use the `*_in` helpers below.
    `tries` is the number of acquire attempts; None keeps the store default (the CLI retries, the hook does not)."""
    store: Any = state_io.FileStore(root)
    if tries is None:
        return store.lock(state_io.INTAKE_REL)
    return store.lock(state_io.INTAKE_REL, tries=tries)


def append_in(root: Path, items: list[dict[str, Any]], classified: tuple[str, str], source: str, threshold: int,
              budget: int) -> dict[str, Any]:
    """Append a new item to the already-loaded `items`. The caller holds the lock."""
    record: dict[str, Any] = build_record(next_id(items), classified[0], classified[1], source, threshold, budget)
    save_items(root, [*items, record])
    return record


def add_item(root: Path, prompt: str, source: str = "cli", threshold: int = CLARITY_THRESHOLD, budget: int = QUESTION_BUDGET) -> dict[str, Any] | None:
    classified: tuple[str, str] | None = classify(prompt)
    if classified is None:
        return None
    with locked(root):
        return append_in(root, load_items(root), classified, source, threshold, budget)


def find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise KeyError(f"no intake item {item_id}")


def answer_in(root: Path, items: list[dict[str, Any]], item_id: str, text: str, threshold: int, budget: int) -> dict[str, Any]:
    """Attach an answer to an item of the already-loaded `items`. The caller holds the lock."""
    item: dict[str, Any] = find_item(items, item_id)
    item.setdefault("answers", []).append(text[:MAX_TEXT_CHARS])
    item["score"] = clarity_score(combined_text(item))
    if item["score"] >= threshold:
        item["status"] = SET
    elif len(item["answers"]) >= budget:
        item["status"] = SET
        item["assumption"] = assumption_for(combined_text(item))
    save_items(root, items)
    return item


def answer_item(root: Path, item_id: str, text: str, threshold: int = CLARITY_THRESHOLD, budget: int = QUESTION_BUDGET) -> dict[str, Any]:
    with locked(root):
        return answer_in(root, load_items(root), item_id, text, threshold, budget)


def resolve_item(root: Path, item_id: str, target: str, note: str | None = None) -> dict[str, Any]:
    with locked(root):
        items: list[dict[str, Any]] = load_items(root)
        item: dict[str, Any] = find_item(items, item_id)
        if target == DONE:
            item["status"] = DONE
        else:
            item["kind"] = target
            item["status"] = {FOLD: SET, STEER: STEERED, CLARIFY: OPEN}[target]
        if note:
            item["note"] = note
        save_items(root, items)
        return item


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for item in items:
        key: str = f"{item['kind']}/{item['status']}"
        tally[key] = tally.get(key, 0) + 1
    return tally


def context_text(item: dict[str, Any], budget: int = QUESTION_BUDGET) -> str:
    """What the agent sees. The person's message already reaches the agent as their own turn, so it is never echoed
    here: echoing it inside an untrusted fence would tell the agent to ignore the person's request."""
    item_id: str = item["id"]
    if item["kind"] == STEER:
        return (f"dts2 STEER {item_id}: the person's message above asks to stop and redirect. Finish the current atomic "
                f"step only, then run /dts2:steer with that new direction.")
    if item["status"] == SET:
        return (f"dts2 intake {item_id} (fold): the person's message above is added to the task ledger. Keep working; "
                f"fold it in where it fits, do not stop current work.")
    asks: str = " | ".join(item["questions"])
    text: str = (f"dts2 intake {item_id} ({item['kind']}, clarity {item['score']}/100): the person's message above is "
                 f"queued; do not stop current work. At the next safe point ask at most {budget} short questions: "
                 f"{asks}. Then run `intake.py answer {item_id}`; after the budget the item is set on your best reading.")
    if item["kind"] == CLARIFY:
        text += " It may change direction of running work; confirm before acting on it."
    return text


def prompt_from_stdin() -> str:
    raw: str = sys.stdin.read()
    try:
        data: Any = json.loads(raw)
    except ValueError:
        return ""
    value: Any = data.get(HOOK_FIELD) if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def open_clarify(items: list[dict[str, Any]], budget: int) -> dict[str, Any] | None:
    """The most recent item when it is an open clarify item still waiting on answers, else None."""
    if not items:
        return None
    last: dict[str, Any] = items[-1]
    waiting: bool = bool(last.get("questions")) and len(last.get("answers", [])) < budget
    return last if last.get("kind") == CLARIFY and last.get("status") == OPEN and waiting else None


def is_reply(text: str, threshold: int) -> bool:
    return len(words_of(text)) <= SHORT_WORDS or clarity_score(text) < threshold


def record_hook_prompt(root: Path, prompt: str, threshold: int, budget: int) -> dict[str, Any] | None:
    """Record a hook prompt under one lock. A short or unclear non-steer reply to an open clarify item answers it."""
    classified: tuple[str, str] | None = classify(prompt)
    if classified is None:
        return None
    with locked(root, tries=HOOK_LOCK_TRIES):
        items: list[dict[str, Any]] = load_items(root)
        target: dict[str, Any] | None = open_clarify(items, budget)
        if target is not None and classified[0] != STEER and is_reply(classified[1], threshold):
            return answer_in(root, items, target["id"], classified[1], threshold, budget)
        return append_in(root, items, classified, "hook", threshold, budget)


def cmd_hook(root: Path, args: argparse.Namespace) -> int:
    try:
        record: dict[str, Any] | None = record_hook_prompt(root, prompt_from_stdin(), args.threshold, args.budget)
        if record is not None:
            print(context_text(record, args.budget))
    except Exception:  # noqa: BLE001 - a hook must never fail the prompt (LockBusy and StateError land here too)
        return 0
    return 0


def cmd_add(root: Path, args: argparse.Namespace) -> int:
    prompt: str = args.text if args.text is not None else prompt_from_stdin()
    record: dict[str, Any] | None = add_item(root, prompt, args.source, args.threshold, args.budget)
    print(json.dumps(record, ensure_ascii=False) if record else json.dumps({"skipped": True}))
    return 0


def cmd_list(root: Path, args: argparse.Namespace) -> int:
    items: list[dict[str, Any]] = [i for i in load_items(root) if not args.status or i["status"] == args.status]
    if args.json:
        print(json.dumps(items, ensure_ascii=False))
        return 0
    for item in items:
        print(f"{item['id']} [{item['kind']}/{item['status']}] clarity {item['score']}/100: {item['text'][:120]}")
    return 0


def cmd_status(root: Path, args: argparse.Namespace) -> int:
    tally: dict[str, int] = counts(load_items(root))
    for key in sorted(tally):
        print(f"{key}: {tally[key]}")
    if not tally:
        print("empty: 0")
    return 0


def cmd_answer(root: Path, args: argparse.Namespace) -> int:
    print(json.dumps(answer_item(root, args.id, args.text, args.threshold, args.budget), ensure_ascii=False))
    return 0


def cmd_resolve(root: Path, args: argparse.Namespace) -> int:
    print(json.dumps(resolve_item(root, args.id, args.target, args.note), ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".")
    common.add_argument("--threshold", type=int, default=CLARITY_THRESHOLD)
    common.add_argument("--budget", type=int, default=QUESTION_BUDGET)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", parents=[common])
    add.add_argument("--text")
    add.add_argument("--source", choices=SOURCES, default="cli")
    ls = sub.add_parser("list", parents=[common])
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--json", action="store_true")
    sub.add_parser("status", parents=[common])
    sub.add_parser("hook", parents=[common])
    ans = sub.add_parser("answer", parents=[common])
    ans.add_argument("id")
    ans.add_argument("--text", required=True)
    res = sub.add_parser("resolve", parents=[common])
    res.add_argument("id")
    res.add_argument("--as", dest="target", required=True, choices=RESOLVE_TARGETS)
    res.add_argument("--note")
    return parser


COMMANDS: Final[dict[str, Any]] = {"add": cmd_add, "list": cmd_list, "status": cmd_status, "hook": cmd_hook,
                                   "answer": cmd_answer, "resolve": cmd_resolve}


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        return int(COMMANDS[args.cmd](Path(args.root), args))
    except KeyError as error:
        print(str(error).strip("'\""), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
