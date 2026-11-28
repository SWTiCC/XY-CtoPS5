"""截一张 XY-CtoPS5 窗口的图，用来核对版本号与界面是否正常。

用法：<带 Pillow 的 python> tools/capture_window.py <输出 png>
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab

# 必须先声明 DPI 感知：否则 GetWindowRect 返回的是被系统虚拟化的逻辑坐标，
# 而 ImageGrab 抓的是物理像素，截出来只有窗口左上角的一部分。
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

user32 = ctypes.windll.user32
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "window.png"
    title = sys.argv[2] if len(sys.argv) > 2 else "XY-CtoPS5"
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        print(f"没找到 {title} 窗口")
        return 1
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    box = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(box))
    print(f"rect = {box.left},{box.top},{box.right},{box.bottom}")
    image = ImageGrab.grab(
        bbox=(box.left, box.top, box.right, box.bottom), all_screens=True
    )
    image.save(out)
    print(f"saved {out} {image.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
