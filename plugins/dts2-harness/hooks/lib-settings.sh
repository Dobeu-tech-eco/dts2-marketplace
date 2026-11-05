#!/usr/bin/env bash
# Read one field from .claude/dts2-harness.local.md frontmatter.
# Usage: setting <field> <default>
# Parses exactly like lanes.read_setting: CRLF tolerated, the first `#` starts a comment (even inside quotes), outer quotes stripped.
SETTINGS_FILE=".claude/dts2-harness.local.md"
frontmatter_line() {
  awk -v field="$1" '
    { sub(/\r$/, ""); fence = $0; gsub(/^[ \t]+|[ \t]+$/, "", fence) }
    fence == "---" { fences++; if (fences == 2) exit; next }
    fences == 1 && index($0, field ":") == 1 { print substr($0, length(field) + 2); exit }
  ' "$SETTINGS_FILE"
}
setting() {
  local field="$1" fallback="$2" value=""
  if [[ -f "$SETTINGS_FILE" ]]; then
    value="$(frontmatter_line "$field")"
    value="${value%%#*}"
    value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^["'"'"']+//; s/["'"'"']+$//')"
  fi
  echo "${value:-$fallback}"
}
