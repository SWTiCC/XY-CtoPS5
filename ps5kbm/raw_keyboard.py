"""Win32 Raw Input 键盘读取器。

为什么需要它：
    pynput 失去窗口焦点后收不到按键；低级钩子在本机环境也不稳定。
    Raw Input 直接读设备报文，注册时带 RIDEV_INPUTSINK，**窗口不在前台
    也能收到**，不依赖钩子链。

用法：
    reader = RawKeyboardReader(on_key)
    reader.start()
    ...
    reader.stop()

回调参数：(vk_code, pressed)。键名转换用 win_hooks.vk_to_name。
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1

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


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


# RAWINPUT 的 union 必须按最大成员分配：HID 报文比 KEYBOARD 大，只按
# RAWKEYBOARD 算尺寸会让 GetRawInputData 因“缓冲区不足”返回 0。
_RAWINPUT_UNION_SIZE = 40


class RAWINPUTKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", ctypes.c_ubyte * _RAWINPUT_UNION_SIZE),
    ]


def _declare_api() -> None:
    # 不要声明 RegisterClassW.argtypes：raw_mouse 里有另一个 WNDCLASSW 类定义，
    # 两个模块会互相覆盖这个进程级声明，导致后调用的一方类型不匹配
    # （expected LP_WNDCLASSW instance instead of pointer to WNDCLASSW）。
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
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    user32.GetRawInputData.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]


_declare_api()


def _scancode_to_vk(make_code: int, flags: int) -> int:
    """修饰键在 Raw Input 里有时 VKey=0，只能用扫描码推断。"""
    extended = bool(flags & 0x01)  # RI_KEY_E0
    if make_code == 0x1D:
        return 0xA3 if extended else 0xA2  # ctrl_r / ctrl_l
    if make_code == 0x38:
        return 0xA5 if extended else 0xA4  # alt_r / alt_l
    if make_code == 0x2A:
        return 0xA0  # shift
    if make_code == 0x36:
        return 0xA1  # shift_r
    if make_code == 0x5B:
        return 0x5B  # win
    if make_code == 0x5C:
        return 0x5C  # win_r
    return 0


class RawKeyboardReader(threading.Thread):
    """后台线程读取 Raw Input 键盘报文。"""

    def __init__(self, on_key):
        super().__init__(daemon=True)
        self._on_key = on_key
        self._hwnd = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._stop_event = threading.Event()
        self._wndproc_ref = None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, timeout: float = 3.0) -> bool:  # noqa: D401 - 覆盖 Thread.start
        if self.is_alive():
            return self._error is None
        super().start()
        self._ready.wait(timeout)
        return self._error is None

    def stop(self) -> None:
        self._stop_event.set()
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self.is_alive():
            self.join(timeout=1.5)

    def run(self) -> None:
        try:
            self._create_window()
            self._register()
            self._ready.set()
            self._message_loop()
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()

    def _create_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "Ps5KbmRawKeyboard"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                # MSDN: lParam 是 HRAWINPUT 句柄（wParam 只是 RIM_INPUT/
                # RIM_INPUTSINK 标识），GetRawInputData 必须用 lParam。
                self._handle_input(lparam)
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)
        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc_ref
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            raise OSError("RegisterClassW 失败")
        # 必须给标准窗口样式和非零尺寸：style=0 + 0x0 的窗口在部分系统上
        # 不被视为有效顶层窗口，Raw Input 不会投递 WM_INPUT。
        ws_overlapped_window = 0x00CF0000
        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "ps5kbm-kbd",
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
        device.usUsagePage = 0x01  # Generic Desktop
        device.usUsage = 0x06  # Keyboard
        device.dwFlags = RIDEV_INPUTSINK
        device.hwndTarget = self._hwnd
        if not user32.RegisterRawInputDevices(
            ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)
        ):
            raise OSError("RegisterRawInputDevices(键盘) 失败")

    def _message_loop(self) -> None:
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _handle_input(self, hraw) -> None:
        raw = RAWINPUTKEYBOARD()
        size = wintypes.UINT(ctypes.sizeof(raw))
        written = user32.GetRawInputData(
            wintypes.HANDLE(hraw),
            RID_INPUT,
            ctypes.byref(raw),
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if written == 0 or written == 0xFFFFFFFF:
            return
        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return
        keyboard = RAWKEYBOARD.from_buffer(raw.data)
        vk = int(keyboard.VKey)
        make_code = int(keyboard.MakeCode)
        flags = int(keyboard.Flags)
        if vk == 0 or vk == 0xFF:
            # 修饰键（Ctrl/Alt/Shift/Win）经常只给扫描码
            vk = _scancode_to_vk(make_code, flags)
        if vk == 0:
            return
        # 用 Flags 的 RI_KEY_BREAK 位判断按下/释放（1=释放）。
        # 不要依赖 Message 字段：很多设备上报它是 0，会把所有按键
        # 都当成释放事件，表现就是“键盘完全不起作用”。
        pressed = not bool(flags & 0x01)
        self._on_key(vk, pressed)
