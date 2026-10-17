#!/usr/bin/env bash
# Install the dts2 marketplace on Linux, macOS, or WSL.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${DTS2_HOME:-$HOME/.dts2/marketplace}"
mkdir -p "$(dirname "$DEST")"
if [[ -d "$DEST" ]]; then
  mv "$DEST" "$DEST.bak-$(date +%Y%m%d-%H%M%S)"
fi
cp -R "$SRC" "$DEST"
chmod +x "$DEST"/plugins/dts2-harness/hooks/*.sh "$DEST"/plugins/dts2-harness/scripts/*.py "$DEST"/plugins/dts2-harness/sdk/*.py
python3 "$DEST/plugins/dts2-harness/scripts/env-detect.py" || true
cat <<MSG

Copied to: $DEST

If the env report above says claudeWrapsWindows is true, your WSL 'claude' runs the
Windows app and uses the Windows home. Install from Windows with install.ps1 instead,
unless you have a native Linux Claude CLI.

Inside Claude Code, run:
  /plugin marketplace add $DEST   (offline copy; normally: /plugin marketplace add Dobeu-tech-eco/dts2-marketplace)
  /plugin install dts2-harness@dts2
Then disable the older copies so agents are not duplicated:
  /plugin -> Installed -> harness and harness-ops -> Disable
  (or run /dts2-harness:machine-prep, which does it with a settings backup)
Restart Claude Code, then run /dts2-harness:onboard
MSG
