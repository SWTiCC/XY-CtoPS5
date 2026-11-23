# 安装 XY-CtoPS5（开发版 / 源码版）
# 作用：创建虚拟环境、安装依赖、在桌面创建快捷方式
# 用法：双击同目录的 install-dev.cmd
# 前提：已安装 Python 3.12，并在 PATH 里

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python。请先安装 Python 3.12 并勾选 Add to PATH。"
}

Write-Host "[1/2] 安装依赖（创建 .venv）..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "install.ps1")

$Pythonw = Join-Path $Here ".venv\Scripts\pythonw.exe"
$Launcher = Join-Path $Here "launch.pyw"
if (-not (Test-Path $Pythonw)) {
    throw "虚拟环境创建失败：$Pythonw 不存在"
}

Write-Host "[2/2] 创建桌面快捷方式..."
$Desktop = [Environment]::GetFolderPath("Desktop")
$Lnk = Join-Path $Desktop "XY-CtoPS5.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Lnk)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = """$Launcher"""
$Shortcut.WorkingDirectory = $Here
$IconFile = Join-Path $Here "ps5kbm.ico"
if (Test-Path $IconFile) {
    $Shortcut.IconLocation = $IconFile
}
$Shortcut.Description = "XY-CtoPS5 键鼠玩 PS5（开发版）"
$Shortcut.Save()

Write-Host ""
Write-Host "安装完成（开发版）"
Write-Host "  快捷方式: $Lnk"
Write-Host "  直接用 .venv\Scripts\pythonw.exe launch.pyw 也能启动"
