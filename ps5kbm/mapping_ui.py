"""映射页：预设 / 模式的切换与编辑，以及按键映射列表。

单独成模块，避免 ui_pages.py 越滚越大；这里只摆控件，业务逻辑在 app.py。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme as T
from .keys import display_key
from .ui_common import describe_action, format_stick_keys
from .ui_widgets import (
    build_card,
    bulk_build,
    divider,
    font,
    secondary_button,
)


# ---------------------------------------------------------------- 映射页
def build_mapping_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    config_card = build_card(
        page,
        "预设与模式",
        "一个预设 = 整套按键（含所有模式）；选中下拉即生效，新建的预设映射为空",
    )
    config_card.pack(fill="x", pady=(0, T.S2))
    inner = ctk.CTkFrame(config_card, fg_color="transparent")
    inner.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))

    # 第一行：预设（整套配置）的切换 / 新建 / 删除
    preset_row = ctk.CTkFrame(inner, fg_color="transparent")
    preset_row.pack(fill="x")
    ctk.CTkLabel(
        preset_row, text="预设", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    app._preset_box = ctk.CTkComboBox(
        preset_row,
        variable=app._preset_var,
        values=app._preset_values,
        width=140,
        height=30,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        border_color=T.BORDER,
        button_color=T.SURFACE_HOVER,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
        state="readonly",
        command=app.apply_preset,
    )
    app._preset_box.pack(side="left")
    secondary_button(preset_row, "新建预设", app.create_preset, width=88, height=30).pack(
        side="left", padx=T.S2
    )
    secondary_button(
        preset_row, "另存为…", app.save_as_preset, width=88, height=30
    ).pack(side="left")
    secondary_button(preset_row, "删除", app.remove_preset, width=60, height=30).pack(
        side="left", padx=T.S2
    )
    # 所有改动（映射 / 模式 / 滑条）都会即时写盘，这里只做提示，不再放"保存"按钮
    ctk.CTkLabel(
        preset_row,
        text="改动会自动保存",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="right")

    divider(inner)

    # 第二行：模式（预设内部的一套键位）的编辑与切换
    mode_row = ctk.CTkFrame(inner, fg_color="transparent")
    mode_row.pack(fill="x")
    ctk.CTkLabel(
        mode_row, text="编辑模式", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    mode_labels, mode_map = app._mode_option_labels()
    app._mode_option_map = mode_map
    app._mode_var = tk.StringVar(value=app._mode_option_for(app._edit_mode))
    app._mode_box = ctk.CTkOptionMenu(
        mode_row,
        variable=app._mode_var,
        values=mode_labels,
        command=app.choose_mode,
        width=130,
        height=30,
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
        f"切换键 {display_key(app._config.mode_switch)}",
        app.set_mode_switch_key,
        width=120,
        height=30,
    )
    app._mode_switch_btn.pack(side="right")

    # 第三行：自动切换（规则跟当前预设绑在一起，一个游戏一套）
    auto_row = ctk.CTkFrame(inner, fg_color="transparent")
    auto_row.pack(fill="x", pady=(T.S2, 0))
    ctk.CTkLabel(
        auto_row, text="自动切换", font=font(T.XS), text_color=T.TEXT_DIM
    ).pack(side="left", padx=(0, T.S2))
    app._auto_switch_var = tk.BooleanVar(value=bool(app._config.auto_switch))
    app._auto_switch_box = ctk.CTkCheckBox(
        auto_row,
        text="启用",
        variable=app._auto_switch_var,
        command=app.toggle_auto_switch,
        font=font(T.XS),
        text_color=T.TEXT_DIM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        border_color=T.BORDER,
        checkbox_width=16,
        checkbox_height=16,
    )
    app._auto_switch_box.pack(side="left")
    app._rules_summary_label = ctk.CTkLabel(
        auto_row, text="", font=font(T.XS), text_color=T.TEXT_FAINT
    )
    app._rules_summary_label.pack(side="left", padx=T.S3)
    secondary_button(
        auto_row,
        "编辑规则…",
        lambda: app.open_rules_editor(),
        width=88,
        height=28,
    ).pack(side="right")
    refresh_rules_row(app)

    list_card = build_card(page, "按键映射", "双击或点编辑修改；支持单按钮、组合键、序列")
    list_card.pack(fill="both", expand=True)
    # CTkScrollableFrame 内部滚动条默认长度会把列表卡撑高，用固定高度的容器包一层；
    # 容器本身 fill+expand，实际显示时仍会随着页面剩余空间长高。
    holder = ctk.CTkFrame(list_card, fg_color="transparent", height=T.S8 * 3)
    holder.pack(fill="both", expand=True, padx=T.S1, pady=(T.S1, T.S1))
    holder.pack_propagate(False)
    app._mapping_list = ctk.CTkScrollableFrame(
        holder, fg_color="transparent", corner_radius=0
    )
    app._mapping_list.pack(fill="both", expand=True)

    bottom = ctk.CTkFrame(page, fg_color="transparent")
    bottom.pack(fill="x", pady=(T.S2, T.S2))
    secondary_button(bottom, "添加映射", app._add_mapping, width=110).pack(side="left")
    app._mapping_count_label = ctk.CTkLabel(
        bottom, text="共 0 条", font=font(T.XS), text_color=T.TEXT_FAINT
    )
    app._mapping_count_label.pack(side="left", padx=T.S3)
    ctk.CTkLabel(
        bottom,
        text="键名写法：w / space / esc / mouse_x1",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="right")

    stick_card = build_card(page)
    stick_card.pack(fill="x")
    keys_row = ctk.CTkFrame(stick_card, fg_color="transparent")
    keys_row.pack(fill="x", padx=T.S4, pady=T.S2)
    ctk.CTkLabel(
        keys_row, text="左摇杆", font=font(T.SM, bold=True), text_color=T.TEXT
    ).pack(side="left", padx=(0, T.S3))
    app._stick_keys_label = ctk.CTkLabel(
        keys_row,
        text=format_stick_keys(app._mode_cfg().keyboard_sticks),
        font=font(T.SM, mono=True),
        text_color=T.TEXT,
    )
    app._stick_keys_label.pack(side="left")
    secondary_button(keys_row, "编辑", app.edit_stick_keys, width=56, height=26).pack(
        side="right"
    )
    ctk.CTkLabel(
        keys_row,
        text="幅度用映射动作切换",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="right", padx=T.S3)
    return page


def refresh_mapping_list(app) -> None:
    """刷新映射列表。

    键位没变时**原地改文字**，不重建控件：每条映射 6 个 CTk 控件，一轮重建 40 条
    要 770ms（都跑在界面线程，等于切模式时卡一下）；原地 configure 只要几毫秒。
    键位集合变了（加/删/改键）才整块重建。
    """
    rows = app._binding_rows()
    if getattr(app, "_mapping_count_label", None) is not None:
        app._mapping_count_label.configure(text=f"共 {len(rows)} 条")
    if _refresh_rows_in_place(app, rows):
        return
    with bulk_build(app.root):
        for child in app._mapping_list.winfo_children():
            child.destroy()
        app._mapping_views = {}
        if not rows:
            empty = ctk.CTkFrame(app._mapping_list, fg_color=T.SURFACE, corner_radius=T.R_MD)
            empty.pack(fill="x", padx=T.S2, pady=T.S2)
            ctk.CTkLabel(
                empty,
                text="还没有映射，点下面的「添加映射」开始",
                font=font(T.SM),
                text_color=T.TEXT_FAINT,
            ).pack(padx=T.S4, pady=T.S4)
            return
        for source, value in rows:
            _mapping_row(app, source, value)


def _refresh_rows_in_place(app, rows) -> bool:
    """键位集合没变就只改动作文字 / 键名 chip 颜色；变了返回 False 交给整块重建。"""
    views: dict = getattr(app, "_mapping_views", {})
    if not views or list(views) != [source for source, _value in rows]:
        return False
    for source, value in rows:
        view = views[source]
        try:
            view.action.configure(text=describe_action(value))
            view.chip.configure(
                fg_color=T.ACCENT_SOFT if source.startswith("mouse_") else T.SURFACE_HOVER
            )
        except Exception:  # noqa: BLE001 - 控件被销毁过就退化成整块重建
            return False
    return True


class _MappingRowView:
    """一行映射里会被刷新的控件（键位不变时只改这些）。"""

    __slots__ = ("chip", "action")

    def __init__(self, chip, action) -> None:
        self.chip = chip
        self.action = action


def _mapping_row(app, source: str, value) -> None:
    """一条映射：键名 chip + 动作描述 + 改键 / 编辑 / 删除。"""
    row = ctk.CTkFrame(app._mapping_list, fg_color=T.SURFACE, corner_radius=T.R_MD)
    row.pack(fill="x", padx=T.S2, pady=2)

    is_mouse = source.startswith("mouse_")
    chip = ctk.CTkLabel(
        row,
        text=display_key(source),
        width=128,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.ACCENT_SOFT if is_mouse else T.SURFACE_HOVER,
        text_color=T.TEXT,
        font=font(T.SM, mono=not is_mouse),
    )
    chip.pack(side="left", padx=(T.S2, T.S2), pady=T.S1)

    action = ctk.CTkLabel(
        row,
        text=describe_action(value),
        anchor="w",
        font=font(T.SM),
        text_color=T.TEXT_DIM,
    )
    action.pack(side="left", fill="x", expand=True, pady=T.S1)

    ctk.CTkButton(
        row,
        text="×",
        width=28,
        height=28,
        corner_radius=T.R_SM,
        fg_color="transparent",
        hover_color=T.ERR,
        text_color=T.TEXT_FAINT,
        font=font(T.BASE),
        command=lambda name=source: app.remove_mapping(name),
    ).pack(side="right", padx=(0, T.S2), pady=T.S1)
    secondary_button(row, "编辑", lambda: app.edit_mapping(source), width=52, height=28).pack(
        side="right", padx=(0, T.S2), pady=T.S1
    )
    # 改键：把这条映射换到另一个键盘 / 鼠标键上，动作不动
    secondary_button(row, "改键", lambda: app.rebind_mapping(source), width=52, height=28).pack(
        side="right", padx=(0, T.S2), pady=T.S1
    )
    if not hasattr(app, "_mapping_views"):
        app._mapping_views = {}
    app._mapping_views[source] = _MappingRowView(chip, action)


def refresh_stick_keys(app) -> None:
    app._stick_keys_label.configure(
        text=format_stick_keys(app._mode_cfg().keyboard_sticks)
    )


def refresh_mode_ui(app) -> None:
    """同步模式下拉框的选项与当前编辑模式。"""
    labels, mapping = app._mode_option_labels()
    app._mode_option_map = mapping
    app._mode_var.set(app._mode_option_for(app._edit_mode))
    if getattr(app, "_mode_box", None) is not None:
        app._mode_box.configure(values=labels)
    if getattr(app, "_mode_switch_btn", None) is not None:
        app._mode_switch_btn.configure(
            text=f"切换键 {display_key(app._config.mode_switch)}"
        )
    refresh_rules_row(app)


def refresh_rules_row(app) -> None:
    """同步「自动切换」那一行：开关状态与规则摘要（规则跟着当前预设走）。"""
    summary = getattr(app, "_rules_summary_label", None)
    if summary is None:
        return
    box = getattr(app, "_auto_switch_box", None)
    if box is not None:
        app._auto_switch_var.set(bool(app._config.auto_switch))
    rules = app._config.rules
    if not rules:
        summary.configure(text="这个预设还没有规则")
        return
    targets = "、".join(
        dict.fromkeys(f"「{app._mode_label(rule.target)}」" for rule in rules)
    )
    text = f"{len(rules)} 条规则 → {targets}"
    if not app._config.auto_switch:
        text += "（已停用）"
    summary.configure(text=text)
