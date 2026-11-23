# 创建桌面快捷方式，双击即可启动 ps5-kbm 图形界面。
# 优先指向 app\XY-CtoPS5.exe（PyInstaller onedir 产物）；没有时回退到 pythonw + launch.pyw。
# 注意：本文件含中文，必须保持 UTF-8 BOM（Windows PowerShell 5.1 否则按 GBK 解析会报错）。
[CmdletBinding()]
param(
    [string]$LinkName = "XY-CtoPS5"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$LinkPath = Join-Path $Desktop "$LinkName.lnk"

$AppExe = Join-Path $Root "app\XY-CtoPS5.exe"
$DistExe = Join-Path $Root "dist\XY-CtoPS5\XY-CtoPS5.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Launcher = Join-Path $Root "launch.pyw"
$FallbackIcon = Join-Path $Root "ps5kbm.ico"

if (Test-Path -LiteralPath $AppExe) {
    $Target = $AppExe
    $Arguments = ""
    $WorkingDir = Split-Path -Parent $AppExe
    $IconLocation = "$AppExe,0"
}
elseif (Test-Path -LiteralPath $DistExe) {
    $Target = $DistExe
    $Arguments = ""
    $WorkingDir = Split-Path -Parent $DistExe
    $IconLocation = "$DistExe,0"
}
elseif (Test-Path -LiteralPath $Pythonw) {
    $Target = $Pythonw
    $Arguments = "`"$Launcher`""
    $WorkingDir = $Root
    $IconLocation = "$FallbackIcon,0"
}
else {
    throw "找不到 app\XY-CtoPS5.exe 或 pythonw.exe，请先运行 build-exe.ps1 或 install.ps1"
}

$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($LinkPath)
$shortcut.TargetPath = $Target
$shortcut.Arguments = $Arguments
$shortcut.WorkingDirectory = $WorkingDir
$shortcut.Description = "用键鼠玩 PS5：连接、映射、拦截"
if (Test-Path -LiteralPath ($IconLocation.Split(",")[0])) {
    $shortcut.IconLocation = $IconLocation
}
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Output "已创建桌面快捷方式：$LinkPath"
Write-Output "指向：$Target"
