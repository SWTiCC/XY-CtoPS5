"""运行页：捕获状态、手感调参、捕获目标。

布局目标是一屏放得下（默认窗口 940×760）：整页排成一张卡，按
「状态 / 左摇杆 / 鼠标 / 扳机 / 捕获目标」分段，滑条走三列网格，
避免旧版那样横向被窗口裁掉、纵向把日志区挤没。

只负责"长什么样"；回调都在 app.py，尺寸与颜色来自 theme.py。
手感调参区（滑条）在 run_tuning_ui.py。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import run_tuning_ui
from . import theme as T
from . import windows
from .ui_widgets import build_card, divider, font, primary_button, secondary_button, switch


def build_run_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)
    card = build_card(page)
    card.pack(fill="x")
    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=T.S2)

    _build_status(app, inner)
    run_tuning_ui.build_mouse_tuning(app, inner)
    run_tuning_ui.build_triggers(app, inner)
    _build_target(app, inner)

    ctk.CTkLabel(
        inner,
        text="捕获时拦截键鼠 · F8 开关捕获 · 关闭窗口自动释放会话",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        anchor="w",
    ).pack(fill="x", pady=(T.S2, 0))
    return page


# ---------------------------------------------------------------- 状态
def _build_status(app, parent) -> None:
    app._run_title = ctk.CTkLabel(
        parent,
        text="未连接主机",
        font=font(T.XXL, bold=True),
        text_color=T.TEXT,
        anchor="w",
    )
    app._run_title.pack(fill="x")
    app._run_subtitle = ctk.CTkLabel(
        parent,
        text="先到「连接」页建立会话，再回到这里开始捕获",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        anchor="w",
    )
    app._run_subtitle.pack(fill="x", pady=(T.S1, T.S1))

    controls = ctk.CTkFrame(parent, fg_color="transparent")
    controls.pack(fill="x")
    app._capture_button = primary_button(
        controls, "开始捕获", app._toggle_capture, width=160
    )
    app._capture_button.pack(side="left")
    app._capture_button.configure(state="disabled")
    app._topmost_var = tk.BooleanVar(value=False)
    switch(controls, "窗口置顶", app._topmost_var, app._toggle_topmost).pack(
        side="left", padx=T.S4
    )
    app._stick_value_label = ctk.CTkLabel(
        controls,
        text=f"左摇杆幅度 {app._config.left_stick.value:.2f}",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    app._stick_value_label.pack(side="left")
    # 过渡速度也是左摇杆的设置，挨着幅度放在同一行
    run_tuning_ui.build_left_stick(app, controls)

    info = ctk.CTkFrame(parent, fg_color="transparent")
    info.pack(fill="x", pady=(T.S1, 0))
    app._input_state_label = ctk.CTkLabel(
        info, text="输入：未捕获", font=font(T.XS, mono=True), text_color=T.TEXT_FAINT
    )
    app._input_state_label.pack(side="left")
    app._stick_state_label = ctk.CTkLabel(
        info,
        text="摇杆  左 (0.00, 0.00)   右 (0.00, 0.00)",
        font=font(T.XS, mono=True),
        text_color=T.TEXT_FAINT,
    )
    app._stick_state_label.pack(side="left", padx=T.S4)


# ---------------------------------------------------------------- 捕获目标
def _build_target(app, parent) -> None:
    divider(parent)
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x")
    ctk.CTkLabel(
        row, text="捕获时切到窗口", font=font(T.SM), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    app._target_var = tk.StringVar(value=app._config.target_window or "（不切换）")
    app._target_box = ctk.CTkOptionMenu(
        row,
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
    secondary_button(row, "刷新", app.refresh_targets, width=56, height=30).pack(
        side="left", padx=T.S2
    )
    ctk.CTkLabel(
        row, text="留空则由透明层保持焦点", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(side="left")
