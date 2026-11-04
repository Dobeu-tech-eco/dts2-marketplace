"""B4/B8 second review round: tracked and no-git apply-update, unknown instruction change, pin text, pin ref."""
from __future__ import annotations

import importlib.util
import json
import unittest

import skill_pins_loader  # noqa: F401  (puts scripts/ on sys.path)
import skill_pins as pins
from helpers import PLUGIN_ROOT
from test_skill_pins import PIN_KEEP, SHA_A, SHA_B, pin_fixture


def store_proposal(fx) -> None:  # type: ignore[no-untyped-def]
    fx.heads = {"mattpocock/skills": SHA_B}
    fx.run("--fix")


class ApplyUpdateGuardTests(unittest.TestCase):
    def test_tracked_skill_is_not_reported_applied(self) -> None:
        fx = pin_fixture(PIN_KEEP)
        fx.commit({".claude/skills/grill-me/SKILL.md": "OLD VENDORED CONTENT\n"})
        store_proposal(fx)
        keep_before = fx.keep_text()
        out = fx.run("--fix", "--apply-update", f"grill-me={SHA_B}")["skills"]
        self.assertEqual(out["applied"], [])
        self.assertEqual(fx.keep_text(), keep_before)
        self.assertIn(f"pin: {SHA_A}", fx.keep_text())
        self.assertEqual(fx.skill("grill-me").read_text(encoding="utf-8"), "OLD VENDORED CONTENT\n")
        self.assertTrue(any(r["name"] == "grill-me" and "git-tracked" in r["reason"] for r in out["rejected"]))
        stored = json.loads((fx.repo / ".harness" / "skill-updates.json").read_text(encoding="utf-8"))
        self.assertIn(SHA_B, [p["upstream"] for p in stored if p["name"] == "grill-me"])

    def test_git_failure_runs_no_npx_and_writes_nothing(self) -> None:
        fx = pin_fixture(PIN_KEEP)
        fx.commit({".claude/skills/grill-me/SKILL.md": "OLD VENDORED CONTENT\n"})
        store_proposal(fx)
        broken = fx.fake / "git.py"
        broken.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        fx.git_bin = str(broken)
        keep_before = fx.keep_text()
        npx_before = fx.log("npx")
        out = fx.run("--fix", "--apply-update", f"grill-me={SHA_B}")["skills"]
        self.assertEqual(out["applied"], [])
        self.assertEqual(out["tracked_check"], "unavailable")
        self.assertEqual(fx.log("npx"), npx_before)
        self.assertEqual(fx.keep_text(), keep_before)
        self.assertEqual(fx.skill("grill-me").read_text(encoding="utf-8"), "OLD VENDORED CONTENT\n")
        self.assertIn({"name": "grill-me", "step": "apply-update", "reverted": []}, out["tracked_skipped"])
        stored = json.loads((fx.repo / ".harness" / "skill-updates.json").read_text(encoding="utf-8"))
        self.assertIn(SHA_B, [p["upstream"] for p in stored if p["name"] == "grill-me"])


class UnknownInstructionChangeTests(unittest.TestCase):
    def test_none_files_give_unknown_for_update_and_pin_proposals(self) -> None:
        entries = [{"name": "grill-me", "ref": "https://github.com/mattpocock/skills --skill grill-me", "pin": SHA_A},
                   {"name": "pr", "ref": "https://github.com/mattpocock/skills --skill pr"}]
        found = pins.build_proposals(entries, lambda repo: SHA_B, lambda repo, a, b: None)
        self.assertEqual({p["kind"] for p in found}, {"update", "pin"})
        for proposal in found:
            self.assertIsNone(proposal["instruction_files_changed"])

    def test_run_skill_explains_null(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`null` means unknown", text)


class PinTextTests(unittest.TestCase):
    def test_comment_inside_an_entry_does_not_keep_the_old_pin(self) -> None:
        text = f"skills:\n  - name: grill-me\n    # note\n    pin: {SHA_A}\n    serves: x\n"
        out = pins.set_pin_text(text, "grill-me", SHA_B)
        self.assertEqual(out.count("pin:"), 1)
        self.assertIn(f"pin: {SHA_B}", out)
        self.assertIn("    # note\n", out)
        self.assertIn("    serves: x\n", out)


class PinRefTests(unittest.TestCase):
    def test_valid_pin_on_an_unpinnable_ref_is_rejected_not_installed_plain(self) -> None:
        spec = importlib.util.spec_from_file_location("skills_check_mod", PLUGIN_ROOT / "scripts" / "skills-check.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report = mod.new_report()
        entry = {"name": "grill-me", "ref": "https://example.com/other/skills --skill grill-me"}
        self.assertFalse(mod.attach_pin(entry, SHA_A, report))
        self.assertNotIn("pin", entry)
        self.assertEqual([r["name"] for r in report["rejected"]], ["grill-me"])
        good = {"name": "grill-me", "ref": "https://github.com/mattpocock/skills --skill grill-me"}
        self.assertTrue(mod.attach_pin(good, SHA_A, mod.new_report()))


if __name__ == "__main__":
    unittest.main()
