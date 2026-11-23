"""Raw Input 独立验证程序（打包成 exe 供实机运行）。

和主程序完全相同的窗口/注册/消息循环结构，但把结果直接写文件，
用来区分「代码问题」还是「环境问题」。

运行后：动鼠标 5 秒，然后看同目录 rawtest.log
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes

LOG_PATH = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__), "rawtest.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_INPUT = 0x00FF
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
PM_REMOVE = 0x0001

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", ctypes.c_ubyte * 64),
    ]


stats = {"messages": 0, "wm_input": 0, "written": 0, "delta": 0}


def declare() -> None:
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.WORD
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterRawInputDevices.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICE),
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    user32.GetRawInputData.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t


def main() -> int:
    declare()
    logging.info("=== rawtest 启动 ===")

    def wndproc(hwnd, msg, wparam, lparam):
        stats["messages"] += 1
        if msg == WM_INPUT:
            stats["wm_input"] += 1
            raw = RAWINPUT()
            size = wintypes.UINT(ctypes.sizeof(raw))
            written = user32.GetRawInputData(
                wintypes.HANDLE(lparam),
                RID_INPUT,
                ctypes.byref(raw),
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER),
            )
            stats["written"] = int(written)
            logging.info(
                "WM_INPUT #%s written=%s type=%s",
                stats["wm_input"],
                written,
                raw.header.dwType,
            )
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc_ref = WNDPROC(wndproc)
    hinstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc_ref
    wc.hInstance = hinstance
    wc.lpszClassName = "RawSelfTestExe"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        logging.error("RegisterClassW 失败")
        return 1
    hwnd = user32.CreateWindowExW(
        0, "RawSelfTestExe", "rawtest", 0x00CF0000, 0, 0, 120, 120, None, None, hinstance, None
    )
    logging.info("窗口 hwnd=%s", hwnd)

    rid = RAWINPUTDEVICE()
    rid.usUsagePage = 0x01
    rid.usUsage = 0x02
    rid.dwFlags = RIDEV_INPUTSINK
    rid.hwndTarget = hwnd
    ok = user32.RegisterRawInputDevices(
        ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)
    )
    logging.info("注册鼠标 = %s err=%s", ok, kernel32.GetLastError())

    # 窗口和消息循环在同一线程（主线程），用 PeekMessage 轮询 6 秒
    msg = wintypes.MSG()
    deadline = time.time() + 6.0
    while time.time() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.001)

    logging.info("统计：%s", stats)
    logging.info(
        "结论：WM_INPUT=%s%s",
        stats["wm_input"],
        "（Raw Input 正常）" if stats["wm_input"] else "（Raw Input 未投递）",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
