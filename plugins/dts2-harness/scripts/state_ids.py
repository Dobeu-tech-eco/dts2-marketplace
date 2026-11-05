"""Run stamps and lane ids as value objects. Parsing is the only way in, so a path built from one can never be
`runs/None/` (a missing stamp stringified) or climb out of `.harness/` with `..`."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Final

STAMP_FORMAT: Final[str] = "%Y%m%d-%H%M%S"
STAMP_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d{8}-\d{1,6}")
LANE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
REJECTED_WORDS: Final[frozenset[str]] = frozenset({"none", "null", "undefined", "nan"})


class InvalidId(ValueError):
    """Raised when a stamp or lane id does not have the allowed shape."""


def check(kind: str, value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str):
        raise InvalidId(f"{kind} must be a string, got {type(value).__name__}")
    if value.lower() in REJECTED_WORDS or pattern.fullmatch(value) is None:
        raise InvalidId(f"not a valid {kind}: {value!r}")
    return value


@dataclass(frozen=True)
class Stamp:
    """A run stamp such as `20261104-101500`: the date, a dash, then 1 to 6 digits."""
    value: str
    KIND: ClassVar[str] = "run stamp"

    @classmethod
    def parse(cls, value: Any) -> Stamp:
        return cls(check(cls.KIND, value, STAMP_PATTERN))

    @classmethod
    def new(cls, now: datetime | None = None) -> Stamp:
        return cls((now or datetime.now()).strftime(STAMP_FORMAT))

    @classmethod
    def coerce(cls, value: Any) -> Stamp:
        return value if isinstance(value, cls) else cls.parse(value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class LaneId:
    """A lane id such as `a` or `lane-1`: letters, digits, `_` and `-`, up to 32, starting with a letter or digit."""
    value: str
    KIND: ClassVar[str] = "lane id"

    @classmethod
    def parse(cls, value: Any) -> LaneId:
        return cls(check(cls.KIND, value, LANE_PATTERN))

    @classmethod
    def coerce(cls, value: Any) -> LaneId:
        return value if isinstance(value, cls) else cls.parse(value)

    def __str__(self) -> str:
        return self.value
