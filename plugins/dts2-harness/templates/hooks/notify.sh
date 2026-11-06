#!/usr/bin/env bash
# dts2 optional hook: Notification. Shows a desktop notification with the message. Always exits 0.
set -uo pipefail

msg="Claude Code needs your attention"
if command -v python3 >/dev/null 2>&1; then
  parsed="$(cat | python3 -I -c 'import json,sys
try:
    print(str(json.load(sys.stdin).get("message", ""))[:300])
except Exception:
    pass' 2>/dev/null)"
  [ -n "$parsed" ] && msg="$parsed"
fi

case "$(uname -s 2>/dev/null)" in
  Darwin)
    command -v osascript >/dev/null 2>&1 &&
      osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "Claude Code"' -e 'end run' "$msg" >/dev/null 2>&1
    ;;
  MINGW*|MSYS*|CYGWIN*)
    if command -v powershell.exe >/dev/null 2>&1; then
      # shellcheck disable=SC2016
      DTS2_MSG="$msg" powershell.exe -NoProfile -Command \
        'Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; $n.ShowBalloonTip(5000, "Claude Code", $env:DTS2_MSG, "Info"); Start-Sleep -Seconds 6; $n.Dispose()' \
        >/dev/null 2>&1 || msg.exe '*' "$msg" >/dev/null 2>&1
    elif command -v msg.exe >/dev/null 2>&1; then
      msg.exe '*' "$msg" >/dev/null 2>&1
    fi
    ;;
  *)
    command -v notify-send >/dev/null 2>&1 && notify-send "Claude Code" "$msg" >/dev/null 2>&1
    ;;
esac
exit 0
