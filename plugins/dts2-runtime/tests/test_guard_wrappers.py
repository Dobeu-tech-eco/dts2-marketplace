"""guard.strip_wrappers keeps the command behind `env -i`, `env VAR=x` and `env -i VAR=x` (merge-guard bypass regression)."""
from __future__ import annotations

import shlex
import sys
import unittest
from pathlib import Path
from typing import Final

SCRIPTS: Final[Path] = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import guard  # noqa: E402

GIT_PUSH: Final[list[str]] = ["git", "push", "--force"]
PREFIXES: Final[tuple[str, ...]] = ("env -i", "env -i FOO=1", "env FOO=1", "command env -i", "env -i -u BAR FOO=1", "env -u BAR")


class StripWrappersTest(unittest.TestCase):
    def test_env_prefixes_keep_the_command(self) -> None:
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix):
                words: list[str] = shlex.split(f"{prefix} git push --force")
                self.assertEqual(guard.strip_wrappers(words), GIT_PUSH)

    def test_env_wrapper_is_reported_as_seen(self) -> None:
        seen: list[str] = []
        guard.strip_wrappers(shlex.split("command env -i FOO=1 git push"), seen)
        self.assertEqual(seen, ["command", "env"])

    def test_timeout_still_swallows_its_value_flag(self) -> None:
        self.assertEqual(guard.strip_wrappers(shlex.split("timeout -s KILL 5 git push")), ["git", "push"])

    def test_segments_see_the_push_behind_env_i(self) -> None:
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertIn(GIT_PUSH, guard.segments(f"{prefix} git push --force"))


if __name__ == "__main__":
    unittest.main()
