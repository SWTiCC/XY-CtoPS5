"""Windows 窗口枚举与激活。

用途：开始捕获时把焦点自动切到用户选定的窗口（例如采集卡预览窗口），
让游戏/预览窗口保持在前台，而不是被本程序的透明层一直抢焦点。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _declare_api() -> None:
    user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD


_declare_api()


def list_windows(exclude: str = "") -> list[tuple[int, str]]:
    """列出可见且有标题的顶层窗口，返回 (hwnd, 标题)。"""
    result: list[tuple[int, str]] = []

    def _collect(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        if exclude and exclude in title:
            return True
        result.append((int(hwnd), title))
        return True

    user32.EnumWindows(_WNDENUMPROC(_collect), 0)
    return result


def find_window(title_keyword: str, exclude: str = "") -> int | None:
    """按标题子串找窗口，返回 hwnd；找不到返回 None。"""
    if not title_keyword:
        return None
    keyword = title_keyword.lower()
    for hwnd, title in list_windows(exclude=exclude):
        if keyword in title.lower():
            return hwnd
    return None


def activate_window(hwnd: int) -> bool:
    """把窗口切到前台。前台锁可能让它失败，失败时返回 False。"""
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(user32.SetForegroundWindow(hwnd))
    except OSError as exc:
        _LOGGER.warning("激活窗口失败：%s", exc)
        return False


def activate_by_title(title_keyword: str, exclude: str = "") -> bool:
    """按标题激活窗口，找不到或失败返回 False。"""
    hwnd = find_window(title_keyword, exclude=exclude)
    if hwnd is None:
        return False
    return activate_window(hwnd)


def mouse_button_down() -> bool:
    """用户此刻是否按着鼠标左键或右键。

    低级钩子挡不住「改变激活窗口」对拖拽的破坏：拖动窗口 / 滑块的过程中，只要
    有别的窗口被抢到前台，Windows 就会取消整次拖动，窗口弹回原位。所有会动焦点
    的操作（覆盖层抢焦点、切目标窗口）动手前都先问一句这里。
    """
    for vk in (VK_LBUTTON, VK_RBUTTON):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def foreground_is_ours() -> bool:
    """前台窗口是不是本程序（本进程）的。没有前台窗口时返回 False。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return process_id.value == kernel32.GetCurrentProcessId()


# 单实例互斥体句柄：必须一直持有，否则互斥体会被系统释放
_instance_mutex = None
_ERROR_ALREADY_EXISTS = 183


def acquire_single_instance(name: str = "XY-CtoPS5") -> bool:
    """命名互斥体做单实例保护；已有实例在跑返回 False。

    两个实例同时跑会抢同一个 DualSense 的 HID 句柄，还会互相覆盖 config.json，
    所以第二次启动只提示一下然后退出。创建失败时不拦（宁可多开也别打不开）。
    """
    global _instance_mutex
    if _instance_mutex is not None:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    except Exception as exc:  # noqa: BLE001 - 拿不到互斥体就不做保护
        _LOGGER.debug("单实例互斥体创建失败：%s", exc)
        return True
    if not handle:
        return True
    _instance_mutex = handle
    return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
