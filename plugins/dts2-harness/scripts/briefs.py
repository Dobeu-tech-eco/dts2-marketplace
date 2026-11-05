#!/usr/bin/env python3
"""Briefs and the cached prompt prefix for sons and the lead (B1, N5, Q-11). Nothing here starts a process.

  son-brief  <manifest> --lane L --epoch N [--max-bundle K] [--out FILE]   the ~4 KB son brief (templates/son-brief.md)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SON_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "son-brief.md"
DISCIPLINE_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "discipline.md"
DEFAULT_MAX_BUNDLE: Final[int] = 5
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{(\w+)\}\}")
NONE_TEXT: Final[str] = "none"


class BriefError(Exception):
    """A brief cannot be built (unknown lane, unreadable template or input)."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BriefError(f"cannot read {path}: {exc}") from exc


def find_lane(manifest: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in manifest.get("lanes", []):
        if lane.get("id") == lane_id:
            return dict(lane)
    raise BriefError(f"unknown lane '{lane_id}'")


def bullets(items: list[str]) -> str:
    return "\n".join(f"- `{i}`" for i in items) if items else f"- {NONE_TEXT}"


def task_lines(lane: dict[str, Any]) -> str:
    tasks: list[Any] = list(lane.get("tasks") or [])
    if not tasks:
        return f"- {lane.get('item', NONE_TEXT)}"
    return "\n".join(f"- {t}" for t in tasks)


def son_values(manifest: dict[str, Any], lane_id: str, epoch: int, max_bundle: int) -> dict[str, str]:
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    stamp: str = str(manifest.get("stamp"))
    files: list[str] = sorted({str(f).replace("\\", "/") for f in lane.get("files", []) if f})
    return {
        "stamp": stamp, "lane": str(lane["id"]), "epoch": str(epoch), "branch": f"dts2/{stamp}/lane-{lane['id']}",
        "base": str(manifest.get("base") or NONE_TEXT), "item": str(lane.get("item") or NONE_TEXT),
        "tier": str(lane.get("tier") or "standard"), "max_bundle": str(max_bundle),
        "depends": ", ".join(str(d) for d in lane.get("depends_on", [])) or NONE_TEXT,
        "files": bullets(files), "tasks": task_lines(lane),
    }


def son_brief(manifest: dict[str, Any], lane_id: str, epoch: int, max_bundle: int = DEFAULT_MAX_BUNDLE) -> str:
    """The son's own brief: the lane facts filled into templates/son-brief.md."""
    values: dict[str, str] = son_values(manifest, lane_id, epoch, max_bundle)
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), read_text(SON_TEMPLATE))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read JSON {path}: {exc}") from exc


def run_main(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "son-brief":
        text: str = son_brief(load_json(Path(args.manifest)), args.lane, args.epoch, args.max_bundle)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return {"ok": True, "bytes": len(text.encode("utf-8")), "out": args.out}
    raise BriefError(f"unknown command {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    son_p = sub.add_parser("son-brief")
    son_p.add_argument("manifest")
    son_p.add_argument("--lane", required=True)
    son_p.add_argument("--epoch", type=int, required=True)
    son_p.add_argument("--max-bundle", type=int, default=DEFAULT_MAX_BUNDLE)
    son_p.add_argument("--out", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_main(args)
    except BriefError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    if args.out or args.command != "son-brief":
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
