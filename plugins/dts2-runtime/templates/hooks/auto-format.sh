#!/usr/bin/env bash
# dts2 optional hook: PostToolUse (Edit|Write|MultiEdit). Formats the edited file with the first available formatter.
# Never blocks: always exits 0.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat)"
file="$(printf '%s' "$input" | python3 -I -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    pass' 2>/dev/null)"
[ -n "$file" ] && [ -f "$file" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-.}"

node_format() {
  if [ -x "$root/node_modules/.bin/biome" ]; then
    "$root/node_modules/.bin/biome" format --write "$file"
  elif [ -x "$root/node_modules/.bin/prettier" ]; then
    "$root/node_modules/.bin/prettier" --write "$file"
  fi
}

case "$file" in
  *.js|*.ts|*.jsx|*.tsx|*.json|*.css|*.md) node_format >/dev/null 2>&1 ;;
  *.py) command -v ruff >/dev/null 2>&1 && ruff format "$file" >/dev/null 2>&1 ;;
  *.go) command -v gofmt >/dev/null 2>&1 && gofmt -w "$file" >/dev/null 2>&1 ;;
  *.rs) command -v rustfmt >/dev/null 2>&1 && rustfmt "$file" >/dev/null 2>&1 ;;
esac
exit 0
