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

SW_RESTORE = 9
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
