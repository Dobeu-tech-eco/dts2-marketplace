"""G-22: one config parser (miniyaml), one script loader (_load), settings parsed once into a mtime-keyed cache."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _load  # noqa: E402
import miniyaml  # noqa: E402
import settings_cache  # noqa: E402

CONFIG: Final[str] = """\
# top comment
project: "demo # app"   # trailing note
url: http://x.test/a#frag
commands:
  test: pytest -q   # run tests
  lint: 'ruff check .'
do_not_touch: [".env", secrets/**]
roster:
  - name: claude
  - name: codex
    roles: [builder, second-opinion]
    included: false
keep:
  - one
  - "two"
budget:
  max_turns: 80
  max_usd: 2.5
  strict: true
empty:
"""


class CommentRuleTests(unittest.TestCase):
    def test_hash_starts_a_comment_only_at_line_start_or_after_space_and_outside_quotes(self) -> None:
        self.assertEqual(miniyaml.strip_comment("a: b # c"), "a: b")
        self.assertEqual(miniyaml.strip_comment("a: b#c"), "a: b#c")
        self.assertEqual(miniyaml.strip_comment('a: "b # c" # d'), 'a: "b # c"')
        self.assertEqual(miniyaml.strip_comment("# whole line"), "")

    def test_unquote(self) -> None:
        self.assertEqual(miniyaml.unquote('"a b"'), "a b")
        self.assertEqual(miniyaml.unquote("'a'"), "a")
        self.assertEqual(miniyaml.unquote("plain"), "plain")


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = miniyaml.parse(CONFIG)

    def test_scalars_and_comments(self) -> None:
        self.assertEqual(self.data["project"], "demo # app")
        self.assertEqual(self.data["url"], "http://x.test/a#frag")

    def test_nested_mapping(self) -> None:
        self.assertEqual(self.data["commands"], {"test": "pytest -q", "lint": "ruff check ."})

    def test_inline_and_block_lists(self) -> None:
        self.assertEqual(self.data["do_not_touch"], [".env", "secrets/**"])
        self.assertEqual(self.data["keep"], ["one", "two"])

    def test_list_of_mappings(self) -> None:
        self.assertEqual(self.data["roster"][0], {"name": "claude"})
        self.assertEqual(self.data["roster"][1], {"name": "codex", "roles": ["builder", "second-opinion"], "included": "false"})

    def test_empty_value_is_empty_string(self) -> None:
        self.assertEqual(self.data["empty"], "")

    def test_typed_accessors(self) -> None:
        self.assertEqual(miniyaml.get_int(self.data, "budget.max_turns", 1), 80)
        self.assertEqual(miniyaml.get_float(self.data, "budget.max_usd", 0.0), 2.5)
        self.assertIs(miniyaml.get_bool(self.data, "budget.strict", False), True)
        self.assertIs(miniyaml.get_bool(self.data, "roster.nope", True), True)
        self.assertEqual(miniyaml.get_int(self.data, "budget.missing", 7), 7)
        self.assertEqual(miniyaml.get_int(self.data, "project", 9), 9)  # not a number: default
        self.assertEqual(miniyaml.get_str(self.data, "commands.test", ""), "pytest -q")
        self.assertEqual(miniyaml.get_list(self.data, "keep"), ["one", "two"])
        self.assertEqual(miniyaml.get_list(self.data, "project"), [])

    def test_frontmatter(self) -> None:
        text = "---\nenabled: true\nmax_builders: 4  # cap\n---\nbody: ignored\n"
        self.assertEqual(miniyaml.parse_frontmatter(text), {"enabled": "true", "max_builders": "4"})
        self.assertEqual(miniyaml.parse_frontmatter("no fence"), {})

    def test_garbage_does_not_raise(self) -> None:
        self.assertIsInstance(miniyaml.parse("\t\t- - :\n: x\n  deep: 1\n"), dict)


class LoaderTests(unittest.TestCase):
    def test_hyphenated_and_importable_names_resolve_to_the_same_module(self) -> None:
        a = _load.load("action-items")
        b = _load.load("action_items")
        self.assertIs(a, b)
        self.assertTrue(hasattr(a, "list_items"))

    def test_unknown_script_raises(self) -> None:
        with self.assertRaises(_load.ScriptNotFound):
            _load.load("no-such-script")


class SettingsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / ".harness").mkdir()
        (self.repo / ".claude").mkdir()
        (self.repo / ".harness" / "config.yaml").write_text("budget:\n  max_turns: 12\nsupervisor:\n  retry_max: nope\n")
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nmax_builders: 3\n---\n")

    def test_defaults_fill_and_bad_values_fall_back(self) -> None:
        s = settings_cache.load(self.repo)
        self.assertEqual(s["budget"]["max_turns"], 12)
        self.assertEqual(s["budget"]["max_rounds"], settings_cache.DEFAULTS["budget"]["max_rounds"])
        self.assertEqual(s["supervisor"]["retry_max"], settings_cache.DEFAULTS["supervisor"]["retry_max"])
        self.assertEqual(s["local"]["max_builders"], 3)
        self.assertEqual(s["local"]["son_permission_mode"], "bypassPermissions")

    def test_cache_file_is_private_and_reused_until_a_source_changes(self) -> None:
        settings_cache.load(self.repo)
        cache = self.repo / ".harness" / "settings.cache.json"
        self.assertTrue(cache.is_file())
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        marker = json.loads(cache.read_text())
        marker["settings"]["budget"]["max_turns"] = 999  # tamper: a cache hit must return it
        cache.write_text(json.dumps(marker))
        os.chmod(cache, 0o600)
        self.assertEqual(settings_cache.load(self.repo)["budget"]["max_turns"], 999)
        config = self.repo / ".harness" / "config.yaml"
        config.write_text("budget:\n  max_turns: 20\n")
        stamp = config.stat().st_mtime_ns + 5_000_000_000
        os.utime(config, ns=(stamp, stamp))
        self.assertEqual(settings_cache.load(self.repo)["budget"]["max_turns"], 20)

    def test_no_sources_still_returns_defaults(self) -> None:
        empty = Path(tempfile.mkdtemp(prefix="b12-"))
        self.assertEqual(settings_cache.load(empty)["budget"]["max_turns"], settings_cache.DEFAULTS["budget"]["max_turns"])

    def test_cache_is_gitignored_by_ensure_ignored(self) -> None:
        text = (SCRIPTS / "ensure-ignored.py").read_text(encoding="utf-8")
        self.assertIn(".harness/settings.cache.json", text)


class RepointedConsumersTests(unittest.TestCase):
    def test_model_call_reads_blocks_through_miniyaml(self) -> None:
        import model_call
        tmp = Path(tempfile.mkdtemp(prefix="b12-"))
        (tmp / ".harness").mkdir()
        (tmp / ".harness" / "config.yaml").write_text("budget:\n  max_turns: 9 # c\nother:\n  max_turns: 1\n")
        self.assertEqual(model_call.read_block(tmp, "budget"), {"max_turns": "9"})
        self.assertEqual(model_call.read_budget(tmp)["max_turns"], 9)


if __name__ == "__main__":
    unittest.main()
