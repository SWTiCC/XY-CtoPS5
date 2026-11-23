"""输入采集层（回退版）：pynput 监听 + 光标轮询 + 系统级 F8。

为什么回退：
    pynput + 光标轮询这套此前实测可用。Raw Input 与低级钩子的组合在本机
    反而让所有按键都收不到（钩子装上了但回调不触发，且会吞掉事件）。
    这里只保留验证过能工作的路径，F8 仍用 RegisterHotKey 保证不依赖焦点。

切换捕获时需要重建 pynput 监听器（suppress 只能在构造时指定），
重建放在延迟线程里执行，避免在监听回调线程里 stop 自己。
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

from pynput import keyboard, mouse

from .global_hotkey import GlobalHotkey
from .keys import key_name, mouse_button_name
from .raw_keyboard import RawKeyboardReader
from .raw_mouse import RawMouseReader
from .win_hooks import KeyboardHook, MouseHook, vk_to_name

_LOGGER = logging.getLogger(__name__)

user32 = ctypes.windll.user32


class InputSource:
    """pynput 全局监听 + 光标锁定轮询。"""

    def __init__(self, mapper, hotkey: str = "f8"):
        self._mapper = mapper
        self._hotkey = hotkey.lower()
        self._lock = threading.RLock()
        self._capturing = False
        self._hotkey_down = False
        self._hotkey_external = False
        self._down_keys: set[str] = set()
        self._on_capture_changed = None
        self._on_key_event = None
        self._lock_center: tuple[int, int] | None = None
        self._last_pos: tuple[int, int] | None = None
        # 光标差值兜底用：上一帧光标位置
        self._cursor_last: tuple[int, int] | None = None
        self._keyboard_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_hook: KeyboardHook | None = None
        self._mouse_hook: MouseHook | None = None
        self._hotkey_handle: GlobalHotkey | None = None
        self._raw_keyboard = RawKeyboardReader(self._on_raw_key)
        self._raw_mouse = RawMouseReader(self._on_raw_mouse_delta)
        self._raw_mouse_ok = False
        self._raw_dx = 0
        self._raw_dy = 0
        self._raw_still_frames = 0
        self._last_raw_log = 0.0
        self._last_lock_log = 0.0
        self._rebuild_pending = False
        self._listening = False
        self._mode_switch = ""
        self._mode_switch_down = False
        self._on_mode_switch = None
        self._on_scroll_callback = None
        self._on_l2_adjust = None

    def set_l2_adjust_callback(self, callback) -> None:
        """注册 L2 深度调整回调（键盘 - / = 触发，参数 ±1）。"""
        self._on_l2_adjust = callback

    def set_scroll_callback(self, callback) -> None:
        """注册鼠标滚轮回调（捕获时生效），参数是滚轮方向 dy。"""
        self._on_scroll_callback = callback

    def set_mode_switch(self, name: str, callback) -> None:
        """注册模式切换键：按下时回调，切换由上层执行。"""
        self._mode_switch = (name or "").lower()
        self._on_mode_switch = callback

    # ------------------------------------------------------------ 生命周期
    def start(self) -> bool:
        # pynput：窗口聚焦时可靠；失去焦点可能收不到
        self._start_listeners(suppress=False)

        # Raw Input 鼠标：窗口和注册必须在主线程完成（实测子线程收不到
        # WM_INPUT），消息由 app 的主线程定时 pump。
        raw_kb_ok = False
        self._raw_mouse_ok = self._raw_mouse.setup()
        if not self._raw_mouse_ok:
            _LOGGER.warning("Raw Input 鼠标不可用（%s）", self._raw_mouse.error)

        # 键盘钩子：捕获时吞掉全部键盘事件（F8 放行给全局热键），
        # 这样 Alt、Win、Alt+Tab 都不会传给系统。
        # 鼠标只监听不吞：万一 F8 失效，你还能用鼠标点窗口按钮退出捕获。
        self._keyboard_hook = KeyboardHook(
            lambda name: self._capturing and name != self._hotkey,
            lambda name, pressed: self._handle_key(name, pressed),
        )
        self._mouse_hook = MouseHook(
            lambda button: False,
            lambda button, pressed: self._handle_mouse(button, pressed),
        )
        keyboard_ok = self._keyboard_hook.start()
        mouse_ok = self._mouse_hook.start()
        if not keyboard_ok:
            _LOGGER.warning("键盘钩子不可用（%s），后台可能收不到按键", self._keyboard_hook.error)

        self._hotkey_handle = GlobalHotkey(self._hotkey, self.toggle_capture)
        if self._hotkey_handle.start():
            self._hotkey_external = True
            _LOGGER.info("全局热键生效（系统级）：%s", self._hotkey.upper())
        else:
            _LOGGER.warning("全局热键注册失败（%s）", self._hotkey_handle.error)
        self._listening = (
            raw_kb_ok
            or keyboard_ok
            or (
                self._keyboard_listener is not None
                and self._mouse_listener is not None
            )
        )
        return True

    def stop(self) -> None:
        if self._hotkey_handle is not None:
            self._hotkey_handle.stop()
            self._hotkey_handle = None
        for hook in (self._keyboard_hook, self._mouse_hook):
            if hook is not None:
                hook.stop()
        self._keyboard_hook = None
        self._mouse_hook = None
        self._raw_keyboard.stop()
        self._raw_mouse.stop()
        self._raw_mouse_ok = False
        self._stop_listeners()
        self._release_cursor()

    @property
    def capturing(self) -> bool:
        return self._capturing

    @property
    def full_capture(self) -> bool:
        """回退版不做系统级拦截，恒为 False。"""
        return False

    @property
    def listening(self) -> bool:
        return self._listening

    def set_capture_callback(self, callback) -> None:
        self._on_capture_changed = callback

    def set_key_callback(self, callback) -> None:
        self._on_key_event = callback

    def pressed_keys(self) -> set[str]:
        """当前物理按下的键集合，供上层做残留校正。"""
        with self._lock:
            return set(self._down_keys)

    def pump_mouse_messages(self) -> None:
        """主线程定时调用，排空 Raw Input 窗口消息。"""
        if self._raw_mouse_ok:
            self._raw_mouse.pump()

    def toggle_capture(self) -> bool:
        with self._lock:
            self._capturing = not self._capturing
            state = self._capturing
            self._down_keys.clear()
        _LOGGER.info("捕获模式：%s", "开" if state else "关")
        if state:
            self._lock_cursor()
        else:
            self._release_cursor()
        callback = self._on_capture_changed
        if callback:
            callback(state)
        return state

    # ------------------------------------------------------------ 鼠标位移
    def _on_raw_mouse_delta(self, dx: int, dy: int) -> None:
        with self._lock:
            self._raw_dx += dx
            self._raw_dy += dy

    def poll_mouse_delta(self) -> tuple[int, int]:
        """取本帧鼠标位移。

        优先用 Raw Input 的设备相对位移（本地鼠标最准）。
        远程桌面（ToDesk 等）的注入往往不产生 WM_INPUT，此时退回用
        光标位置差值——ToDesk 直接设置光标坐标，前后差值就是真实移动。
        """
        point = wintypes.POINT()
        has_point = bool(user32.GetCursorPos(ctypes.byref(point)))

        if self._raw_mouse_ok:
            with self._lock:
                dx, dy = self._raw_dx, self._raw_dy
                self._raw_dx = 0
                self._raw_dy = 0
                if has_point:
                    # 同步光标基准，避免下一帧把同一段移动再算一次
                    self._cursor_last = (point.x, point.y)
            if dx or dy:
                return int(dx), int(dy)

        if not has_point:
            return 0, 0
        with self._lock:
            last = self._cursor_last
            self._cursor_last = (point.x, point.y)
        if last is None:
            return 0, 0
        cdx = point.x - last[0]
        cdy = point.y - last[1]

        # 绝对坐标会撞屏幕边缘，靠近边缘时把光标挪回中心继续
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        margin = 8
        if (
            point.x <= margin
            or point.x >= screen_w - margin
            or point.y <= margin
            or point.y >= screen_h - margin
        ):
            center_x = screen_w // 2
            center_y = screen_h // 2
            user32.SetCursorPos(center_x, center_y)
            with self._lock:
                self._cursor_last = (center_x, center_y)
        return int(cdx), int(cdy)

    def lock_cursor(self) -> None:
        point = wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            with self._lock:
                self._lock_center = (point.x, point.y)
                self._last_pos = (point.x, point.y)

    def keep_cursor_locked(self) -> None:
        with self._lock:
            center = self._lock_center
        if center is not None:
            user32.SetCursorPos(center[0], center[1])

    def release_cursor(self) -> None:
        with self._lock:
            self._lock_center = None
            self._last_pos = None

    # ------------------------------------------------------------ 内部实现
    def _lock_cursor(self) -> None:
        self.lock_cursor()

    def _release_cursor(self) -> None:
        with self._lock:
            self._lock_center = None
            self._last_pos = None

    def _start_listeners(self, suppress: bool) -> None:
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=suppress,
        )
        self._keyboard_listener.start()
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            suppress=suppress,
        )
        self._mouse_listener.start()

    def _stop_listeners(self) -> None:
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener is not None:
                listener.stop()
        self._keyboard_listener = None
        self._mouse_listener = None

    def _schedule_rebuild_locked(self) -> None:
        """延迟重建监听器：不能在监听回调线程里 stop 自己。"""
        if self._rebuild_pending:
            return
        self._rebuild_pending = True

        def _rebuild() -> None:
            with self._lock:
                self._rebuild_pending = False
                suppress = self._capturing
            try:
                self._stop_listeners()
                self._start_listeners(suppress=suppress)
                self._listening = True
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("重建输入监听失败：%s", exc)
                self._listening = False

        threading.Timer(0.08, _rebuild).start()

    def _on_press(self, key) -> None:
        self._handle_key(key_name(key), True)

    def _on_release(self, key) -> None:
        self._handle_key(key_name(key), False)

    def _on_raw_key(self, vk: int, pressed: bool) -> None:
        name = vk_to_name(vk)
        if name:
            self._handle_key(name, pressed)

    def _handle_key(self, name: str, pressed: bool) -> None:
        """所有键盘来源（pynput / 钩子 / Raw Input）的统一入口，按名字去重。"""
        # 键盘 - / = 调整 L2 输出深度（捕获时生效）
        if self._on_l2_adjust is not None and name in ("-", "=", "+"):
            if pressed:
                self._on_l2_adjust(-1 if name == "-" else 1)
            return
        if name == self._mode_switch:
            if pressed:
                if not self._mode_switch_down:
                    self._mode_switch_down = True
                    if self._on_mode_switch:
                        self._on_mode_switch()
            else:
                self._mode_switch_down = False
            return
        if name == self._hotkey:
            if self._hotkey_external:
                return  # 由 RegisterHotKey 处理
            if pressed:
                if self._hotkey_down:
                    return
                self._hotkey_down = True
                self.toggle_capture()
            else:
                self._hotkey_down = False
            return
        if pressed:
            with self._lock:
                if name in self._down_keys:
                    return
                self._down_keys.add(name)
            if not self._capturing:
                return
            if self._on_key_event:
                self._on_key_event(name)
            self._mapper.on_key(name, True)
        else:
            with self._lock:
                self._down_keys.discard(name)
            if self._capturing:
                self._mapper.on_key(name, False)

    def _on_click(self, x, y, button, pressed) -> None:
        self._handle_mouse(
            mouse_button_name(button).replace("mouse_", "", 1), pressed
        )

    def _on_scroll(self, x, y, dx, dy) -> None:
        """鼠标滚轮：捕获中用于调整 L2 扳机深度。"""
        if self._capturing and self._on_scroll_callback:
            self._on_scroll_callback(dy)

    def _handle_mouse(self, name: str, pressed: bool) -> None:
        # 鼠标键也允许当作模式切换键（name 是 left/right/middle/x1/x2）
        full_name = f"mouse_{name}"
        if self._mode_switch and (
            full_name == self._mode_switch or name == self._mode_switch
        ):
            if pressed:
                if not self._mode_switch_down:
                    self._mode_switch_down = True
                    if self._on_mode_switch:
                        self._on_mode_switch()
            else:
                self._mode_switch_down = False
            return
        if self._capturing:
            self._mapper.on_mouse_button(name, pressed)
