"""Win32 Raw Input 鼠标位移读取器（主线程消息泵版）。

关键结论（实测得出）：
    同样的窗口/注册/读取代码，放在独立子线程里收不到 WM_INPUT，
    放在程序主线程里就能收到。所以这里不再自己开线程，改为：

    1. setup()  在调用线程（必须是 Tk 主线程）创建窗口并注册
    2. pump()   由主线程定时调用，用 PeekMessage 排空消息队列
    3. stop()   销毁窗口

这样窗口、注册、消息处理都在同一个有消息泵的线程里，和验证程序一致。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_INPUT = 0x00FF
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
_PM_REMOVE = 0x0001
# RAWMOUSE.usFlags 位：绝对坐标（远程桌面注入就是这种）
MOUSE_MOVE_ABSOLUTE = 0x01

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


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("ulButtons", wintypes.ULONG),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("lLastX", ctypes.c_long),
        ("lLastY", ctypes.c_long),
    ]


def _declare_api() -> None:
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
    user32.DestroyWindow.argtypes = [wintypes.HWND]


_declare_api()


class RawMouseReader:
    """主线程消息泵驱动的 Raw Input 鼠标位移读取器。"""

    def __init__(self, on_delta):
        self._on_delta = on_delta
        self._hwnd = None
        self._error: str | None = None
        self._wndproc_ref = None
        self._debug_count = 0
        # 绝对坐标模式下的上一帧位置（远程桌面注入用）
        self._abs_last: tuple[int, int] | None = None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def ready(self) -> bool:
        return self._hwnd is not None and self._error is None

    def setup(self) -> bool:
        """在调用线程（必须是主线程）创建隐藏窗口并注册 Raw Input 鼠标。"""
        if self._hwnd is not None:
            return True
        try:
            self._create_window()
            self._register()
            _LOGGER.info("Raw Input 鼠标窗口已创建 hwnd=%s", self._hwnd)
            return True
        except Exception as exc:  # noqa: BLE001 - 需要把失败暴露给上层
            self._error = f"{type(exc).__name__}: {exc}"
            _LOGGER.warning("Raw Input 鼠标初始化失败：%s", self._error)
            return False

    def pump(self) -> None:
        """排空消息队列；由主线程定时调用（非阻塞）。"""
        if self._hwnd is None:
            return
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self) -> None:
        if self._hwnd is not None:
            try:
                user32.DestroyWindow(self._hwnd)
            except Exception:  # noqa: BLE001
                pass
            self._hwnd = None

    # ------------------------------------------------------------ 内部实现
    def _create_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "Ps5KbmRawMouseMain"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                # MSDN：lParam 才是 HRAWINPUT 句柄
                self._handle_input(lparam)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)
        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc_ref
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            raise OSError("RegisterClassW 失败")
        # 标准窗口样式 + 非零尺寸，但不显示
        ws_overlapped_window = 0x00CF0000
        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "ps5kbm-raw",
            ws_overlapped_window,
            0,
            0,
            100,
            100,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise OSError("CreateWindowExW 失败")
        self._hwnd = hwnd

    def _register(self) -> None:
        device = RAWINPUTDEVICE()
        device.usUsagePage = 0x01
        device.usUsage = 0x02
        device.dwFlags = RIDEV_INPUTSINK
        device.hwndTarget = self._hwnd
        if not user32.RegisterRawInputDevices(
            ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)
        ):
            raise OSError("RegisterRawInputDevices 失败")

    def _handle_input(self, hraw) -> None:
        raw = RAWINPUT()
        size = wintypes.UINT(ctypes.sizeof(raw))
        written = user32.GetRawInputData(
            wintypes.HANDLE(hraw),
            RID_INPUT,
            ctypes.byref(raw),
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if self._debug_count < 10:
            self._debug_count += 1
            _LOGGER.info(
                "WM_INPUT hraw=%s written=%s type=%s",
                hraw,
                written,
                raw.header.dwType,
            )
        if not written or written == 0xFFFFFFFF:
            return
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        mouse = RAWMOUSE.from_buffer(raw.data)
        flags = int(mouse.usFlags)
        x = int(mouse.lLastX)
        y = int(mouse.lLastY)
        if flags & MOUSE_MOVE_ABSOLUTE:
            # 远程桌面（ToDesk / RDP 等）用绝对坐标注入鼠标：lLastX/lLastY
            # 是屏幕坐标而不是相对位移。直接当位移用会导致数值永远是正的大
            # 数（没有负值），所以这里和上一帧做差还原成位移。
            last = self._abs_last
            self._abs_last = (x, y)
            if last is None:
                return
            dx = x - last[0]
            dy = y - last[1]
            # 绝对坐标会撞屏幕边缘导致视角卡住，靠近边缘时把光标挪回中心，
            # 并把基准一起重置，让下一段移动还能继续产生位移。
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            margin = 8
            if (
                x <= margin
                or x >= screen_w - margin
                or y <= margin
                or y >= screen_h - margin
            ):
                center_x = screen_w // 2
                center_y = screen_h // 2
                user32.SetCursorPos(center_x, center_y)
                self._abs_last = (center_x, center_y)
        else:
            dx = x
            dy = y
        if dx or dy:
            self._on_delta(dx, dy)
