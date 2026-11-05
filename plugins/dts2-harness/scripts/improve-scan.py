#!/usr/bin/env python3
"""Read-only audit of every improvement option for a repo: facts, inventory and ranked recommendations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

SKIP_DIRS: Final[frozenset[str]] = frozenset({".git", "node_modules", "dist", "build", ".venv"})
SOURCE_SUFFIXES: Final[frozenset[str]] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".php", ".c", ".cpp", ".cs", ".swift", ".kt",
})
TEST_DIRS: Final[frozenset[str]] = frozenset({"tests", "test", "__tests__"})
FRONTEND_DEPS: Final[tuple[str, ...]] = ("react", "vue", "svelte", "next", "nuxt", "astro", "@angular/core")
MARKETING_PARENTS: Final[frozenset[str]] = frozenset({"src", "app", "pages"})
BROAD_ALLOW: Final[frozenset[str]] = frozenset({
    "Bash", "Bash(*)", "Bash(rm:*)", "Bash(rm *)", "Bash(sudo:*)", "Bash(git push:*)",
})
LARGE_FILES: Final[int] = 2000
BROWNFIELD_FILES: Final[int] = 20
CATEGORIES: Final[tuple[str, ...]] = (
    "skills", "database", "hooks", "mcp", "plugins", "commands", "subagents", "permissions", "ci", "docs",
)
# dependency name -> (engines, orms) it implies; matched against package.json deps and python dependency text.
DB_DEPS: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "prisma": ((), ("prisma",)), "@prisma/client": ((), ("prisma",)),
    "drizzle-orm": ((), ("drizzle",)), "@supabase/supabase-js": (("postgres",), ("supabase",)),
    "pg": (("postgres",), ()), "postgres": (("postgres",), ()),
    "@neondatabase/serverless": (("postgres",), ()), "better-sqlite3": (("sqlite",), ()),
    "kysely": ((), ("kysely",)), "typeorm": ((), ("typeorm",)), "sequelize": ((), ("sequelize",)),
    "mongoose": (("mongodb",), ()), "sqlalchemy": ((), ("sqlalchemy",)), "psycopg": (("postgres",), ()),
    "alembic": ((), ("alembic",)), "django": ((), ("django",)),
}
PY_DB_DEPS: Final[tuple[str, ...]] = ("sqlalchemy", "psycopg", "alembic", "django")
PY_DEP_FILES: Final[tuple[str, ...]] = ("pyproject.toml", "requirements.txt")
MIGRATION_DIRS: Final[tuple[str, ...]] = ("migrations", "prisma/migrations", "supabase/migrations", "drizzle")
DB_DENY: Final[str] = "Bash(*prisma migrate reset*), Bash(*supabase db reset*), Bash(*DROP TABLE*)"
TOKEN_NOTE: Final[str] = "put tokens in environment variables, never in args or files"
HOOKS_SETUP: Final[str] = 'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hooks-setup.py" recommend'

Rec = dict[str, Any]


def read_json(path: Path, bad: list[str]) -> dict[str, Any]:
    """Return the JSON object in path; a missing file is empty, an invalid one is empty and noted in bad."""
    if not path.is_file():
        return {}
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bad.append(path.name)
        return {}
    if not isinstance(data, dict):
        bad.append(path.name)
        return {}
    return data


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def walk(root: Path) -> tuple[int, int, bool, bool]:
    """Cheap walk: (file count, source file count, has tests, has marketing)."""
    files = sources = 0
    has_tests = has_marketing = False
    stack: list[Path] = [root]
    while stack:
        current: Path = stack.pop()
        try:
            entries: list[Path] = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            name: str = entry.name
            if entry.is_dir() and not entry.is_symlink():
                if name in SKIP_DIRS:
                    continue
                if name in TEST_DIRS:
                    has_tests = True
                if name.lower() in ("pricing", "landing") and current.name in MARKETING_PARENTS:
                    has_marketing = True
                stack.append(entry)
            elif entry.is_file():
                files += 1
                if entry.suffix in SOURCE_SUFFIXES:
                    sources += 1
                lowered: str = name.lower()
                if "test" in lowered:
                    has_tests = True
                if current.name in MARKETING_PARENTS and lowered.split(".")[0] in ("pricing", "landing"):
                    has_marketing = True
    return files, sources, has_tests, has_marketing


def package_deps(package: dict[str, Any]) -> set[str]:
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section: Any = package.get(key)
        if isinstance(section, dict):
            deps.update(str(name) for name in section)
    return deps


def count_hooks(settings: dict[str, Any]) -> int:
    hooks: Any = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    total = 0
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            inner: Any = group.get("hooks") if isinstance(group, dict) else None
            total += len(inner) if isinstance(inner, list) else 1
    return total


def permission_list(settings: dict[str, Any], key: str) -> list[str]:
    permissions: Any = settings.get("permissions")
    values: Any = permissions.get(key) if isinstance(permissions, dict) else None
    return [str(item) for item in values] if isinstance(values, list) else []


def enabled_plugins(settings: dict[str, Any]) -> list[str]:
    plugins: Any = settings.get("enabledPlugins")
    if isinstance(plugins, dict):
        return sorted(str(name) for name, on in plugins.items() if on)
    if isinstance(plugins, list):
        return sorted(str(name) for name in plugins)
    return []


def server_names(data: dict[str, Any]) -> list[str]:
    servers: Any = data.get("mcpServers")
    return [str(name) for name in servers] if isinstance(servers, dict) else []


def stems(directory: Path, patterns: tuple[str, ...]) -> list[str]:
    found: set[str] = set()
    for pattern in patterns:
        found.update(path.name for path in directory.glob(pattern) if path.is_file())
    return sorted(found)


def db_signals(cwd: Path, deps: set[str]) -> dict[str, Any]:
    """Detect database engines, ORMs and migration directories from files and dependencies."""
    names: set[str] = {dep.lower() for dep in deps}
    python_text: str = " ".join(read_text(cwd / name).lower() for name in PY_DEP_FILES)
    for dep in PY_DB_DEPS:
        if dep in python_text:
            names.add(dep)
    engines: set[str] = set()
    orms: set[str] = set()
    for dep, (dep_engines, dep_orms) in DB_DEPS.items():
        if dep in names:
            engines.update(dep_engines)
            orms.update(dep_orms)
    if (cwd / "prisma" / "schema.prisma").is_file():
        orms.add("prisma")
    if (cwd / "supabase").is_dir():
        orms.add("supabase")
        engines.add("postgres")
    if any(cwd.glob("drizzle.config.*")):
        orms.add("drizzle")
    if any(cwd.glob("knexfile.*")):
        orms.add("knex")
    if (cwd / "alembic.ini").is_file():
        orms.add("alembic")
    if "neondatabase" in " ".join(names) or "@neondatabase/serverless" in names:
        orms.add("neon")
    dirs: list[str] = [name for name in MIGRATION_DIRS if (cwd / name).is_dir()]
    if (cwd / "alembic.ini").is_file():
        dirs.append("alembic")
    return {"engines": sorted(engines), "orms": sorted(orms), "migrations_dirs": sorted(set(dirs))}


def scan_state(cwd: Path, home: Path) -> dict[str, Any]:
    """Collect everything the rules need. Never writes."""
    bad: list[str] = []
    claude: Path = cwd / ".claude"
    project = read_json(claude / "settings.json", bad)
    local = read_json(claude / "settings.local.json", bad)
    user = read_json(home / ".claude" / "settings.json", bad)
    mcp_file = read_json(cwd / ".mcp.json", bad)
    home_json = read_json(home / ".claude.json", bad)
    package = read_json(cwd / "package.json", bad)
    files, sources, has_tests, has_marketing = walk(cwd)
    git_config: str = read_text(cwd / ".git" / "config")
    workflows: list[str] = stems(cwd / ".github" / "workflows", ("*.yml", "*.yaml"))
    workflow_text: str = " ".join(read_text(cwd / ".github" / "workflows" / name) for name in workflows)
    deps: set[str] = package_deps(package)
    scripts: Any = package.get("scripts")
    github_dir: Path = cwd / ".github"
    pr_templates: list[Path] = [
        entry for entry in (list(github_dir.iterdir()) if github_dir.is_dir() else [])
        if entry.name.lower().startswith("pull_request_template")
    ]
    has_manifest: bool = any((cwd / name).is_file() for name in ("package.json", "pyproject.toml", "go.mod", "Cargo.toml"))
    return {
        "bad": sorted(set(bad)), "project": project, "local": local, "user": user,
        "mcp": sorted(set(server_names(mcp_file) + server_names(home_json))),
        "deps": deps, "script_count": len(scripts) if isinstance(scripts, dict) else 0,
        "files": files, "sources": sources, "has_tests": has_tests, "has_marketing": has_marketing,
        "has_git": (cwd / ".git").exists(), "github_remote": "github.com" in git_config,
        "has_github_dir": github_dir.is_dir(), "workflows": workflows,
        "workflow_text": workflow_text.lower(), "pr_template": bool(pr_templates),
        "dependabot": (github_dir / "dependabot.yml").is_file() or (github_dir / "dependabot.yaml").is_file()
        or (cwd / "renovate.json").is_file(),
        "commands": [Path(name).stem for name in stems(claude / "commands", ("*.md",))],
        "agents": [Path(name).stem for name in stems(claude / "agents", ("*.md",))],
        "has_agent_docs": (cwd / "CLAUDE.md").is_file() or (cwd / "AGENTS.md").is_file(),
        "db": db_signals(cwd, deps), "has_manifest": has_manifest, "has_makefile": (cwd / "Makefile").is_file(),
        "supabase": (cwd / "supabase").is_dir() or "@supabase/supabase-js" in deps,
        "vercel": (cwd / "vercel.json").is_file(),
        "prisma": "prisma" in deps or "@prisma/client" in deps or (cwd / "prisma" / "schema.prisma").is_file(),
    }


def build_facts(state: dict[str, Any]) -> dict[str, bool]:
    db: dict[str, Any] = state["db"]
    return {
        "is_brownfield": bool(state["has_git"] or state["sources"] > BROWNFIELD_FILES),
        "is_large": state["files"] > LARGE_FILES,
        "has_tests": bool(state["has_tests"]),
        "has_frontend": any(dep in state["deps"] for dep in FRONTEND_DEPS),
        "has_pr": bool(state["has_github_dir"] or state["github_remote"]),
        "has_ci": bool(state["workflows"]),
        "has_marketing": bool(state["has_marketing"]),
        "has_agent_docs": bool(state["has_agent_docs"]),
        "has_database": bool(db["engines"] or db["orms"] or db["migrations_dirs"]),
        "has_prisma": "prisma" in db["orms"],
        "has_supabase": "supabase" in db["orms"],
        "has_drizzle": "drizzle" in db["orms"],
        "has_postgres": "postgres" in db["engines"],
        "has_sqlite": "sqlite" in db["engines"],
    }


def build_inventory(state: dict[str, Any]) -> dict[str, Any]:
    allow: list[str] = []
    deny: list[str] = []
    for name in ("project", "local", "user"):
        allow += permission_list(state[name], "allow")
        deny += permission_list(state[name], "deny")
    return {
        "hooks": {name: count_hooks(state[name]) for name in ("project", "local", "user")},
        "mcp_servers": state["mcp"],
        "plugins": sorted(set(enabled_plugins(state["project"]) + enabled_plugins(state["local"]) + enabled_plugins(state["user"]))),
        "commands": state["commands"], "agents": state["agents"],
        "allow": len(allow), "deny": len(deny), "ci_workflows": state["workflows"],
        "database": state["db"],
    }


def rec(category: str, ident: str, title: str, why: str, how: str, priority: int) -> Rec:
    return {"category": category, "id": ident, "title": title, "why": why, "how": how, "priority": priority}


def mcp_how(name: str, command: str) -> str:
    return f"claude mcp add --scope project {name} {command} ({TOKEN_NOTE})"


def broken_json_recs(state: dict[str, Any]) -> list[Rec]:
    category_of: dict[str, str] = {
        "settings.json": "permissions", "settings.local.json": "permissions", ".mcp.json": "mcp",
        ".claude.json": "mcp", "package.json": "docs",
    }
    recs: list[Rec] = []
    for name in state["bad"]:
        stem: str = Path(name).stem.lstrip(".")
        recs.append(rec(
            category_of.get(name, "docs"), f"fix-{stem}-json", f"Fix invalid JSON in {name}",
            f"{name} does not parse, so its settings are ignored.", f"Open {name} and repair the JSON syntax.", 1,
        ))
    return recs


def hook_recs(state: dict[str, Any], inventory: dict[str, Any]) -> list[Rec]:
    if inventory["hooks"]["project"] + inventory["hooks"]["local"] > 0:
        return []
    return [rec("hooks", "add-recommended-hooks", "Add recommended hooks",
                "No project or local hooks are set, so nothing runs automatically on tool calls.", HOOKS_SETUP, 1)]


def mcp_recs(state: dict[str, Any], facts: dict[str, bool]) -> list[Rec]:
    names: list[str] = [name.lower() for name in state["mcp"]]

    def missing(word: str) -> bool:
        return not any(word in name for name in names)

    recs: list[Rec] = []
    if state["github_remote"] and missing("github"):
        recs.append(rec("mcp", "mcp-github", "Add the GitHub MCP server", "The repo has a GitHub remote.",
                        mcp_how("github", "--transport http https://api.githubcopilot.com/mcp/"), 2))
    if facts["has_frontend"] and missing("playwright"):
        recs.append(rec("mcp", "mcp-playwright", "Add the Playwright MCP server", "Frontend code can be checked in a real browser.",
                        mcp_how("playwright", "-- npx @playwright/mcp@latest"), 2))
    if state["vercel"] and missing("vercel"):
        recs.append(rec("mcp", "mcp-vercel", "Add the Vercel MCP server", "vercel.json is present.",
                        mcp_how("vercel", "--transport http https://mcp.vercel.com"), 3))
    pyproject_or_package: bool = state["has_manifest"]
    if pyproject_or_package and missing("context7"):
        recs.append(rec("mcp", "mcp-context7", "Add the Context7 MCP server", "Current library docs help when code depends on packages.",
                        mcp_how("context7", "-- npx -y @upstash/context7-mcp"), 3))
    return recs


def database_recs(state: dict[str, Any], facts: dict[str, bool], inventory: dict[str, Any]) -> list[Rec]:
    """Featured database tooling; empty when the repo shows no database use."""
    if not facts["has_database"]:
        return []
    names: list[str] = [name.lower() for name in state["mcp"]]
    db: dict[str, Any] = state["db"]
    hook_text: str = json.dumps([state["project"].get("hooks"), state["local"].get("hooks")])
    deny: list[str] = []
    for name in ("project", "local", "user"):
        deny += permission_list(state[name], "deny")
    read_only: str = "read-only database role recommended; credentials from env vars"
    recs: list[Rec] = []
    if "db-guard" not in hook_text:
        recs.append(rec("database", "db-guard-hook", "Add database guard hooks",
                        "Blocks destructive SQL and checks migrations before they run.",
                        'python3 "$CLAUDE_PLUGIN_ROOT/scripts/hooks-setup.py" apply --ids db-guard,migration-check --dry-run, then apply after the user confirms', 2))
    if facts["has_supabase"] and not any("supabase" in name for name in names):
        recs.append(rec("database", "mcp-supabase", "Add the Supabase MCP server", "The repo uses Supabase.",
                        mcp_how("supabase", "--transport http https://mcp.supabase.com/mcp?read_only=true") + f"; {read_only}", 2))
    if facts["has_postgres"] and not facts["has_supabase"] and not any("postgres" in name or "neon" in name for name in names):
        recs.append(rec("database", "mcp-postgres", "Add a Postgres MCP server", "The repo uses Postgres.",
                        mcp_how("postgres", "-- npx -y @modelcontextprotocol/server-postgres \"$DATABASE_URL\"") + f"; {read_only}", 2))
    if "neon" in db["orms"] and not any("neon" in name for name in names):
        recs.append(rec("database", "mcp-neon", "Add the Neon MCP server", "The repo uses Neon.",
                        mcp_how("neon", "--transport http https://mcp.neon.tech/mcp") + f"; {read_only}", 3))
    if facts["has_prisma"] and not any("prisma" in name for name in names):
        recs.append(rec("database", "mcp-prisma", "Add the Prisma MCP server", "The repo uses Prisma.",
                        mcp_how("prisma", "-- npx prisma mcp") + f"; {read_only}", 3))
    if not any("reset" in item.lower() or "drop" in item.lower() for item in deny):
        recs.append(rec("database", "db-deny-destructive", "Deny destructive database commands",
                        "Resets and DROP statements can erase data in one command.",
                        f"Append to permissions.deny in .claude/settings.json: {DB_DENY}", 2))
    if (db["migrations_dirs"] or facts["has_prisma"] or facts["has_supabase"]) and "migrat" not in state["workflow_text"] \
            and "db lint" not in state["workflow_text"]:
        recs.append(rec("database", "db-migration-ci", "Check migrations in CI",
                        "CI does not check that migrations match the schema.",
                        "Add a CI step on a branch, such as prisma migrate diff --exit-code or supabase db lint, and open a PR.", 2))
    recs.append(rec("database", "db-skills", "Add database skills",
                    "Postgres, schema design, SQL optimization and migration skills fit this repo.",
                    f"python3 -I \"${{CLAUDE_PLUGIN_ROOT}}/scripts/skill-suggest.py\" --facts '{json.dumps(facts, sort_keys=True)}'", 2))
    return recs


def simple_recs(state: dict[str, Any], facts: dict[str, bool], inventory: dict[str, Any]) -> list[Rec]:
    recs: list[Rec] = []
    if not enabled_plugins(state["project"]) and enabled_plugins(state["user"]):
        recs.append(rec("plugins", "pin-plugins-in-project", "Pin plugins in the project settings",
                        "Plugins are enabled only at user level, so teammates do not get them.",
                        "Copy the wanted ids into enabledPlugins in .claude/settings.json.", 3))
    if not state["commands"] and (state["script_count"] >= 3 or state["has_makefile"]):
        recs.append(rec("commands", "wrap-scripts-as-commands", "Wrap common scripts as slash commands",
                        "The repo has build scripts that a short command could run.",
                        "Write a short file under .claude/commands for each script you run often.", 3))
    if not state["agents"] and facts["has_tests"]:
        recs.append(rec("subagents", "add-test-runner-agent", "Add a test-runner subagent",
                        "The repo has tests; a subagent keeps test output out of the main chat (dts2:verifier already exists).",
                        "Write a short file under .claude/agents that runs the test command and reports failures.", 3))
    if not state["has_agent_docs"]:
        recs.append(rec("docs", "add-agent-docs", "Add CLAUDE.md or AGENTS.md",
                        "No agent docs, so each session relearns the repo.", "Run /init.", 2))
    return recs


def permission_recs(state: dict[str, Any], inventory: dict[str, Any]) -> list[Rec]:
    allow: list[str] = []
    for name in ("project", "local", "user"):
        allow += permission_list(state[name], "allow")
    recs: list[Rec] = []
    if inventory["allow"] == 0:
        recs.append(rec("permissions", "allowlist-read-only", "Allow read-only commands",
                        "An empty allow list means a prompt for every command.",
                        "Run the fewer-permission-prompts skill, or append read-only Bash patterns plus the detected test and lint commands to permissions.allow.", 2))
    if any(item.strip() in BROAD_ALLOW for item in allow):
        recs.append(rec("permissions", "remove-broad-allow", "Remove a broad allow entry",
                        "An allow entry such as Bash(*), rm, sudo or git push removes the safety prompt for risky commands.",
                        "Delete that entry from permissions.allow in the settings file.", 1))
    if inventory["deny"] == 0:
        recs.append(rec("permissions", "deny-secrets-read", "Deny reading secret files",
                        "No deny rules, so .env files can be read.", "Add Read(./.env*) to permissions.deny in .claude/settings.json.", 3))
    return recs


def ci_recs(state: dict[str, Any]) -> list[Rec]:
    recs: list[Rec] = []
    if not state["workflows"]:
        recs.append(rec("ci", "add-ci", "Add a CI workflow", "No workflow files, so nothing checks changes before merge.",
                        "Copy the plugin templates/ci.yml to .github/workflows/ci.yml on a branch and open a PR.", 1))
    elif "test" not in state["workflow_text"]:
        recs.append(rec("ci", "ci-run-tests", "Run tests in CI", "Workflows exist but none mentions tests.",
                        "Add a test step to a workflow on a branch and open a PR.", 2))
    if not state["dependabot"]:
        recs.append(rec("ci", "add-dependabot", "Add dependency updates", "No dependabot.yml or renovate.json.",
                        "Copy the plugin templates/dependabot.yml to .github/dependabot.yml on a branch and open a PR.", 3))
    if not state["pr_template"]:
        recs.append(rec("ci", "add-pr-template", "Add a pull request template", "No pull request template.",
                        "Copy the plugin templates/pr-template.md to .github/pull_request_template.md on a branch and open a PR.", 3))
    return recs


def skills_rec(facts: dict[str, bool]) -> Rec:
    facts_json: str = json.dumps(facts, sort_keys=True)
    return rec("skills", "suggest-skills", "Add suggested skills", "Skills matched to this repo speed up common work.",
               f"python3 -I \"${{CLAUDE_PLUGIN_ROOT}}/scripts/skill-suggest.py\" --facts '{facts_json}'", 2)


def recommend(state: dict[str, Any], facts: dict[str, bool], inventory: dict[str, Any]) -> list[Rec]:
    recs: list[Rec] = [skills_rec(facts)]
    recs += broken_json_recs(state) + hook_recs(state, inventory) + mcp_recs(state, facts)
    recs += database_recs(state, facts, inventory)
    recs += simple_recs(state, facts, inventory) + permission_recs(state, inventory) + ci_recs(state)
    order: dict[str, int] = {name: index for index, name in enumerate(CATEGORIES)}
    return sorted(recs, key=lambda item: (item["priority"], order[item["category"]], item["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=".", help="repo directory to audit")
    parser.add_argument("--home", default=None, help="home directory holding user-level Claude settings")
    args = parser.parse_args()
    cwd: Path = Path(args.cwd)
    home: Path = Path(args.home) if args.home else Path.home()
    state: dict[str, Any] = scan_state(cwd, home)
    facts: dict[str, bool] = build_facts(state)
    inventory: dict[str, Any] = build_inventory(state)
    print(json.dumps({"facts": facts, "inventory": inventory, "recommendations": recommend(state, facts, inventory)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
