"""手柄页：DualSense 连接状态、输入模式、陀螺仪与震动设置。

只摆控件，业务在 app.py；颜色/字号/间距都来自 theme.py。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme as T
from .ui_widgets import (
    build_card,
    font,
    secondary_button,
    switch,
)

ACTIVATION_CHOICES = {
    "常开": "always",
    "按住 L2": "l2",
    "按住 L1": "l1",
    "按住 R2": "r2",
    "按住 R1": "r1",
    "按住 L3": "l3",
    "按住 R3": "r3",
    "按住 ✕": "cross",
    "按住 ○": "circle",
    "按住 □": "square",
    "按住 △": "triangle",
    "按住 分享": "share",
    "按住 选项": "options",
    "按住 触摸板": "touchpad",
}
CUSTOM_CHOICE = "自定义…"
CAPTURE_HINT = "按下手柄按键…"

# 按键名 → 界面显示名
_BUTTON_LABELS = {
    "l2": "L2",
    "l1": "L1",
    "r2": "R2",
    "r1": "R1",
    "l3": "L3",
    "r3": "R3",
    "cross": "✕",
    "circle": "○",
    "square": "□",
    "triangle": "△",
    "share": "分享",
    "options": "选项",
    "touchpad": "触摸板",
    "mute": "静音",
    "ps": "PS",
}


def button_label(value: str) -> str:
    """手柄按键名 → 界面显示名。"""
    return _BUTTON_LABELS.get(str(value or "").strip().lower(), str(value or "").upper())


def activation_choice(value: str) -> str:
    """config 里的激活值 → 下拉框显示文字。"""
    name = str(value or "l2").strip().lower()
    for text, key in ACTIVATION_CHOICES.items():
        if key == name:
            return text
    return f"按住 {button_label(name)}"


def activation_value(choice: str) -> str:
    """下拉框显示文字 → config 里的激活值。"""
    return ACTIVATION_CHOICES.get(choice, "l2")


MODE_LABELS = {"键鼠": "keyboard", "手柄": "controller"}
MODE_LABELS_REVERSE = {value: key for key, value in MODE_LABELS.items()}


def build_controller_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    # ---------------------------------------------------------- 连接状态
    status_card = build_card(
        page,
        "手柄",
        "手柄的连接与设置都在这一页；PS5 连接在「连接」页。用 USB 线或蓝牙把手柄接到电脑",
    )
    status_card.pack(fill="x", pady=(0, T.S2))
    inner = ctk.CTkFrame(status_card, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))

    status_row = ctk.CTkFrame(inner, fg_color="transparent")
    status_row.pack(fill="x")
    app._controller_dot = ctk.CTkLabel(
        status_row, text="●", font=font(T.SM), text_color=T.TEXT_FAINT, width=16
    )
    app._controller_dot.pack(side="left")
    app._controller_status = ctk.CTkLabel(
        status_row, text="未检测到手柄", font=font(T.SM), text_color=T.TEXT, anchor="w"
    )
    app._controller_status.pack(side="left")
    app._controller_detail = ctk.CTkLabel(
        status_row, text="", font=font(T.XS), text_color=T.TEXT_FAINT, anchor="w"
    )
    app._controller_detail.pack(side="left", padx=T.S2)
    secondary_button(
        status_row, "重新检测", app.refresh_controller, width=88, height=26
    ).pack(side="right")
    app._diagnostics_var = tk.BooleanVar(value=False)
    switch(status_row, "抓包诊断", app._diagnostics_var, app._toggle_diagnostics).pack(
        side="right", padx=T.S2
    )
    # 没连上手柄时显示怎么连（USB / 蓝牙配对按键），连上后自动隐藏
    app._controller_help = ctk.CTkLabel(
        inner,
        text="",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        anchor="w",
        justify="left",
        wraplength=700,
    )

    remote_row = ctk.CTkFrame(inner, fg_color="transparent")
    remote_row.pack(fill="x", pady=(T.S2, 0))
    ctk.CTkLabel(
        remote_row,
        text="PS5 会话：在「连接」页查看 / 断开",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left")

    # ---------------------------------------------------------- 陀螺仪
    gyro_card = build_card(
        page,
        "陀螺仪 → 右摇杆",
        "按住设定的激活键时用陀螺仪微调视角，松手立刻停；灵敏度 / 死区 / 平滑都可以调",
    )
    gyro_card.pack(fill="x", pady=(0, T.S2))
    gyro_inner = ctk.CTkFrame(gyro_card, fg_color="transparent")
    gyro_inner.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))

    gyro_row = ctk.CTkFrame(gyro_inner, fg_color="transparent")
    gyro_row.pack(fill="x")
    app._gyro_var = tk.BooleanVar(value=app._config.controller.gyro.enabled)
    switch(gyro_row, "启用陀螺仪", app._gyro_var, app._toggle_gyro).pack(side="left")

    ctk.CTkLabel(
        gyro_row, text="激活键", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(T.S4, T.S2))
    app._gyro_activation_var = tk.StringVar(
        value=activation_choice(app._config.controller.gyro.activation)
    )
    ctk.CTkOptionMenu(
        gyro_row,
        variable=app._gyro_activation_var,
        values=list(ACTIVATION_CHOICES) + [CUSTOM_CHOICE, CAPTURE_HINT],
        command=app.set_gyro_activation,
        width=110,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    ).pack(side="left")

    secondary_button(gyro_row, "校准陀螺仪", app.calibrate_gyro, width=96, height=28).pack(
        side="right"
    )
    app._gyro_calibration_label = ctk.CTkLabel(
        gyro_row, text="未校准", font=font(T.XS), text_color=T.TEXT_FAINT
    )
    app._gyro_calibration_label.pack(side="right", padx=T.S2)

    grid1 = ctk.CTkFrame(gyro_inner, fg_color="transparent")
    grid1.pack(fill="x", pady=(T.S2, 0))
    for index in range(3):
        grid1.columnconfigure(index, weight=1, uniform="gyro")
    cell = ctk.CTkFrame(grid1, fg_color="transparent")
    cell.grid(row=0, column=0, sticky="w", padx=(0, T.S3))
    app._gyro_sens_x_label = _slider_cell(
        app,
        cell,
        f"水平灵敏度 {app._config.controller.gyro.sensitivity_x:.2f}",
        app._config.controller.gyro.sensitivity_x,
        0.1,
        3.0,
        app._apply_gyro_sens_x,
    )
    cell = ctk.CTkFrame(grid1, fg_color="transparent")
    cell.grid(row=0, column=1, sticky="w", padx=(0, T.S3))
    app._gyro_sens_y_label = _slider_cell(
        app,
        cell,
        f"垂直灵敏度 {app._config.controller.gyro.sensitivity_y:.2f}",
        app._config.controller.gyro.sensitivity_y,
        0.1,
        3.0,
        app._apply_gyro_sens_y,
    )
    cell = ctk.CTkFrame(grid1, fg_color="transparent")
    cell.grid(row=0, column=2, sticky="w")
    app._gyro_deadzone_label = _slider_cell(
        app,
        cell,
        f"死区 {app._config.controller.gyro.deadzone:.3f}",
        app._config.controller.gyro.deadzone,
        0.0,
        0.1,
        app._apply_gyro_deadzone,
    )

    bottom_row = ctk.CTkFrame(gyro_inner, fg_color="transparent")
    bottom_row.pack(fill="x", pady=(T.S1, 0))
    smooth_cell = ctk.CTkFrame(bottom_row, fg_color="transparent")
    smooth_cell.pack(side="left")
    app._gyro_smoothing_label = _slider_cell(
        app,
        smooth_cell,
        f"平滑 {app._config.controller.gyro.smoothing:.2f}",
        app._config.controller.gyro.smoothing,
        0.0,
        0.9,
        app._apply_gyro_smoothing,
        width=150,
    )
    app._gyro_readout = ctk.CTkLabel(
        bottom_row,
        text="陀 +0.00/+0.00/+0.00  摇 +0.00/+0.00",
        font=font(T.XS, mono=True),
        text_color=T.TEXT_FAINT,
    )
    app._gyro_readout.pack(side="right")
    # 反 X / 反 Y 放在平滑后面，既省高度也不会挤到校准按钮
    invert_frame = ctk.CTkFrame(bottom_row, fg_color="transparent")
    invert_frame.pack(side="left", padx=(T.S4, 0))
    app._gyro_invert_x_var = tk.BooleanVar(value=app._config.controller.gyro.invert_x)
    switch(invert_frame, "反 X", app._gyro_invert_x_var, app._toggle_gyro_invert_x).pack(
        side="left"
    )
    app._gyro_invert_y_var = tk.BooleanVar(value=app._config.controller.gyro.invert_y)
    switch(invert_frame, "反 Y", app._gyro_invert_y_var, app._toggle_gyro_invert_y).pack(
        side="left", padx=T.S3
    )

    # ---------------------------------------------------------- 震动 / 扳机
    feedback_card = build_card(
        page, "震动与自适应扳机", "USB 连接：震动（实验性）+ 自适应扳机；蓝牙：仅自适应扳机"
    )
    feedback_card.pack(fill="x")
    fb_inner = ctk.CTkFrame(feedback_card, fg_color="transparent")
    fb_inner.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))

    rumble_row = ctk.CTkFrame(fb_inner, fg_color="transparent")
    rumble_row.pack(fill="x")
    app._rumble_var = tk.BooleanVar(value=app._config.controller.rumble_enabled)
    switch(rumble_row, "震动转发", app._rumble_var, app._toggle_rumble).pack(side="left")
    ctk.CTkLabel(
        rumble_row, text="强度", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(T.S4, T.S2))
    app._rumble_gain_label = _slider_cell(
        app,
        rumble_row,
        f"{app._config.controller.rumble_gain:.2f}",
        app._config.controller.rumble_gain,
        0.0,
        2.0,
        app._apply_rumble_gain,
        width=120,
        horizontal=True,
    )
    app._haptics_var = tk.BooleanVar(value=app._config.controller.haptics_usb)
    switch(rumble_row, "USB 震动（实验）", app._haptics_var, app._toggle_haptics_usb).pack(
        side="right", padx=T.S2
    )
    secondary_button(rumble_row, "试一下", app.test_rumble, width=72, height=28).pack(
        side="right"
    )

    trigger_row = ctk.CTkFrame(fb_inner, fg_color="transparent")
    trigger_row.pack(fill="x", pady=(T.S2, 0))
    app._adaptive_trigger_var = tk.BooleanVar(
        value=app._config.controller.adaptive_triggers
    )
    switch(
        trigger_row,
        "自适应扳机",
        app._adaptive_trigger_var,
        app._toggle_adaptive_triggers,
    ).pack(side="left")
    ctk.CTkLabel(
        trigger_row, text="试效果", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(T.S4, T.S2))
    app._trigger_effect_var = tk.StringVar(value="阻力")
    ctk.CTkOptionMenu(
        trigger_row,
        variable=app._trigger_effect_var,
        values=["关闭", "阻力", "开枪", "震动", "拉弓"],
        width=84,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left")
    app._trigger_side_var = tk.StringVar(value="R2")
    ctk.CTkOptionMenu(
        trigger_row,
        variable=app._trigger_side_var,
        values=["R2", "L2", "双"],
        width=64,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left", padx=T.S2)
    secondary_button(trigger_row, "应用", app.apply_trigger_effect, width=56, height=28).pack(
        side="left"
    )
    secondary_button(trigger_row, "停止", app.stop_trigger_effect, width=56, height=28).pack(
        side="left", padx=T.S2
    )
    ctk.CTkLabel(
        trigger_row,
        text="开启后才会写入手柄",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left", padx=T.S3)

    return page


def _slider_cell(
    app,
    parent,
    caption: str,
    value: float,
    from_: float,
    to: float,
    command,
    width: int = 140,
    horizontal: bool = False,
) -> ctk.CTkLabel:
    """一行小滑条：上面是标题，下面是滑条（返回标题 label 方便更新文字）。"""
    label = ctk.CTkLabel(
        parent,
        text=caption,
        font=font(T.SM if horizontal else T.XS),
        text_color=T.TEXT_DIM,
        anchor="w",
    )
    slider = ctk.CTkSlider(
        parent,
        from_=from_,
        to=to,
        number_of_steps=max(2, int((to - from_) * 100)),
        command=command,
        width=width,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    slider.set(value)
    if horizontal:
        label.pack(side="left", padx=(0, T.S2))
        slider.pack(side="left")
    else:
        label.pack(anchor="w")
        slider.pack(anchor="w", pady=(T.S1, 0))
    slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")
    return label


def refresh_activation(app) -> None:
    """把激活键下拉框同步成当前配置（自定义键捕获完成后调用）。"""
    app._gyro_activation_var.set(
        activation_choice(app._config.controller.gyro.activation)
    )


def refresh(app) -> None:
    """按手柄状态刷新页面（由 app 的轮询调用）。"""
    state = app.controller_snapshot()
    connected = state is not None
    if connected:
        app._controller_dot.configure(text_color=T.OK)
        # 电量直接写在状态行里，进手柄页第一眼就能看到
        status_text = app._controller.device_label or "手柄已连接"
        if state.battery is not None:
            status_text += f" · 电量 {state.battery}%"
        app._controller_status.configure(text=status_text, text_color=T.TEXT)
        transport = "USB" if state.transport == "usb" else "蓝牙"
        parts = [transport]
        if state.charging:
            parts.append("充电中")
        app._controller_detail.configure(text=" · ".join(parts))
        app._controller_help.pack_forget()
        app._gyro_readout.configure(
            text=(
                f"陀 {state.gyro[0]:+.2f}/{state.gyro[1]:+.2f}/{state.gyro[2]:+.2f}"
                f"  摇 {app._gyro_output[0]:+.2f}/{app._gyro_output[1]:+.2f}"
            )
        )
    else:
        app._controller_dot.configure(text_color=T.TEXT_FAINT)
        app._controller_status.configure(text="未检测到手柄", text_color=T.TEXT_DIM)
        error = app._controller.error if app._controller else ""
        app._controller_detail.configure(text=error or "USB 或蓝牙连接")
        app._controller_help.configure(
            text=(
                "USB：用数据线把手柄接到电脑，插上自动识别\n"
                "蓝牙：按住 PS 键 + 创建键（Share，触摸板左侧小键）约 3 秒，灯条快闪后，"
                "在 Windows「设置 → 蓝牙和设备 → 添加设备」里选 Wireless Controller"
            )
        )
        app._controller_help.pack(fill="x", pady=(T.S1, 0))
        app._gyro_readout.configure(text="陀 +0.00/+0.00/+0.00  摇 +0.00/+0.00")
    app._gyro_calibration_label.configure(
        text="已校准" if app._gyro_calibrated else "未校准"
    )
