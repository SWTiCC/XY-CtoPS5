"""诊断脚本：量一量「各页面整块重建」各要多少毫秒。

这些函数都在界面线程跑，耗时就是用户看到的卡顿。不连主机，只建界面。
"""

from __future__ import annotations

import ctypes
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import customtkinter as ctk  # noqa: E402

from ps5kbm import connect_ui, mapping_ui, rules_ui  # noqa: E402
from ps5kbm.app import Ps5KbmApp  # noqa: E402

ROUNDS = 5


def timed(label: str, func) -> None:
    samples: list[float] = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        func()
        try:
            root.update_idletasks()
        except Exception:  # noqa: BLE001
            pass
        samples.append((time.perf_counter() - start) * 1000)
    print(f"{label:<28} 中位数 {statistics.median(samples):7.1f} ms")


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass

ctk.set_default_color_theme("blue")
root = ctk.CTk()
app = Ps5KbmApp(root)
root.update()

timed("连接页 render", lambda: connect_ui.render(app))
timed("映射列表重建", lambda: mapping_ui.refresh_mapping_list(app))
timed("摇杆方向键重建", lambda: mapping_ui.refresh_stick_keys(app))
timed("自动切换那一行", lambda: mapping_ui.refresh_rules_row(app))
timed("模式下拉刷新", lambda: mapping_ui.refresh_mode_ui(app))
timed("切页面 运行", lambda: app.show_page("run"))
timed("切页面 映射", lambda: app.show_page("mapping"))

app.show_page("mapping")
app.open_rules_editor()
root.update()
timed("规则面板整页重画", lambda: rules_ui.refresh_rules_page(app))

root.destroy()
