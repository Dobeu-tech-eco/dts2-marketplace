"""Typing `lock roadmap <key>` records the roadmap approval (approvals.grant, grant-from-prompt, hooks/roadmap-lock.sh)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final
from unittest import mock

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import approvals  # noqa: E402
from test_stop_checks_portable import path_without_timeout  # noqa: E402
import roadmap  # noqa: E402
import state_io  # noqa: E402
from test_roadmap import END_STATE  # noqa: E402

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "roadmap-lock.sh"
OTHER_KEY: Final[str] = "0" * 12


def make_repo() -> Path:
    root: Path = Path(tempfile.mkdtemp())
    path: Path = root / state_io.END_STATE_REL
    path.parent.mkdir(parents=True)
    path.write_text(END_STATE, encoding="utf-8")
    return root


def payload(prompt: str) -> str:
    return json.dumps({"prompt": prompt})


def settings(repo: Path) -> dict[str, object]:
    return json.loads((repo / approvals.MARKER_REL).read_text(encoding="utf-8"))


class GrantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("DTS2_SON", None)

    def tearDown(self) -> None:
        self.env.stop()

    def test_creates_the_file_and_parent_dirs(self) -> None:
        self.assertTrue(approvals.grant(self.repo, "roadmap", "abc"))
        self.assertEqual(settings(self.repo), {"dts2_approvals": {"roadmap": ["abc"]}})
        self.assertTrue(approvals.is_human_approved("roadmap", "abc", self.repo))
        self.assertFalse((self.repo / (approvals.MARKER_REL + ".bak")).exists())

    def test_adds_to_existing_keeps_other_keys_and_backs_up(self) -> None:
        path: Path = self.repo / approvals.MARKER_REL
        path.parent.mkdir(parents=True)
        original: str = json.dumps({"permissions": {"allow": ["x"]}, "dts2_approvals": {"merge": ["42"], "roadmap": ["old"]}})
        path.write_text(original, encoding="utf-8")
        self.assertTrue(approvals.grant(self.repo, "roadmap", "new"))
        data = settings(self.repo)
        self.assertEqual(data["permissions"], {"allow": ["x"]})
        self.assertEqual(data["dts2_approvals"], {"merge": ["42"], "roadmap": ["old", "new"]})
        self.assertEqual((self.repo / (approvals.MARKER_REL + ".bak")).read_text(encoding="utf-8"), original)

    def test_dedupes(self) -> None:
        approvals.grant(self.repo, "roadmap", "abc")
        approvals.grant(self.repo, "roadmap", "abc")
        self.assertEqual(settings(self.repo)["dts2_approvals"], {"roadmap": ["abc"]})

    def test_refused_for_a_son(self) -> None:
        with mock.patch.dict(os.environ, {"DTS2_SON": "1"}):
            self.assertFalse(approvals.grant(self.repo, "roadmap", "abc"))
        self.assertFalse((self.repo / approvals.MARKER_REL).exists())

    def test_unreadable_existing_file_is_left_alone(self) -> None:
        path: Path = self.repo / approvals.MARKER_REL
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertFalse(approvals.grant(self.repo, "roadmap", "abc"))
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(approvals.ApprovalError):
            approvals.grant(self.repo, "bogus", "abc")

    def test_logs_the_grant(self) -> None:
        approvals.grant(self.repo, "roadmap", "abc")
        self.assertIn("| roadmap | abc | human |", (self.repo / approvals.LOG_REL).read_text(encoding="utf-8"))


class GrantFromPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo()
        self.key: str = roadmap.status(self.repo)["key"]
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("DTS2_SON", None)

    def tearDown(self) -> None:
        self.env.stop()

    def test_lock_phrase_is_in_status(self) -> None:
        self.assertEqual(roadmap.status(self.repo)["lock_phrase"], f"lock roadmap {self.key}")

    def test_matching_key_locks(self) -> None:
        out: str = approvals.grant_from_prompt(payload(f"  Lock Roadmap {self.key.upper()}\n"), self.repo)
        self.assertEqual(out, f"dt: roadmap {self.key} locked by the owner")
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_wrong_key_locks_nothing(self) -> None:
        out: str = approvals.grant_from_prompt(payload(f"lock roadmap {OTHER_KEY}"), self.repo)
        self.assertEqual(out, f"dt: roadmap key {OTHER_KEY} does not match the current roadmap {self.key}; nothing locked")
        self.assertFalse((self.repo / approvals.MARKER_REL).exists())

    def test_other_prompts_are_ignored(self) -> None:
        for prompt in ("yes", f"please lock roadmap {self.key}", f"lock roadmap {self.key} now", "lock roadmap abc"):
            self.assertEqual(approvals.grant_from_prompt(payload(prompt), self.repo), "")
        self.assertFalse((self.repo / approvals.MARKER_REL).exists())

    def test_bad_input_never_raises(self) -> None:
        for raw in ("", "{oops", "[]", json.dumps({"prompt": 5}), json.dumps({})):
            self.assertEqual(approvals.grant_from_prompt(raw, self.repo), "")

    def test_son_cannot_lock(self) -> None:
        with mock.patch.dict(os.environ, {"DTS2_SON": "1"}):
            out: str = approvals.grant_from_prompt(payload(f"lock roadmap {self.key}"), self.repo)
        self.assertIn("not locked", out)
        self.assertFalse(roadmap.status(self.repo)["approved"])


GIT_BASH: Final[str] = r"C:\Program Files\Git\bin\bash.exe"


def hook_bash() -> str | None:
    """The bash Claude Code runs hooks with. On Windows that is Git Bash, never the WSL launcher in System32."""
    found: str | None = shutil.which("bash")
    if os.name != "nt":
        return found
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        return found
    return GIT_BASH if os.path.exists(GIT_BASH) else None


@unittest.skipUnless(hook_bash(), "bash (Git Bash on Windows) is required")
class HookTests(unittest.TestCase):
    def run_hook(self, repo: Path, stdin: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
        env: dict[str, str] = {k: v for k, v in os.environ.items() if k != "DTS2_SON"}
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        if path is not None:
            env["PATH"] = path
        return subprocess.run([str(hook_bash()), str(HOOK)], input=stdin, capture_output=True, text=True, cwd=repo, env=env, check=False)

    def test_end_to_end(self) -> None:
        repo: Path = make_repo()
        key: str = roadmap.status(repo)["key"]
        result = self.run_hook(repo, payload(f"lock roadmap {key}"))
        self.assertEqual((result.returncode, result.stdout.strip()), (0, f"dt: roadmap {key} locked by the owner"))
        self.assertTrue(roadmap.status(repo)["approved"])

    @unittest.skipIf(os.name == "nt", "symlinked PATH needs a POSIX host")
    def test_locks_without_gnu_timeout(self) -> None:
        """Stock macOS has no timeout or gtimeout; the hook must still lock."""
        repo: Path = make_repo()
        key: str = roadmap.status(repo)["key"]
        bin_dir: Path = Path(tempfile.mkdtemp()) / "bin"
        self.addCleanup(shutil.rmtree, bin_dir.parent, True)
        result = self.run_hook(repo, payload(f"lock roadmap {key}"), path=path_without_timeout(bin_dir))
        self.assertEqual((result.returncode, result.stdout.strip()), (0, f"dt: roadmap {key} locked by the owner"))
        self.assertTrue(roadmap.status(repo)["approved"])

    def test_silent_for_other_prompts_and_bad_json(self) -> None:
        repo: Path = make_repo()
        for stdin in (payload("hello"), "not json", ""):
            result = self.run_hook(repo, stdin)
            self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse((repo / approvals.MARKER_REL).exists())


if __name__ == "__main__":
    unittest.main()
