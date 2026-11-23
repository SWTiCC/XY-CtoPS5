"""界面骨架：顶栏、侧边导航、日志区。

连接页在 connect_ui.py / connect_full_ui.py，映射页在 mapping_ui.py，运行页在 run_ui.py。
只负责“长什么样”与控件摆放，业务逻辑仍在 app.py。
所有颜色 / 字号 / 间距 / 圆角都来自 theme.py，不写魔法值。
"""

from __future__ import annotations

import customtkinter as ctk

from . import __version__ as APP_VERSION
from . import theme as T
from .ui_widgets import build_status_pill, font


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
        sidebar, text=f"v{APP_VERSION}", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(side="bottom", anchor="w")


def set_nav_state(app, active: str) -> None:
    for key, button in app._nav_buttons.items():
        if key == active:
            button.configure(fg_color=T.ACCENT_SOFT, text_color=T.TEXT)
        else:
            button.configure(fg_color="transparent", text_color=T.TEXT_DIM)


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
