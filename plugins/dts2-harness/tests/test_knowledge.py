"""Tests for scripts/knowledge.py: the personal cross-device knowledge store."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import knowledge  # noqa: E402

HAVE_GIT: Final[bool] = shutil.which("git") is not None
GIT_ENV: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.invalid",
    "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}
CLOCK_TICK: Final[float] = 1.1  # entry timestamps have one-second resolution


def make_bare_remote(path: Path) -> str:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "--bare", "-q", str(path)],
        check=True, capture_output=True, env={**os.environ, **GIT_ENV},
    )
    return str(path)


class KnowledgeCase(unittest.TestCase):
    """Each test gets a private store, profile and environment; nothing touches ~/.dts2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root: Path = Path(self.tmp.name)
        self.store: Path = self.root / "store"
        self.profile: Path = self.root / "profile.json"
        patcher = unittest.mock.patch.dict(os.environ, {
            **GIT_ENV, "DTS2_KNOWLEDGE": str(self.store), "DTS2_KNOWLEDGE_PROFILE": str(self.profile),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("DTS2_HOME", "DTS2_GIT_BIN"):
            os.environ.pop(name, None)

    def run_cli(self, *args: str, store: Path | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE": str(store or self.store)}):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code: int = knowledge.main(list(args))
                except SystemExit as exit_:  # argparse rejects bad input with exit 2
                    code = int(exit_.code or 0)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *args: str, store: Path | None = None) -> str:
        code, out, err = self.run_cli(*args, store=store)
        self.assertEqual(code, 0, f"{args}: {err}")
        return out

    def json_of(self, *args: str, store: Path | None = None) -> Any:
        return json.loads(self.ok(*args, "--json", store=store))


class WriteReadTests(KnowledgeCase):
    def test_init_without_git_binary_still_creates_store(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"DTS2_GIT_BIN": str(self.root / "no-such-git")}):
            self.ok("init")
        self.assertTrue((self.store / "entries" / "term").is_dir())
        self.assertTrue((self.store / "README.md").is_file())
        self.assertFalse((self.store / ".git").exists())

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_init_with_git_creates_repo_and_is_idempotent(self) -> None:
        self.ok("init")
        self.ok("init")
        self.assertTrue((self.store / ".git").exists())
        for kind in knowledge.KINDS:
            self.assertTrue((self.store / "entries" / kind).is_dir())

    def test_set_get_roundtrip_and_file_format(self) -> None:
        self.ok("init")
        self.ok("set", "agents.standard", "6 agents", "--by", "laptop")
        self.assertEqual(self.ok("get", "agents.standard").strip(), "6 agents")
        text: str = (self.store / "entries" / "preference" / "agents.standard.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nkey: agents.standard\nkind: preference\naliases: []\ntags: []\nupdated: "))
        self.assertIn("by: laptop\n---\n6 agents\n", text)

    def test_alias_lookup_is_case_insensitive(self) -> None:
        self.ok("set", "acme", "a product family", "--kind", "term", "--alias", "ACME-Corp", "--alias", "acme-*")
        entry: dict[str, Any] = self.json_of("get", "acme-corp")
        self.assertEqual(entry["key"], "acme")
        self.assertEqual(entry["aliases"], ["ACME-Corp", "acme-*"])

    def test_exact_key_beats_alias(self) -> None:
        self.ok("set", "alpha", "first", "--alias", "beta")
        self.ok("set", "beta", "second")
        self.assertEqual(self.ok("get", "beta").strip(), "second")

    def test_get_missing_exits_3(self) -> None:
        self.ok("init")
        self.assertEqual(self.run_cli("get", "nope")[0], 3)

    def test_get_with_store_missing_exits_3(self) -> None:
        self.assertEqual(self.run_cli("get", "x")[0], 3)
        self.assertEqual(self.run_cli("list")[0], 3)

    def test_find_matches_key_alias_tag_value(self) -> None:
        self.ok("set", "agents.standard", "six builders", "--tag", "roster")
        self.ok("set", "acme", "product line", "--kind", "term", "--alias", "Widget Works")
        self.assertEqual([e["key"] for e in self.json_of("find", "SIX")], ["agents.standard"])
        self.assertEqual([e["key"] for e in self.json_of("find", "roster")], ["agents.standard"])
        self.assertEqual([e["key"] for e in self.json_of("find", "widget")], ["acme"])
        self.assertEqual([e["key"] for e in self.json_of("find", "agents.st")], ["agents.standard"])
        self.assertEqual(self.json_of("find", "acme", "--kind", "preference"), [])

    def test_list_sorted_by_kind_then_key_and_filters(self) -> None:
        self.ok("set", "zeta", "z", "--kind", "learning")
        self.ok("set", "beta", "b", "--kind", "term")
        self.ok("set", "alpha", "a", "--kind", "term")
        self.ok("set", "omega", "o")
        order: list[str] = [f"{e['kind']}/{e['key']}" for e in self.json_of("list")]
        self.assertEqual(order, ["preference/omega", "term/alpha", "term/beta", "learning/zeta"])
        self.assertEqual(len(self.json_of("list", "--kind", "term")), 2)
        self.assertIn("term/alpha: a", self.ok("list"))

    def test_rm_removes_and_missing_exits_3(self) -> None:
        self.ok("set", "gone", "x")
        self.ok("rm", "gone")
        self.assertFalse((self.store / "entries" / "preference" / "gone.md").exists())
        self.assertEqual(self.run_cli("rm", "gone")[0], 3)

    def test_changing_kind_moves_the_file(self) -> None:
        self.ok("set", "acme", "v1")
        self.ok("set", "acme", "v2", "--kind", "term")
        self.assertFalse((self.store / "entries" / "preference" / "acme.md").exists())
        self.assertTrue((self.store / "entries" / "term" / "acme.md").exists())
        self.assertEqual(len(self.json_of("list")), 1)

    def test_key_validation(self) -> None:
        for bad in ("Has Space", "UPPER-ok-no", "-lead", ".lead", "a/b", "x" * 65, ""):
            self.assertEqual(self.run_cli("set", bad, "v")[0], 2, bad)
        self.assertEqual(self.run_cli("set", "ok", "v", "--kind", "nonsense")[0], 2)
        self.assertEqual(self.run_cli("set", "a.b_c-d9", "v")[0], 0)
        self.assertEqual(self.run_cli("set", "x" * 64, "v")[0], 0)
        self.assertEqual(self.run_cli("rm", "BAD KEY")[0], 2)

    def test_multiline_value_survives(self) -> None:
        self.ok("set", "notes", "line one\nline two\n---\nline four")
        self.assertEqual(self.json_of("get", "notes")["value"], "line one\nline two\n---\nline four")


class SecretGuardTests(KnowledgeCase):
    def refused(self, key: str, value: str, *extra: str) -> None:
        code, _, err = self.run_cli("set", key, value, *extra)
        self.assertEqual(code, 2, f"{key!r} {value!r} was accepted")
        self.assertIn("looks like a secret", err)
        self.assertEqual(self.json_of("list") if self.store.exists() else [], [])

    def test_secret_words_in_key_rejected(self) -> None:
        for word in knowledge.SECRET_NAME_WORDS:
            self.refused(f"my.{word}", "x")

    def test_secret_words_in_alias_rejected(self) -> None:
        self.refused("fine", "x", "--alias", "My Password")

    def test_value_patterns_rejected(self) -> None:
        samples: list[str] = [
            "sk-" + "a1" * 10,
            "ghp_" + "A" * 24,
            "gho_" + "b" * 22,
            "github_pat_" + "x" * 5,
            "xoxb-" + "1" * 6,
            "AKIA" + "ABCDEFGH12345678",
            "-----BEGIN " + "PRIVATE KEY-----",
            "eyJhbGciOi" + ".eyJzdWIiOiIx.sig",
            "abcdefghij0123456789abcdefghij01",
        ]
        for sample in samples:
            self.refused("some-key", f"use {sample} here")

    def test_normal_values_accepted(self) -> None:
        for value in ("6 agents", "acme is a family of repos: acme-api, acme-web", "a" * 40, "1" * 40,
                      "run `make test` before pushing"):
            self.assertEqual(self.run_cli("set", "ok", value)[0], 0, value)


class ContextTests(KnowledgeCase):
    def test_context_json_with_repo_matches(self) -> None:
        self.ok("set", "agents.standard", "6 agents")
        self.ok("set", "acme", "product line", "--kind", "term", "--alias", "acme-*", "--tag", "widgets")
        self.ok("set", "other", "unrelated", "--kind", "term")
        self.ok("set", "xy", "too short to match", "--kind", "term")
        repo: Path = self.root / "acme-api"
        repo.mkdir()
        context: dict[str, Any] = self.json_of("context", "--repo", str(repo))
        self.assertEqual(context["store"], str(self.store))
        self.assertEqual([e["key"] for e in context["preferences"]], ["agents.standard"])
        self.assertEqual([e["key"] for e in context["terms"]], ["acme", "other", "xy"])
        self.assertEqual(context["repo_matches"], ["acme"])
        self.assertEqual(set(context["preferences"][0]), {"key", "kind", "value", "aliases", "tags", "updated", "by"})

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_repo_matches_use_origin_url(self) -> None:
        self.ok("set", "widgets", "tag test", "--kind", "term")
        repo: Path = self.root / "plain-name"
        repo.mkdir()
        env: dict[str, str] = {**os.environ}
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://example.invalid/org/widgets-api"],
                       check=True, env=env)
        self.assertEqual(self.json_of("context", "--repo", str(repo))["repo_matches"], ["widgets"])

    def test_context_with_store_missing_exits_0(self) -> None:
        context: dict[str, Any] = self.json_of("context")
        self.assertEqual(context, {"store": None, "preferences": [], "terms": [], "repo_matches": []})
        self.assertIn("no store", self.ok("context"))

    def test_context_human_output(self) -> None:
        self.ok("set", "agents.standard", "6 agents")
        out: str = self.ok("context", "--repo", str(self.root))
        self.assertIn("Personal knowledge", out)
        self.assertIn("agents.standard: 6 agents", out)


class StatusTests(KnowledgeCase):
    def test_status_missing_store_exits_0(self) -> None:
        report: dict[str, Any] = self.json_of("status")
        self.assertFalse(report["exists"])
        self.assertIsNone(report["remote"])
        self.assertFalse(report["dirty"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_status_counts_remote_and_dirty(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        self.ok("init", "--remote", bare)
        self.ok("set", "a", "1")
        self.ok("set", "b", "2", "--kind", "term")
        report: dict[str, Any] = self.json_of("status")
        self.assertTrue(report["exists"])
        self.assertEqual(report["counts"], {"preference": 1, "term": 1, "learning": 0})
        self.assertEqual(report["remote"], bare)
        self.assertTrue(report["dirty"])
        self.assertEqual(report["backend"], "git")
        self.ok("sync")
        self.assertFalse(self.json_of("status")["dirty"])
        self.assertIn("backend: git", self.ok("status"))


@unittest.skipUnless(HAVE_GIT, "git not installed")
class SyncTests(KnowledgeCase):
    def test_sync_without_remote_commits_locally(self) -> None:
        self.ok("init")
        self.ok("set", "a", "1")
        self.assertIn("no remote; committed locally", self.ok("sync"))
        log: str = subprocess.run(["git", "-C", str(self.store), "log", "--oneline"], capture_output=True, text=True,
                                  check=True).stdout
        self.assertIn("knowledge: sync from", log)
        self.assertFalse(self.json_of("status")["dirty"])

    def test_sync_outside_git_exits_0(self) -> None:
        self.store.mkdir()
        code, out, _ = self.run_cli("sync")
        self.assertEqual(code, 0)
        self.assertIn("not a git repository", out)

    def test_same_entry_edited_on_two_devices_newer_wins_loser_kept(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        first, second = self.root / "device-a", self.root / "device-b"
        self.ok("init", "--remote", bare, store=first)
        self.ok("set", "agents.standard", "4 agents", store=first)
        self.ok("sync", store=first)
        self.ok("init", "--remote", bare, store=second)
        self.assertEqual(self.ok("get", "agents.standard", store=second).strip(), "4 agents")
        self.ok("set", "agents.standard", "from a", "--by", "a", store=first)
        time.sleep(CLOCK_TICK)
        self.ok("set", "agents.standard", "from b", "--by", "b", store=second)
        self.ok("sync", store=first)
        self.ok("sync", store=second)
        self.assertEqual(self.ok("get", "agents.standard", store=second).strip(), "from b")
        folder: Path = second / "entries" / "preference"
        losers: list[Path] = sorted(folder.glob("agents.standard.conflict-*.md"))
        self.assertEqual(len(losers), 1)
        self.assertIn("from a", losers[0].read_text(encoding="utf-8"))
        self.assertEqual(len(self.json_of("list", store=second)), 1)  # the conflict copy is not an entry
        self.assertEqual(self.json_of("status", store=second)["conflicts"], 1)
        self.ok("sync", store=first)
        self.assertEqual(self.ok("get", "agents.standard", store=first).strip(), "from b")
        self.assertEqual(len(list((first / "entries" / "preference").glob("agents.standard.conflict-*.md"))), 1)

    def test_non_entry_conflict_aborts_with_exit_2(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        first, second = self.root / "device-a", self.root / "device-b"
        self.ok("init", "--remote", bare, store=first)
        self.ok("init", "--remote", bare, store=second)
        (first / "README.md").write_text("from a\n", encoding="utf-8")
        (second / "README.md").write_text("from b\n", encoding="utf-8")
        self.ok("sync", store=first)
        code, _, err = self.run_cli("sync", store=second)
        self.assertEqual(code, 2)
        self.assertIn("README.md", err)


class ProfileAndBackendTests(KnowledgeCase):
    def test_profile_path_override_and_home_fallback(self) -> None:
        self.assertEqual(knowledge.profile_path(), self.profile)
        with unittest.mock.patch.dict(os.environ, {"DTS2_HOME": "/x/home"}):
            os.environ.pop("DTS2_KNOWLEDGE_PROFILE")
            self.assertEqual(knowledge.profile_path(), Path("/x/home/knowledge.json"))

    def test_store_resolution_order(self) -> None:
        knowledge.save_profile("me", "local", self.root / "from-profile", None)
        self.assertEqual(knowledge.store_path(), self.store)  # env wins
        os.environ.pop("DTS2_KNOWLEDGE")
        self.assertEqual(knowledge.store_path(), (self.root / "from-profile").resolve())
        self.profile.unlink()
        with unittest.mock.patch.dict(os.environ, {"DTS2_HOME": "/x/home"}):
            self.assertEqual(knowledge.store_path(), Path("/x/home/knowledge"))

    def test_corrupt_profile_reads_as_absent(self) -> None:
        self.profile.write_text("{not json", encoding="utf-8")
        self.assertIsNone(knowledge.load_profile())

    def test_setup_local_writes_profile_marker_and_readme(self) -> None:
        self.ok("setup", "--owner", "acme-team", "--backend", "local")
        profile: dict[str, Any] = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual({k: profile[k] for k in ("schema", "owner", "backend", "remote")},
                         {"schema": 1, "owner": "acme-team", "backend": "local", "remote": None})
        self.assertEqual(profile["store"], str(self.store.resolve()))
        self.assertIn("T", profile["joined"])
        marker: dict[str, Any] = json.loads((self.store / "store.json").read_text(encoding="utf-8"))
        self.assertEqual((marker["schema"], marker["owner"]), (1, "acme-team"))
        self.assertIn("acme-team", (self.store / "README.md").read_text(encoding="utf-8"))
        self.assertFalse((self.store / ".git").exists())
        self.assertIn("local store", self.ok("sync"))
        self.assertEqual(self.json_of("status")["owner"], "acme-team")

    def test_setup_refuses_existing_store_unless_forced(self) -> None:
        self.ok("setup", "--owner", "one", "--backend", "local")
        code, _, err = self.run_cli("setup", "--owner", "two", "--backend", "local")
        self.assertEqual(code, 2)
        self.assertIn("already holds a store", err)
        self.ok("setup", "--owner", "two", "--backend", "local", "--force")
        self.assertEqual(json.loads((self.store / "store.json").read_text(encoding="utf-8"))["owner"], "two")

    def test_setup_folder_requires_path_and_syncs_as_noop(self) -> None:
        self.assertEqual(self.run_cli("setup", "--owner", "acme", "--backend", "folder")[0], 2)
        drive: Path = self.root / "drive" / "knowledge"
        self.ok("setup", "--owner", "acme", "--backend", "folder", "--path", str(drive))
        self.assertTrue((drive / "store.json").is_file())
        self.assertTrue((drive / "entries" / "term").is_dir())
        self.assertFalse((drive / ".git").exists())
        self.assertEqual(json.loads(self.profile.read_text(encoding="utf-8"))["store"], str(drive.resolve()))
        self.assertIn("folder is synced by your drive app", self.ok("sync", store=drive))

    def test_join_folder_reads_owner_and_ties_device(self) -> None:
        drive: Path = self.root / "drive"
        self.ok("setup", "--owner", "acme", "--backend", "folder", "--path", str(drive))
        self.profile.unlink()
        out: str = self.ok("join", "--backend", "folder", "--path", str(drive))
        self.assertIn("this device is now tied to acme's knowledge store", out)
        profile: dict[str, Any] = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual((profile["owner"], profile["backend"]), ("acme", "folder"))

    def test_join_missing_store_exits_3_and_writes_no_profile(self) -> None:
        empty: Path = self.root / "empty-drive"
        empty.mkdir()
        self.assertEqual(self.run_cli("join", "--backend", "folder", "--path", str(empty))[0], 3)
        self.assertFalse(self.profile.exists())

    def test_join_argument_errors(self) -> None:
        self.assertEqual(self.run_cli("join", "--backend", "folder")[0], 2)
        self.assertEqual(self.run_cli("join", "--backend", "git")[0], 2)
        self.assertEqual(self.run_cli("join", "--backend", "local")[0], 2)

    def test_backend_dispatch(self) -> None:
        self.assertIsInstance(knowledge.backend_for(None), knowledge.GitBackend)
        for name, cls in knowledge.BACKENDS.items():
            backend = knowledge.backend_for({"backend": name, "owner": "o", "remote": None})
            self.assertIsInstance(backend, cls)
            self.assertEqual(backend.describe()["backend"], name)

    def test_profile_never_holds_credentials(self) -> None:
        self.ok("setup", "--owner", "acme", "--backend", "local")
        self.assertEqual(set(json.loads(self.profile.read_text(encoding="utf-8"))),
                         {"schema", "owner", "backend", "store", "remote", "joined"})

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_setup_git_with_remote_pushes_then_join_clones(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        self.ok("setup", "--owner", "acme", "--backend", "git", "--remote", bare)
        self.ok("set", "agents.standard", "6 agents")
        self.ok("sync")
        self.assertEqual(json.loads(self.profile.read_text(encoding="utf-8"))["remote"], bare)
        remote_files: str = subprocess.run(["git", "--git-dir", bare, "ls-tree", "-r", "--name-only", "main"],
                                           capture_output=True, text=True, check=True).stdout
        self.assertIn("store.json", remote_files)
        self.assertIn("entries/preference/agents.standard.md", remote_files)
        other: Path = self.root / "device-b"
        self.profile.unlink()
        out: str = self.ok("join", "--backend", "git", "--remote", bare, "--path", str(other))
        self.assertIn("tied to acme's knowledge store", out)
        self.assertEqual(self.ok("get", "agents.standard", store=other).strip(), "6 agents")
        profile: dict[str, Any] = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual((profile["backend"], profile["remote"], profile["store"]), ("git", bare, str(other.resolve())))
        # joining again from an existing matching clone verifies it instead of cloning
        self.ok("join", "--backend", "git", "--remote", bare, "--path", str(other))

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_setup_refuses_a_second_time_on_a_cloned_store(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        self.ok("setup", "--owner", "acme", "--backend", "git", "--remote", bare)
        self.assertEqual(self.run_cli("setup", "--owner", "x", "--backend", "git", "--remote", bare)[0], 2)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_join_git_rejects_foreign_directory_and_empty_remote(self) -> None:
        bare: str = make_bare_remote(self.root / "remote.git")
        occupied: Path = self.root / "occupied"
        occupied.mkdir()
        (occupied / "file.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.run_cli("join", "--backend", "git", "--remote", bare, "--path", str(occupied))[0], 2)
        self.assertEqual(self.run_cli("join", "--backend", "git", "--remote", bare, "--path", str(self.root / "new"))[0], 3)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_init_alias_defaults_owner_and_writes_profile(self) -> None:
        self.ok("init")
        profile: dict[str, Any] = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual(profile["backend"], "git")
        self.assertTrue(profile["owner"])
        self.assertTrue((self.store / "store.json").is_file())


class CloudflareBackendTests(KnowledgeCase):
    URL: Final[str] = "https://acme-knowledge.example.invalid"
    SECRET: Final[str] = "tok-test-value-123"

    def profile_data(self) -> dict[str, Any]:
        return json.loads(self.profile.read_text(encoding="utf-8"))

    def test_setup_records_backend_and_url_without_token(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_TOKEN": self.SECRET}):
            self.ok("setup", "--owner", "acme-team", "--backend", "cloudflare", "--url", self.URL)
        data = self.profile_data()
        self.assertEqual((data["backend"], data["remote"]), ("cloudflare", self.URL))
        self.assertTrue((self.store / "store.json").is_file())
        self.assertNotIn(self.SECRET, self.profile.read_text(encoding="utf-8"))
        self.assertNotIn("token", " ".join(data).lower())

    def test_setup_without_token_succeeds_with_note(self) -> None:
        os.environ.pop("DTS2_KNOWLEDGE_TOKEN", None)
        code, _, err = self.run_cli("setup", "--backend", "cloudflare", "--url", self.URL)
        self.assertEqual(code, 0)
        self.assertIn("DTS2_KNOWLEDGE_TOKEN", err)

    def test_missing_url_exits_2(self) -> None:
        self.assertEqual(self.run_cli("setup", "--backend", "cloudflare")[0], 2)
        self.assertEqual(self.run_cli("join", "--backend", "cloudflare")[0], 2)
        self.assertFalse(self.profile.exists())

    def test_join_records_profile(self) -> None:
        os.environ.pop("DTS2_KNOWLEDGE_TOKEN", None)
        code, _, err = self.run_cli("join", "--backend", "cloudflare", "--url", self.URL)
        self.assertEqual(code, 0, err)
        self.assertIn("DTS2_KNOWLEDGE_TOKEN", err)
        data = self.profile_data()
        self.assertEqual((data["backend"], data["remote"]), ("cloudflare", self.URL))

    def test_status_shows_backend_and_url(self) -> None:
        self.ok("setup", "--backend", "cloudflare", "--url", self.URL)
        report = self.json_of("status")
        self.assertEqual((report["backend"], report["url"]), ("cloudflare", self.URL))
        self.assertIn(self.URL, self.ok("status"))

    def test_sync_delegates_to_cloudflare_backend(self) -> None:
        self.ok("setup", "--backend", "cloudflare", "--url", self.URL)
        fake = unittest.mock.Mock()
        fake.CloudflareBackend.from_env.return_value.sync.return_value = 2
        with unittest.mock.patch.dict(os.environ, {"DTS2_KNOWLEDGE_TOKEN": self.SECRET}):
            with unittest.mock.patch.dict(sys.modules, {"knowledge_cloudflare": fake}):
                out = self.ok("sync")
        fake.CloudflareBackend.from_env.assert_called_once_with(self.URL)
        fake.CloudflareBackend.from_env.return_value.sync.assert_called_once_with(self.store)
        self.assertIn("2", out)

    def test_sync_without_token_exits_2(self) -> None:
        self.ok("setup", "--backend", "cloudflare", "--url", self.URL)
        os.environ.pop("DTS2_KNOWLEDGE_TOKEN", None)
        code, _, err = self.run_cli("sync")
        self.assertEqual(code, 2)
        self.assertIn("DTS2_KNOWLEDGE_TOKEN", err)


if __name__ == "__main__":
    unittest.main()
