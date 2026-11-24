"""完整连接流程视图：主机（IP / 扫描）、配对（Account ID + PIN）、连接 / 断开。

首次使用、或自动检测不到已配对主机时显示这一页。只负责"长什么样"和控件状态，
判定逻辑在 connect_flow.py，业务编排在 app.py。
"""

from __future__ import annotations

import customtkinter as ctk

from . import connect_flow as flow
from . import theme as T
from .ui_widgets import build_card, field, font, ghost_button, primary_button, secondary_button


def build_full_view(app, parent) -> ctk.CTkFrame:
    view = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)
    _build_notice(app, view)
    _build_host_card(app, view)
    _build_pair_card(app, view)
    _build_action_row(app, view)
    return view


def render_full(app, paired, state, probe_error, bridge, connecting) -> None:
    """按当前状态刷新按钮可用性与提示条。"""
    notice = flow.full_notice(paired, state, probe_error)
    if notice:
        app._notice_text.configure(text=notice)
        # 重复 pack 只更新选项，不会重复添加；before 保证提示条始终在最上面
        app._notice_card.pack(fill="x", pady=(0, T.S3), before=app._host_card)
        app._notice_visible = True
    elif app._notice_visible:
        app._notice_card.pack_forget()
        app._notice_visible = False

    busy = bridge is not None or connecting or state == flow.STATE_CHECKING
    app._notice_recheck_button.configure(
        state="disabled" if busy or paired is None else "normal"
    )
    app._notice_back_button.configure(state="disabled" if paired is None else "normal")
    # 有凭据才能连接：没配对时点「连接主机」只会报错，直接置灰更直观
    app._connect_button.configure(
        state="normal" if paired is not None and not busy else "disabled"
    )
    app._disconnect_button.configure(
        state="normal" if bridge is not None else "disabled"
    )


def _build_notice(app, parent) -> None:
    """从快捷视图回落时显示的提示条：说明原因，并给重试 / 返回入口。

    做成"文字 + 右侧两个小按钮"的单行结构，避免把下面的卡片顶出窗口。
    """
    card = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=T.R_LG)
    app._notice_card = card
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="x", padx=T.S4, pady=T.S3)

    buttons = ctk.CTkFrame(body, fg_color="transparent")
    buttons.pack(side="right", padx=(T.S3, 0))
    app._notice_recheck_button = secondary_button(
        buttons, "重新检测", app._start_probe, width=96, height=28
    )
    app._notice_recheck_button.pack(anchor="e")
    app._notice_back_button = ghost_button(
        buttons, "用已配对主机", app._use_quick_view, width=110, height=26
    )
    app._notice_back_button.pack(anchor="e", pady=(T.S1, 0))

    app._notice_text = ctk.CTkLabel(
        body,
        text="",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        justify="left",
        anchor="w",
        wraplength=460,
    )
    app._notice_text.pack(side="left", fill="x", expand=True)
    app._notice_visible = False


def _build_host_card(app, parent) -> None:
    host_card = build_card(parent, "主机", "扫描局域网，或直接填 PS5 的 IP")
    app._host_card = host_card
    host_card.pack(fill="x", pady=(0, T.S3))

    row = ctk.CTkFrame(host_card, fg_color="transparent")
    row.pack(fill="x", padx=T.S4, pady=T.S3)
    app._host_entry = field(row, "PS5 IP", width=180, textvariable=app._host_var)
    secondary_button(row, "扫描局域网", app._scan_devices, width=110).pack(
        side="left", pady=(T.S4, 0)
    )

    # CTkScrollableFrame 内部的滚动条默认长度会把整张卡片撑高（要 96 的列表能撑到
    # 200+），这里用固定高度的容器包一层，保证列表区高度可控、不顶掉下面的按钮。
    holder = ctk.CTkFrame(host_card, fg_color="transparent", height=T.S8 * 2)
    holder.pack(fill="x", padx=T.S4, pady=(0, T.S4))
    holder.pack_propagate(False)
    app._device_list = ctk.CTkScrollableFrame(
        holder, fg_color=T.SURFACE_HOVER, corner_radius=T.R_SM
    )
    app._device_list.pack(fill="both", expand=True)
    ctk.CTkLabel(
        app._device_list,
        text="还没有扫描结果",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(anchor="w", padx=T.S2, pady=T.S2)


def _build_pair_card(app, parent) -> None:
    card = build_card(parent, "配对", "首次使用才需要；凭据会保存在 credentials.json")
    card.pack(fill="x", pady=(0, T.S3))
    row = ctk.CTkFrame(card, fg_color="transparent")
    row.pack(fill="x", padx=T.S4, pady=T.S3)
    app._account_entry = field(
        row, "PSN Account ID", width=220, textvariable=app._account_var
    )
    field(row, "8 位 PIN", width=110, textvariable=app._pin_var)
    secondary_button(row, "配对", app._pair_console, width=80).pack(
        side="left", pady=(T.S4, 0)
    )
    ctk.CTkLabel(
        card,
        text="Account ID 用 run.cmd login 获取\nPIN 在 PS5：设置 → 系统 → 远程游玩 → 关联设备",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=T.S4, pady=(0, T.S4))


def build_mode_selector(app, parent):
    """玩法选择（键鼠 / 手柄）——快捷视图和完整流程共用同一个变量。"""
    return ctk.CTkSegmentedButton(
        parent,
        values=["键鼠", "手柄"],
        variable=app._input_mode_var,
        command=app.set_input_mode,
        font=font(T.XS),
        selected_color=T.ACCENT,
        selected_hover_color=T.ACCENT_HOVER,
        unselected_color=T.SURFACE_HOVER,
        unselected_hover_color=T.BORDER,
        text_color=T.TEXT,
        height=30,
        width=150,
    )


def _build_action_row(app, parent) -> None:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(T.S2, 0))
    ctk.CTkLabel(
        row, text="玩法", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    build_mode_selector(app, row).pack(side="left")
    app._connect_button = primary_button(row, "连接主机", app._connect, width=180)
    app._connect_button.pack(side="left", padx=(T.S4, 0))
    app._disconnect_button = secondary_button(row, "断开", app._disconnect, width=96)
    app._disconnect_button.pack(side="left", padx=T.S2)
    app._disconnect_button.configure(state="disabled")
    app._wake_button = secondary_button(row, "唤醒主机", app._wake_console, width=110)
    app._wake_button.pack(side="left")
    app._wake_buttons.append(app._wake_button)

    ctk.CTkLabel(
        parent,
        text=(
            "注意：PS5 停在登录 / 密码界面时 Remote Play 连不上——先在主机上完成登录，"
            "并到「设置 → 用户与账户 → 登录设置」打开自动登录。"
        ),
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        anchor="w",
        justify="left",
        wraplength=640,
    ).pack(fill="x", pady=(T.S1, 0))
