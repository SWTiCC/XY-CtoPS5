"""XY-CtoPS5 图形安装程序。

界面功能：
- 显示 / 修改安装路径（默认 %LOCALAPPDATA%\\XY-CtoPS5）
- 浏览选择目录
- 是否创建桌面快捷方式
- 安装进度条
- 完成后可直接启动

程序文件要求：安装程序同级（或上一级）存在 XY-CtoPS5\\ 文件夹。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "XY-CtoPS5"
TITLE = "XY-CtoPS5 安装程序"


def _default_target() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def _desktop_path() -> str:
    for path in (
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    ):
        if os.path.isdir(path):
            return path
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _find_source() -> str | None:
    """定位程序目录：安装器同级或上一级。"""
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for path in (
        os.path.join(here, APP_NAME),
        os.path.join(os.path.dirname(here), APP_NAME),
    ):
        if os.path.isfile(os.path.join(path, f"{APP_NAME}.exe")):
            return path
    return None


def _create_shortcut(exe: str, work_dir: str, lnk: str) -> None:
    script = (
        "$s = New-Object -ComObject WScript.Shell;"
        f"$sc = $s.CreateShortcut('{lnk}');"
        f"$sc.TargetPath = '{exe}';"
        f"$sc.WorkingDirectory = '{work_dir}';"
        f"$sc.IconLocation = '{exe}';"
        "$sc.Description = 'XY-CtoPS5 - keyboard/mouse for PS5';"
        "$sc.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        timeout=30,
    )


class InstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.source = _find_source()
        root.title(TITLE)
        root.geometry("560x300")
        root.resizable(False, False)

        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        pad = 14
        header = tk.Label(
            root,
            text="XY-CtoPS5",
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        )
        header.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(
            root,
            text="把 PC 键盘鼠标变成 PS5 手柄输入（Remote Play 输入通道）",
            font=("Microsoft YaHei UI", 9),
            fg="#666666",
            anchor="w",
        ).pack(fill="x", padx=pad, pady=(2, 12))

        tk.Label(root, text="安装位置：", anchor="w").pack(fill="x", padx=pad)
        row = tk.Frame(root)
        row.pack(fill="x", padx=pad, pady=(4, 10))
        self.path_var = tk.StringVar(value=_default_target())
        tk.Entry(row, textvariable=self.path_var, font=("Consolas", 9)).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(row, text="浏览…", width=8, command=self._browse).pack(
            side="left", padx=(8, 0)
        )

        self.shortcut_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            root, text="创建桌面快捷方式", variable=self.shortcut_var, anchor="w"
        ).pack(fill="x", padx=pad)

        self.progress = ttk.Progressbar(root, maximum=100)
        self.progress.pack(fill="x", padx=pad, pady=(12, 4))

        self.status_var = tk.StringVar(value="准备就绪")
        tk.Label(
            root, textvariable=self.status_var, anchor="w", fg="#666666"
        ).pack(fill="x", padx=pad)

        self.install_btn = tk.Button(
            root,
            text="开始安装",
            height=2,
            font=("Microsoft YaHei UI", 10, "bold"),
            command=self._start,
        )
        self.install_btn.pack(fill="x", padx=pad, pady=(10, pad))

        if self.source is None:
            self.status_var.set("未找到程序文件，请确认压缩包已完整解压")
            self.install_btn.configure(state="disabled")

    # ------------------------------------------------------------ 交互
    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=_default_target())
        if chosen:
            self.path_var.set(os.path.join(chosen, APP_NAME))

    def _set_progress(self, value: float) -> None:
        self.progress["value"] = max(0.0, min(100.0, value * 100.0))

    def _start(self) -> None:
        if self.source is None:
            return
        target = self.path_var.get().strip()
        if not target:
            messagebox.showwarning(TITLE, "请填写安装位置")
            return
        self.install_btn.configure(state="disabled")
        self.status_var.set("正在安装……")
        threading.Thread(
            target=self._install, args=(self.source, target), daemon=True
        ).start()

    def _install(self, source: str, target: str) -> None:
        try:
            files: list[str] = []
            for base, _dirs, names in os.walk(source):
                for name in names:
                    files.append(os.path.join(base, name))
            total = max(1, len(files))
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            for index, path in enumerate(files, start=1):
                rel = os.path.relpath(path, source)
                dest = os.path.join(target, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(path, dest)
                if index % 15 == 0 or index == total:
                    self.root.after(0, self._set_progress, index / total)

            exe = os.path.join(target, f"{APP_NAME}.exe")
            if self.shortcut_var.get():
                try:
                    lnk = os.path.join(_desktop_path(), f"{APP_NAME}.lnk")
                    _create_shortcut(exe, target, lnk)
                except Exception:  # noqa: BLE001 - 快捷方式失败不算安装失败
                    pass
            self.root.after(0, self._done, exe)
        except Exception as exc:  # noqa: BLE001 - 把错误反馈到界面
            self.root.after(0, self._failed, str(exc))

    def _done(self, exe: str) -> None:
        self._set_progress(1.0)
        self.status_var.set("安装完成")
        self.install_btn.configure(state="normal", text="完成")
        if messagebox.askyesno(TITLE, f"安装完成！\n\n程序位置：{exe}\n\n现在启动吗？"):
            try:
                subprocess.Popen([exe])
            except Exception:  # noqa: BLE001
                pass
            self.root.destroy()

    def _failed(self, detail: str) -> None:
        self.status_var.set("安装失败")
        self.install_btn.configure(state="normal")
        messagebox.showerror(TITLE, f"安装失败：\n{detail}")


def main() -> int:
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
