"""XY-CtoPS5 安装程序。

做的事：
1. 找到同目录的 XY-CtoPS5\\ 程序文件夹
2. 复制到 %LOCALAPPDATA%\\XY-CtoPS5
3. 在桌面创建快捷方式
4. 打印结果，按回车退出

打包命令见 build-setup.ps1。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

APP_NAME = "XY-CtoPS5"


def _desktop_path() -> str:
    """取桌面路径（优先用户桌面，OneDrive 桌面也能命中）。"""
    candidates = [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


def _create_shortcut(target_exe: str, work_dir: str, lnk_path: str) -> bool:
    """用 PowerShell 的 WScript.Shell 创建 .lnk（无需额外依赖）。"""
    script = (
        "$s = New-Object -ComObject WScript.Shell;"
        f"$sc = $s.CreateShortcut('{lnk_path}');"
        f"$sc.TargetPath = '{target_exe}';"
        f"$sc.WorkingDirectory = '{work_dir}';"
        f"$sc.IconLocation = '{target_exe}';"
        "$sc.Description = 'XY-CtoPS5 - keyboard/mouse for PS5';"
        "$sc.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"创建快捷方式失败：{exc}")
        return False


def _pause(silent: bool) -> None:
    """等待回车；silent 或没有 stdin 时直接跳过。"""
    if silent:
        return
    try:
        input("\n按回车退出...")
    except EOFError:
        pass


def main() -> int:
    # --silent 用于自动化测试：跳过最后的“按回车退出”
    silent = "--silent" in sys.argv
    print("=" * 46)
    print("  XY-CtoPS5 安装程序")
    print("=" * 46)

    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    # 程序目录可能和安装器同级，也可能在安装器目录的上一级（zip 里两者并列）
    candidates = [
        os.path.join(here, APP_NAME),
        os.path.join(os.path.dirname(here), APP_NAME),
    ]
    source = next(
        (
            path
            for path in candidates
            if os.path.isfile(os.path.join(path, f"{APP_NAME}.exe"))
        ),
        candidates[0],
    )
    exe_source = os.path.join(source, f"{APP_NAME}.exe")

    print(f"源目录：{source}")
    if not os.path.isfile(exe_source):
        print()
        print(f"错误：未找到 {APP_NAME}\\{APP_NAME}.exe")
        print("请确认压缩包已经完整解压，并且本安装程序和程序文件夹在同一目录。")
        _pause(silent)
        return 1

    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    target = os.path.join(local_appdata, APP_NAME)
    print(f"目标目录：{target}")

    if os.path.isdir(target):
        print("检测到已安装版本，正在覆盖……")
        shutil.rmtree(target, ignore_errors=True)
    try:
        shutil.copytree(source, target)
    except OSError as exc:
        print(f"\n复制失败：{exc}")
        print("请确认程序没有在运行，然后重新安装。")
        _pause(silent)
        return 1

    exe_target = os.path.join(target, f"{APP_NAME}.exe")
    lnk_path = os.path.join(_desktop_path(), f"{APP_NAME}.lnk")
    print(f"创建快捷方式：{lnk_path}")
    ok = _create_shortcut(exe_target, target, lnk_path)

    print()
    if ok:
        print("安装完成！")
    else:
        print("程序已复制完成，但快捷方式创建失败，可直接运行：")
        print(f"  {exe_target}")
    print(f"  程序目录：{target}")
    if ok:
        print(f"  桌面快捷方式：{lnk_path}")
    if not silent:
        _pause(silent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
