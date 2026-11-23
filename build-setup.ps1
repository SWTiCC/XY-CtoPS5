# build-setup.ps1 - build the exe installer (XY-CtoPS5-Setup.exe)
# Usage: powershell -ExecutionPolicy Bypass -File .\build-setup.ps1
# Note: kept ASCII-only so Windows PowerShell 5.1 never mis-decodes it.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "venv not found, run install.ps1 first" }

Write-Host "[1/2] building installer exe (onedir: onefile needs writable %TEMP%)..."
& $Python -m PyInstaller `
  --noconfirm --clean --onedir --console `
  --name "XY-CtoPS5-Setup" `
  --icon "$Root\ps5kbm.ico" `
  --distpath "$Root\dist" `
  --workpath "$Root\build" `
  --specpath "$Root\build" `
  "$Root\setup_installer.py"

$Built = Join-Path $Root "dist\XY-CtoPS5-Setup\XY-CtoPS5-Setup.exe"
if (-not (Test-Path $Built)) { throw "build failed: $Built not found" }
Write-Host "[2/2] done: $Built"
