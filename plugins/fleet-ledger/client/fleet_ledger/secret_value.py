"""A string that never prints itself: repr, str and format all show a mask."""
from __future__ import annotations

from typing import Final

MASK: Final[str] = "***"


class SecretValue:
    """Holds a credential. Only `reveal()` returns the real value; pass it straight to the driver."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("a secret value cannot be empty")
        self._value: Final[str] = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue({MASK})"

    def __str__(self) -> str:
        return MASK

    def __format__(self, spec: str) -> str:
        return MASK

    def __reduce__(self) -> object:
        raise TypeError("a SecretValue cannot be pickled")
