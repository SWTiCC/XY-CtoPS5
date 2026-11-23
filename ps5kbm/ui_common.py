"""界面公共组件：日志 Handler、动作描述、动作编辑弹窗。"""

from __future__ import annotations

import logging
import queue
from tkinter import messagebox

import customtkinter as ctk
from pynput import keyboard, mouse

from . import theme as T
from .keys import key_name, mouse_button_name
from .mapping import VALID_BUTTONS, parse_action
from .ui_widgets import font, primary_button, secondary_button

BUTTON_LIST = sorted(VALID_BUTTONS)
ACTION_KINDS = ("单按钮", "组合键（同时按）", "序列（依次按）", "摇杆幅度")

# 手柄按键在界面上的符号显示：DS4/DS5 的图形按键用形状表示，比英文名直观
BUTTON_SYMBOLS = {
    "CROSS": "✕",
    "CIRCLE": "○",
    "SQUARE": "□",
    "TRIANGLE": "△",
    "UP": "↑",
    "DOWN": "↓",
    "LEFT": "←",
    "RIGHT": "→",
    "OPTIONS": "≡",
    "TOUCHPAD": "▭",
}
SYMBOL_TO_NAME = {symbol: name for name, symbol in BUTTON_SYMBOLS.items()}


def button_label(name: str) -> str:
    """内部名 → 界面显示：有符号的显示「✕ CROSS」，没有的原样显示。"""
    name = str(name).upper()
    symbol = BUTTON_SYMBOLS.get(name)
    return f"{symbol} {name}" if symbol else name


def button_name(label: str) -> str:
    """界面显示 → 内部名，供下拉框选择后回写配置。"""
    label = str(label).strip()
    parts = label.split()
    if len(parts) == 2 and parts[0] in SYMBOL_TO_NAME:
        return parts[1].upper()
    return label.upper()


class QueueLogHandler(logging.Handler):
    """把日志塞进队列，由界面线程轮询显示。"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self._queue = log_queue
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        self._queue.put(self.format(record))


def describe_action(raw) -> str:
    """把动作配置转成一行人类可读描述。"""
    try:
        action = parse_action(raw)
    except ValueError:
        return "（非法配置）"
    if action.kind == "button":
        return " → ".join(button_label(name) for name in action.buttons)
    if action.kind == "chord":
        return " + ".join(button_label(name) for name in action.buttons)
    if action.kind == "stick":
        if len(action.values) > 1:
            joined = " ↔ ".join(f"{value:.2f}" for value in action.values)
            return f"左摇杆幅度 {joined}（循环）"
        return f"左摇杆幅度 {action.value:.2f}"
    steps = " → ".join(
        f"{button_label(button)} {hold:g}s" for button, hold in action.steps
    )
    return f"序列 [{steps}]"


DIRECTIONS = (("up", "上 ↑"), ("down", "下 ↓"), ("left", "左 ←"), ("right", "右 →"))


def format_stick_keys(sticks: dict) -> str:
    """把四个方向键配置压成一行显示。"""

    def first(direction: str) -> str:
        keys = sticks.get(direction, [])
        return str(keys[0]).upper() if keys else "—"

    return (
        f"↑ {first('up')}    ↓ {first('down')}    "
        f"← {first('left')}    → {first('right')}"
    )


class KeyCaptureDialog(ctk.CTkToplevel):
    """按下键盘或鼠标键，自动识别键名。

    键盘改用 Tk 原生 <KeyPress>：对话框本身有焦点，事件一定收得到，
    不再依赖 pynput（它在部分环境只对特定窗口生效）。
    """

    # Tk keysym → 配置键名
    _TK_KEYS = {
        "Control_L": "ctrl_l",
        "Control_R": "ctrl_r",
        "Alt_L": "alt_l",
        "Alt_R": "alt_r",
        "Shift_L": "shift",
        "Shift_R": "shift_r",
        "space": "space",
        "Tab": "tab",
        "Escape": "esc",
        "Return": "enter",
        "BackSpace": "backspace",
        "Caps_Lock": "caps_lock",
        "Up": "up",
        "Down": "down",
        "Left": "left",
        "Right": "right",
        "Home": "home",
        "End": "end",
        "Insert": "insert",
        "Delete": "delete",
        "Prior": "pageup",
        "Next": "pagedown",
        "Super_L": "cmd",
        "Super_R": "cmd_r",
        "Menu": "menu",
        # 标点键在 Tk 里是字母 keysym，不映射的话没法绑 - / = 这类键
        "equal": "=",
        "plus": "+",
        "minus": "-",
        "bracketleft": "[",
        "bracketright": "]",
        "semicolon": ";",
        "apostrophe": "'",
        "comma": ",",
        "period": ".",
        "slash": "/",
        "backslash": "\\",
        "grave": "`",
    }

    @classmethod
    def _tk_key_name(cls, keysym: str) -> str | None:
        if keysym in cls._TK_KEYS:
            return cls._TK_KEYS[keysym]
        if len(keysym) == 1:
            return keysym.lower()
        if keysym.startswith("F") and keysym[1:].isdigit():
            return keysym.lower()
        return None

    def __init__(self, parent, on_captured, allow_wheel: bool = False):
        super().__init__(parent)
        self.title("按下要绑定的按键")
        self.geometry("400x190" if not allow_wheel else "400x210")
        self.configure(fg_color=T.BG)
        self.resizable(False, False)
        self._on_captured = on_captured
        self._done = False

        frame = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=T.S6, pady=T.S4)
        ctk.CTkLabel(
            frame, text="请按下要绑定的键", font=font(T.LG, bold=True), text_color=T.TEXT
        ).pack(anchor="w")
        hint = "键盘任意键，或鼠标任意键（含侧键）"
        if allow_wheel:
            hint += "\n也可以用鼠标滚轮（上 / 下）"
        hint += "\nEsc 取消"
        ctk.CTkLabel(
            frame,
            text=hint,
            font=font(T.XS),
            text_color=T.TEXT_DIM,
            justify="left",
        ).pack(anchor="w", pady=(T.S1, T.S3))
        self._result_label = ctk.CTkLabel(
            frame, text="等待输入…", font=font(T.BASE, mono=True), text_color=T.ACCENT
        )
        self._result_label.pack(anchor="w")

        # 鼠标仍用 pynput（Tk 能收到 Button 事件但侧键支持有限）
        self._ms_listener = mouse.Listener(
            on_click=lambda x, y, button, pressed: self._on_mouse(button, pressed),
            on_scroll=self._on_scroll if allow_wheel else None,
        )
        self._ms_listener.start()
        # 应用级绑定：焦点在对话框或主窗口都能收到，避免“按了没反应”
        self.bind_all("<KeyPress>", self._on_key)
        self.focus_force()
        self.after(100, self.focus_force)
        self.transient(parent)
        self.after(150, self.grab_set)
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

    def _on_key(self, event) -> None:
        if self._done:
            return
        keysym = getattr(event, "keysym", "")
        if keysym == "Escape":
            self._finish(None)
            return
        name = self._tk_key_name(keysym)
        if name:
            self._finish(name)

    def _on_mouse(self, button, pressed) -> None:
        if self._done or not pressed:
            return
        name = mouse_button_name(button)
        # 回到 Tk 主线程完成 UI 操作
        self.after(0, lambda: self._finish(name))

    def _on_scroll(self, x, y, dx, dy) -> None:
        """滚轮捕获（只有 allow_wheel=True 时才挂）：上 / 下各算一个键。"""
        if self._done:
            return
        name = "wheel_up" if dy > 0 else "wheel_down"
        self.after(0, lambda: self._finish(name))

    def _finish(self, name: str | None) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.unbind_all("<KeyPress>")
        except Exception:  # noqa: BLE001
            pass
        self._ms_listener.stop()
        callback = self._on_captured
        self.destroy()
        if callback:
            callback(name)


class StickKeysEditor(ctk.CTkToplevel):
    """编辑左摇杆四个方向对应的键盘按键。"""

    def __init__(self, parent, sticks: dict, on_save):
        super().__init__(parent)
        self.title("左摇杆方向键")
        self.geometry("420x300")
        self.configure(fg_color=T.BG)
        self.resizable(False, False)
        self._on_save = on_save

        frame = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=T.S6, pady=T.S4)
        ctk.CTkLabel(
            frame,
            text="WASD 这类方向键映射到左摇杆；一个方向可以绑多个键（逗号分隔），留空表示不绑定",
            font=font(T.XS),
            text_color=T.TEXT_FAINT,
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(0, T.S3))

        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x")
        self._vars: dict[str, ctk.StringVar] = {}
        for index, (direction, label) in enumerate(DIRECTIONS):
            ctk.CTkLabel(
                grid, text=label, font=font(T.SM), text_color=T.TEXT_DIM
            ).grid(row=index // 2, column=(index % 2) * 2, sticky="w", padx=(0, T.S2), pady=T.S2)
            keys = sticks.get(direction, [])
            # 这里要显示全部键：只显示第一个的话，点保存就把其余键丢了
            var = ctk.StringVar(value=", ".join(str(key) for key in keys))
            self._vars[direction] = var
            ctk.CTkEntry(
                grid,
                textvariable=var,
                width=100,
                height=32,
                corner_radius=T.R_SM,
                fg_color=T.SURFACE_HOVER,
                border_color=T.BORDER,
                text_color=T.TEXT,
                font=font(T.SM, mono=True),
            ).grid(row=index // 2, column=(index % 2) * 2 + 1, sticky="w", pady=T.S2)

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", side="bottom")
        primary_button(buttons, "保存", self._save, width=96, height=36).pack(side="right")
        secondary_button(buttons, "取消", self.destroy, width=80, height=36).pack(
            side="right", padx=T.S2
        )

    def _save(self) -> None:
        sticks: dict[str, list[str]] = {}
        for direction, var in self._vars.items():
            keys = [part.strip().lower() for part in var.get().split(",") if part.strip()]
            if keys:
                sticks[direction] = keys
        self._on_save(sticks)
        self.destroy()


class ActionEditor(ctk.CTkToplevel):
    """单按钮 / 组合键 / 序列 的编辑弹窗。"""

    def __init__(self, parent, source_name: str, raw_action, on_save):
        super().__init__(parent)
        self.title(f"编辑映射 · {source_name}")
        self.geometry("520x440")
        self.configure(fg_color=T.BG)
        self.resizable(False, False)
        self._on_save = on_save
        self._checkbox_vars: dict[str, ctk.BooleanVar] = {}
        self._build()
        self._fill(raw_action)
        self.transient(parent)
        self.after(120, self.grab_set)

    def _build(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=T.S6, pady=T.S4)

        kind_row = ctk.CTkFrame(frame, fg_color="transparent")
        kind_row.pack(fill="x", pady=(0, T.S3))
        ctk.CTkLabel(
            kind_row, text="动作类型", font=font(T.XS), text_color=T.TEXT_DIM
        ).pack(side="left", padx=(0, T.S2))
        self._kind = ctk.StringVar(value=ACTION_KINDS[0])
        ctk.CTkSegmentedButton(
            kind_row,
            values=list(ACTION_KINDS),
            variable=self._kind,
            command=lambda _value: self._switch_kind(),
            font=font(T.XS),
            selected_color=T.ACCENT,
            selected_hover_color=T.ACCENT_HOVER,
            unselected_color=T.SURFACE_HOVER,
            unselected_hover_color=T.BORDER,
            text_color=T.TEXT,
            height=32,
        ).pack(side="left", fill="x", expand=True)

        self._single_frame = ctk.CTkFrame(frame, fg_color=T.SURFACE, corner_radius=T.R_LG)
        self._single_var = ctk.StringVar(value=button_label("CROSS"))
        ctk.CTkLabel(
            self._single_frame, text="手柄按钮", font=font(T.XS), text_color=T.TEXT_DIM
        ).pack(anchor="w", padx=T.S4, pady=(T.S3, 0))
        ctk.CTkOptionMenu(
            self._single_frame,
            variable=self._single_var,
            values=[button_label(name) for name in BUTTON_LIST],
            width=180,
            height=34,
            corner_radius=T.R_SM,
            fg_color=T.SURFACE_HOVER,
            button_color=T.SURFACE_HOVER,
            button_hover_color=T.BORDER,
            text_color=T.TEXT,
            font=font(T.SM),
        ).pack(anchor="w", padx=T.S4, pady=(T.S1, T.S4))

        self._chord_frame = ctk.CTkFrame(frame, fg_color=T.SURFACE, corner_radius=T.R_LG)
        grid = ctk.CTkFrame(self._chord_frame, fg_color="transparent")
        grid.pack(padx=T.S4, pady=T.S3)
        for index, name in enumerate(BUTTON_LIST):
            var = ctk.BooleanVar(value=False)
            self._checkbox_vars[name] = var
            ctk.CTkCheckBox(
                grid,
                text=button_label(name),
                variable=var,
                font=font(T.XS),
                text_color=T.TEXT_DIM,
                fg_color=T.ACCENT,
                hover_color=T.ACCENT_HOVER,
                border_color=T.BORDER,
                checkbox_width=16,
                checkbox_height=16,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=T.S2, pady=T.S1)

        self._sequence_frame = ctk.CTkFrame(frame, fg_color=T.SURFACE, corner_radius=T.R_LG)
        ctk.CTkLabel(
            self._sequence_frame,
            text="格式：UP:0.05, CROSS:0.05（按钮:保持秒数）",
            font=font(T.XS),
            text_color=T.TEXT_DIM,
        ).pack(anchor="w", padx=T.S4, pady=(T.S3, 0))
        self._sequence_text = ctk.CTkTextbox(
            self._sequence_frame,
            height=72,
            fg_color=T.BG,
            corner_radius=T.R_SM,
            text_color=T.TEXT,
            font=font(T.SM, mono=True),
        )
        self._sequence_text.pack(fill="x", padx=T.S4, pady=(T.S1, T.S4))

        self._stick_frame = ctk.CTkFrame(frame, fg_color=T.SURFACE, corner_radius=T.R_LG)
        ctk.CTkLabel(
            self._stick_frame,
            text=(
                "填一个值：按下固定设为该值；填多个值（逗号分隔）：每按一次循环切换。\n"
                "例如 0.5, 1.0 表示按一下 1.0、再按回 0.5。"
            ),
            font=font(T.XS),
            text_color=T.TEXT_DIM,
            justify="left",
            wraplength=380,
        ).pack(anchor="w", padx=T.S4, pady=(T.S3, 0))
        stick_row = ctk.CTkFrame(self._stick_frame, fg_color="transparent")
        stick_row.pack(fill="x", padx=T.S4, pady=(T.S2, T.S4))
        self._stick_var = ctk.StringVar(value="0.5, 1.0")
        ctk.CTkEntry(
            stick_row,
            textvariable=self._stick_var,
            width=150,
            height=34,
            corner_radius=T.R_SM,
            fg_color=T.SURFACE_HOVER,
            border_color=T.BORDER,
            text_color=T.TEXT,
            font=font(T.SM, mono=True),
        ).pack(side="left")
        for label, preset in (("慢走 0.2", "0.2"), ("走 0.5", "0.5"), ("全速 1.0", "1.0")):
            secondary_button(
                stick_row,
                label,
                lambda target=preset: self._stick_var.set(target),
                width=76,
                height=30,
            ).pack(side="left", padx=(T.S2, 0))

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", side="bottom")
        primary_button(buttons, "保存", self._save, width=96, height=36).pack(side="right")
        secondary_button(buttons, "取消", self.destroy, width=80, height=36).pack(
            side="right", padx=T.S2
        )
        self._switch_kind()

    def _switch_kind(self) -> None:
        for frame in (
            self._single_frame,
            self._chord_frame,
            self._sequence_frame,
            self._stick_frame,
        ):
            frame.pack_forget()
        kind = self._kind.get()
        if kind == ACTION_KINDS[0]:
            self._single_frame.pack(fill="x", pady=T.S2)
        elif kind == ACTION_KINDS[1]:
            self._chord_frame.pack(fill="x", pady=T.S2)
        elif kind == ACTION_KINDS[2]:
            self._sequence_frame.pack(fill="x", pady=T.S2)
        else:
            self._stick_frame.pack(fill="x", pady=T.S2)

    def _fill(self, raw_action) -> None:
        try:
            action = parse_action(raw_action)
        except ValueError:
            return
        if action.kind == "button":
            self._single_var.set(
                button_label(action.buttons[0] if action.buttons else "CROSS")
            )
        elif action.kind == "chord":
            self._kind.set(ACTION_KINDS[1])
            for name in action.buttons:
                if name in self._checkbox_vars:
                    self._checkbox_vars[name].set(True)
        elif action.kind == "stick":
            self._kind.set(ACTION_KINDS[3])
            self._stick_var.set(", ".join(f"{value:g}" for value in action.values))
        else:
            self._kind.set(ACTION_KINDS[2])
            self._sequence_text.insert(
                "1.0", ", ".join(f"{button}:{hold:g}" for button, hold in action.steps)
            )
        self._switch_kind()

    def _save(self) -> None:
        kind = self._kind.get()
        if kind == ACTION_KINDS[0]:
            value = button_name(self._single_var.get())
        elif kind == ACTION_KINDS[1]:
            selected = [name for name, var in self._checkbox_vars.items() if var.get()]
            if not selected:
                messagebox.showwarning("提示", "至少勾选一个按钮", parent=self)
                return
            value = {"chord": selected}
        elif kind == ACTION_KINDS[2]:
            text = self._sequence_text.get("1.0", "end").strip()
            steps = []
            try:
                for part in text.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if ":" in part:
                        button, hold = part.split(":", 1)
                        steps.append([button.strip().upper(), float(hold)])
                    else:
                        steps.append([part.upper(), 0.05])
            except ValueError:
                messagebox.showerror(
                    "格式错误", "序列格式应为 CROSS:0.05, UP:0.05", parent=self
                )
                return
            if not steps:
                messagebox.showwarning("提示", "序列不能为空", parent=self)
                return
            value = {"sequence": steps}
        else:
            parts = [part.strip() for part in self._stick_var.get().split(",") if part.strip()]
            try:
                values = [max(0.05, min(1.0, float(part))) for part in parts]
            except ValueError:
                messagebox.showerror(
                    "格式错误",
                    "摇杆幅度用数字填写，多个值用逗号分隔，例如 0.5, 1.0",
                    parent=self,
                )
                return
            if not values:
                messagebox.showwarning("提示", "至少填一个幅度值", parent=self)
                return
            value = {"stick": values[0] if len(values) == 1 else values}
        self._on_save(value)
        self.destroy()
