"""`python -m fleet_ledger check`: load this seat's credentials from Doppler, sign in, run the rights check.

Prints one line per check and exits 0 only when all pass. Never prints a secret.
"""
from __future__ import annotations

import sys
from typing import Final

from .credentials_error import CredentialsError
from .seat_check import CheckResult, run_seat_check
from .seat_session import SeatSession

USAGE: Final[str] = "usage: python -m fleet_ledger check"
EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_USAGE: Final[int] = 2


def _report(results: list[CheckResult]) -> int:
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'} {result.name}: {result.detail}")
    return EXIT_OK if all(result.passed for result in results) else EXIT_FAILED


def main(argv: list[str]) -> int:
    if argv != ["check"]:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        session: SeatSession = SeatSession.from_doppler()
    except CredentialsError as error:
        print(f"FAIL credentials: {error}", file=sys.stderr)
        return EXIT_FAILED
    with session:
        return _report(run_seat_check(session.connection))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
