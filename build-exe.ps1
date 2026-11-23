# build-exe.ps1 - build a standalone app folder (onedir) with PyInstaller
# Usage: powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
# Output: app\XY-CtoPS5.exe  (runs directly, no temporary extraction)
# Note: kept ASCII-only so Windows PowerShell 5.1 never mis-decodes it.
# Why onedir: onefile needs a writable %TEMP% at runtime; on some locked-down
# machines it fails with "Could not create temporary directory!".

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "venv not found, run install.ps1 first" }

Write-Host "[1/3] building app folder (this can take a minute)..."
& $Python -m PyInstaller `
  --noconfirm --clean --onedir --windowed `
  --name "XY-CtoPS5" `
  --icon "$Root\ps5kbm.ico" `
  --add-data "$Root\ps5kbm\presets;ps5kbm\presets" `
  --paths "$Root\vendor" `
  --hidden-import netifaces `
  --collect-all customtkinter `
  --distpath "$Root\dist" `
  --workpath "$Root\build" `
  --specpath "$Root\build" `
  "$Root\launch.pyw"

$Built = Join-Path $Root "dist\XY-CtoPS5"
if (-not (Test-Path "$Built\XY-CtoPS5.exe")) { throw "build failed: dist\XY-CtoPS5\XY-CtoPS5.exe not found" }

Write-Host "[2/3] copying to app\ (keeping config.json / credentials.json)..."
$AppDir = Join-Path $Root "app"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item "$Built\*" $AppDir -Recurse -Force

Write-Host "[3/3] done: $AppDir\XY-CtoPS5.exe"
