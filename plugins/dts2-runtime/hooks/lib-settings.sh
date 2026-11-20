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
# Portability shims for every hook that sources this file.
# GNU timeout is missing on stock macOS (Homebrew coreutils installs it as gtimeout). Without either, steps run unbounded and
# the hook's own timeout in hooks.json is the backstop.
if ! command -v timeout >/dev/null 2>&1; then
  timeout() {
    if command -v gtimeout >/dev/null 2>&1; then
      gtimeout "$@"
    else
      shift
      "$@"
    fi
  }
fi
# Git Bash on native Windows: python3.exe is often the Microsoft Store stub, while python.exe is the real interpreter.
case "${OSTYPE:-}" in
  msys* | cygwin*)
    if command -v python >/dev/null 2>&1; then
      python3() { python "$@"; }
    fi
    ;;
esac
