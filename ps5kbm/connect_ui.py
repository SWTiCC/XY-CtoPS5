"""连接页骨架与快捷连接视图。

- 页面里同时建好两套视图：快捷连接（已配对、内存态检测结果）与完整流程
  （首次使用，见 connect_full_ui.py）；显示哪一套由 app 通过 show_view 决定。
- 判定逻辑在 connect_flow.py，业务编排在 app.py，这里只摆控件、写状态。
- 所有颜色 / 字号 / 间距 / 圆角都来自 theme.py，不写魔法值。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import connect_flow as flow
from . import connect_full_ui, theme as T
from .ui_widgets import build_card, font, primary_button, secondary_button

# 语气 → 颜色：状态只换颜色，不换布局
_TONE_COLORS = {
    flow.TONE_OK: T.OK,
    flow.TONE_WARN: T.WARN,
    flow.TONE_ERR: T.ERR,
    flow.TONE_DIM: T.TEXT_DIM,
}


def _tone_color(tone: str) -> str:
    return _TONE_COLORS.get(tone, T.TEXT_DIM)


def build_connect_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)
    # 玩法（键鼠 / 手柄）在连接前选好，快捷视图和完整视图各有一个入口
    app._input_mode_var = tk.StringVar(
        value="手柄" if app._config.controller.mode == "controller" else "键鼠"
    )
    app._wake_buttons = []
    app._quick_view = _build_quick_view(app, page)
    app._full_view = connect_full_ui.build_full_view(app, page)
    # 先摆完整流程；启动时 app 会按"有没有配对过"决定要不要切到快捷视图
    show_view(app, flow.VIEW_FULL)
    return page


def _build_quick_mode_row(app, parent) -> ctk.CTkFrame:
    """快捷视图顶部的玩法选择（一行，不额外占太多高度）。"""
    row = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=T.R_LG)
    inner = ctk.CTkFrame(row, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=T.S2)
    ctk.CTkLabel(
        inner, text="玩法", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    connect_full_ui.build_mode_selector(app, inner).pack(side="left")
    ctk.CTkLabel(
        inner,
        text=(
            "键鼠：键盘鼠标玩\n"
            "手柄：DualSense 直通，陀螺仪可由自定义按键触发，手柄状态在这页查看（画面走采集卡）"
        ),
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        justify="left",
    ).pack(side="left", padx=T.S3)
    return row


def show_view(app, view: str) -> None:
    """切换连接页视图（quick / full），由 app 显式调用。"""
    target = view if view in (flow.VIEW_QUICK, flow.VIEW_FULL) else flow.VIEW_FULL
    for name, frame in (
        (flow.VIEW_QUICK, app._quick_view),
        (flow.VIEW_FULL, app._full_view),
    ):
        if name == target:
            frame.pack(fill="both", expand=True)
        else:
            frame.pack_forget()
    app._connect_view = target


def render(app) -> None:
    """把 app 的连接状态渲染到两套视图上（只更新内容，不切换视图）。"""
    paired = getattr(app, "_paired", None)
    bridge = getattr(app, "_bridge", None)
    state = getattr(app, "_probe_state", flow.STATE_UNPAIRED)
    probe_error = getattr(app, "_probe_error", "")
    connecting = bool(getattr(app, "_connecting", False))
    _render_quick(
        app,
        flow.describe(
            paired,
            state,
            connected=bridge is not None,
            connected_host=bridge.host if bridge is not None else "",
            connecting=connecting,
            probe_error=probe_error,
            connect_error=getattr(app, "_connect_error", ""),
        ),
    )
    connect_full_ui.render_full(app, paired, state, probe_error, bridge, connecting)


# ---------------------------------------------------------------- 快捷视图
def _build_quick_view(app, parent) -> ctk.CTkFrame:
    view = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)
    _build_quick_mode_row(app, view).pack(fill="x", pady=(0, T.S2))
    _build_quick_card(app, view).pack(fill="x", pady=(0, T.S3))
    _build_quick_tips(view).pack(fill="x")
    return view


def _build_quick_card(app, parent):
    card = build_card(
        parent,
        "已配对主机",
        "直接连接用已保存的配对凭据建立输入通道，不用再填 IP / PIN",
    )
    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=(T.S3, T.S4))

    app._quick_title = ctk.CTkLabel(
        inner, text="", font=font(T.XXL, bold=True), text_color=T.TEXT, anchor="w"
    )
    app._quick_title.pack(fill="x")
    app._quick_subtitle = ctk.CTkLabel(
        inner, text="", font=font(T.XS), text_color=T.TEXT_FAINT, anchor="w"
    )
    app._quick_subtitle.pack(fill="x", pady=(T.S1, T.S2))

    status_row = ctk.CTkFrame(inner, fg_color="transparent")
    status_row.pack(fill="x")
    app._quick_status_dot = ctk.CTkLabel(
        status_row, text="●", font=font(T.SM), text_color=T.TEXT_FAINT, width=16
    )
    app._quick_status_dot.pack(side="left")
    app._quick_status = ctk.CTkLabel(
        status_row, text="", font=font(T.SM), text_color=T.TEXT_DIM, anchor="w"
    )
    app._quick_status.pack(side="left")

    buttons = ctk.CTkFrame(inner, fg_color="transparent")
    buttons.pack(fill="x", pady=(T.S3, 0))
    app._quick_connect_button = primary_button(
        buttons, "直接连接", app._quick_connect, width=150
    )
    app._quick_connect_button.pack(side="left")
    app._quick_disconnect_button = secondary_button(
        buttons, "断开", app._disconnect, width=88
    )
    app._quick_disconnect_button.pack(side="left", padx=T.S2)
    app._quick_recheck_button = secondary_button(
        buttons, "重新检测", app._start_probe, width=100
    )
    app._quick_recheck_button.pack(side="left")
    app._quick_switch_button = secondary_button(
        buttons, "换 ID 连接", app._switch_account, width=120
    )
    app._quick_switch_button.pack(side="left", padx=T.S2)
    app._wake_button = secondary_button(
        buttons, "唤醒主机", app._wake_console, width=100
    )
    app._wake_button.pack(side="left", padx=T.S2)
    app._wake_buttons.append(app._wake_button)

    ctk.CTkLabel(
        inner,
        text="「换 ID 连接」会回到完整流程：可改 Account ID、重新配对另一台主机。",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        anchor="w",
        justify="left",
        wraplength=560,
    ).pack(fill="x", pady=(T.S2, 0))
    return card


def _build_quick_tips(parent):
    card = build_card(parent, "下一步")
    for tip in (
        "连接成功后切到「运行」页，点「开始捕获」（或按 F8）把键鼠交给 PS5。",
        "画面仍走采集卡 HDMI 环出，本程序只走 Remote Play 的输入通道。",
        "PS5 只能有一条 Remote Play；若停在登录/密码界面，先在主机登录并开启自动登录。",
    ):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=T.S4, pady=(0, T.S2))
        ctk.CTkLabel(
            row, text="·", font=font(T.SM), text_color=T.TEXT_FAINT, width=12
        ).pack(side="left", anchor="n")
        ctk.CTkLabel(
            row,
            text=tip,
            font=font(T.SM),
            text_color=T.TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(side="left", fill="x", expand=True)
    ctk.CTkFrame(card, fg_color="transparent", height=T.S1).pack()
    return card


def _render_quick(app, quick) -> None:
    color = _tone_color(quick.tone)
    app._quick_title.configure(text=quick.title)
    app._quick_subtitle.configure(text=quick.subtitle)
    app._quick_status.configure(text=quick.status_text, text_color=color)
    app._quick_status_dot.configure(text_color=color)
    app._quick_connect_button.configure(
        state="normal" if quick.can_connect else "disabled"
    )
    app._quick_disconnect_button.configure(
        state="normal" if quick.can_disconnect else "disabled"
    )
    app._quick_recheck_button.configure(
        state="normal" if quick.can_recheck else "disabled"
    )
