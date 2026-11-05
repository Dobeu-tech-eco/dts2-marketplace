"""One Markdown tokenizer for the harness's own files (ballots, decisions, reports, end-state tables, state.md).

Not a full Markdown parser: it knows headings, bullets, checkboxes, table rows and plain text, line by line, and it
skips fenced code, so a `## ` line inside a code block never starts a section. The contract parsers in contracts.py
and the old regex readers in council, handoff-write and check-in all sit on it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Union

FENCE: Final[re.Pattern[str]] = re.compile(r"^\s{0,3}(```|~~~)")
HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
BULLET: Final[re.Pattern[str]] = re.compile(r"^\s*[-*+][ \t]+(.*?)\s*$")
CHECKBOX: Final[re.Pattern[str]] = re.compile(r"^\[([ xX])\][ \t]+(.*)$")
SEPARATOR_CELL: Final[re.Pattern[str]] = re.compile(r"^:?-{1,}:?$")
KEY_VALUE: Final[re.Pattern[str]] = re.compile(r"^\s*-?\s*([A-Za-z][\w -]*?):[ \t]*(.*?)\s*$")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int


@dataclass(frozen=True)
class Bullet:
    text: str
    line: int
    checked: bool | None = None  # None: not a checkbox


@dataclass(frozen=True)
class Row:
    cells: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Text:
    text: str
    line: int


Token = Union[Heading, Bullet, Row, Text]


def table_cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def classify(line: str, number: int) -> Token | None:
    if not line.strip():
        return None
    heading = HEADING.match(line)
    if heading:
        return Heading(len(heading.group(1)), heading.group(2), number)
    if line.lstrip().startswith("|"):
        cells = table_cells(line)
        return None if all(SEPARATOR_CELL.match(c) for c in cells if c) and any(cells) else Row(cells, number)
    bullet = BULLET.match(line)
    if bullet:
        box = CHECKBOX.match(bullet.group(1))
        return Bullet(box.group(2).strip(), number, box.group(1).lower() == "x") if box else Bullet(bullet.group(1), number)
    return Text(line.strip(), number)


def tokenize(text: str) -> list[Token]:
    """Tokens in order. Blank lines, table separator rows and fenced code are left out."""
    tokens: list[Token] = []
    fenced: str = ""
    for number, line in enumerate(text.splitlines(), start=1):
        fence = FENCE.match(line)
        if fence:
            fenced = "" if fenced == fence.group(1) else (fenced or fence.group(1))
            continue
        if fenced:
            continue
        token = classify(line, number)
        if token is not None:
            tokens.append(token)
    return tokens


def first_line(text: str) -> str:
    """The first non-blank line, stripped; empty when there is none."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def split_heading(heading: str) -> tuple[int, str]:
    """("## Dissent brief") -> (2, "Dissent brief"). A heading without hashes is level 2."""
    found = HEADING.match(heading.strip())
    return (len(found.group(1)), found.group(2)) if found else (2, heading.strip())


def section_lines(text: str, heading: str, *, stop_at: int | None = None, prefix: bool = False) -> list[str] | None:
    """The raw lines under `heading` ("## Name"), up to the next heading of the same level or higher (`stop_at` raises the
    deepest level that ends it: 3 ends at a `###` too). None when there is no such heading. `prefix` matches a heading
    that merely starts with the name."""
    level, title = split_heading(heading)
    limit: int = stop_at or level
    lines: list[str] = text.splitlines()
    marks: dict[int, Heading] = {t.line: t for t in tokenize(text) if isinstance(t, Heading)}
    start: int | None = None
    for number in sorted(marks):
        found = marks[number]
        if start is None:
            if found.level == level and (found.text.startswith(title) if prefix else found.text == title):
                start = number
        elif found.level <= limit:
            return lines[start:number - 1]
    return lines[start:] if start is not None else None


def section(text: str, heading: str, *, stop_at: int | None = None, prefix: bool = False) -> str:
    """The body under `heading`, stripped; empty when the heading is missing."""
    found = section_lines(text, heading, stop_at=stop_at, prefix=prefix)
    return "\n".join(found).strip() if found is not None else ""


def has_section(text: str, heading: str) -> bool:
    return section_lines(text, heading) is not None


def rows(text: str) -> list[tuple[str, ...]]:
    return [t.cells for t in tokenize(text) if isinstance(t, Row)]


def bullets(text: str) -> list[Bullet]:
    return [t for t in tokenize(text) if isinstance(t, Bullet)]


def headings(text: str, level: int | None = None) -> list[Heading]:
    return [t for t in tokenize(text) if isinstance(t, Heading) and (level is None or t.level == level)]


def subsections(body: str, level: int) -> dict[str, str]:
    """{title: body} for each heading of `level` inside `body`, in order."""
    lines: list[str] = body.splitlines()
    marks: list[Heading] = headings(body, level)
    stops: list[int] = [h.line for h in headings(body) if h.level <= level]
    out: dict[str, str] = {}
    for mark in marks:
        later: list[int] = [n for n in stops if n > mark.line]
        out[mark.text] = "\n".join(lines[mark.line:(later[0] - 1) if later else None]).strip()
    return out
