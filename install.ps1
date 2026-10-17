# Install the dts2 marketplace on Windows.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = if ($env:DTS2_HOME) { $env:DTS2_HOME } else { Join-Path $env:USERPROFILE ".dts2\marketplace" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
if (Test-Path $dest) {
  Move-Item $dest ("$dest.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
Copy-Item -Recurse -Path $src -Destination $dest
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if ($py) { & $py.Source (Join-Path $dest "plugins\dts2-harness\scripts\env-detect.py") }
Write-Host ""
Write-Host "Copied to: $dest"
Write-Host ""
Write-Host "Inside Claude Code, run:"
Write-Host "  /plugin marketplace add $dest"
Write-Host "  /plugin install dts2-harness@dts2"
Write-Host "Then disable the older copies so agents are not duplicated:"
Write-Host "  /plugin -> Installed -> harness and harness-ops -> Disable"
Write-Host "  (or run /dts2-harness:machine-prep, which does it with a settings backup)"
Write-Host "Restart Claude Code, then run /dts2-harness:onboard"
