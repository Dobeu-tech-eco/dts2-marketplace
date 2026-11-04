"""Append-only logs: concurrent writers never drop a line, and the header lands once."""
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
from state_io import append_text  # noqa: E402

WRITERS: Final[int] = 8
ROWS_PER_WRITER: Final[int] = 50
HEADER: Final[str] = "# log\n"


def write_rows(path: str, writer: int) -> None:
    for row in range(ROWS_PER_WRITER):
        append_text(path, json.dumps({"w": writer, "r": row}) + "\n", header=HEADER)


class AppendTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path: Path = Path(tempfile.mkdtemp(prefix="dts2-append-")) / "sub" / "log.jsonl"

    def test_concurrent_writers_lose_no_rows(self) -> None:
        procs = [multiprocessing.Process(target=write_rows, args=(str(self.path), w)) for w in range(WRITERS)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=60)
            self.assertEqual(proc.exitcode, 0)
        lines: list[str] = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count(HEADER.strip()), 1)
        self.assertEqual(lines[0], HEADER.strip())
        rows = {(d["w"], d["r"]) for d in (json.loads(line) for line in lines[1:])}
        self.assertEqual(len(rows), WRITERS * ROWS_PER_WRITER)

    def test_header_only_on_new_file(self) -> None:
        append_text(self.path, "a\n", header=HEADER)
        append_text(self.path, "b\n", header=HEADER)
        self.assertEqual(self.path.read_text(encoding="utf-8"), HEADER + "a\nb\n")

    def test_no_header(self) -> None:
        append_text(self.path, "a\n")
        append_text(self.path, "b\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "a\nb\n")


if __name__ == "__main__":
    unittest.main()
