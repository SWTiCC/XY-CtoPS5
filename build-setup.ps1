# build-setup.ps1 - build the single-file installer with Inno Setup
# Usage: powershell -ExecutionPolicy Bypass -File .\build-setup.ps1
# Output: dist\XY-CtoPS5-Setup.exe
# Requires: Inno Setup 6 (ISCC.exe), and dist\XY-CtoPS5\ built by build-exe.ps1
# Note: kept ASCII-only so Windows PowerShell 5.1 never mis-decodes it.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }

$Iiss = Join-Path $Root "installer.iss"
Write-Host "[1/2] compiling installer with Inno Setup..."
& $Iscc $Iiss

$Setup = Join-Path $Root "dist\XY-CtoPS5-Setup.exe"
if (-not (Test-Path $Setup)) { throw "compile failed: $Setup not found" }
Write-Host "[2/2] done: $Setup"
