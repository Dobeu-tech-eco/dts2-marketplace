"""Batch 5M: process rules, plugin metadata (frontmatter), context budget, changelog fragments and CI wiring."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home, read_run_skill
from test_handoff import SCRIPT as HANDOFF_SCRIPT, make_repo as make_handoff_repo

REPO_ROOT: Final[Path] = PLUGIN_ROOT.parent.parent
AGENTS: Final[Path] = PLUGIN_ROOT / "agents"
SKILLS: Final[Path] = PLUGIN_ROOT / "skills"
WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "test.yml"
# Documented keys (Claude Code docs: sub-agents, skills). Unknown keys are silently ignored, so a typo goes unnoticed.
AGENT_KEYS: Final[frozenset[str]] = frozenset({
    "name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns", "autoCompactWindow", "skills",
    "mcpServers", "hooks", "memory", "background", "omitClaudeMd", "effort", "isolation", "color", "initialPrompt", "experimental"})
SKILL_KEYS: Final[frozenset[str]] = frozenset({
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
    "metadata", "license", "compatibility"})
COLORS: Final[frozenset[str]] = frozenset({"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"})
EFFORTS: Final[frozenset[str]] = frozenset({"low", "medium", "high", "xhigh", "max"})
USER_ONLY_SKILLS: Final[tuple[str, ...]] = ("dpp-full", "fullauto", "machine-prep", "sdk", "onboard", "model")
MAX_TURNS: Final[dict[str, int]] = {"scout": 15, "lead": 25, "reviewer": 30, "verifier": 40, "builder": 60, "auditor": 20}
LOW_EFFORT: Final[tuple[str, ...]] = ("scout", "auditor")
READ_ONLY_AGENTS: Final[tuple[str, ...]] = ("lead", "reviewer", "scout", "auditor", "verifier")
WRITE_TOOLS: Final[frozenset[str]] = frozenset({"Write", "Edit", "NotebookEdit"})
DESCRIPTION_HARD_CAP: Final[int] = 300


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), PLUGIN_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def frontmatter_lines(path: Path) -> list[str]:
    lines: list[str] = path.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "---", path
    return lines[1:lines.index("---", 1)]


def frontmatter_map(path: Path) -> dict[str, str]:
    """Same parser the context-tax gate uses (gathers folded and block-list values), so the two cannot drift."""
    assert path.read_text(encoding="utf-8").startswith("---\n"), path
    return load_script("context-tax").frontmatter(path.read_text(encoding="utf-8"))


def tool_names(value: str) -> set[str]:
    """Tool names from a CSV, a flow list `[A, B]` or a gathered block list `- A - B`."""
    cleaned: str = re.sub(r"(^|\s)-\s", " ", value.replace("[", " ").replace("]", " ").replace(",", " "))
    return {part for part in cleaned.split() if part}


def read_only_violations(meta: dict[str, str]) -> list[str]:
    """Why an agent is not read-only: no declaration, an empty one, or a write tool on the allowlist."""
    if not meta.get("tools") and not meta.get("disallowedTools"):
        return ["declares neither tools nor disallowedTools"]
    if meta.get("tools"):
        return sorted(tool_names(meta["tools"]) & WRITE_TOOLS)
    return sorted(WRITE_TOOLS - tool_names(meta["disallowedTools"]))


def agent_files() -> list[Path]:
    return sorted(AGENTS.glob("*.md"))


def skill_files() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


class FrontmatterAllowlist(unittest.TestCase):
    """Q-18: every frontmatter key is a documented one."""

    def test_agent_keys_are_documented(self) -> None:
        for path in agent_files():
            self.assertLessEqual(set(frontmatter_map(path)) - AGENT_KEYS, set(), path.name)

    def test_skill_keys_are_documented(self) -> None:
        for path in skill_files():
            self.assertLessEqual(set(frontmatter_map(path)) - SKILL_KEYS, set(), path.parent.name)

    def test_name_matches_file(self) -> None:
        for path in agent_files():
            self.assertEqual(frontmatter_map(path)["name"], path.stem)
        for path in skill_files():
            self.assertEqual(frontmatter_map(path)["name"], path.parent.name)

    def test_no_legacy_commands_folder(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "commands").exists())


class AgentMetadata(unittest.TestCase):
    def test_max_turns_per_agent(self) -> None:
        for name, turns in MAX_TURNS.items():
            self.assertEqual(frontmatter_map(AGENTS / f"{name}.md").get("maxTurns"), str(turns), name)

    def test_effort_values_are_valid_and_low_for_cheap_seats(self) -> None:
        for path in agent_files():
            effort: str | None = frontmatter_map(path).get("effort")
            if effort is not None:
                self.assertIn(effort, EFFORTS, path.name)
        for name in LOW_EFFORT:
            self.assertEqual(frontmatter_map(AGENTS / f"{name}.md").get("effort"), "low", name)

    def test_every_agent_has_a_valid_color(self) -> None:
        colors: list[str] = []
        for path in agent_files():
            color: str = frontmatter_map(path).get("color", "")
            self.assertIn(color, COLORS, path.name)
            colors.append(color)
        self.assertEqual(len(colors), len(set(colors)), "agents should be told apart by color")

    def test_read_only_agents_cannot_write(self) -> None:
        """Q-3: each read-only agent either allowlists tools without a write tool or denies all of them."""
        for name in READ_ONLY_AGENTS:
            meta: dict[str, str] = frontmatter_map(AGENTS / f"{name}.md")
            value: str = meta.get("tools") or meta.get("disallowedTools") or ""
            self.assertTrue(value, f"{name} declares neither tools nor disallowedTools")
            self.assertNotRegex(value, r"[\[\]\n]", f"{name}: list form not parsed as plain CSV")
            self.assertEqual(read_only_violations(meta), [], name)

    def test_verifier_keeps_bash_but_denies_writes(self) -> None:
        meta: dict[str, str] = frontmatter_map(AGENTS / "verifier.md")
        self.assertTrue(meta.get("disallowedTools"))
        self.assertNotRegex(meta["disallowedTools"], r"[\[\]\n]")
        self.assertEqual(tool_names(meta["disallowedTools"]), set(WRITE_TOOLS))
        self.assertNotIn("tools", meta, "an allowlist would drop the tools the verifier needs to run tests")

    def test_builder_may_write(self) -> None:
        self.assertLessEqual(WRITE_TOOLS - {"NotebookEdit"}, tool_names(frontmatter_map(AGENTS / "builder.md")["tools"]))

    def test_seat_wording_matches_pins(self) -> None:
        """Q-12: reviewers are advisory seats on the standard tier, frontier only for design-risk."""
        reviewer: str = (AGENTS / "reviewer.md").read_text(encoding="utf-8")
        lead: str = (AGENTS / "lead.md").read_text(encoding="utf-8")
        self.assertIn("design-risk", reviewer)
        self.assertIn("design-risk", lead)
        self.assertNotIn("the reviewers' and verifier's", lead)
        self.assertEqual(frontmatter_map(AGENTS / "reviewer.md")["model"], "sonnet")
        for text in (reviewer, lead):
            self.assertIn("sign-off", text)
            self.assertIn("frontier", text)
        self.assertIn("final whole-diff review you hold the sign-off seat and run at frontier", reviewer)
        self.assertIn("the final whole-diff reviewer", lead)


class SkillMetadata(unittest.TestCase):
    def test_user_only_skills_disable_model_invocation(self) -> None:
        """Q-2: exactly the listed skills are user-invoked only. setup and evolve stay model-invocable: run, ship and the context guard call them."""
        flagged: set[str] = {p.parent.name for p in skill_files() if frontmatter_map(p).get("disable-model-invocation") == "true"}
        self.assertEqual(flagged, set(USER_ONLY_SKILLS))

    def test_descriptions_stay_short(self) -> None:
        """Q-1: a description is the always-loaded part of a skill or agent."""
        for path in skill_files() + agent_files():
            description: str = frontmatter_map(path)["description"]
            self.assertTrue(description, path)
            self.assertLessEqual(len(description), DESCRIPTION_HARD_CAP, f"{path.name}: {len(description)} chars")


class ContextTax(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_script("context-tax")

    def test_plugin_is_under_budget(self) -> None:
        result = self.mod.report(PLUGIN_ROOT, self.mod.DEFAULT_BUDGET, self.mod.DEFAULT_MAX_DESCRIPTION)
        self.assertTrue(result["ok"], result["problems"])
        self.assertGreater(result["tokens"], 0)

    def test_script_exit_codes(self) -> None:
        script: str = str(PLUGIN_ROOT / "scripts" / "context-tax.py")
        ok = subprocess.run(["python3", "-I", script], capture_output=True, text=True, check=False)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertTrue(json.loads(ok.stdout)["ok"])
        over = subprocess.run(["python3", "-I", script, "--budget", "10"], capture_output=True, text=True, check=False)
        self.assertEqual(over.returncode, 1)
        self.assertIn("over the 10 budget", json.loads(over.stdout)["problems"][0])

    def test_long_description_is_a_problem(self) -> None:
        root: Path = make_tmp_home()
        skill: Path = root / "skills" / "x" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\nname: x\ndescription: {'a' * 400}\n---\nbody\n", encoding="utf-8")
        result = self.mod.report(root, 6000, 300)
        self.assertFalse(result["ok"])
        self.assertIn("400 chars", result["problems"][0])

    def test_missing_description_is_a_problem(self) -> None:
        root: Path = make_tmp_home()
        agent: Path = root / "agents" / "a.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("---\nname: a\n---\nbody\n", encoding="utf-8")
        self.assertIn("no description", self.mod.report(root, 6000, 300)["problems"][0])

    def test_user_only_skills_are_reported_apart_from_the_total(self) -> None:
        root: Path = make_tmp_home()
        for name, extra in (("a", ""), ("b", "disable-model-invocation: true\n")):
            skill: Path = root / "skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(f"---\nname: {name}\ndescription: {'d' * 40}\n{extra}---\nbody\n", encoding="utf-8")
        result = self.mod.report(root, 6000, 300)
        self.assertEqual([e["file"] for e in result["entries"]], ["skills/a/SKILL.md"])
        self.assertEqual([e["file"] for e in result["user_only"]], ["skills/b/SKILL.md"])
        self.assertEqual(result["tokens"], result["entries"][0]["tokens"])

    def test_tokens_are_chars_over_four_rounded_up(self) -> None:
        self.assertEqual(self.mod.tokens_of(9), 3)
        self.assertEqual(self.mod.tokens_of(8), 2)

    def test_frontmatter_ignores_body_and_unterminated_blocks(self) -> None:
        self.assertEqual(self.mod.frontmatter("---\nname: a\n---\nname: b\n"), {"name": "a"})
        self.assertEqual(self.mod.frontmatter("---\nname: a\n"), {})
        self.assertEqual(self.mod.frontmatter("no block"), {})


class ChangelogJoin(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_script("changelog-join")
        self.root: Path = make_tmp_home()
        (self.root / "changelog.d").mkdir()
        (self.root / "README.md").write_text("# T\n\n## Changelog\n\n## Unreleased\n\n- old line\n\n## Notes\n\ntail\n", encoding="utf-8")

    def fragment(self, name: str, text: str) -> None:
        (self.root / "changelog.d" / name).write_text(text, encoding="utf-8")

    def test_dry_run_changes_nothing(self) -> None:
        self.fragment("batch-2.md", "- two\n")
        before: str = (self.root / "README.md").read_text(encoding="utf-8")
        out = self.mod.run(self.root, None, False, "2026-11-04")
        self.assertEqual(out["bullets"], 1)
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), before)
        self.assertTrue((self.root / "changelog.d" / "batch-2.md").exists())

    def test_joins_newest_batch_first_right_under_the_heading(self) -> None:
        self.fragment("batch-10.md", "# heading is ignored\n- ten\n")
        self.fragment("batch-2.md", "- two\n")
        self.fragment("README.md", "- never joined\n")
        out = self.mod.run(self.root, None, True, "2026-11-04")
        self.assertEqual(out["fragments"], ["batch-10.md", "batch-2.md"])
        self.assertEqual(out["dropped"], [])
        text: str = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased\n\n- ten\n- two\n- old line\n\n## Notes", text)
        self.assertNotIn("never joined", text)
        self.assertEqual(sorted(p.name for p in (self.root / "changelog.d").iterdir()), ["README.md"])

    def test_indented_continuation_lines_join_their_bullet(self) -> None:
        self.fragment("batch-1.md", "- one\n  wrapped tail\n")
        self.mod.run(self.root, None, True, "2026-11-04")
        self.assertIn("- one wrapped tail\n", (self.root / "README.md").read_text(encoding="utf-8"))

    def test_prose_is_reported_and_apply_refuses(self) -> None:
        self.fragment("batch-1.md", "- one\nstray prose\n")
        before: str = (self.root / "README.md").read_text(encoding="utf-8")
        dry = self.mod.run(self.root, None, False, "2026-11-04")
        self.assertEqual(dry["dropped"], ["batch-1.md: stray prose"])
        refused = self.mod.run(self.root, None, True, "2026-11-04")
        self.assertFalse(refused["applied"])
        self.assertIn("error", refused)
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), before)
        self.assertTrue((self.root / "changelog.d" / "batch-1.md").exists())
        script: str = str(PLUGIN_ROOT / "scripts" / "changelog-join.py")
        proc = subprocess.run(["python3", "-I", script, "--root", str(self.root), "--apply"], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["dropped"], ["batch-1.md: stray prose"])

    def test_release_renames_and_reopens_unreleased(self) -> None:
        self.fragment("batch-1.md", "- one\n")
        self.mod.run(self.root, "3.10.0", True, "2026-11-04")
        text: str = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased\n\n## 3.10.0 (2026-11-04)\n\n- one\n- old line\n\n## Notes", text)
        self.assertEqual(text.count("## Unreleased"), 1)

    def real_shape_readme(self) -> str:
        return ("# T\n\n## Changelog\n\n## Unreleased\n\n- newest line\n- older line\n"
                "- 3.1.0 \u2014 history entry\n- 2.0.0: first release.\n")

    def test_real_readme_shape_inserts_at_top_and_keeps_history(self) -> None:
        """The real README has no later `## ` heading: history bullets live inside `## Unreleased`."""
        (self.root / "README.md").write_text(self.real_shape_readme(), encoding="utf-8")
        self.fragment("batch-5.md", "- five\n")
        self.mod.run(self.root, None, True, "2026-11-04")
        text: str = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased\n\n- five\n- newest line\n- older line\n- 3.1.0", text)
        self.assertTrue(text.rstrip("\n").endswith("- 2.0.0: first release."))

    def test_real_readme_shape_release_moves_only_lines_above_history(self) -> None:
        (self.root / "README.md").write_text(self.real_shape_readme(), encoding="utf-8")
        self.fragment("batch-5.md", "- five\n")
        self.mod.run(self.root, "3.99.0", True, "2026-11-04")
        text: str = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased\n\n## 3.99.0 (2026-11-04)\n\n- five\n- newest line\n- older line\n\n- 3.1.0", text)
        self.assertLess(text.index("- older line"), text.index("- 3.1.0"))
        self.assertLess(text.index("## 3.99.0"), text.index("- five"))
        self.assertTrue(text.rstrip("\n").endswith("- 2.0.0: first release."))
        self.assertEqual(text.count("## 3.99.0"), 1)

    def test_bad_version_and_missing_heading_are_errors(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.run(self.root, "v3", False, "2026-11-04")
        (self.root / "README.md").write_text("# no heading\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.mod.run(self.root, None, False, "2026-11-04")

    def test_cli_reports_error_as_json(self) -> None:
        (self.root / "README.md").write_text("# no heading\n", encoding="utf-8")
        script: str = str(PLUGIN_ROOT / "scripts" / "changelog-join.py")
        proc = subprocess.run(["python3", "-I", script, "--root", str(self.root)], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stdout))

    def test_mechanism_is_documented(self) -> None:
        doc: str = (PLUGIN_ROOT / "changelog.d" / "README.md").read_text(encoding="utf-8")
        self.assertIn("changelog-join.py", doc)
        self.assertIn("batch-<n>.md", doc)
        self.assertIn("newest batch first", doc)
        self.assertIn("dropped", doc)


class ProcessRules(unittest.TestCase):
    def test_pr_templates_name_predecessor_and_merge_commit(self) -> None:
        """P1."""
        for path in (PLUGIN_ROOT / "templates" / "pr-template.md", REPO_ROOT / ".github" / "pull_request_template.md"):
            text: str = path.read_text(encoding="utf-8")
            self.assertIn("Follows:", text, path.name)
            self.assertIn("merge commit only", text, path.name)

    def test_ship_fills_the_follows_and_merge_lines(self) -> None:
        text: str = (SKILLS / "ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`Follows:` line", text)
        self.assertIn("merge commit only", text)

    def test_run_router_phrases_are_pinned(self) -> None:
        """P2: the router and its phase files keep the text other files point at."""
        router: str = (SKILLS / "run" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("Follow the phases in order", "## Phase files", "## Companion skills", "## Preflight", "## Guardrails",
                       "subagent_type: dts2-harness:<role>", "Rule 9.2"):
            self.assertIn(phrase, router)
        for name in ("phase-0-size.md", "phase-1-plan.md", "phase-2-build.md", "phase-3-review.md", "phase-4-ship.md",
                     "modes.md", "operations.md"):
            self.assertIn(name, router)
            self.assertTrue((SKILLS / "run" / name).is_file(), name)
        self.assertIn("Isolation (Rule 10)", read_run_skill())

    def test_rule_10_has_seven_rules_and_the_run_skill_keeps_its_two_halves(self) -> None:
        """P2: Rule 10 text in discipline.md, and the copy of it in operations.md, stay in step."""
        discipline: str = (PLUGIN_ROOT / "templates" / "discipline.md").read_text(encoding="utf-8")
        section: str = discipline.split("## Rule 10", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(re.findall(r"^(\d)\. \*\*", section, re.MULTILINE), list("1234567"))
        operations: str = (SKILLS / "run" / "operations.md").read_text(encoding="utf-8")
        for shared in ("git worktree add ../<repo>-dts2-<n> -b dts2/<stamp>/main-b<n> dts2/<stamp>/main", ".harness/wt/<n>/",
                       "dts2/<stamp>/main"):
            self.assertIn(shared, section, shared)
            self.assertIn(shared, operations, shared)

    def test_lead_text_has_sequencing_and_lead_only_file_rules(self) -> None:
        """P3 and P5."""
        lead: str = (AGENTS / "lead.md").read_text(encoding="utf-8")
        self.assertIn("share a hot file", lead)
        self.assertIn("one after another", lead)
        self.assertIn("Lead-only files", lead)
        self.assertIn("tests/test_text_contracts.py", lead)
        self.assertIn("when the repo has a `changelog.d/` folder", lead)
        for name in ("README changelog", "tests/helpers.py", "changelog.d/batch-<n>.md"):
            self.assertIn(name, lead)


class HandoffSkip(unittest.TestCase):
    """Q-9: a Stop that changed nothing leaves the handoff file alone."""

    def run_handoff(self, repo: Path) -> dict[str, object]:
        proc = subprocess.run(["python3", "-I", str(HANDOFF_SCRIPT), str(repo)], capture_output=True, text=True, check=True)
        parsed: dict[str, object] = json.loads(proc.stdout)
        return parsed

    def test_second_run_with_same_state_does_not_rewrite(self) -> None:
        repo: Path = make_handoff_repo()
        first = self.run_handoff(repo)
        target: Path = repo / ".harness" / "handoff" / "latest.md"
        stamp: int = target.stat().st_mtime_ns
        os.utime(target, ns=(stamp - 10**9, stamp - 10**9))
        before: int = target.stat().st_mtime_ns
        second = self.run_handoff(repo)
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(second["reason"], "unchanged")
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_changed_state_is_rewritten(self) -> None:
        repo: Path = make_handoff_repo()
        self.run_handoff(repo)
        with (repo / ".harness" / "state.md").open("a", encoding="utf-8") as handle:
            handle.write("- 2026-10-21 something new happened\n")
        (repo / ".harness" / "runs" / "20261021-090000").mkdir()
        self.assertTrue(self.run_handoff(repo)["written"])


class CiWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.text: str = WORKFLOW.read_text(encoding="utf-8")

    def test_context_tax_runs_in_ci(self) -> None:
        self.assertIn("python3 plugins/dts2-harness/scripts/context-tax.py", self.text)

    def test_plugin_validate_strict_runs_in_ci(self) -> None:
        self.assertIn("claude plugin validate plugins/dts2-harness --strict", self.text)

    def test_cli_is_installed_with_npm_as_the_docs_show(self) -> None:
        self.assertIn("npm install -g @anthropic-ai/claude-code", self.text)


if __name__ == "__main__":
    unittest.main()
