#!/usr/bin/env bash
# Read one field from .claude/dts2-harness.local.md frontmatter.
# Usage: setting <field> <default>
SETTINGS_FILE=".claude/dts2-harness.local.md"
setting() {
  local field="$1" fallback="$2" value=""
  if [[ -f "$SETTINGS_FILE" ]]; then
    value=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$SETTINGS_FILE" \
      | grep "^${field}:" | head -1 | sed "s/^${field}: *//" | sed 's/^"\(.*\)"$/\1/')
  fi
  echo "${value:-$fallback}"
}
