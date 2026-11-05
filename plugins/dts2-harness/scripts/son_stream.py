"""G-56 / G-57: what the head learns from a son's `--output-format stream-json` output while it runs.

Three small, pure parts:
  - `detect_stuck(events)`: a stuck-loop detector over the tool calls and results (the same call and result 4 times,
    the same call failing 3 times, or two calls taking turns 6 times).
  - `api_retries_exhausted(stdout)`: whether the CLI gave up on its own `api_retry` loop (the harness retries only then).
  - `SonWatcher`: the line handler `proc.run_once` calls; it beats the lane's heartbeat from the events, keeps the
    last events for the detector and says when the son must be stopped.
Model output is untrusted: only a few typed fields are read."""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable, Final

STUCK_SAME: Final[int] = 4  # identical action and identical observation, in a row
STUCK_ERROR: Final[int] = 3  # the same action failing, in a row
STUCK_PING_PONG: Final[int] = 6  # two actions taking turns (A, B, A, B, A, B)
KEEP_EVENTS: Final[int] = 400
HEARTBEAT_EVERY_S: Final[float] = 5.0
OBSERVATION_CHARS: Final[int] = 2000
SUBTYPE_API_RETRY: Final[str] = "api_retry"

Step = tuple[str, str, bool]  # (action, observation, is_error)


def content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message: Any = event.get("message")
    content: Any = message.get("content") if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def observation_text(content: Any) -> str:
    if isinstance(content, str):
        return content[:OBSERVATION_CHARS]
    if isinstance(content, list):
        parts: list[str] = [str(b.get("text", "")) for b in content if isinstance(b, dict)]
        return "".join(parts)[:OBSERVATION_CHARS]
    return ""


def action_key(block: dict[str, Any]) -> str:
    try:
        arguments: str = json.dumps(block.get("input"), sort_keys=True, default=str)
    except (TypeError, ValueError):
        arguments = ""
    return f"{block.get('name')}:{arguments}"


def steps(events: list[dict[str, Any]]) -> list[Step]:
    """Each tool call paired with its result, in order. A call with no result yet is not a step."""
    pending: dict[str, str] = {}
    found: list[Step] = []
    for event in events:
        for block in content_blocks(event):
            kind: Any = block.get("type")
            if kind == "tool_use" and isinstance(block.get("id"), str):
                pending[block["id"]] = action_key(block)
            elif kind == "tool_result" and block.get("tool_use_id") in pending:
                found.append((pending.pop(block["tool_use_id"]), observation_text(block.get("content")),
                              block.get("is_error") is True))
    return found


def repeated(tail: list[Step], count: int) -> bool:
    return len(tail) >= count and len(set(tail[-count:])) == 1


def failing(tail: list[Step], count: int) -> bool:
    last: list[Step] = tail[-count:]
    return len(last) == count and all(s[2] for s in last) and len({s[0] for s in last}) == 1


def ping_pong(tail: list[Step], count: int) -> bool:
    actions: list[str] = [s[0] for s in tail[-count:]]
    if len(actions) < count or actions[-1] == actions[-2]:
        return False
    return all(actions[i] == actions[i - 2] for i in range(2, count))


def detect_stuck(events: list[dict[str, Any]]) -> str | None:
    """The reason a son is going round in circles, or None. Looks only at the end of the transcript."""
    tail: list[Step] = steps(events)
    if repeated(tail, STUCK_SAME):
        return f"same action and observation {STUCK_SAME} times: {tail[-1][0][:80]}"
    if failing(tail, STUCK_ERROR):
        return f"same action failed {STUCK_ERROR} times: {tail[-1][0][:80]}"
    if ping_pong(tail, STUCK_PING_PONG):
        return f"two actions took turns {STUCK_PING_PONG} times: {tail[-1][0][:40]} / {tail[-2][0][:40]}"
    return None


def api_retries_exhausted(stdout: str) -> bool | None:
    """None when the output has no `api_retry` event (an old CLI, or no stream). True when the last one used the CLI's last
    retry (attempt >= max_retries): the CLI gave up, so the harness may back off and retry. False while it was still trying."""
    last: dict[str, Any] | None = None
    for line in stdout.splitlines():
        try:
            event: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("subtype") == SUBTYPE_API_RETRY:
            last = event
    if last is None:
        return None
    attempt: Any = last.get("attempt")
    limit: Any = last.get("max_retries")
    numbers: bool = all(isinstance(n, int) and not isinstance(n, bool) for n in (attempt, limit))
    return bool(numbers and attempt >= limit)


class SonWatcher:
    """Feed it every stdout line of a running son. `feed` returns True when the son must be stopped (it is stuck)."""

    def __init__(self, beat: Callable[[], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.beat: Callable[[], None] = beat
        self.clock: Callable[[], float] = clock
        self.events: deque[dict[str, Any]] = deque(maxlen=KEEP_EVENTS)
        self.stuck: str | None = None
        self.last_beat: float | None = None

    def feed(self, line: str) -> bool:
        try:
            event: Any = json.loads(line)
        except ValueError:
            return False
        if not isinstance(event, dict):
            return False
        self.events.append(event)
        now: float = self.clock()
        if self.last_beat is None or now - self.last_beat >= HEARTBEAT_EVERY_S:
            self.last_beat = now
            self.beat()
        if content_blocks(event) and any(b.get("type") == "tool_result" for b in content_blocks(event)):
            self.stuck = detect_stuck(list(self.events))
        return self.stuck is not None
