"""用 pywin32 实现的 Raw Input 鼠标读取器。

背景：纯 ctypes 版本的实现与开源参考逐行对比几乎完全一致，但本机实测
收不到任何 WM_INPUT。参考实现（neural-network-game-bot/record.py）用的是
pywin32 的 win32gui 窗口与 PumpMessages 消息泵，因此这里照它的写法重写，
作为 Raw Input 的备选通道。
"""

from __future__ import annotations

import ctypes
import logging
import threading

import win32api
import win32con
import win32gui

_LOGGER = logging.getLogger(__name__)

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEMOUSE = 0


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("hwndTarget", ctypes.wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", ctypes.c_ulong),
        ("dwSize", ctypes.c_ulong),
        ("hDevice", ctypes.wintypes.HANDLE),
        ("wParam", ctypes.wintypes.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", ctypes.c_ushort),
        ("ulButtons", ctypes.c_ulong),
        ("usButtonFlags", ctypes.c_ushort),
        ("usButtonData", ctypes.c_ushort),
        ("lLastX", ctypes.c_long),
        ("lLastY", ctypes.c_long),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", RAWMOUSE),
    ]


class RawMousePyWin32:
    """后台线程用 pywin32 窗口接收 Raw Input 鼠标位移。"""

    def __init__(self, on_delta):
        self._on_delta = on_delta
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._stopped = False
        self._debug_count = 0

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, timeout: float = 3.0) -> bool:
        if self._thread is not None:
            return self._ready.is_set() and self._error is None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._error is None

    def stop(self) -> None:
        self._stopped = True
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    # ------------------------------------------------------------ 内部实现
    def _run(self) -> None:
        try:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "Ps5KbmRawMousePy"
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hCursor = win32api.LoadCursor(0, win32con.IDC_ARROW)
            class_atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(
                class_atom,
                "ps5kbm-raw",
                0,
                0,
                0,
                100,
                100,
                0,
                0,
                wc.hInstance,
                None,
            )
            _LOGGER.info("pywin32 Raw Input 窗口已创建 hwnd=%s", self._hwnd)

            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 1
            rid.usUsage = 2
            rid.dwFlags = RIDEV_INPUTSINK
            rid.hwndTarget = self._hwnd
            ok = ctypes.windll.user32.RegisterRawInputDevices(
                ctypes.byref(rid), 1, ctypes.sizeof(rid)
            )
            _LOGGER.info("pywin32 Raw Input 注册鼠标 = %s", ok)
            if not ok:
                raise OSError("RegisterRawInputDevices 失败")
            self._ready.set()
            win32gui.PumpMessages()
            _LOGGER.info("pywin32 Raw Input 消息循环结束")
        except Exception as exc:  # noqa: BLE001 - 需要把失败暴露给上层
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            self._handle_input(lparam)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _handle_input(self, lparam) -> None:
        raw = RAWINPUT()
        size = ctypes.c_uint(ctypes.sizeof(raw))
        written = ctypes.windll.user32.GetRawInputData(
            lparam,
            RID_INPUT,
            ctypes.byref(raw),
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if self._debug_count < 10:
            self._debug_count += 1
            _LOGGER.info(
                "pywin32 WM_INPUT written=%s type=%s", written, raw.header.dwType
            )
        if not written or written == 0xFFFFFFFF:
            return
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        dx = int(raw.data.lLastX)
        dy = int(raw.data.lLastY)
        if dx or dy:
            self._on_delta(dx, dy)
