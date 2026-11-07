"""The one reader for the harness's small YAML-shaped files (.harness/config.yaml, keep.yaml, the settings frontmatter).

Not general YAML. It reads: `key: value`, nested mappings by indentation, `- item` lists, `- key: value` lists of
mappings, one-line `[a, b]` lists, quoted values and `#` comments. Every scalar comes back as a string; the typed
accessors (`get_int`, `get_float`, `get_bool`, `get_str`, `get_list`) convert with a default, so a bad value never
raises. One comment rule: `#` starts a comment at the start of a line or after whitespace, outside quotes."""
from __future__ import annotations

import math
import re
from typing import Any, Final

FENCE: Final[str] = "---"
ITEM: Final[str] = "- "
KEY_LINE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z0-9_.\-/]+)\s*:(?:\s+(.*)|)$")
TRUE_WORDS: Final[frozenset[str]] = frozenset({"true", "yes", "on"})
FALSE_WORDS: Final[frozenset[str]] = frozenset({"false", "no", "off"})
Line = tuple[int, str]


def strip_comment(line: str) -> str:
    """Drop a trailing comment and trailing space. `#` opens a comment only at line start or after whitespace, never in quotes."""
    quote: str = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'" and (index == 0 or line[index - 1] in " \t:[,-"):
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line.rstrip()


def unquote(value: str) -> str:
    text: str = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def inline_list(value: str) -> list[str] | None:
    """A one-line flow list such as [".env", "a b"]; None when the text is not one."""
    text: str = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    return [unquote(part) for part in text[1:-1].split(",") if part.strip()]


def scalar(value: str) -> Any:
    listed: list[str] | None = inline_list(value)
    return listed if listed is not None else unquote(value)


def is_item(content: str) -> bool:
    return content == "-" or content.startswith(ITEM)


def logical_lines(text: str) -> list[Line]:
    lines: list[Line] = []
    for raw in text.splitlines():
        body: str = strip_comment(raw.replace("\t", "  "))
        if body.strip():
            lines.append((len(body) - len(body.lstrip(" ")), body.strip()))
    return lines


def parse_list(lines: list[Line], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index: int = start
    while index < len(lines) and lines[index][0] == indent and is_item(lines[index][1]):
        content: str = lines[index][1][1:].strip()
        if KEY_LINE.match(content) and not content.startswith(("[", "\"", "'")):
            shifted: list[Line] = [(indent + 2, content)] + lines[index + 1:]
            mapping, used = parse_mapping(shifted, 0, indent + 2)
            items.append(mapping)
            index += used
        else:
            items.append(scalar(content))
            index += 1
    return items, index - start


def parse_mapping(lines: list[Line], start: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    index: int = start
    while index < len(lines):
        depth, content = lines[index]
        if depth < indent:
            break
        match = KEY_LINE.match(content) if depth == indent else None
        if match is None:
            index += 1  # deeper junk or an unreadable line: skip it, never raise
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        index += 1
        if value:
            result[key] = scalar(value)
            continue
        nested: Any = ""
        if index < len(lines) and (lines[index][0] > indent or (lines[index][0] == indent and is_item(lines[index][1]))):
            child_indent: int = lines[index][0]
            if is_item(lines[index][1]):
                nested, used = parse_list(lines, index, child_indent)
            else:
                nested, used = parse_mapping(lines, index, child_indent)
            index += used
        result[key] = nested
    return result, index - start


def parse(text: str) -> dict[str, Any]:
    """The top-level mapping of `text`. Unreadable lines are skipped; this never raises."""
    lines: list[Line] = logical_lines(text)
    if not lines:
        return {}
    mapping, _ = parse_mapping(lines, 0, lines[0][0])
    return mapping


def parse_frontmatter(text: str) -> dict[str, Any]:
    """The mapping between the first two `---` lines (the .claude/dts2-harness.local.md form); {} when there is none."""
    rows: list[str] = text.splitlines()
    if not rows or rows[0].strip() != FENCE:
        return {}
    for end in range(1, len(rows)):
        if rows[end].strip() == FENCE:
            return parse("\n".join(rows[1:end]))
    return {}


def get(data: Any, path: str, default: Any = None) -> Any:
    """Look up a dotted path such as `budget.max_turns`; `default` when any step is missing."""
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_str(data: Any, path: str, default: str = "") -> str:
    value: Any = get(data, path)
    return value if isinstance(value, str) and value else default


def get_int(data: Any, path: str, default: int) -> int:
    value: Any = get(data, path)
    return int(value) if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()) else default


def get_float(data: Any, path: str, default: float) -> float:
    value: Any = get(data, path)
    if not isinstance(value, str):
        return default
    try:
        number: float = float(value)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def get_bool(data: Any, path: str, default: bool) -> bool:
    value: Any = get(data, path)
    word: str = value.strip().lower() if isinstance(value, str) else ""
    if word in TRUE_WORDS:
        return True
    return False if word in FALSE_WORDS else default


def get_list(data: Any, path: str) -> list[str]:
    value: Any = get(data, path)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
