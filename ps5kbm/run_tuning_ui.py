"""运行页的手感调参区：鼠标 → 右摇杆、扳机深度。

单独成模块，避免 run_ui.py 越滚越大；只摆控件，回调都在 app.py。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme as T
from .config import TRIGGER_LABELS
from .keys import display_key
from .ui_widgets import divider, font, switch

CURVE_CHOICES = ("线性", "二次", "三次", "幂")
_CURVE_LABELS = {
    "linear": "线性",
    "quadratic": "二次",
    "cubic": "三次",
    "power": "幂",
}


def trigger_label(action: str) -> str:
    return TRIGGER_LABELS.get(action, action)


# 按钮上的箭头：↑ 加深 / ↓ 减浅
_MARK = {"r2_up": "↑", "r2_down": "↓", "l2_up": "↑", "l2_down": "↓"}


def curve_label(value: str) -> str:
    return _CURVE_LABELS.get((value or "linear").lower(), "线性")


def build_mouse_tuning(app, parent) -> None:
    """三列网格排 6 个滑条 + 一行曲线 / 开关，横向不会被窗口裁掉。"""
    divider(parent)
    _section_header(parent, "鼠标 → 右摇杆", "拖动即时生效，松手保存")

    app._stick_ramp_var = tk.DoubleVar(value=app._config.left_stick.ramp)
    app._deadzone_var = tk.DoubleVar(value=app._config.mouse.deadzone)
    app._sens_var = tk.DoubleVar(value=app._config.mouse.sensitivity)
    app._slow_sens_var = tk.DoubleVar(value=app._config.mouse.slow_sensitivity)
    app._fast_sens_var = tk.DoubleVar(value=app._config.mouse.fast_sensitivity)
    app._smoothing_var = tk.DoubleVar(value=app._config.mouse.smoothing)

    row1 = _grid_row(parent, 3)
    cell, app._stick_ramp_label = _tuning_cell(
        app,
        row1,
        f"过渡 {app._config.left_stick.ramp:.1f}/s",
        app._stick_ramp_var,
        0.0,
        12.0,
        24,
        app._apply_stick_ramp,
    )
    cell.grid(row=0, column=0, sticky="w", padx=(0, T.S3))
    cell, app._deadzone_label = _tuning_cell(
        app,
        row1,
        f"死区 {app._config.mouse.deadzone:.3f}",
        app._deadzone_var,
        0.0,
        0.2,
        40,
        app._apply_deadzone,
    )
    cell.grid(row=0, column=1, sticky="w", padx=(0, T.S3))
    cell, app._sens_label = _tuning_cell(
        app,
        row1,
        f"灵敏度 {app._config.mouse.sensitivity:.1f}",
        app._sens_var,
        0.2,
        6.0,
        58,
        app._apply_sensitivity,
    )
    cell.grid(row=0, column=2, sticky="w")

    row2 = _grid_row(parent, 3)
    cell, app._slow_sens_label = _tuning_cell(
        app,
        row2,
        f"慢灵敏 {app._config.mouse.slow_sensitivity:.2f}",
        app._slow_sens_var,
        0.2,
        3.0,
        28,
        app._apply_slow_sensitivity,
    )
    cell.grid(row=0, column=0, sticky="w", padx=(0, T.S3))
    cell, app._fast_sens_label = _tuning_cell(
        app,
        row2,
        f"快灵敏 {app._config.mouse.fast_sensitivity:.1f}",
        app._fast_sens_var,
        0.5,
        6.0,
        55,
        app._apply_fast_sensitivity,
    )
    cell.grid(row=0, column=1, sticky="w", padx=(0, T.S3))
    cell, app._smoothing_label = _tuning_cell(
        app,
        row2,
        f"平滑 {app._config.mouse.smoothing:.2f}",
        app._smoothing_var,
        0.0,
        0.6,
        60,
        app._apply_smoothing,
    )
    cell.grid(row=0, column=2, sticky="w")

    extras = ctk.CTkFrame(parent, fg_color="transparent")
    extras.pack(fill="x")
    app._curve_var = tk.StringVar(value=curve_label(app._config.mouse.curve_type))
    ctk.CTkLabel(
        extras, text="曲线", font=font(T.SM), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    ctk.CTkOptionMenu(
        extras,
        variable=app._curve_var,
        values=list(CURVE_CHOICES),
        command=app._choose_curve,
        width=96,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    ).pack(side="left")

    app._mouse_enabled_var = tk.BooleanVar(value=app._config.mouse.enabled)
    switch(extras, "启用鼠标视角", app._mouse_enabled_var, app._toggle_mouse_view).pack(
        side="left", padx=T.S6
    )
    app._flick_var = tk.BooleanVar(value=app._config.mouse.flick_enabled)
    switch(extras, "Flick Stick 快速转身", app._flick_var, app._toggle_flick).pack(
        side="left"
    )


def build_triggers(app, parent) -> None:
    divider(parent)
    _section_header(parent, "扳机深度", "按下时按此深度输出 · 点右侧键名可以改键")

    app._trigger_buttons = {}
    # 深度存 tuning.json：重启后还是上次调好的值，不是每次都回到满按
    app._r2_var = tk.DoubleVar(value=app._config.r2_depth)
    app._r2_label = _trigger_row(
        app, parent, f"R2 {app._config.r2_depth:.1f}", app._r2_var, app._apply_r2, "r2"
    )
    app._l2_var = tk.DoubleVar(value=app._config.l2_depth)
    app._l2_label = _trigger_row(
        app, parent, f"L2 {app._config.l2_depth:.1f}", app._l2_var, app._apply_l2, "l2"
    )
    refresh_trigger_buttons(app)


def refresh_trigger_buttons(app) -> None:
    """按当前配置刷新四个调参键按钮的文字（改键后调用）。"""
    for action, button in (getattr(app, "_trigger_buttons", None) or {}).items():
        mark = _MARK[action]
        key = display_key(getattr(app._config, action, ""))
        button.configure(text=f"{mark} {key}")


# ---------------------------------------------------------------- 小工具
def _section_header(parent, title: str, hint: str = "") -> None:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(0, T.S1))
    ctk.CTkLabel(row, text=title, font=font(T.SM, bold=True), text_color=T.TEXT).pack(
        side="left"
    )
    if hint:
        ctk.CTkLabel(
            row, text=hint, font=font(T.XS), text_color=T.TEXT_FAINT
        ).pack(side="left", padx=T.S3)


def _grid_row(parent, columns: int) -> ctk.CTkFrame:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(0, T.S1))
    for index in range(columns):
        row.columnconfigure(index, weight=1, uniform="tune")
    return row


def _tuning_cell(app, parent, caption, var, from_, to, steps, command):
    cell = ctk.CTkFrame(parent, fg_color="transparent")
    label = ctk.CTkLabel(
        cell, text=caption, font=font(T.SM), text_color=T.TEXT_DIM, anchor="w"
    )
    label.pack(anchor="w")
    slider = ctk.CTkSlider(
        cell,
        from_=from_,
        to=to,
        number_of_steps=steps,
        variable=var,
        command=command,
        width=170,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    slider.pack(anchor="w", pady=(T.S1, 0))
    # 拖动时只更新内存，松开才写盘：每次拖动都 persist 会让 UI 一顿一顿
    slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")
    return cell, label


def _trigger_row(app, parent, caption, var, command, prefix: str):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(0, T.S1))
    label = ctk.CTkLabel(
        row, text=caption, font=font(T.SM), text_color=T.TEXT_DIM, width=64, anchor="w"
    )
    label.pack(side="left")
    slider = ctk.CTkSlider(
        row,
        from_=0.0,
        to=1.0,
        number_of_steps=100,
        variable=var,
        command=command,
        width=230,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    slider.pack(side="left", padx=(0, T.S3))
    slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    # 加深 / 减浅两个键都可以点开重新捕获（默认滚轮上下 / - 和 =）
    for action in (f"{prefix}_up", f"{prefix}_down"):
        button = ctk.CTkButton(
            row,
            text=f"{_MARK[action]} {display_key(getattr(app._config, action, ''))}",
            width=96,
            height=28,
            corner_radius=T.R_SM,
            fg_color=T.SURFACE_HOVER,
            hover_color=T.BORDER,
            text_color=T.TEXT_DIM,
            font=font(T.XS),
            command=lambda name=action: app._rebind_trigger(name),
        )
        button.pack(side="left", padx=(0, T.S2))
        app._trigger_buttons[action] = button
    return label
