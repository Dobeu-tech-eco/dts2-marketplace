#!/usr/bin/env bash
# Read one field from .claude/dts2-harness.local.md frontmatter, in pure bash (no external command).
# Usage: setting <field> <default>
# Parses exactly like lanes.read_setting: CRLF tolerated, the first `#` starts a comment (even inside quotes), outer quotes stripped.
SETTINGS_FILE=".claude/dts2-harness.local.md"
frontmatter_line() {
  local field="$1" line fence fences=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    fence="${line#"${line%%[![:space:]]*}"}"
    fence="${fence%"${fence##*[![:space:]]}"}"
    if [[ "$fence" == "---" ]]; then
      fences=$((fences + 1))
      [[ "$fences" -eq 2 ]] && return 0
      continue
    fi
    if [[ "$fences" -eq 1 && "$line" == "$field:"* ]]; then
      printf '%s\n' "${line#"$field:"}"
      return 0
    fi
  done < "$SETTINGS_FILE"
  return 0
}
setting() {
  local field="$1" fallback="$2" value=""
  if [[ -f "$SETTINGS_FILE" ]]; then
    value="$(frontmatter_line "$field")"
    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    while [[ "$value" == [\"\']* ]]; do value="${value#?}"; done
    while [[ "$value" == *[\"\'] ]]; do value="${value%?}"; done
  fi
  echo "${value:-$fallback}"
}
