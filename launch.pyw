"""无控制台启动入口：桌面快捷方式指向这里。

为什么需要它：
    `python -m ps5kbm.app` 需要包路径，而快捷方式直接启动 exe 时工作目录与
    sys.path 不一定对；这里显式补齐路径，并把启动异常写到 launch-error.log。

为什么重定向 stdout/stderr：
    PyInstaller `--windowed` 下 sys.stdout / sys.stderr 为 None，任何库里的
    print() 都会抛 AttributeError 导致进程无提示退出。这里先兜底重定向到文件。
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))


def _log_dir() -> str:
    """打包成 exe 后，__file__ 在程序目录里，日志就写在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return ROOT


def _ensure_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(
            os.path.join(_log_dir(), "stdout.log"),
            "w",
            encoding="utf-8",
            buffering=1,
        )
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _report(exc: BaseException) -> None:
    log_path = os.path.join(_log_dir(), "launch-error.log")
    with open(log_path, "w", encoding="utf-8") as handle:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror("ps5-kbm 启动失败", f"错误详情已写入：\n{log_path}")
    except Exception:  # noqa: BLE001 - 错误提示本身失败时不再抛错
        pass


def main() -> int:
    from ps5kbm.app import main as app_main

    return app_main()


if __name__ == "__main__":
    _ensure_streams()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 无控制台时必须落盘提示
        _report(exc)
        raise SystemExit(1)
