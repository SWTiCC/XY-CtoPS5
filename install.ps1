# install.ps1 - set up the Python environment for ps5-kbm
# Run:  powershell -ExecutionPolicy Bypass -File .\install.ps1
# Note: kept ASCII-only on purpose so Windows PowerShell 5.1 never mis-decodes it.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Find-Python312 {
    # Prefer the py launcher entries that are 3.11+, then fall back to PATH.
    foreach ($launcher in @("py -3.12", "py -3.14", "py -3.13", "py -3.11")) {
        $parts = $launcher.Split(" ")
        try {
            $version = & $parts[0] $parts[1] -c "import sys; print(sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) { return $launcher }
        } catch { }
    }
    return "python"
}

$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $base = Find-Python312
    Write-Host "[1/3] creating venv with: $base"
    $parts = $base.Split(" ")
    if ($parts.Length -gt 1) {
        & $parts[0] $parts[1] -m venv $Venv
    } else {
        & $base -m venv $Venv
    }
} else {
    Write-Host "[1/3] venv already exists"
}

$versionCheck = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "      python version: $versionCheck"
if ([version]$versionCheck -lt [version]"3.11") {
    throw "Python 3.11+ is required (playdirector requirement). Delete .venv and install a newer Python."
}

Write-Host "[2/3] installing playdirector without netifaces (vendor shim is used instead)"
& $Python -m pip install --no-deps playdirector

Write-Host "[3/3] installing dependencies"
& $Python -m pip install aiohttp async-timeout pyps4-2ndscreen cryptography pycryptodomex "protobuf>=4.21.1,<7" requests "pyee>=12,<13" pyyaml cffi pynput psutil customtkinter

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  .\run.cmd scan"
Write-Host "  .\run.cmd login        # get PSN Account ID"
Write-Host "  .\run.cmd pair --help"
Write-Host "  .\run.cmd run"
