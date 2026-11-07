#!/usr/bin/env python3
"""Fake `gh` for the smoke eval: no open pull requests, every other command succeeds silently."""
from __future__ import annotations

import sys


def main() -> int:
    if sys.argv[1:3] == ["pr", "list"]:
        print("[]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
