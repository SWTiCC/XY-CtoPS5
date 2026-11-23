"""Win32 低级键鼠钩子：全局拦截，不依赖窗口焦点。

为什么不用 pynput：
    pynput 的监听器在本机部分环境下只在程序窗口聚焦时收到按键，
    鼠标 suppress 也不生效。低级钩子（WH_KEYBOARD_LL / WH_MOUSE_LL）
    是系统级安装，任何窗口聚焦都能收到，并能返回 1 吞掉事件。

设计：
    - 钩子安装后常驻，拦截与否由 should_suppress 回调实时决定，
      切换捕获不需要重建钩子；
    - 每个钩子在独立线程跑消息循环，回调里只做轻量处理；
    - 键盘回调给出与 pynput 兼容的键名（w / space / shift / ctrl_l ...），
      鼠标回调给出 left / right / middle / x1 / x2。
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


_KEY_NAMES = {
    0x08: "backspace",
    0x09: "tab",
    0x0D: "enter",
    0x13: "pause",
    0x14: "caps_lock",
    0x1B: "esc",
    0x20: "space",
    0x21: "pageup",
    0x22: "pagedown",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2C: "print_screen",
    0x2D: "insert",
    0x2E: "delete",
    # 通用修饰键（部分键盘/驱动只报这些，不区分左右）
    0x10: "shift",
    0x11: "ctrl_l",
    0x12: "alt_l",
    0x5B: "cmd",
    0x5C: "cmd_r",
    0x5D: "menu",
    0x90: "num_lock",
    0x91: "scroll_lock",
    # 左右修饰键
    0xA0: "shift",
    0xA1: "shift_r",
    0xA2: "ctrl_l",
    0xA3: "ctrl_r",
    0xA4: "alt_l",
    0xA5: "alt_r",
    # 符号键
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}


def vk_to_name(vk: int) -> str | None:
    """虚拟键码 → 配置键名；无法识别返回 None。"""
    if vk in _KEY_NAMES:
        return _KEY_NAMES[vk]
    if 0x41 <= vk <= 0x5A:  # A-Z
        return chr(vk).lower()
    if 0x30 <= vk <= 0x39:  # 0-9
        return chr(vk)
    if 0x70 <= vk <= 0x87:  # F1-F24
        return f"f{vk - 0x70 + 1}"
    if 0x60 <= vk <= 0x69:  # 小键盘 0-9
        return f"num{vk - 0x60}"
    if 0x6A <= vk <= 0x6F:  # 小键盘 * + - . /
        return {0x6A: "num*", 0x6B: "num+", 0x6D: "num-", 0x6E: "num.", 0x6F: "num/"}.get(vk)
    return None


class _BaseHook(threading.Thread):
    """安装一个低级钩子并跑消息循环。"""

    WH = 0

    def __init__(self, should_suppress, handler):
        super().__init__(daemon=True)
        # should_suppress(current) -> bool：当前这个键/按钮是否要吞掉
        self._should_suppress = should_suppress
        self._handler = handler
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread_id: int | None = None
        self._hook = None
        self._proc_ref = None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, timeout: float = 2.0) -> bool:  # noqa: D401 - 覆盖 Thread.start
        super().start()
        self._ready.wait(timeout)
        return self._error is None

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._proc_ref = HOOKPROC(self._proc)
        # 低级钩子的钩子过程在本进程内，hMod 必须传 NULL；
        # 传 python.exe 的模块句柄会报 126（ERROR_MOD_NOT_FOUND）。
        self._hook = user32.SetWindowsHookExW(self.WH, self._proc_ref, None, 0)
        if not self._hook:
            self._error = f"SetWindowsHookEx 失败（错误码 {kernel32.GetLastError()}）"
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.is_alive():
            self.join(timeout=1.5)

    def _proc(self, n_code, w_param, l_param):
        raise NotImplementedError


class KeyboardHook(_BaseHook):
    WH = WH_KEYBOARD_LL

    def __init__(self, should_suppress, handler):
        super().__init__(should_suppress, handler)

    def _proc(self, n_code, w_param, l_param):
        if n_code == HC_ACTION:
            try:
                data = ctypes.cast(
                    l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
                ).contents
                name = vk_to_name(data.vkCode)
                if name:
                    pressed = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    self._handler(name, pressed)
                    # 热键本身不能吞：吞掉后 RegisterHotKey 收不到
                    if self._should_suppress(name):
                        return 1
            except Exception as exc:  # noqa: BLE001 - 钩子回调绝不能抛
                _LOGGER.error("键盘钩子回调异常：%s", exc)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)


class MouseHook(_BaseHook):
    WH = WH_MOUSE_LL

    _BUTTONS = {
        WM_LBUTTONDOWN: ("left", True),
        WM_LBUTTONUP: ("left", False),
        WM_RBUTTONDOWN: ("right", True),
        WM_RBUTTONUP: ("right", False),
        WM_MBUTTONDOWN: ("middle", True),
        WM_MBUTTONUP: ("middle", False),
        WM_XBUTTONDOWN: (None, True),
        WM_XBUTTONUP: (None, False),
    }

    def _proc(self, n_code, w_param, l_param):
        if n_code == HC_ACTION:
            try:
                button, pressed = self._BUTTONS.get(w_param, (None, None))
                if button is None and pressed is not None:
                    data = ctypes.cast(
                        l_param, ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    high = (data.mouseData >> 16) & 0xFFFF
                    button = "x1" if high == 1 else "x2"
                if button is not None:
                    self._handler(button, bool(pressed))
                    if self._should_suppress(button):
                        return 1
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("鼠标钩子回调异常：%s", exc)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
