"""Win32 全局热键：RegisterHotKey + 独立消息循环。

为什么不用 pynput：
    F8 需要“任何窗口聚焦时都能用”。pynput 的低级钩子在本机部分环境下
    只在程序窗口聚焦时收到按键；RegisterHotKey 是系统级注册，不受焦点影响，
    也不依赖钩子权限。

用法：
    hotkey = GlobalHotkey("f8", callback)
    if hotkey.start():
        ...  # 注册成功
    hotkey.stop()
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


def _virtual_key(name: str) -> int | None:
    """把 "f8" / "space" / "a" 这类名字转成虚拟键码。"""
    name = name.strip().lower()
    if len(name) >= 2 and name[0] == "f" and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    table = {
        "space": 0x20,
        "tab": 0x09,
        "esc": 0x1B,
        "enter": 0x0D,
        "backspace": 0x08,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "home": 0x24,
        "end": 0x23,
        "insert": 0x2D,
        "delete": 0x2E,
        "pageup": 0x21,
        "pagedown": 0x22,
    }
    if name in table:
        return table[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    return None


class GlobalHotkey(threading.Thread):
    """在独立线程里注册并监听一个全局热键。"""

    def __init__(self, combo: str, callback):
        super().__init__(daemon=True)
        self._combo = combo
        self._callback = callback
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread_id: int | None = None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, timeout: float = 2.0) -> bool:  # noqa: D401 - 覆盖 Thread.start
        super().start()
        self._ready.wait(timeout)
        return self._error is None

    def run(self) -> None:
        hotkey_id = 1
        try:
            parts = [part.strip().lower() for part in self._combo.split("+") if part.strip()]
            if not parts:
                raise ValueError("热键为空")
            modifiers = 0
            for part in parts[:-1]:
                if part in ("ctrl", "control"):
                    modifiers |= MOD_CONTROL
                elif part == "shift":
                    modifiers |= MOD_SHIFT
                elif part == "alt":
                    modifiers |= MOD_ALT
                else:
                    raise ValueError(f"不支持的修饰键：{part}")
            vk = _virtual_key(parts[-1])
            if vk is None:
                raise ValueError(f"不支持的按键：{parts[-1]}")

            self._thread_id = kernel32.GetCurrentThreadId()
            if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
                raise OSError("RegisterHotKey 失败（热键可能被其他程序占用）")
            self._ready.set()
            _LOGGER.info("全局热键已注册：%s", self._combo)

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                    try:
                        self._callback()
                    except Exception as exc:  # noqa: BLE001 - 回调异常不能杀死热键线程
                        _LOGGER.error("热键回调异常：%s", exc)
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            self._ready.set()
        finally:
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.is_alive():
            self.join(timeout=1.0)
