"""The checks ledger is append-only: concurrent writers sharing one stamp never drop a record."""
from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from checks import append_ledger, read_ledger  # noqa: E402

WRITERS: Final[int] = 6
ROWS_PER_WRITER: Final[int] = 40


def write_rows(path: str, writer: int) -> None:
    for row in range(ROWS_PER_WRITER):
        append_ledger(Path(path), {"kind": "check", "name": f"w{writer}", "row": row})


class LedgerAppendTests(unittest.TestCase):
    def test_concurrent_lanes_keep_every_record(self) -> None:
        path: Path = Path(tempfile.mkdtemp(prefix="dts2-ledger-")) / "runs" / "s" / "ledger.jsonl"
        procs = [multiprocessing.Process(target=write_rows, args=(str(path), w)) for w in range(WRITERS)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=60)
            self.assertEqual(proc.exitcode, 0)
        rows = {(r["name"], r["row"]) for r in read_ledger(path)}
        self.assertEqual(len(rows), WRITERS * ROWS_PER_WRITER)
        for line in path.read_text(encoding="utf-8").splitlines():
            json.loads(line)


if __name__ == "__main__":
    unittest.main()
