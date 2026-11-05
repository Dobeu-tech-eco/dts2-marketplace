"""closing-a: the OSError fallback in subagent_report.already_blocked is explicit and keeps its result."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import subagent_report  # noqa: E402

PAYLOAD: Final[dict[str, Any]] = {
    "session_id": "s-closing-a", "agent_type": "dts2-harness:builder",
    "tool_name": "SubagentHandback", "tool_input": {"message": "done"},
}


class AlreadyBlockedOSError(unittest.TestCase):
    def test_unwritable_marker_yields_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TMPDIR": tmp}):
            with mock.patch.object(Path, "touch", side_effect=OSError("read-only")):
                self.assertFalse(subagent_report.already_blocked(PAYLOAD))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_unwritable_marker_still_blocks_each_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TMPDIR": tmp}):
            with mock.patch.object(Path, "touch", side_effect=OSError("read-only")):
                first = subagent_report.decide(PAYLOAD, "handback")
                second = subagent_report.decide(PAYLOAD, "handback")
        self.assertIsNotNone(first)
        self.assertEqual(first, second)

    def test_writable_marker_blocks_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TMPDIR": tmp}):
            self.assertIsNotNone(subagent_report.decide(PAYLOAD, "handback"))
            self.assertIsNone(subagent_report.decide(PAYLOAD, "handback"))


if __name__ == "__main__":
    unittest.main()
