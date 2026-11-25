#!/usr/bin/env python3
"""Optional team charter. Maps charter roles onto the seats the harness already uses.

TEAM.md is optional. When it is absent, resolve reports mode "harness" and the
caller keeps /dt:model, lanes and the autopilot vote. A missing file, a probe
that cannot run, or a provider whose CLI, MCP server or other connector does
not answer is a one-line warning and the next listed provider, or the harness
roster. Exit 0 in every one of those cases. This script never starts a provider,
never calls a connector, and never grants a merge, a deploy or a spend.

  resolve     --repo R [--role NAME] [--probe-json F]
  review-cap  --repo R --round N
  brief       [--role R] [--objective T] ...
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miniyaml  # noqa: E402
import roster  # noqa: E402
import state_io  # noqa: E402
from profiles import ADVISORY_ROLES  # noqa: E402

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
BRIEF_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "brief.md"
ROOT_CHARTER: Final[str] = "TEAM.md"
# Where a roster is read from, in order: the harness config (where /dt:setup writes it), then the
# local settings file older setups used. The first file that declares a `roster:` list wins.
LEGACY_ROSTER: Final[str] = ".claude/dts2-harness.local.md"
ROSTER_FILES: Final[tuple[str, ...]] = (state_io.CONFIG_REL, LEGACY_ROSTER)
REVIEW_CAP: Final[int] = 3
APPROVAL: Final[str] = (
    "Merges, deploys and spending need an explicit human approval. This brief does not grant them."
)
HARNESS_NAMES: Final[frozenset[str]] = frozenset({"harness", "none", "default"})
ROLE_ORDER: Final[tuple[str, ...]] = (
    "lead", "builder", "reviewer", "playtester", "copywriter", "dispatcher",
)
ROLE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "lead": ("lead",),
    "planner": ("lead",),
    "lead/planner": ("lead",),
    "builder": ("builder",),
    "builders": ("builder",),
    "reviewer": ("reviewer",),
    "playtester": ("playtester",),
    "reviewer/playtester": ("reviewer", "playtester"),
    "copywriter": ("copywriter",),
    "dispatcher": ("dispatcher",),
}
DEFAULT_SEAT: Final[dict[str, str]] = {
    "lead": "lead",
    "builder": "execution",
    "reviewer": "advisory",
    "playtester": "signoff",
    "copywriter": "advisory",
    "dispatcher": "lead",
}
# Profile roles that may fill a charter seat. Lead matches /dt:model (a lead, a reviewer, or a
# second opinion, and never an API-key agent). Sign-off is the verifier, which the same agents
# are also refused.
SEAT_ROLES: Final[dict[str, frozenset[str]]] = {
    "lead": frozenset({"lead", *ADVISORY_ROLES}),
    "execution": frozenset({"builder"}),
    "advisory": frozenset(ADVISORY_ROLES),
    "signoff": frozenset({"verifier"}),
}
LEAD_BOUND_SEATS: Final[frozenset[str]] = frozenset({"lead", "signoff"})
SEAT_ALIASES: Final[dict[str, str]] = {
    "lead": "lead",
    "planner": "lead",
    "execution": "execution",
    "builder": "execution",
    "advisory": "advisory",
    "reviewer": "advisory",
    "signoff": "signoff",
    "sign-off": "signoff",
    "verifier": "signoff",
    "playtester": "signoff",
}
BRIEF_FIELDS: Final[tuple[str, ...]] = (
    "role", "objective", "context", "scope", "authorized", "prohibited",
    "inputs", "deliverable", "evidence", "deadline", "dependencies",
)
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{(\w+)\}\}")
SEPARATOR: Final[re.Pattern[str]] = re.compile(r"^:?-{3,}:?$")
HEADER_ROLES: Final[frozenset[str]] = frozenset({"role", "roles"})


def charter_rels() -> tuple[str, ...]:
    """Root TEAM.md, then the copy under the harness directory (built in state_io, the one path module)."""
    return (ROOT_CHARTER, state_io.rel(ROOT_CHARTER))


def find_charter(repo: Path) -> Path | None:
    for rel in charter_rels():
        path = repo / rel
        if path.is_file():
            return path
    return None


def split_row(line: str) -> list[str]:
    body = line.strip()
    if not body.startswith("|"):
        return []
    return [cell.strip().strip("`") for cell in body.strip("|").split("|")]


def is_separator(cells: list[str]) -> bool:
    return all(SEPARATOR.match(cell.replace(" ", "")) for cell in cells)


def providers_of(cell: str) -> list[str]:
    names: list[str] = []
    for part in cell.split(","):
        name = part.strip().strip("`").lower()
        if name and name not in names:
            names.append(name)
    return names


def normalize_role(cell: str) -> tuple[str, ...]:
    return ROLE_ALIASES.get(cell.strip().lower(), ())


def seat_for(role: str, cell: str) -> tuple[str, str | None]:
    key = cell.strip().lower().strip("`")
    if not key:
        return DEFAULT_SEAT[role], None
    if key in SEAT_ALIASES:
        return SEAT_ALIASES[key], None
    fallback = DEFAULT_SEAT[role]
    return fallback, (
        f"team charter: {role} seat '{cell.strip()}' is not a harness seat; using {fallback}"
    )


def parse_table(text: str) -> tuple[dict[str, tuple[str, list[str]]], list[str]]:
    """Role to (seat, providers). A combined role fills a seat only when that role has no own row."""
    assigned: dict[str, tuple[str, list[str]]] = {}
    combined: dict[str, tuple[str, list[str]]] = {}
    warnings: list[str] = []
    for line in text.splitlines():
        cells = split_row(line)
        if len(cells) < 3 or is_separator(cells) or cells[0].strip().lower() in HEADER_ROLES:
            continue
        roles = normalize_role(cells[0])
        if not roles:
            warnings.append(
                f"team charter: unknown role '{cells[0].strip()}'; using the harness roster"
            )
            continue
        providers = providers_of(cells[2])
        target = combined if len(roles) > 1 else assigned
        for role in roles:
            seat, warning = seat_for(role, cells[1])
            if warning:
                warnings.append(warning)
            target[role] = (seat, providers)
    for role, value in combined.items():
        assigned.setdefault(role, value)
    return assigned, warnings


def read_charter(repo: Path) -> tuple[Path | None, dict[str, tuple[str, list[str]]], list[str]]:
    path = find_charter(repo)
    if path is None:
        return None, {}, []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path, {}, ["team charter: TEAM.md unreadable; using the harness roster"]
    rows, warnings = parse_table(text)
    if not rows:
        warnings.append("team charter: TEAM.md has no role table; using the harness roster")
    return path, rows, warnings


def known_profiles(repo: Path) -> dict[str, Any]:
    """Bundled and project profiles, with no roster warning on stderr. A load failure leaves none."""
    try:
        return roster.Profiles.load(project=repo).as_dict()
    except Exception:
        return {}


def declared_roster(path: Path) -> list[dict[str, Any]] | None:
    """The roster entries a file declares, or None when it is absent or has no `roster:` list.
    An unreadable file raises, so the caller's warning covers it."""
    if not path.exists():
        return None
    block: Any = miniyaml.parse(path.read_text(encoding="utf-8")).get("roster")
    entries = [entry for entry in map(roster.roster_entry, block) if entry] if isinstance(block, list) else []
    return entries or None


def repo_roster(repo: Path) -> list[dict[str, Any]]:
    """The roster from .harness/config.yaml, else the legacy local settings file, else the default."""
    for name in ROSTER_FILES:
        entries = declared_roster(repo / name)
        if entries:
            return entries
    return [dict(item) for item in roster.DEFAULT_ROSTER]


def repo_budget(repo: Path) -> dict[str, str]:
    """`budget:` statuses, with .harness/config.yaml overriding the legacy local settings file."""
    budget: dict[str, str] = {}
    for name in reversed(ROSTER_FILES):
        budget.update(roster.read_budget(repo / name))
    return budget


def bound_profiles(repo: Path, profiles: dict[str, Any]) -> dict[str, Any]:
    """Profile by the name a charter row uses, including a roster entry whose `profile:` points elsewhere."""
    bound = dict(profiles)
    try:
        entries = repo_roster(repo)
    except Exception:
        return bound
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        backing: Any = profiles.get(entry.get("profile") or entry["name"])
        if isinstance(backing, dict):
            bound[entry["name"]] = backing
    return bound


def agent_facts(
    name: str, probe: dict[str, Any], profiles: dict[str, Any],
) -> tuple[list[str] | None, bool]:
    """(roles, may_lead). Roles stay None when neither the probe nor a profile lists them."""
    roles: list[str] | None = None
    lead: bool | None = None
    agents: Any = probe.get("agents")
    info: Any = agents.get(name) if isinstance(agents, dict) else None
    if isinstance(info, dict):
        listed: Any = info.get("roles")
        if isinstance(listed, list):
            roles = [str(role) for role in listed]
        if isinstance(info.get("leadEligible"), bool):
            lead = info["leadEligible"]
    profile: Any = profiles.get(name)
    if isinstance(profile, dict):
        if roles is None:
            listed = profile.get("roles")
            roles = [str(role) for role in listed] if isinstance(listed, list) else []
        if lead is None and isinstance(profile.get("leadEligible"), bool):
            lead = profile["leadEligible"]
    return roles, lead is not False


def covers(roles: list[str], seat: str) -> bool:
    if seat == "lead":
        return "lead" in roles or any(role in ADVISORY_ROLES for role in roles)
    bases = {roster.base_role(role) for role in roles}
    return bool(bases & SEAT_ROLES[seat])


def seat_eligible(name: str, seat: str, probe: dict[str, Any], profiles: dict[str, Any]) -> bool:
    """A known profile or a probe role list must be allowed to fill the seat. An unknown connector is."""
    roles, may_lead = agent_facts(name, probe, profiles)
    if roles is None:
        return True
    if not covers(roles, seat):
        return False
    return may_lead or seat not in LEAD_BOUND_SEATS


def fallback_warning(role: str, skipped: list[tuple[str, str]], chosen: str | None) -> str:
    tail = f"using {chosen}" if chosen else "using the harness roster"
    if all(reason == "unreachable" for _, reason in skipped):
        names = ", ".join(name for name, _ in skipped)
        return f"team charter: {role} seat {names} unreachable; {tail}"
    parts = [
        f"{name} unreachable" if reason == "unreachable" else f"{name} {reason}"
        for name, reason in skipped
    ]
    return f"team charter: {role} seat {', '.join(parts)}; {tail}"


def provider_available(name: str, probe: dict[str, Any]) -> bool:
    agents: Any = probe.get("agents")
    if isinstance(agents, dict):
        info: Any = agents.get(name)
        if not isinstance(info, dict):
            return False
        return bool(info.get("available"))
    usable: Any = probe.get("usable")
    return isinstance(usable, list) and name in usable


def live_probe(repo: Path) -> dict[str, Any]:
    """Roster probe only. A failure is the caller's warning, not a raised error for the run."""
    profiles = roster.load_profiles(repo)
    entries = [
        entry for entry in repo_roster(repo)
        if (entry.get("profile") or entry["name"]) in profiles
    ]
    if not entries:
        entries = [dict(item) for item in roster.DEFAULT_ROSTER if item["name"] in profiles]
    return roster.probe(entries, profiles, repo_budget(repo), repo)


def load_probe(repo: Path, probe_path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if probe_path is not None:
        try:
            data: Any = json.loads(probe_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "team charter: probe unreadable; using the harness roster"
        if not isinstance(data, dict):
            return None, "team charter: probe unreadable; using the harness roster"
        return data, None
    try:
        return live_probe(repo), None
    except Exception as exc:
        return None, (
            f"team charter: roster probe unreachable ({type(exc).__name__}); using the harness roster"
        )


def assign_role(
    role: str, seat: str, providers: list[str], probe: dict[str, Any] | None,
    profiles: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    named = [name for name in providers if name not in HARNESS_NAMES]
    if not named:
        return {"seat": seat, "agent": None, "source": "harness", "skipped": []}, None
    if probe is None:
        return {"seat": seat, "agent": None, "source": "harness", "skipped": named}, (
            f"team charter: {role} seat {', '.join(named)} unreachable; using the harness roster"
        )
    skipped: list[tuple[str, str]] = []
    for name in named:
        if not provider_available(name, probe):
            skipped.append((name, "unreachable"))
            continue
        if not seat_eligible(name, seat, probe, profiles):
            skipped.append((name, f"cannot fill {seat}"))
            continue
        warning = fallback_warning(role, skipped, name) if skipped else None
        return {
            "seat": seat, "agent": name, "source": "charter",
            "skipped": [item for item, _ in skipped],
        }, warning
    return {"seat": seat, "agent": None, "source": "harness", "skipped": [item for item, _ in skipped]}, (
        fallback_warning(role, skipped, None)
    )


def resolve_charter(
    repo: Path, probe: dict[str, Any] | None, probe_warning: str | None, role: str | None,
) -> dict[str, Any]:
    path, rows, warnings = read_charter(repo)
    if probe_warning and path is not None and rows:
        warnings.append(probe_warning)
    if path is None:
        return {
            "ok": True, "present": False, "mode": "harness", "warnings": [], "roles": {},
        }
    if not rows:
        return {
            "ok": True, "present": True, "mode": "harness", "warnings": warnings, "roles": {},
        }
    wanted = tuple(name for name in ROLE_ORDER if name in rows)
    if role is not None:
        names = normalize_role(role)
        if not names:
            warnings.append(f"team charter: unknown role '{role}'; using the harness roster")
            return {
                "ok": True, "present": True, "mode": "harness", "warnings": warnings, "roles": {},
            }
        wanted = names
    chosen: dict[str, Any] = {}
    profiles = bound_profiles(repo, known_profiles(repo))
    for name in wanted:
        if name not in rows:
            warnings.append(f"team charter: {name} is not in TEAM.md; using the harness roster")
            chosen[name] = {
                "seat": DEFAULT_SEAT[name], "agent": None, "source": "harness", "skipped": [],
            }
            continue
        seat, providers = rows[name]
        record, warning = assign_role(name, seat, providers, probe, profiles)
        if warning and not probe_warning:
            warnings.append(warning)
        chosen[name] = record
    return {
        "ok": True, "present": True, "mode": "charter", "warnings": warnings, "roles": chosen,
    }


def review_status(repo: Path, round_n: int) -> dict[str, Any]:
    path, rows, warnings = read_charter(repo)
    if path is None or not rows:
        return {
            "ok": True, "present": path is not None, "mode": "harness", "cap": None,
            "round": round_n, "escalate": False, "warning": warnings[0] if warnings else None,
            "warnings": warnings,
        }
    escalate = round_n > REVIEW_CAP
    warning = (
        f"team charter: review loop reached {REVIEW_CAP} rounds; escalating to the human"
        if escalate else None
    )
    listed = [warning] if warning else []
    return {
        "ok": True, "present": True, "mode": "charter", "cap": REVIEW_CAP,
        "round": round_n, "escalate": escalate, "warning": warning, "warnings": listed,
    }


def brief_values(raw: dict[str, str]) -> dict[str, str]:
    values = {key: (raw.get(key) or "").strip() or "none" for key in BRIEF_FIELDS}
    return values


def render_brief(raw: dict[str, str]) -> str:
    template = BRIEF_TEMPLATE.read_text(encoding="utf-8")
    values = brief_values(raw)
    return PLACEHOLDER.sub(lambda match: values.get(match.group(1), "none"), template)


def emit(payload: dict[str, Any]) -> int:
    for line in payload.get("warnings") or []:
        print(line, file=sys.stderr)
    lone = payload.get("warning")
    if lone and lone not in (payload.get("warnings") or []):
        print(lone, file=sys.stderr)
    print(json.dumps(payload))
    return 0


def add_brief_args(parser: argparse.ArgumentParser) -> None:
    for name in BRIEF_FIELDS:
        parser.add_argument(f"--{name}", default="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve_p = sub.add_parser("resolve")
    resolve_p.add_argument("--repo", default=".")
    resolve_p.add_argument("--role", default=None)
    resolve_p.add_argument("--probe-json", default=None)
    cap_p = sub.add_parser("review-cap")
    cap_p.add_argument("--repo", default=".")
    cap_p.add_argument("--round", type=int, required=True)
    brief_p = sub.add_parser("brief")
    add_brief_args(brief_p)
    args = parser.parse_args(argv)
    if args.command == "brief":
        raw = {name: getattr(args, name) for name in BRIEF_FIELDS}
        try:
            sys.stdout.write(render_brief(raw))
        except OSError as exc:
            print(f"team charter: brief template unreadable ({type(exc).__name__})", file=sys.stderr)
            return 1
        return 0
    repo = Path(args.repo)
    if args.command == "review-cap":
        return emit(review_status(repo, args.round))
    probe_path = Path(args.probe_json) if args.probe_json else None
    path, rows, _warnings = read_charter(repo)
    probe: dict[str, Any] | None = None
    probe_warning: str | None = None
    if path is not None and rows:
        probe, probe_warning = load_probe(repo, probe_path)
    return emit(resolve_charter(repo, probe, probe_warning, args.role))


if __name__ == "__main__":
    sys.exit(main())
