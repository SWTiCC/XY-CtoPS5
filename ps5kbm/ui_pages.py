"""界面布局：顶栏、侧边导航、三个页面、日志区。

只负责“长什么样”与控件摆放，业务逻辑仍在 app.py。
所有颜色 / 字号 / 间距 / 圆角都来自 theme.py，不写魔法值。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme as T
from . import windows

_CURVE_LABELS = {
    "linear": "线性",
    "quadratic": "二次",
    "cubic": "三次",
    "power": "幂",
}


def curve_label(value: str) -> str:
    return _CURVE_LABELS.get((value or "linear").lower(), "线性")
from .ui_common import describe_action, format_stick_keys
from .ui_widgets import (
    build_card,
    build_status_pill,
    field,
    font,
    ghost_button,
    primary_button,
    secondary_button,
)


# ---------------------------------------------------------------- 顶栏与侧栏
def build_topbar(app, root) -> None:
    bar = ctk.CTkFrame(root, fg_color=T.BG, corner_radius=0, height=72)
    bar.pack(fill="x", padx=T.S6, pady=(T.S4, 0))
    bar.pack_propagate(False)

    brand = ctk.CTkFrame(bar, fg_color="transparent")
    brand.pack(side="left", pady=T.S2)
    ctk.CTkLabel(
        brand, text="XY-CtoPS5", font=font(T.XXL, bold=True), text_color=T.TEXT
    ).pack(anchor="w")
    ctk.CTkLabel(
        brand, text="键鼠玩 PS5 · Remote Play 输入通道", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(anchor="w")

    pill, dot, text = build_status_pill(bar)
    pill.pack(side="right", pady=T.S4)
    app._status_dot = dot
    app._status_text = text


def build_sidebar(app, body) -> None:
    sidebar = ctk.CTkFrame(body, fg_color=T.BG, corner_radius=0, width=T.SIDEBAR_WIDTH)
    sidebar.pack(side="left", fill="y", padx=(T.S6, 0))
    sidebar.pack_propagate(False)

    app._nav_buttons: dict[str, ctk.CTkButton] = {}
    items = (("connect", "连接"), ("mapping", "映射"), ("run", "运行"))
    for key, label in items:
        button = ctk.CTkButton(
            sidebar,
            text=label,
            anchor="w",
            height=40,
            corner_radius=T.R_SM,
            fg_color="transparent",
            hover_color=T.SURFACE_HOVER,
            text_color=T.TEXT_DIM,
            font=font(T.SM),
            command=lambda name=key: app.show_page(name),
        )
        button.pack(fill="x", pady=(0, T.S1))
        app._nav_buttons[key] = button

    ctk.CTkLabel(
        sidebar, text="F8 捕获", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(side="bottom", anchor="w", pady=T.S2)
    ctk.CTkLabel(
        sidebar, text="v0.2", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(side="bottom", anchor="w")


def set_nav_state(app, active: str) -> None:
    for key, button in app._nav_buttons.items():
        if key == active:
            button.configure(fg_color=T.ACCENT_SOFT, text_color=T.TEXT)
        else:
            button.configure(fg_color="transparent", text_color=T.TEXT_DIM)


# ---------------------------------------------------------------- 连接页
def build_connect_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    host_card = build_card(page, "主机", "扫描局域网，或直接填 PS5 的 IP")
    host_card.pack(fill="x", pady=(0, T.S3))
    row = ctk.CTkFrame(host_card, fg_color="transparent")
    row.pack(fill="x", padx=T.S4, pady=T.S3)
    app._host_entry = field(row, "PS5 IP", width=180, textvariable=app._host_var)
    scan = secondary_button(row, "扫描局域网", app._scan_devices, width=110)
    scan.pack(side="left", pady=(T.S4, 0))

    app._device_list = ctk.CTkScrollableFrame(
        host_card, fg_color=T.SURFACE_HOVER, corner_radius=T.R_SM, height=96
    )
    app._device_list.pack(fill="x", padx=T.S4, pady=(0, T.S4))
    ctk.CTkLabel(
        app._device_list,
        text="还没有扫描结果",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(anchor="w", padx=T.S2, pady=T.S2)

    pair_card = build_card(page, "配对", "首次使用才需要；凭据会保存在 credentials.json")
    pair_card.pack(fill="x", pady=(0, T.S3))
    pair_row = ctk.CTkFrame(pair_card, fg_color="transparent")
    pair_row.pack(fill="x", padx=T.S4, pady=T.S3)
    account = field(pair_row, "PSN Account ID", width=220, textvariable=app._account_var)
    pin = field(pair_row, "8 位 PIN", width=110, textvariable=app._pin_var)
    secondary_button(pair_row, "配对", app._pair_console, width=80).pack(
        side="left", pady=(T.S4, 0)
    )
    ctk.CTkLabel(
        pair_card,
        text="Account ID 用 run.cmd login 获取\nPIN 在 PS5：设置 → 系统 → 远程游玩 → 关联设备",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=T.S4, pady=(0, T.S4))

    action_row = ctk.CTkFrame(page, fg_color="transparent")
    action_row.pack(fill="x", pady=(T.S2, 0))
    app._connect_button = primary_button(action_row, "连接主机", app._connect, width=180)
    app._connect_button.pack(side="left")
    app._disconnect_button = secondary_button(action_row, "断开", app._disconnect, width=96)
    app._disconnect_button.pack(side="left", padx=T.S2)
    app._disconnect_button.configure(state="disabled")
    return page


# ---------------------------------------------------------------- 映射页
def build_mapping_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    toolbar = ctk.CTkFrame(page, fg_color="transparent")
    toolbar.pack(fill="x", pady=(0, T.S3))
    ctk.CTkLabel(
        toolbar, text="预设", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    app._preset_box = ctk.CTkComboBox(
        toolbar,
        variable=app._preset_var,
        values=app._preset_values,
        width=140,
        height=34,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        border_color=T.BORDER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
        state="readonly",
    )
    app._preset_box.pack(side="left")
    secondary_button(toolbar, "应用预设", app._apply_preset, width=92).pack(
        side="left", padx=T.S2
    )
    primary_button(toolbar, "保存配置", app._save_config, width=104, height=34).pack(
        side="right"
    )
    secondary_button(
        toolbar, "保存为预设", app.save_as_preset, width=104, height=34
    ).pack(side="right", padx=(0, T.S2))

    mode_row = ctk.CTkFrame(page, fg_color="transparent")
    mode_row.pack(fill="x", pady=(0, T.S2))
    ctk.CTkLabel(
        mode_row, text="编辑模式", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    app._mode_var = tk.StringVar(value=app._mode_label(app._edit_mode))
    app._mode_box = ctk.CTkOptionMenu(
        mode_row,
        variable=app._mode_var,
        values=[app._mode_label(name) for name in app._config.modes],
        command=app.choose_mode,
        width=140,
        height=32,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    )
    app._mode_box.pack(side="left")
    secondary_button(mode_row, "新建", app.add_mode, width=56, height=30).pack(
        side="left", padx=T.S2
    )
    secondary_button(mode_row, "重命名", app.rename_mode, width=70, height=30).pack(
        side="left"
    )
    secondary_button(mode_row, "删除", app.remove_mode, width=56, height=30).pack(
        side="left", padx=T.S2
    )
    app._mode_switch_btn = secondary_button(
        mode_row,
        f"切换键 {app._config.mode_switch.upper()}",
        app.set_mode_switch_key,
        width=120,
        height=30,
    )
    app._mode_switch_btn.pack(side="right")

    list_card = build_card(page, "按键映射", "双击或点编辑修改；支持单按钮、组合键、序列")
    list_card.pack(fill="both", expand=True)
    app._mapping_list = ctk.CTkScrollableFrame(
        list_card, fg_color="transparent", corner_radius=0
    )
    app._mapping_list.pack(fill="both", expand=True, padx=T.S2, pady=(T.S1, T.S2))

    bottom = ctk.CTkFrame(page, fg_color="transparent")
    bottom.pack(fill="x", pady=(T.S3, T.S2))
    secondary_button(bottom, "添加映射", app._add_mapping, width=110).pack(side="left")
    ctk.CTkLabel(
        bottom,
        text="键名写法：w / space / esc / mouse_x1",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left", padx=T.S3)

    stick_card = build_card(
        page,
        "左摇杆",
        "方向键推左摇杆；想切换摇杆幅度，在上面的映射表里加一条「摇杆幅度」动作",
    )
    stick_card.pack(fill="x")
    keys_row = ctk.CTkFrame(stick_card, fg_color="transparent")
    keys_row.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))
    ctk.CTkLabel(
        keys_row, text="方向键", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left")
    app._stick_keys_label = ctk.CTkLabel(
        keys_row,
        text=format_stick_keys(app._mode_cfg().keyboard_sticks),
        font=font(T.SM, mono=True),
        text_color=T.TEXT,
    )
    app._stick_keys_label.pack(side="left", padx=T.S3)
    secondary_button(keys_row, "编辑", app.edit_stick_keys, width=56, height=26).pack(
        side="right"
    )
    return page


def refresh_mapping_list(app) -> None:
    for child in app._mapping_list.winfo_children():
        child.destroy()
    rows = app._binding_rows()
    if not rows:
        ctk.CTkLabel(
            app._mapping_list,
            text="还没有映射，点下面的「添加映射」开始",
            font=font(T.SM),
            text_color=T.TEXT_FAINT,
        ).pack(anchor="w", padx=T.S3, pady=T.S3)
        return
    for source, value in rows:
        row = ctk.CTkFrame(app._mapping_list, fg_color="transparent", height=38)
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(
            row,
            text=source,
            width=180,
            anchor="w",
            font=font(T.SM, mono=True),
            text_color=T.TEXT,
        ).pack(side="left", padx=(T.S3, 0))
        ctk.CTkLabel(
            row,
            text=describe_action(value),
            anchor="w",
            font=font(T.SM),
            text_color=T.TEXT_DIM,
        ).pack(side="left", padx=T.S2, fill="x", expand=True)
        button = secondary_button(
            row, "编辑", lambda name=source: app.edit_mapping(name), width=56, height=28
        )
        button.pack(side="right", padx=(0, T.S1))
        remove = ctk.CTkButton(
            row,
            text="删除",
            width=56,
            height=28,
            corner_radius=T.R_SM,
            fg_color="transparent",
            hover_color=T.BORDER,
            text_color=T.TEXT_FAINT,
            font=font(T.XS),
            command=lambda name=source: app.remove_mapping(name),
        )
        remove.pack(side="right", padx=(0, T.S1))
    app._mapping_list.update_idletasks()


def refresh_stick_keys(app) -> None:
    app._stick_keys_label.configure(
        text=format_stick_keys(app._mode_cfg().keyboard_sticks)
    )


def refresh_mode_ui(app) -> None:
    """同步模式下拉框的选项与当前编辑模式。"""
    app._mode_var.set(app._mode_label(app._edit_mode))
    if getattr(app, "_mode_box", None) is not None:
        app._mode_box.configure(
            values=[app._mode_label(name) for name in app._config.modes]
        )
    if getattr(app, "_mode_switch_btn", None) is not None:
        app._mode_switch_btn.configure(
            text=f"切换键 {app._config.mode_switch.upper()}"
        )


# ---------------------------------------------------------------- 运行页
def build_run_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    state_card = build_card(page)
    state_card.pack(fill="x", pady=(0, T.S3))
    inner = ctk.CTkFrame(state_card, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=T.S4)
    app._run_title = ctk.CTkLabel(
        inner, text="未连接主机", font=font(T.XXL, bold=True), text_color=T.TEXT
    )
    app._run_title.pack(anchor="w")
    app._run_subtitle = ctk.CTkLabel(
        inner,
        text="先到「连接」页建立会话，再回到这里开始捕获",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._run_subtitle.pack(anchor="w", pady=(T.S1, T.S4))

    controls = ctk.CTkFrame(inner, fg_color="transparent")
    controls.pack(fill="x")
    app._capture_button = primary_button(controls, "开始捕获", app._toggle_capture, width=180)
    app._capture_button.pack(side="left")
    app._capture_button.configure(state="disabled")
    app._stick_value_label = ctk.CTkLabel(
        controls,
        text=f"左摇杆幅度 {app._config.left_stick.value:.2f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._stick_value_label.pack(side="left", padx=T.S6)
    app._topmost_var = tk.BooleanVar(value=False)
    ctk.CTkSwitch(
        controls,
        text="窗口置顶",
        variable=app._topmost_var,
        command=app._toggle_topmost,
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    ).pack(side="left", padx=T.S2)

    # 手感微调：左摇杆过渡速度 + 鼠标死区
    tune_row = ctk.CTkFrame(inner, fg_color="transparent")
    tune_row.pack(fill="x", pady=(T.S2, 0))
    app._stick_ramp_var = tk.DoubleVar(value=app._config.left_stick.ramp)
    app._stick_ramp_label = ctk.CTkLabel(
        tune_row,
        text=f"过渡 {app._config.left_stick.ramp:.1f}/s",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._stick_ramp_label.pack(side="left")
    ramp_slider = ctk.CTkSlider(
        tune_row,
        from_=0.0,
        to=12.0,
        number_of_steps=24,
        variable=app._stick_ramp_var,
        command=app._apply_stick_ramp,
        width=110,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    ramp_slider.pack(side="left", padx=(T.S1, T.S6))
    # 拖动时只更新内存，松开才写盘：每次拖动都 persist 会让 UI 一顿一顿
    ramp_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    app._deadzone_var = tk.DoubleVar(value=app._config.mouse.deadzone)
    app._deadzone_label = ctk.CTkLabel(
        tune_row,
        text=f"死区 {app._config.mouse.deadzone:.3f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._deadzone_label.pack(side="left")
    deadzone_slider = ctk.CTkSlider(
        tune_row,
        from_=0.0,
        to=0.2,
        number_of_steps=40,
        variable=app._deadzone_var,
        command=app._apply_deadzone,
        width=110,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    deadzone_slider.pack(side="left", padx=(T.S1, 0))
    deadzone_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    app._sens_var = tk.DoubleVar(value=app._config.mouse.sensitivity)
    app._sens_label = ctk.CTkLabel(
        tune_row,
        text=f"灵敏度 {app._config.mouse.sensitivity:.1f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._sens_label.pack(side="left", padx=(T.S6, 0))
    sens_slider = ctk.CTkSlider(
        tune_row,
        from_=0.2,
        to=6.0,
        number_of_steps=58,
        variable=app._sens_var,
        command=app._apply_sensitivity,
        width=110,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    sens_slider.pack(side="left", padx=(T.S1, 0))
    sens_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    # 第二行微调：两段灵敏度 + 平滑 + 曲线类型
    tune_row2 = ctk.CTkFrame(inner, fg_color="transparent")
    tune_row2.pack(fill="x", pady=(T.S2, 0))

    app._slow_sens_var = tk.DoubleVar(value=app._config.mouse.slow_sensitivity)
    app._slow_sens_label = ctk.CTkLabel(
        tune_row2,
        text=f"慢灵敏 {app._config.mouse.slow_sensitivity:.2f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._slow_sens_label.pack(side="left")
    slow_slider = ctk.CTkSlider(
        tune_row2,
        from_=0.2,
        to=3.0,
        number_of_steps=28,
        variable=app._slow_sens_var,
        command=app._apply_slow_sensitivity,
        width=100,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    slow_slider.pack(side="left", padx=(T.S1, T.S6))
    slow_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    app._fast_sens_var = tk.DoubleVar(value=app._config.mouse.fast_sensitivity)
    app._fast_sens_label = ctk.CTkLabel(
        tune_row2,
        text=f"快灵敏 {app._config.mouse.fast_sensitivity:.1f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._fast_sens_label.pack(side="left")
    fast_slider = ctk.CTkSlider(
        tune_row2,
        from_=0.5,
        to=6.0,
        number_of_steps=55,
        variable=app._fast_sens_var,
        command=app._apply_fast_sensitivity,
        width=100,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    fast_slider.pack(side="left", padx=(T.S1, T.S6))
    fast_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    app._smoothing_var = tk.DoubleVar(value=app._config.mouse.smoothing)
    app._smoothing_label = ctk.CTkLabel(
        tune_row2,
        text=f"平滑 {app._config.mouse.smoothing:.2f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._smoothing_label.pack(side="left")
    smooth_slider = ctk.CTkSlider(
        tune_row2,
        from_=0.0,
        to=0.6,
        number_of_steps=60,
        variable=app._smoothing_var,
        command=app._apply_smoothing,
        width=100,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    smooth_slider.pack(side="left", padx=(T.S1, T.S6))
    smooth_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")

    app._curve_var = tk.StringVar(value=curve_label(app._config.mouse.curve_type))
    ctk.CTkOptionMenu(
        tune_row2,
        variable=app._curve_var,
        values=["线性", "二次", "三次", "幂"],
        command=app._choose_curve,
        width=104,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    ).pack(side="left")

    # 第三行：R2 输出深度（按下 R2 时按此深度送出）
    trigger_row = ctk.CTkFrame(inner, fg_color="transparent")
    trigger_row.pack(fill="x", pady=(T.S2, 0))
    app._r2_var = tk.DoubleVar(value=1.0)
    app._r2_label = ctk.CTkLabel(
        trigger_row,
        text="R2 1.0",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._r2_label.pack(side="left")
    r2_slider = ctk.CTkSlider(
        trigger_row,
        from_=0.0,
        to=1.0,
        number_of_steps=100,
        variable=app._r2_var,
        command=app._apply_r2,
        width=220,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    r2_slider.pack(side="left", padx=(T.S1, T.S6))
    r2_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")
    ctk.CTkLabel(
        trigger_row,
        text="按下 R2 时按此深度输出；捕获时滚轮可调",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left")

    # 鼠标视角总开关（只影响右摇杆，不动键盘与按键）
    mouse_row = ctk.CTkFrame(inner, fg_color="transparent")
    mouse_row.pack(fill="x", pady=(T.S2, 0))
    app._mouse_enabled_var = tk.BooleanVar(value=app._config.mouse.enabled)
    ctk.CTkSwitch(
        mouse_row,
        text="启用鼠标视角",
        variable=app._mouse_enabled_var,
        command=app._toggle_mouse_view,
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    ).pack(side="left")
    ctk.CTkLabel(
        mouse_row,
        text="关掉后鼠标不再控制右摇杆，键盘/按键照常",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left", padx=T.S3)

    app._flick_var = tk.BooleanVar(value=app._config.mouse.flick_enabled)
    ctk.CTkSwitch(
        mouse_row,
        text="Flick Stick 快速转身",
        variable=app._flick_var,
        command=app._toggle_flick,
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    ).pack(side="left", padx=(T.S6, 0))

    # 第四行：L2 输出深度（键盘 - / = 或滑条调整）
    l2_row = ctk.CTkFrame(inner, fg_color="transparent")
    l2_row.pack(fill="x", pady=(T.S2, 0))
    app._l2_var = tk.DoubleVar(value=1.0)
    app._l2_label = ctk.CTkLabel(
        l2_row,
        text="L2 1.0",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._l2_label.pack(side="left")
    l2_slider = ctk.CTkSlider(
        l2_row,
        from_=0.0,
        to=1.0,
        number_of_steps=100,
        variable=app._l2_var,
        command=app._apply_l2,
        width=220,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )
    l2_slider.pack(side="left", padx=(T.S1, T.S6))
    l2_slider.bind("<ButtonRelease-1>", app._commit_sliders, add="+")
    ctk.CTkLabel(
        l2_row,
        text="按下 L2 时按此深度输出；捕获时按 - / = 调整",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left")

    app._input_state_label = ctk.CTkLabel(
        inner,
        text="输入：未捕获",
        font=font(T.XS, mono=True),
        text_color=T.TEXT_FAINT,
        anchor="w",
    )
    app._input_state_label.pack(anchor="w", pady=(T.S2, 0))

    target_row = ctk.CTkFrame(inner, fg_color="transparent")
    target_row.pack(fill="x", pady=(T.S2, 0))
    ctk.CTkLabel(
        target_row,
        text="捕获时切到窗口",
        font=font(T.XS),
        text_color=T.TEXT_DIM,
    ).pack(side="left", padx=(0, T.S2))
    app._target_var = tk.StringVar(value=app._config.target_window or "（不切换）")
    app._target_box = ctk.CTkOptionMenu(
        target_row,
        variable=app._target_var,
        values=["（不切换）"]
        + [title for _, title in windows.list_windows(exclude="XY-CtoPS5")],
        command=app._choose_target,
        width=300,
        height=30,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    )
    app._target_box.pack(side="left")
    secondary_button(
        target_row, "刷新", app.refresh_targets, width=56, height=30
    ).pack(side="left", padx=T.S2)
    ctk.CTkLabel(
        target_row,
        text="留空则由透明层保持焦点",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left")

    app._stick_state_label = ctk.CTkLabel(
        inner,
        text="摇杆  左 (0.00, 0.00)   右 (0.00, 0.00)",
        font=font(T.XS, mono=True),
        text_color=T.TEXT_FAINT,
        anchor="w",
    )
    app._stick_state_label.pack(anchor="w")

    tip_card = build_card(page, "工作方式")
    tip_card.pack(fill="x")
    tips = (
        "捕获开启后，键盘与鼠标事件被拦截，不再传给 Windows。",
        "鼠标位移从设备原始报文读取，光标不会乱跑。",
        "F8 开关捕获；摇杆幅度档位在「映射」页配置；关闭窗口会自动释放会话。",
    )
    for tip in tips:
        row = ctk.CTkFrame(tip_card, fg_color="transparent")
        row.pack(fill="x", padx=T.S4, pady=(0, T.S2))
        ctk.CTkLabel(
            row, text="·", font=font(T.SM), text_color=T.TEXT_FAINT, width=12
        ).pack(side="left")
        ctk.CTkLabel(
            row,
            text=tip,
            font=font(T.SM),
            text_color=T.TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(side="left", fill="x", expand=True)
    ctk.CTkFrame(tip_card, fg_color="transparent", height=T.S2).pack()
    return page


# ---------------------------------------------------------------- 日志区
def build_log_panel(app, root) -> None:
    panel = ctk.CTkFrame(root, fg_color=T.SURFACE, corner_radius=T.R_LG)
    panel.pack(fill="x", padx=T.S6, pady=(T.S2, T.S4))

    header = ctk.CTkFrame(panel, fg_color="transparent")
    header.pack(fill="x", padx=T.S4, pady=(T.S2, 0))
    ctk.CTkLabel(
        header, text="日志", font=font(T.SM, bold=True), text_color=T.TEXT
    ).pack(side="left")
    clear = ctk.CTkButton(
        header,
        text="清空",
        width=52,
        height=24,
        corner_radius=T.R_XS,
        fg_color="transparent",
        hover_color=T.SURFACE_HOVER,
        text_color=T.TEXT_FAINT,
        font=font(T.XS),
        command=app.clear_logs,
    )
    clear.pack(side="right")

    app._log_text = ctk.CTkTextbox(
        panel,
        height=104,
        fg_color=T.BG,
        corner_radius=T.R_SM,
        border_width=0,
        text_color=T.TEXT_DIM,
        font=font(T.XS, mono=True),
        wrap="word",
    )
    app._log_text.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))
