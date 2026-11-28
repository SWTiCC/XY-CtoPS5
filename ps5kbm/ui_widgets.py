"""基础控件与样式封装：字体、主/次按钮、输入框、卡片、状态胶囊。

单独成模块，避免 ui_pages 与 ui_common 互相导入形成循环依赖。
所有尺寸都来自 theme，不写魔法值。
"""

from __future__ import annotations

from contextlib import contextmanager

import customtkinter as ctk
from customtkinter.windows.widgets.core_rendering import CTkCanvas

from . import theme as T


@contextmanager
def bulk_build(root):
    """批量建控件时，屏蔽 customtkinter 每个控件自带的 update_idletasks。

    为什么需要：``CTkOptionMenu._draw()`` 末尾会调一次 ``canvas.update_idletasks()``，
    本意是让下拉箭头立刻排版；但整块界面重建时一次要建几十个控件，每建一个就把
    整棵控件的待处理队列（排布、重绘）排空一遍，实测变成 O(n²)：
    规则编辑面板整页重画 1140ms、映射列表重建 771ms。
    customtkinter 6.0.0 没有「延后 draw」的开关，所以只能在重建期间把它置空，
    重建结束后统一 update_idletasks 一次 —— 画面结果一样，耗时少一半以上。

    用法：``with bulk_build(app.root): ...建控件...``
    """

    original = CTkCanvas.update_idletasks
    CTkCanvas.update_idletasks = lambda self: None
    try:
        yield
    finally:
        CTkCanvas.update_idletasks = original
        try:
            root.update_idletasks()
        except Exception:  # noqa: BLE001 - 关窗过程中 Tk 可能已经销毁
            pass


def font(size: int, bold: bool = False, mono: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(
        family=T.FONT_MONO if mono else T.FONT_FAMILY,
        size=size,
        weight="bold" if bold else "normal",
    )


def primary_button(parent, text: str, command, width: int = 0, height: int = 40):
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=T.R_SM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        text_color="#FFFFFF",
        font=font(T.SM, bold=True),
    )


def secondary_button(parent, text: str, command, width: int = 0, height: int = 34):
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=width or 96,
        height=height,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    )


def ghost_button(parent, text: str, command, width: int = 56, height: int = 28):
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=T.R_XS,
        fg_color="transparent",
        hover_color=T.BORDER,
        text_color=T.TEXT_FAINT,
        font=font(T.XS),
    )


def field(parent, label: str, width: int = 170, textvariable=None) -> ctk.CTkEntry:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(side="left", padx=(0, T.S3))
    ctk.CTkLabel(wrap, text=label, font=font(T.XS), text_color=T.TEXT_DIM).pack(
        anchor="w"
    )
    entry = ctk.CTkEntry(
        wrap,
        width=width,
        height=34,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        border_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
        textvariable=textvariable,
    )
    entry.pack(anchor="w", pady=(T.S1, 0))
    return entry


def build_card(parent, title: str = "", subtitle: str = "") -> ctk.CTkFrame:
    card = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=T.R_LG)
    if title:
        ctk.CTkLabel(
            card, text=title, font=font(T.BASE, bold=True), text_color=T.TEXT
        ).pack(anchor="w", padx=T.S4, pady=(T.S3, 0))
    if subtitle:
        ctk.CTkLabel(
            card,
            text=subtitle,
            font=font(T.XS),
            text_color=T.TEXT_FAINT,
            justify="left",
            anchor="w",
            wraplength=600,
        ).pack(fill="x", padx=T.S4, pady=(T.S1, 0))
    return card


def divider(parent) -> None:
    """一行细分隔线，用来把长表单分成几段。"""
    ctk.CTkFrame(parent, fg_color=T.BORDER, height=1).pack(fill="x", pady=(T.S2, T.S1))


def switch(parent, text: str, variable, command):
    """统一的开关样式（运行页各处的开关都用它）。"""
    return ctk.CTkSwitch(
        parent,
        text=text,
        variable=variable,
        command=command,
        font=font(T.SM),
        text_color=T.TEXT_DIM,
        progress_color=T.ACCENT,
        button_color=T.TEXT,
        button_hover_color=T.TEXT,
    )


def build_status_pill(parent) -> tuple[ctk.CTkFrame, ctk.CTkLabel, ctk.CTkLabel]:
    """返回 (pill 容器, 圆点, 文字)，状态更新时只改颜色和文案。"""
    pill = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=999, height=32)
    pill.pack_propagate(False)
    dot = ctk.CTkLabel(pill, text="●", font=font(T.SM), text_color=T.TEXT_FAINT, width=16)
    dot.pack(side="left", padx=(T.S3, 0))
    text = ctk.CTkLabel(pill, text="未连接", font=font(T.SM), text_color=T.TEXT_DIM)
    text.pack(side="left", padx=(T.S1, T.S3))
    return pill, dot, text
