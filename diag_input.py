"""输入诊断：分别统计 pynput 与 Win32 钩子收到的按键，定位输入断点。

用法：双击 diag-input.cmd，按提示敲几个键。
"""

import sys
import time

sys.path.insert(0, r"E:\Code Project\Other\ps5-kbm")
sys.path.insert(0, r"E:\Code Project\Other\ps5-kbm\vendor")

from pynput import keyboard  # noqa: E402

from ps5kbm.win_hooks import KeyboardHook  # noqa: E402

py_events: list[str] = []
hook_events: list[str] = []

hook = KeyboardHook(
    lambda name: False,
    lambda name, pressed: hook_events.append(f"{name}:{'down' if pressed else 'up'}"),
)
hook_ok = hook.start()

listener = keyboard.Listener(
    on_press=lambda key: py_events.append(str(key)),
)
listener.start()
time.sleep(0.5)

print("=" * 50)
print(f"Win32 钩子安装：{hook_ok}" + (f"（错误：{hook.error}）" if hook.error else ""))
print("=" * 50)
print("请在 8 秒内依次按：W、空格、左 Ctrl、鼠标左键")
print("=" * 50)

time.sleep(8)

listener.stop()
hook.stop()

print()
print(f"pynput 收到 {len(py_events)} 个按键：{py_events[:8]}")
print(f"钩子收到 {len(hook_events)} 个事件：{hook_events[:8]}")
print()
if py_events or hook_events:
    print("结论：至少一路能收到按键，输入链路可用。")
else:
    print("结论：两路都没收到按键，系统层输入被拦截（安全软件/远程桌面/沙箱）。")
