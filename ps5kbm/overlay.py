"""捕获覆盖层：全屏透明置顶窗口。

思路：
    pynput 在本机只在窗口聚焦时可靠。捕获时开一个几乎全透明的全屏窗口，
    抢走焦点并定时抢回，于是：
    - pynput 始终能收到按键（窗口聚焦）；
    - 按键不会落到下面的 OBS / 游戏窗口；
    - 鼠标点击也被这层挡住，不会误点 PC 上的窗口。

退出方式：
    - 只保留 F8（系统级 RegisterHotKey，任何窗口聚焦都有效）。
    不在覆盖层上绑定其他退出键，避免和游戏按键冲突（鼠标键、Q 等都是游戏要用的）。
    万一 F8 失效，用 Ctrl+Alt+Del 打开任务管理器结束进程。
"""

from __future__ import annotations

import ctypes
import logging
import tkinter as tk

from . import windows

_LOGGER = logging.getLogger(__name__)

_user32 = ctypes.windll.user32

# 透明度：不能为 0，完全透明的窗口在 Windows 上可能失去点击/焦点
_ALPHA = 0.01
# 抢焦点间隔（毫秒）：太频繁会让 Tk 主线程忙于窗口操作，UI 卡顿
_KEEP_FOCUS_MS = 800
# 模式名小标签显示时长（毫秒）：只在切换时提示一下
_BADGE_MS = 2500


class CaptureOverlay:
    """全屏透明窗口，捕获期间占住焦点、置顶并隐藏鼠标指针。"""

    def __init__(self, root: tk.Misc, on_escape):
        self._root = root
        self._on_escape = on_escape
        self._win: tk.Toplevel | None = None
        self._badge: tk.Toplevel | None = None
        self._badge_label: tk.Label | None = None
        self._mode_text = ""
        self._timer: str | None = None
        self._badge_timer: str | None = None
        self._cursor_hidden = False
        self._grab_focus = True

    def set_grab_focus(self, enabled: bool) -> None:
        """是否由透明层抢占焦点。

        设了目标窗口时关闭：让用户选定的窗口保持前台，按键靠 Raw Input 等
        不依赖焦点的通道接收。
        """
        self._grab_focus = bool(enabled)

    @property
    def active(self) -> bool:
        return self._win is not None

    def set_mode_text(self, text: str) -> None:
        """显示模式名几秒后自动隐藏（兼容旧调用名）。"""
        self.show_notice(text)

    def show_notice(self, text: str) -> None:
        """在右上角短暂显示一条提示（约 2.5 秒后自动隐藏）。"""
        self._mode_text = text
        if self._badge_label is None or self._badge is None:
            return
        try:
            self._badge_label.configure(text=text)
            self._badge.deiconify()
            self._badge.attributes("-topmost", True)
            self._badge.lift()
        except tk.TclError:
            return
        if self._badge_timer is not None:
            try:
                self._root.after_cancel(self._badge_timer)
            except tk.TclError:
                pass
        self._badge_timer = self._root.after(_BADGE_MS, self._hide_badge)

    def _hide_badge(self) -> None:
        self._badge_timer = None
        if self._badge is not None:
            try:
                self._badge.withdraw()
            except tk.TclError:
                pass

    def _create_badge(self, width: int) -> tk.Toplevel:
        """右上角不透明小标签：透明层 alpha 太低，文字放里面看不清。"""
        badge = tk.Toplevel(self._root)
        badge.overrideredirect(True)
        badge.attributes("-topmost", True)
        badge.configure(bg="#181818")
        badge.geometry(f"200x44+{width - 220}+20")
        label = tk.Label(
            badge,
            text=self._mode_text or "模式",
            fg="#EDEDED",
            bg="#181818",
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        label.pack(fill="both", expand=True)
        return badge

    def show(self) -> None:
        if self._win is not None:
            return
        width = self._root.winfo_screenwidth()
        height = self._root.winfo_screenheight()
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="black", cursor="none")
        # 只用 alpha 透明。不要用 -transparentcolor：颜色键透明的区域会把
        # 鼠标事件穿透到下层窗口，覆盖层就接收不到输入了。
        try:
            win.attributes("-alpha", _ALPHA)
        except tk.TclError:
            pass
        win.geometry(f"{width}x{height}+0+0")
        win.focus_force()
        # 不用 grab_set：它会限制 Tk 的事件分发，实测可能导致主线程卡顿
        self._win = win

        self._badge = self._create_badge(width)
        self._badge_label = self._badge.winfo_children()[0]
        # 默认隐藏：只在切换模式时提示几秒
        self._badge.withdraw()
        if self._mode_text:
            self.set_mode_text(self._mode_text)

        # Windows 上 cursor="none" 不一定生效，用 ShowCursor 全局隐藏指针
        if not self._cursor_hidden:
            _user32.ShowCursor(False)
            self._cursor_hidden = True
        self._keep_focus()
        _LOGGER.info("捕获覆盖层已打开（全屏透明置顶、鼠标指针隐藏）")

    def hide(self) -> None:
        was_active = self._win is not None
        if self._timer is not None:
            try:
                self._root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        if self._badge_timer is not None:
            try:
                self._root.after_cancel(self._badge_timer)
            except tk.TclError:
                pass
            self._badge_timer = None
        if self._cursor_hidden:
            _user32.ShowCursor(True)
            self._cursor_hidden = False
        for window in (self._badge, self._win):
            if window is not None:
                try:
                    window.grab_release()
                except tk.TclError:
                    pass
                try:
                    window.destroy()
                except tk.TclError:
                    pass
        self._badge = None
        self._badge_label = None
        self._win = None
        if was_active:
            _LOGGER.info("捕获覆盖层已关闭")

    def _keep_focus(self) -> None:
        win = self._win
        if win is None:
            return
        try:
            # 每轮重新置顶（便宜、不动焦点）；焦点只在真被别的程序抢走时才抢回来
            win.attributes("-topmost", True)
            if self._badge is not None:
                self._badge.attributes("-topmost", True)
                self._badge.lift()
            if self._grab_focus and self._should_steal_focus():
                win.lift()
                win.focus_force()
                _LOGGER.info("覆盖层抢回焦点（前台原本是别的窗口）")
        except tk.TclError:
            return
        self._timer = self._root.after(_KEEP_FOCUS_MS, self._keep_focus)

    def _should_steal_focus(self) -> bool:
        """这一轮要不要抢焦点。

        两种情况不能抢：
        - 用户正按着鼠标键：拖动窗口 / 拖动滑块时改变激活窗口，Windows 会取消整次
          拖动并把窗口弹回原位 —— 就是「一拖就瞬间回去了」；
        - 前台本来就是本程序：没有可抢的东西，白抢只会打断鼠标操作。

        输入本身不依赖焦点（键盘走低级钩子、鼠标走 Raw Input），所以少抢几次
        不影响按键，只是保留抢焦点作为 pynput 兜底路径的保险。
        """
        if windows.mouse_button_down():
            return False
        if windows.foreground_is_ours():
            return False
        return True
