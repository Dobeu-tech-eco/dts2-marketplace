"""Per-agent rules (batch D): what an agent may be called for, and what it has spent today.

Rules live in a roster entry's `rules:` block in `.harness/config.yaml`. This module holds the pure parts: the schema, the
validator, the effective rules (defaults for a non-subscription agent, forced denies), the permission check, a one-line
summary, and the spend ledger (`.harness/spend.jsonl`, one JSON row per run). `roster.py`, `delegate.py` and
`policy_gate.py` enforce them; nothing here starts a process."""
from __future__ import annotations

import fnmatch
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import state_io  # noqa: E402

AGENT_VAR: Final[str] = "DTS2_AGENT"
AUTH_SUBSCRIPTION: Final[str] = "subscription"
TASK_CLASSES: Final[tuple[str, ...]] = (
    "review", "build", "test", "docs", "research", "deploy", "merge", "release", "secrets", "delete", "infra",
)
FORCED_DENY: Final[tuple[str, ...]] = ("deploy", "merge", "release", "secrets", "delete")
TIERS: Final[tuple[str, ...]] = ("economy", "standard", "frontier")
LIST_KEYS: Final[tuple[str, ...]] = ("allow_tasks", "deny_tasks", "paths_deny")
BOOL_KEYS: Final[tuple[str, ...]] = ("no_secrets", "read_only")
COST_KEYS: Final[tuple[str, ...]] = ("max_cost_usd_per_run", "max_cost_usd_per_day")
KEYS: Final[tuple[str, ...]] = (*LIST_KEYS, "max_tier", *BOOL_KEYS, *COST_KEYS)
DEFAULTS: Final[dict[str, Any]] = {
    "read_only": True, "allow_tasks": ["review", "docs", "research"], "max_tier": "standard",
    "max_cost_usd_per_run": 0.5, "max_cost_usd_per_day": 5.0,
}
TRUE_WORDS: Final[frozenset[str]] = frozenset({"true", "yes", "on"})
FALSE_WORDS: Final[frozenset[str]] = frozenset({"false", "no", "off"})
ROSTER_BLOCK: Final[str] = "roster"
NO_VALUE: Final[str] = "-"
SPEND_REL: Final[str] = state_io.SPEND_REL


def split_list(text: str) -> list[str]:
    return [part.strip() for part in text.strip().strip("[]").split(",") if part.strip()]


def coerce_value(key: str, value: Any) -> Any:
    """A config scalar (miniyaml gives strings) as the type its key wants; a value that does not convert is kept as it was, so
    `validate` can name it."""
    if key in LIST_KEYS and isinstance(value, str):
        return split_list(value)
    if key in BOOL_KEYS and isinstance(value, str):
        word: str = value.strip().lower()
        return True if word in TRUE_WORDS else False if word in FALSE_WORDS else value
    if key in COST_KEYS and isinstance(value, str):
        try:
            number: float = float(value)
        except ValueError:
            return value
        return number if math.isfinite(number) else value
    return value.strip() if key == "max_tier" and isinstance(value, str) else value


def coerce_rules(raw: Any) -> dict[str, Any]:
    """The `rules:` mapping of a roster entry with lists, bools and numbers typed. Not a mapping: `{}`."""
    return {str(key): coerce_value(str(key), value) for key, value in raw.items()} if isinstance(raw, dict) else {}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def list_problems(key: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return [f"{key} must be a list of names"]
    if key == "paths_deny":
        return [f"paths_deny entry '{item}' holds a comma, which the config reader cannot keep" for item in value if "," in item]
    return [f"unknown task class '{item}' in {key} (known: {', '.join(TASK_CLASSES)})" for item in value if item not in TASK_CLASSES]


def key_problems(key: str, value: Any) -> list[str]:
    if key in LIST_KEYS:
        return list_problems(key, value)
    if key == "max_tier":
        return [] if value in TIERS else [f"max_tier '{value}' is not one of {', '.join(TIERS)}"]
    if key in BOOL_KEYS:
        return [] if isinstance(value, bool) else [f"{key} must be true or false"]
    if key in COST_KEYS:
        return [] if is_number(value) and value >= 0 else [f"{key} must be a number of dollars, 0 or more"]
    return [f"unknown key '{key}' (allowed: {', '.join(KEYS)})"]


def validate(rules: Any) -> list[str]:
    """Errors in a `rules:` block: unknown keys or classes, a class in both allow and deny, a bad tier, a negative cost."""
    if not isinstance(rules, dict):
        return ["rules must be a mapping of key to value"]
    errors: list[str] = [problem for key, value in rules.items() for problem in key_problems(str(key), value)]
    both: list[str] = [c for c in rules.get("allow_tasks") or [] if isinstance(rules.get("deny_tasks"), list) and c in rules["deny_tasks"]]
    errors += [f"task class '{c}' is in both allow_tasks and deny_tasks" for c in dict.fromkeys(both) if isinstance(c, str)]
    return errors


def names_of(value: Any, default: Iterable[str] = ()) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else list(default)


def effective_rules_with_warnings(entry: dict[str, Any] | None, auth: str | None) -> tuple[dict[str, Any], list[str]]:
    """(rules in force, warnings) for a roster entry. A subscription agent keeps exactly what it wrote (nothing: no
    restriction). Any other agent gets the defaults under whatever it wrote, and deploy, merge, release, secrets and delete are
    always denied, even when the user allows them (a warning says so)."""
    written: dict[str, Any] = coerce_rules((entry or {}).get("rules"))
    if (auth or AUTH_SUBSCRIPTION) == AUTH_SUBSCRIPTION:
        return written, []
    merged: dict[str, Any] = {**{k: list(v) if isinstance(v, list) else v for k, v in DEFAULTS.items()}, **written}
    name: str = str((entry or {}).get("name") or "agent")
    allow: list[str] = names_of(merged.get("allow_tasks"), DEFAULTS["allow_tasks"])
    overridden: list[str] = [c for c in allow if c in FORCED_DENY]
    merged["allow_tasks"] = [c for c in allow if c not in FORCED_DENY]
    merged["deny_tasks"] = list(dict.fromkeys([*names_of(merged.get("deny_tasks")), *FORCED_DENY]))
    warnings: list[str] = [f"{name}: {', '.join(overridden)} stay denied for a non-subscription agent, whatever allow_tasks says"] if overridden else []
    return merged, warnings


def effective_rules(entry: dict[str, Any] | None, auth: str | None) -> dict[str, Any]:
    return effective_rules_with_warnings(entry, auth)[0]


def tier_rank(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else -1


def path_denied(path: str, globs: Iterable[str]) -> str | None:
    """The first `paths_deny` glob that `path` matches (a leading `./` is ignored; `**/x` also matches a top-level `x`)."""
    clean: str = path[2:] if path.startswith("./") else path
    for glob in globs:
        if any(fnmatch.fnmatchcase(candidate, glob) for candidate in (clean, f"/{clean}")):
            return glob
    return None


def permits(rules: dict[str, Any] | None, task_class: str | None = None, tier: str | None = None,
            paths: Iterable[str] = ()) -> tuple[bool, str]:
    """(allowed, reason) for one task class, model tier and set of paths under these effective rules. No rules: allowed."""
    if not rules:
        return True, "ok"
    if task_class and task_class in names_of(rules.get("deny_tasks")):
        return False, f"task '{task_class}' is denied by this agent's rules"
    if task_class == "secrets" and rules.get("no_secrets") is True:
        return False, "task 'secrets' is denied because this agent has no_secrets set"
    if task_class and isinstance(rules.get("allow_tasks"), list) and task_class not in rules["allow_tasks"]:
        return False, f"task '{task_class}' is not in this agent's allow_tasks"
    cap: Any = rules.get("max_tier")
    if tier and cap in TIERS and tier_rank(tier) > tier_rank(cap):
        return False, f"tier '{tier}' is above this agent's max_tier '{cap}'"
    for path in paths:
        hit: str | None = path_denied(path, names_of(rules.get("paths_deny")))
        if hit:
            return False, f"path '{path}' matches paths_deny '{hit}'"
    return True, "ok"


def number_text(value: Any) -> str:
    return f"{value:g}" if is_number(value) else str(value)


def summary(rules: dict[str, Any] | None) -> str:
    """One short line for `roster list`, such as `ro review,docs,research ≤standard $0.5/$5`; `-` for no restriction."""
    if not rules:
        return NO_VALUE
    parts: list[str] = ["ro"] if rules.get("read_only") is True else []
    if isinstance(rules.get("allow_tasks"), list):
        parts.append(",".join(rules["allow_tasks"]) or "no-tasks")
    explicit: list[str] = [c for c in names_of(rules.get("deny_tasks")) if c not in FORCED_DENY]
    parts += [f"!{','.join(explicit)}"] if explicit else []
    parts += [f"≤{rules['max_tier']}"] if rules.get("max_tier") else []
    parts += ["no-secrets"] if rules.get("no_secrets") is True else []
    if "max_cost_usd_per_run" in rules or "max_cost_usd_per_day" in rules:
        parts.append(f"${number_text(rules.get('max_cost_usd_per_run', NO_VALUE))}/${number_text(rules.get('max_cost_usd_per_day', NO_VALUE))}")
    return " ".join(parts) or NO_VALUE


def entry_for(name: str, config: Path) -> dict[str, Any] | None:
    """The roster entry called `name` in a config file, reduced to name, auth and typed rules; None when absent or unreadable."""
    try:
        block: Any = miniyaml.parse(config.read_text(encoding="utf-8")).get(ROSTER_BLOCK)
    except OSError:
        return None
    for item in block if isinstance(block, list) else []:
        if isinstance(item, dict) and item.get("name") == name:
            return {"name": name, "auth": item.get("auth") if isinstance(item.get("auth"), str) else None,
                    "rules": coerce_rules(item.get("rules"))}
    return None


def config_problems(config: Path) -> list[str]:
    """Every `rules:` error in a config file's roster, as `roster agent 'x': <error>`; empty when it is clean or unreadable."""
    try:
        block: Any = miniyaml.parse(config.read_text(encoding="utf-8")).get(ROSTER_BLOCK)
    except OSError:
        return []
    problems: list[str] = []
    for item in block if isinstance(block, list) else []:
        if isinstance(item, dict) and "rules" in item:
            errors: list[str] = validate(coerce_rules(item["rules"])) if isinstance(item["rules"], dict) else ["rules must be a mapping of key to value"]
            problems += [f"roster agent '{item.get('name')}': {error}" for error in errors]
    return problems


def agent_rules(name: str, config: Path, profile_auth: str | None = None) -> dict[str, Any]:
    """The effective rules of the roster agent `name` (no restriction when it is not in the roster)."""
    entry: dict[str, Any] | None = entry_for(name, config)
    if entry is None:
        return {}
    return effective_rules(entry, entry.get("auth") or profile_auth)


def spend_path(root: Path | str | None = None) -> Path:
    return Path(root or ".").joinpath(*SPEND_REL.split("/"))


def record_spend(agent: str, usd: float | None, run_id: str = "", root: Path | str | None = None,
                 today: date | None = None) -> bool:
    """Append one spend row (agent, dollars, run id, local date). A missing, zero, negative or non-finite cost writes nothing."""
    if not agent or not is_number(usd) or float(usd) <= 0:  # type: ignore[arg-type]
        return False
    row: dict[str, Any] = {"date": (today or date.today()).isoformat(), "agent": agent, "usd": float(usd), "run": run_id}  # type: ignore[arg-type]
    state_io.append_text(spend_path(root), json.dumps(row, sort_keys=True) + "\n")
    return True


def read_spend(root: Path | str | None = None) -> list[dict[str, Any]]:
    try:
        text: str = spend_path(root).read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("agent"), str) and is_number(row.get("usd")):
            rows.append(row)
    return rows


def spent_today(agent: str, root: Path | str | None = None, today: date | None = None) -> float:
    """Dollars the ledger holds for `agent` on the local date `today` (default: now)."""
    stamp: str = (today or date.today()).isoformat()
    return round(sum(float(r["usd"]) for r in read_spend(root) if r["agent"] == agent and r.get("date") == stamp), 6)


def day_exhausted(agent: str, rules: dict[str, Any] | None, root: Path | str | None = None, today: date | None = None) -> bool:
    """True when the agent has a daily cap and today's spend has reached or passed it."""
    cap: Any = (rules or {}).get("max_cost_usd_per_day")
    return is_number(cap) and spent_today(agent, root, today) >= float(cap)


def agent_of(env: dict[str, str] | None = None, argv: Iterable[str] = ()) -> str | None:
    """The agent a launch belongs to: `DTS2_AGENT` in the child env, else a `DTS2_AGENT=<name>` word in its argv."""
    named: str | None = (env or {}).get(AGENT_VAR)
    if named:
        return named
    prefix: str = f"{AGENT_VAR}="
    return next((word[len(prefix):] for word in argv if word.startswith(prefix) and len(word) > len(prefix)), None)
