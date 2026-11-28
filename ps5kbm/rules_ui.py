"""自动切换编辑面板：独立弹窗，目标模式 + 条件树增删改 + 实时信号灯。

入口只有一个：映射页「自动切换」那一行的「编辑规则…」（``open_editor``）。侧栏里没有这一页，
因为自动切换只在键鼠玩法下存在，放在侧栏会让人以为手柄玩法也能用。

只负责「长什么样、点了之后改哪份数据」，判定逻辑在 ``rule_engine.py``（规则、状态机）
与 ``signal_rules.py``（事实、条件节点）。面板直接改 ``app._config.rules`` 里的纯数据，
改完调 ``app._rules_changed(message, scopes=...)``（重建引擎 + 写回当前预设 + 按需重画）。

重画的粒度是本模块最要紧的性能点：整棵条件树约 190 个控件，重建一次 0.6~1 秒（全在界面
线程上，等于点一下卡一下）。所以：
- 改前缀 / 按钮 / 秒数这类纯数据 → 控件本来就显示新值，只更新底部「读法」那一行；
- 增删 / 换类型 → 只重画那个分组（``_refresh_group`` / ``_append_child_row``）；
- 找不到对应容器才退回整棵详情（``_render_detail``），正确性优先。
"""

from __future__ import annotations

import customtkinter as ctk

from . import rule_editing as ED
from . import rule_engine as RE
from . import signal_rules as SR
from . import theme as T
from .ui_widgets import build_card, bulk_build, font, ghost_button, secondary_button

LAMP_INTERVAL_MS = 300
SMALL_ENTRY_WIDTH = 56
TYPE_MENU_WIDTH = 110
WINDOW_WIDTH = 980
WINDOW_HEIGHT = 720


# ---------------------------------------------------------------- 弹窗入口
def open_editor(app):
    """打开（或提到最前）自动切换编辑面板；已经开着就直接复用。"""
    window = getattr(app, "_rules_window", None)
    if window is not None:
        try:
            if window.winfo_exists():
                window.deiconify()
                window.lift()
                window.focus_force()
                return window
        except Exception:  # noqa: BLE001 - 窗口已被销毁
            pass
    window = ctk.CTkToplevel(app.root)
    window.title("自动切换 · 规则编辑")
    window.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    window.configure(fg_color=T.BG)
    window.minsize(820, 560)
    # 跟着主窗口走：主窗最小化/关闭时不留一个孤立的编辑窗
    try:
        window.transient(app.root)
    except Exception:  # noqa: BLE001 - 某些平台不支持
        pass
    app._rules_window = window
    window.protocol("WM_DELETE_WINDOW", lambda: close_editor(app))
    page = build_rules_page(app, window)
    page.pack(fill="both", expand=True, padx=T.S4, pady=T.S4)
    try:
        window.after(60, window.focus_force)
    except Exception:  # noqa: BLE001
        pass
    return window


def close_editor(app) -> None:
    """关闭面板：停掉实时灯，控件交给 Tk 销毁。"""
    window = getattr(app, "_rules_window", None)
    app._rules_window = None
    app._rule_lamp_job = None
    app._rule_list = None
    app._rule_detail = None
    if window is not None:
        try:
            window.destroy()
        except Exception:  # noqa: BLE001 - 已经销毁过
            pass


def window_alive(app) -> bool:
    """面板现在开着吗（关闭后所有刷新都要变成空操作）。"""
    window = getattr(app, "_rules_window", None)
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 面板骨架
def build_rules_page(app, parent) -> ctk.CTkFrame:
    page = ctk.CTkFrame(parent, fg_color=T.BG, corner_radius=0)

    card = build_card(
        page,
        "自动切换",
        "自动切换只在键鼠玩法下生效。规则跟着预设走：换一个预设就换一套规则，改完立即保存。"
        "条件按「信号」拼——扳机类型 / 手柄按钮 / 震动 / 触觉，跟具体游戏无关，"
        "所以换个游戏不用改代码，只改条件里的参数就行。",
    )
    card.pack(fill="x", pady=(0, T.S2))
    header = ctk.CTkFrame(card, fg_color="transparent")
    header.pack(fill="x", padx=T.S4, pady=(T.S2, 0))
    app._rules_header_label = ctk.CTkLabel(
        header, text="", font=font(T.SM, bold=True), text_color=T.TEXT
    )
    app._rules_header_label.pack(side="left")
    app._rules_enable_var = ctk.BooleanVar(value=bool(app._config.auto_switch))
    app._rules_enable_box = ctk.CTkCheckBox(
        header,
        text="启用自动切换",
        variable=app._rules_enable_var,
        command=app.toggle_auto_switch,
        font=font(T.XS),
        text_color=T.TEXT_DIM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        border_color=T.BORDER,
        checkbox_width=16,
        checkbox_height=16,
    )
    app._rules_enable_box.pack(side="right")
    toolbar = ctk.CTkFrame(card, fg_color="transparent")
    toolbar.pack(fill="x", padx=T.S4, pady=(T.S2, T.S3))
    secondary_button(toolbar, "＋ 新建规则", lambda: _add_rule(app), width=104, height=30).pack(
        side="left"
    )
    secondary_button(toolbar, "复制", lambda: _clone_rule(app), width=60, height=30).pack(
        side="left", padx=T.S2
    )
    secondary_button(toolbar, "上移", lambda: _move_rule(app, -1), width=60, height=30).pack(
        side="left"
    )
    secondary_button(toolbar, "下移", lambda: _move_rule(app, 1), width=60, height=30).pack(
        side="left", padx=(T.S2, 0)
    )
    secondary_button(toolbar, "删除", lambda: _delete_rule(app), width=60, height=30).pack(
        side="left", padx=T.S2
    )
    app._rule_toolbar_hint = ctk.CTkLabel(
        toolbar, text="越靠前的规则越先判定", font=font(T.XS), text_color=T.TEXT_FAINT
    )
    app._rule_toolbar_hint.pack(side="right")

    body = ctk.CTkFrame(page, fg_color="transparent")
    body.pack(fill="both", expand=True)
    left = ctk.CTkFrame(body, fg_color=T.SURFACE, corner_radius=T.R_LG, width=248)
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    app._rule_list = ctk.CTkScrollableFrame(
        left, fg_color="transparent", corner_radius=0, width=232
    )
    app._rule_list.pack(fill="both", expand=True, padx=T.S1, pady=T.S1)

    right = ctk.CTkFrame(body, fg_color=T.SURFACE, corner_radius=T.R_LG)
    right.pack(side="left", fill="both", expand=True, padx=(T.S2, 0))
    app._rule_detail = ctk.CTkScrollableFrame(right, fg_color="transparent", corner_radius=0)
    app._rule_detail.pack(fill="both", expand=True, padx=T.S2, pady=T.S2)

    _build_fact_lamps(app, page)
    app._rule_groups: dict = {}
    app._rule_summary_label = None
    _ensure_selection(app)
    refresh_rules_page(app)
    _refresh_lamps(app)
    _tick_lamps(app)
    return page


def _build_fact_lamps(app, page) -> None:
    """底部一排信号灯：调规则时先看「这个信号现在亮不亮」。"""
    panel = ctk.CTkFrame(page, fg_color=T.SURFACE, corner_radius=T.R_LG)
    panel.pack(fill="x", pady=(T.S2, 0))
    head = ctk.CTkFrame(panel, fg_color="transparent")
    head.pack(fill="x", padx=T.S4, pady=(T.S2, 0))
    ctk.CTkLabel(head, text="实时信号", font=font(T.SM, bold=True), text_color=T.TEXT).pack(
        side="left"
    )
    ctk.CTkLabel(
        head,
        text="亮 = 这个信号现在成立（没连主机时全灭）",
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
    ).pack(side="left", padx=T.S2)

    wrap = ctk.CTkFrame(panel, fg_color="transparent")
    wrap.pack(fill="x", padx=T.S4, pady=(T.S1, T.S2))
    app._fact_lamps: dict[str, ctk.CTkLabel] = {}
    for index, (label_text, _node) in enumerate(SR.sample_conditions()):
        cell = ctk.CTkFrame(wrap, fg_color="transparent")
        cell.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, T.S4), pady=1)
        lamp = ctk.CTkLabel(cell, text="●", width=14, font=font(T.XS), text_color=T.TEXT_FAINT)
        lamp.pack(side="left")
        ctk.CTkLabel(
            cell, text=label_text, font=font(T.XS), text_color=T.TEXT_DIM
        ).pack(side="left", padx=(T.S1, 0))
        app._fact_lamps[label_text] = lamp


# ---------------------------------------------------------------- 刷新
def refresh_rules_page(app, scopes=None) -> None:
    """重画面板。``scopes`` 决定重画哪几块：``None`` = 全画。

    三块各自独立：顶部一行（约 5ms）、左侧规则列表（每条 5ms）、右侧详情（整棵
    条件树，几百毫秒）。改一个条件只需要重画详情里那一小段（见 ``_refresh_group``），
    改前缀 / 按钮 / 秒数这类纯数据连重画都不用 —— 控件本来就显示着新值。
    """
    if not window_alive(app):
        return
    if getattr(app, "_rule_refreshing", False):
        # 重画过程中控件销毁会触发 <FocusOut> → 提交 → 再要求重画：忽略掉这一层
        return
    wanted = {"header", "list", "detail"} if scopes is None else set(scopes)
    if not wanted:
        return
    app._rule_refreshing = True
    try:
        with bulk_build(app.root):
            if "header" in wanted:
                _render_header(app)
            if "list" in wanted:
                _render_list(app)
            if "detail" in wanted:
                _render_detail(app)
    finally:
        app._rule_refreshing = False


def _render_header(app) -> None:
    """顶部一行：当前预设 + 规则条数 + 启用开关（规则跟着预设走）。"""
    label = getattr(app, "_rules_header_label", None)
    if label is None:
        return
    preset = app._config.preset or "（未命名预设）"
    label.configure(text=f"预设「{preset}」· {len(app._config.rules)} 条规则")
    box = getattr(app, "_rules_enable_box", None)
    if box is not None:
        app._rules_enable_var.set(bool(app._config.auto_switch))

def _render_list(app) -> None:
    for child in app._rule_list.winfo_children():
        child.destroy()
    app._rule_lamps: dict[str, ctk.CTkLabel] = {}
    rules = app._config.rules
    if not rules:
        ctk.CTkLabel(
            app._rule_list,
            text=(
                "还没有规则\n点上面「＋ 新建规则」"
                if app._config.rules
                else "这个预设还没有规则\n点上面「＋ 新建规则」"
            ),
            font=font(T.SM),
            text_color=T.TEXT_FAINT,
            justify="left",
        ).pack(anchor="w", padx=T.S3, pady=T.S3)
        return
    for rule in rules:
        selected = rule.id == app._edit_rule_id
        row = ctk.CTkFrame(
            app._rule_list,
            fg_color=T.ACCENT_SOFT if selected else T.BG,
            corner_radius=T.R_MD,
        )
        row.pack(fill="x", padx=2, pady=2)
        lamp = ctk.CTkLabel(row, text="●", width=14, font=font(T.XS), text_color=T.TEXT_FAINT)
        lamp.pack(side="left", padx=(T.S2, 0), pady=T.S1)
        app._rule_lamps[rule.id] = lamp
        name = ctk.CTkLabel(
            row,
            text=rule.label or rule.id,
            anchor="w",
            font=font(T.SM),
            text_color=T.TEXT if rule.enabled else T.TEXT_FAINT,
        )
        name.pack(side="left", fill="x", expand=True, padx=(T.S1, 0), pady=T.S1)
        ctk.CTkLabel(
            row,
            text=f"→ {app._mode_label(rule.target)}",
            font=font(T.XS),
            text_color=T.TEXT_DIM,
        ).pack(side="right", padx=(0, T.S2))
        for widget in (row, lamp, name):
            widget.bind("<Button-1>", lambda event, rid=rule.id: _select(app, rid))


def _render_detail(app) -> None:
    frame = app._rule_detail
    for child in frame.winfo_children():
        child.destroy()
    # 整棵条件树要重建：旧的「子条件容器」引用全部作废
    app._rule_groups = {}
    app._rule_summary_label = None
    rule = _selected_rule(app)
    if rule is None:
        ctk.CTkLabel(
            frame,
            text=(
                "左边选一条规则开始编辑，或者点上面「＋ 新建规则」。"
                if app._config.rules
                else "这个预设还没有规则。\n点上面「＋ 新建规则」加一条：先选它切到哪个模式，再拼条件。"
            ),
            font=font(T.SM),
            text_color=T.TEXT_FAINT,
            justify="left",
        ).pack(anchor="w", padx=T.S2, pady=T.S2)
        return

    # 先说清「这条规则干嘛的」：切到哪个模式放在最上面，字号也大一号
    target_row = ctk.CTkFrame(frame, fg_color=T.SURFACE_HOVER, corner_radius=T.R_SM)
    target_row.pack(fill="x", padx=T.S2, pady=(0, T.S2))
    ctk.CTkLabel(
        target_row,
        text="满足条件时切到：",
        font=font(T.SM, bold=True),
        text_color=T.TEXT,
    ).pack(side="left", padx=(T.S3, T.S2), pady=T.S2)
    labels, mapping = app._rule_target_options()
    target_var = ctk.StringVar(
        value=mapping.get(rule.target, labels[0] if labels else "（先建一个非默认模式）")
    )
    ctk.CTkOptionMenu(
        target_row,
        variable=target_var,
        values=labels or ["（先建一个非默认模式）"],
        command=lambda value: _set_target(app, mapping, value),
        width=150,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE,
        button_color=T.SURFACE,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM, bold=True),
    ).pack(side="left", pady=T.S2)
    if len(labels) <= 1:
        ctk.CTkLabel(
            target_row,
            text="（这个预设只有这一个非默认模式）",
            font=font(T.XS),
            text_color=T.TEXT_FAINT,
        ).pack(side="left", padx=(T.S1, 0))

    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.pack(fill="x", padx=T.S2, pady=(0, T.S2))
    enabled_var = ctk.BooleanVar(value=bool(rule.enabled))
    ctk.CTkCheckBox(
        head,
        text="启用",
        variable=enabled_var,
        command=lambda: _set_enabled(app, bool(enabled_var.get())),
        font=font(T.XS),
        text_color=T.TEXT_DIM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        border_color=T.BORDER,
        checkbox_width=16,
        checkbox_height=16,
    ).pack(side="left")
    ctk.CTkLabel(head, text="名称", font=font(T.XS), text_color=T.TEXT_DIM).pack(
        side="left", padx=(T.S3, T.S1)
    )
    name_entry = ctk.CTkEntry(
        head,
        width=220,
        height=28,
        corner_radius=T.R_SM,
        fg_color=T.SURFACE_HOVER,
        border_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.SM),
    )
    name_entry.insert(0, rule.label)
    name_entry.pack(side="left")
    _commit_on_edit(name_entry, lambda: _set_label(app, name_entry.get()))

    timing_row = ctk.CTkFrame(frame, fg_color="transparent")
    timing_row.pack(fill="x", padx=T.S2, pady=(0, T.S2))
    for label_text, value, commit in (
        ("进入去抖", rule.enter_hold, _set_enter_hold),
        ("退出延时", rule.leave_delay, _set_leave_delay),
    ):
        ctk.CTkLabel(
            timing_row, text=label_text, font=font(T.XS), text_color=T.TEXT_DIM
        ).pack(side="left", padx=(0, T.S1))
        entry = ctk.CTkEntry(
            timing_row,
            width=SMALL_ENTRY_WIDTH,
            height=28,
            corner_radius=T.R_SM,
            fg_color=T.SURFACE_HOVER,
            border_color=T.BORDER,
            text_color=T.TEXT,
            font=font(T.SM),
        )
        entry.insert(0, f"{float(value):g}")
        entry.pack(side="left")
        ctk.CTkLabel(timing_row, text="秒", font=font(T.XS), text_color=T.TEXT_FAINT).pack(
            side="left", padx=(T.S1, T.S3)
        )
        _commit_on_edit(entry, lambda e=entry, c=commit: c(app, e.get()))

    problem = ED.rule_error(rule)
    if problem:
        ctk.CTkLabel(frame, text=f"⚠ {problem}", font=font(T.XS), text_color=T.WARN).pack(
            anchor="w", padx=T.S2, pady=(0, T.S1)
        )

    _section(frame, "进入条件：成立并持续「进入去抖」秒后切过去")
    _render_tree(app, frame, rule.enter, (), "enter")

    leave_box = ctk.CTkFrame(frame, fg_color="transparent")
    leave_box.pack(fill="x", padx=T.S2, pady=(T.S2, 0))
    no_leave = ctk.BooleanVar(value=rule.leave is None)
    ctk.CTkCheckBox(
        leave_box,
        text="不自动退出（一直停在这个模式）",
        variable=no_leave,
        command=lambda: _toggle_no_leave(app, bool(no_leave.get())),
        font=font(T.XS),
        text_color=T.TEXT_DIM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        border_color=T.BORDER,
        checkbox_width=16,
        checkbox_height=16,
    ).pack(anchor="w")
    _section(frame, "退出条件：成立并持续「退出延时」秒后回默认模式")
    if rule.leave is None:
        ctk.CTkLabel(
            frame,
            text="现在不会自动退出。取消上面的勾选就给它加一个退出条件。",
            font=font(T.XS),
            text_color=T.TEXT_FAINT,
        ).pack(anchor="w", padx=T.S2)
    else:
        _render_tree(app, frame, rule.leave, (), "leave")

    app._rule_summary_label = ctk.CTkLabel(
        frame,
        text="读法：" + rule.summary(),
        font=font(T.XS),
        text_color=T.TEXT_FAINT,
        wraplength=520,
        justify="left",
    )
    app._rule_summary_label.pack(anchor="w", padx=T.S2, pady=(T.S3, T.S2))


def _section(frame, text: str) -> None:
    ctk.CTkLabel(
        frame, text=text, font=font(T.XS), text_color=T.TEXT_FAINT, anchor="w"
    ).pack(fill="x", padx=T.S2, pady=(T.S2, T.S1))


# ---------------------------------------------------------------- 条件树
def _render_tree(app, parent, root: dict, path: tuple, source: str) -> None:
    """渲染一棵条件树；``source`` 决定改完之后写回 enter 还是 leave。"""
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", padx=T.S2)
    _render_node(app, box, root, path, source)


def _render_node(app, parent, node: dict, path: tuple, source: str) -> None:
    row = ctk.CTkFrame(parent, fg_color=T.SURFACE_HOVER, corner_radius=T.R_SM)
    row.pack(fill="x", pady=1)

    type_ids = list(SR.NODE_LABELS)
    type_labels = [SR.NODE_LABELS[key] for key in type_ids]
    node_type = str(node.get("type", ""))
    type_var = ctk.StringVar(value=SR.NODE_LABELS.get(node_type, type_labels[0]))
    ctk.CTkOptionMenu(
        row,
        variable=type_var,
        values=type_labels,
        command=lambda value: _change_type(
            app, path, type_ids[type_labels.index(value)], source
        ),
        width=TYPE_MENU_WIDTH,
        height=26,
        corner_radius=T.R_XS,
        fg_color=T.SURFACE,
        button_color=T.SURFACE,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left", padx=(T.S1, T.S2), pady=T.S1)

    if node_type == "trigger":
        _render_trigger_fields(app, row, node, path, source)
    elif node_type == "button":
        _render_button_fields(app, row, node, path, source)
    elif node_type == "hold":
        entry = ctk.CTkEntry(
            row,
            width=SMALL_ENTRY_WIDTH,
            height=26,
            corner_radius=T.R_XS,
            fg_color=T.SURFACE,
            border_color=T.BORDER,
            text_color=T.TEXT,
            font=font(T.XS),
        )
        entry.insert(0, f"{float(node.get('seconds', 0)):g}")
        entry.pack(side="left", pady=T.S1)
        ctk.CTkLabel(row, text="秒", font=font(T.XS), text_color=T.TEXT_FAINT).pack(
            side="left", padx=(T.S1, 0)
        )
        _commit_on_edit(
            entry, lambda e=entry, p=path: _change_seconds(app, p, e.get(), source)
        )
    elif node_type in ("all", "any"):
        ghost_button(
            row, "＋条件", lambda p=path: _add_child(app, p, source), width=64, height=26
        ).pack(side="left", pady=T.S1)
        ctk.CTkLabel(
            row,
            text="满足其中任意几条" if node_type == "any" else "按书写顺序全部满足",
            font=font(T.XS),
            text_color=T.TEXT_FAINT,
        ).pack(side="left", padx=T.S2)

    if path:
        ghost_button(
            row, "×", lambda p=path: _remove_node(app, p, source), width=26, height=26
        ).pack(side="right", padx=(0, T.S1), pady=T.S1)

    slots = _child_slots(node, path)
    if not slots:
        getattr(app, "_rule_groups", {}).pop((source, path), None)
        return
    inner = ctk.CTkFrame(parent, fg_color="transparent")
    inner.pack(fill="x", padx=(T.S4, 0))
    # 记住「这个节点下面的子条件画在哪个容器里」：增删一个子条件时只重画这一块，
    # 不用重建整棵条件树（整棵树 ~190 个控件，重建一次要 0.6~1 秒）。
    app._rule_groups[(source, path)] = inner
    _render_children(app, inner, node, path, source)


def _render_children(app, inner, node: dict, path: tuple, source: str) -> None:
    """把一个节点的子条件 / 槽位画进 ``inner``（整树渲染与局部重画共用这一段）。"""
    for label_text, child_node, child_path in _child_slots(node, path):
        if label_text:
            ctk.CTkLabel(
                inner, text=label_text, font=font(T.XS), text_color=T.TEXT_FAINT
            ).pack(anchor="w")
        if child_node is None:
            ghost_button(
                inner,
                "＋ 添加",
                lambda p=child_path, s=source: _fill_empty_slot(app, p, s),
                width=64,
                height=24,
            ).pack(anchor="w", padx=(T.S2, 0), pady=1)
            continue
        _render_node(app, inner, child_node, child_path, source)


# ---------------------------------------------------------------- 局部重画
def _refresh_group(app, source: str, path: tuple) -> bool:
    """只重画某个节点下面的子条件；找不到容器（或控件已经没了）返回 False。

    调用方拿 False 时的做法是退回「重画整棵详情」——功能正确性永远优先于速度。
    """
    frame = getattr(app, "_rule_groups", {}).get((source, tuple(path)))
    node = _node_at(_tree_of(app, source), path)
    if frame is None or node is None:
        return False
    try:
        if not frame.winfo_exists():
            return False
        with bulk_build(app.root):
            for child in frame.winfo_children():
                child.destroy()
            _render_children(app, frame, node, path, source)
    except Exception:  # noqa: BLE001 - 局部重画失败就退回整页重画
        return False
    return True


def _append_child_row(
    app, source: str, path: tuple, child: dict, child_path: tuple
) -> bool:
    """在分组末尾追加一行子条件。

    只有「追加到末尾」可以这么省：删除会让后面兄弟的路径整体前移，那种情况必须
    重画整组（见 ``_refresh_group``）。
    """
    frame = getattr(app, "_rule_groups", {}).get((source, tuple(path)))
    if frame is None:
        return False
    try:
        if not frame.winfo_exists():
            return False
        with bulk_build(app.root):
            _render_node(app, frame, child, child_path, source)
    except Exception:  # noqa: BLE001
        return False
    return True


def _refresh_summary(app) -> None:
    """只更新底部那行「读法」：前缀 / 按钮 / 秒数这类纯数据改动不重建控件。"""
    label = getattr(app, "_rule_summary_label", None)
    rule = _selected_rule(app)
    if label is None or rule is None:
        return
    try:
        label.configure(text="读法：" + rule.summary())
    except Exception:  # noqa: BLE001 - 控件已销毁
        pass


def _parent_path(path: tuple) -> tuple:
    """条件路径的父级：``children/下标`` 退两格，具名槽位退一格。"""
    if len(path) >= 2 and path[-2] == "children":
        return path[:-2]
    return path[:-1] if path else ()


def _child_slots(node: dict, path: tuple) -> list[tuple[str, dict | None, tuple]]:
    """这个节点下面要渲染哪些子节点（标签、节点或 None、路径）。"""
    node_type = str(node.get("type", ""))
    if node_type in ("all", "any"):
        return [
            ("", child, path + ("children", index))
            for index, child in enumerate(node.get("children") or [])
        ]
    if node_type == "not":
        return [("取反：", node.get("child"), path + ("child",))]
    if node_type == "hold":
        return [("条件：", node.get("child"), path + ("child",))]
    if node_type == "latch":
        return [
            ("置位（一旦成立就锁住）：", node.get("set"), path + ("set",)),
            ("清除（成立就解除锁存）：", node.get("clear"), path + ("clear",)),
        ]
    if node_type == "before":
        return [
            ("先出现：", node.get("first"), path + ("first",)),
            ("之后出现：", node.get("then"), path + ("then",)),
        ]
    return []


# ---------------------------------------------------------------- 编辑动作
def _selected_rule(app) -> RE.Rule | None:
    for rule in app._config.rules:
        if rule.id == app._edit_rule_id:
            return rule
    return None


def _ensure_selection(app) -> None:
    if _selected_rule(app) is None:
        app._edit_rule_id = app._config.rules[0].id if app._config.rules else ""


def _select(app, rule_id: str) -> None:
    app._edit_rule_id = rule_id
    # 选中态画在左侧列表上，详情整棵都要换：只重画这两块，不碰顶部
    refresh_rules_page(app, ("list", "detail"))


def _add_rule(app) -> None:
    labels, mapping = app._rule_target_options()
    if not labels:
        _hint(app, "先在这个预设里新建一个非默认模式，再给它配规则")
        return
    rule = ED.new_rule(app._config.rules, mapping[labels[0]])
    app._edit_rule_id = rule.id
    app._rules_changed(f"已新建规则「{rule.label}」", scopes=("header", "list", "detail"))


def _clone_rule(app) -> None:
    rule = _selected_rule(app)
    if rule is None:
        _hint(app, "先选一条规则")
        return
    copy = ED.clone_rule(app._config.rules, rule)
    app._edit_rule_id = copy.id
    app._rules_changed(f"已复制规则「{copy.label}」", scopes=("header", "list", "detail"))


def _move_rule(app, delta: int) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    index = app._config.rules.index(rule)
    if ED.move_rule(app._config.rules, index, delta) == index:
        return
    app._rules_changed("规则顺序已调整（越靠前越先判定）", scopes=("list",))


def _delete_rule(app) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    app._config.rules = [item for item in app._config.rules if item.id != rule.id]
    _ensure_selection(app)
    app._rules_changed(f"已删除规则「{rule.label}」", scopes=("header", "list", "detail"))


def _set_enabled(app, enabled: bool) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    rule.enabled = enabled
    app._rules_changed("规则已启用" if enabled else "规则已停用", scopes=("list",))


def _set_label(app, label: str) -> None:
    rule = _selected_rule(app)
    text = label.strip()
    if rule is None or not text or rule.label == text:
        return
    rule.label = text
    app._rules_changed("规则已改名", scopes=("list",))


def _set_target(app, mapping: dict[str, str], value: str) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    target = mapping.get(value)
    if not target or target == rule.target:
        return
    rule.target = target
    app._rules_changed(f"规则目标改为「{app._mode_label(target)}」", scopes=("list",))


def _set_enter_hold(app, text: str) -> None:
    _set_delay(app, text, "enter_hold", "进入去抖")


def _set_leave_delay(app, text: str) -> None:
    _set_delay(app, text, "leave_delay", "退出延时")


def _set_delay(app, text: str, field_name: str, field_label: str) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    seconds = SR.clamp_seconds(text)
    if abs(seconds - float(getattr(rule, field_name))) < 1e-6:
        return
    setattr(rule, field_name, seconds)
    _refresh_summary(app)
    app._rules_changed(f"{field_label}：{seconds:g} 秒")


def _toggle_no_leave(app, no_leave: bool) -> None:
    rule = _selected_rule(app)
    if rule is None:
        return
    if no_leave:
        rule.leave = None
        app._rules_changed("这条规则不再自动退出", scopes=("detail",))
    else:
        rule.leave = ED.node_default("trigger")
        app._rules_changed("已加退出条件", scopes=("detail",))


def _tree_of(app, source: str) -> dict | None:
    rule = _selected_rule(app)
    if rule is None:
        return None
    return rule.enter if source == "enter" else rule.leave


def _change_type(app, path: tuple, node_type: str, source: str) -> None:
    tree = _tree_of(app, source)
    node = _node_at(tree, path)
    if tree is None or node is None or node.get("type") == node_type:
        return
    new_node = ED.node_default(node_type)
    if not path:
        # 根节点换类型 = 整棵树换掉
        _replace_tree(app, source, new_node)
        app._rules_changed(
            f"节点类型改为「{SR.NODE_LABELS.get(node_type, node_type)}」",
            scopes=("detail",),
        )
        return
    ED.set_node(tree, path, new_node)
    # 改类型会换掉这一行的所有字段：重画它所在的那一组（含它自己）
    local = _refresh_group(app, source, _parent_path(path))
    _refresh_summary(app)
    app._rules_changed(
        f"节点类型改为「{SR.NODE_LABELS.get(node_type, node_type)}」",
        scopes=() if local else ("detail",),
    )


def _replace_tree(app, source: str, node: dict) -> bool:
    """整棵树被换掉（根节点改类型）：只能改 Rule 上的字段。"""
    rule = _selected_rule(app)
    if rule is None:
        return False
    if source == "enter":
        rule.enter = node
    else:
        rule.leave = node
    return True


def _render_trigger_fields(app, row, node: dict, path: tuple, source: str) -> None:
    """扳机叶子：类型 + （自定义码）+ 参数前缀 + 作用侧。"""
    kind_ids = list(SR.TRIGGER_KINDS)
    kind_labels = [SR.TRIGGER_KINDS[key] for key in kind_ids]
    kind = str(node.get("kind", SR.TRIGGER_DEFAULT["kind"]))
    kind_var = ctk.StringVar(
        value=SR.TRIGGER_KINDS.get(kind, kind_labels[0])
    )
    ctk.CTkOptionMenu(
        row,
        variable=kind_var,
        values=kind_labels,
        command=lambda value: _change_trigger_kind(
            app, path, kind_ids[kind_labels.index(value)], source
        ),
        width=140,
        height=26,
        corner_radius=T.R_XS,
        fg_color=T.SURFACE,
        button_color=T.SURFACE,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left", padx=(0, T.S2), pady=T.S1)

    if kind == "custom":
        code_entry = ctk.CTkEntry(
            row,
            width=SMALL_ENTRY_WIDTH,
            height=26,
            corner_radius=T.R_XS,
            fg_color=T.SURFACE,
            border_color=T.BORDER,
            text_color=T.TEXT,
            font=font(T.XS),
        )
        code = node.get("code")
        code_entry.insert(0, f"{int(code):02x}" if isinstance(code, int) else "21")
        code_entry.pack(side="left", padx=(0, T.S2), pady=T.S1)
        _commit_on_edit(
            code_entry,
            lambda e=code_entry, p=path: _change_trigger_code(app, p, e.get(), source),
        )

    ctk.CTkLabel(row, text="前缀", font=font(T.XS), text_color=T.TEXT_FAINT).pack(
        side="left", padx=(0, T.S1)
    )
    prefix_entry = ctk.CTkEntry(
        row,
        width=SMALL_ENTRY_WIDTH,
        height=26,
        corner_radius=T.R_XS,
        fg_color=T.SURFACE,
        border_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    )
    prefix_entry.insert(0, str(node.get("prefix", "") or ""))
    prefix_entry.pack(side="left", padx=(0, T.S2), pady=T.S1)
    _commit_on_edit(
        prefix_entry,
        lambda e=prefix_entry, p=path: _change_trigger_prefix(app, p, e.get(), source),
    )

    side_ids = list(SR.TRIGGER_SIDES)
    side_labels = [SR.TRIGGER_SIDES[key] for key in side_ids]
    side = str(node.get("side", SR.TRIGGER_DEFAULT["side"]))
    side_var = ctk.StringVar(value=SR.TRIGGER_SIDES.get(side, side_labels[0]))
    ctk.CTkOptionMenu(
        row,
        variable=side_var,
        values=side_labels,
        command=lambda value: _change_trigger_side(
            app, path, side_ids[side_labels.index(value)], source
        ),
        width=110,
        height=26,
        corner_radius=T.R_XS,
        fg_color=T.SURFACE,
        button_color=T.SURFACE,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left", pady=T.S1)


def _render_button_fields(app, row, node: dict, path: tuple, source: str) -> None:
    """按钮叶子：选哪个手柄按钮（具体绑到哪个键盘键由映射决定，规则不用管）。"""
    names = list(SR.BUTTON_LABELS)
    labels = [SR.BUTTON_LABELS[name] for name in names]
    current = str(node.get("name", SR.BUTTON_DEFAULT)).strip().upper()
    var = ctk.StringVar(
        value=SR.BUTTON_LABELS.get(current, labels[0])
    )
    ctk.CTkOptionMenu(
        row,
        variable=var,
        values=labels,
        command=lambda value: _change_button(
            app, path, names[labels.index(value)], source
        ),
        width=120,
        height=26,
        corner_radius=T.R_XS,
        fg_color=T.SURFACE,
        button_color=T.SURFACE,
        button_hover_color=T.BORDER,
        text_color=T.TEXT,
        font=font(T.XS),
    ).pack(side="left", pady=T.S1)
    ctk.CTkLabel(
        row, text="按下后 3 秒内为真", font=font(T.XS), text_color=T.TEXT_FAINT
    ).pack(side="left", padx=(T.S2, 0))


def _change_button(app, path: tuple, name: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None or node.get("name") == name:
        return
    node["name"] = name
    _refresh_summary(app)
    app._rules_changed(f"按钮：{SR.BUTTON_LABELS.get(name, name)}")


def _change_trigger_kind(app, path: tuple, kind: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None or node.get("kind") == kind:
        return
    node["kind"] = kind
    if kind == "custom" and not isinstance(node.get("code"), int):
        node["code"] = 0x21
    if kind == "off":
        node["prefix"] = ""
    # 类型会决定这一行多不多「类型码」输入框：重画它所在的那一组
    local = _refresh_group(app, source, _parent_path(path)) if path else False
    _refresh_summary(app)
    app._rules_changed(
        f"扳机类型：{SR.TRIGGER_KINDS.get(kind, kind)}",
        scopes=() if local else ("detail",),
    )


def _change_trigger_side(app, path: tuple, side: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None or node.get("side") == side:
        return
    node["side"] = side
    _refresh_summary(app)
    app._rules_changed(f"作用侧：{SR.TRIGGER_SIDES.get(side, side)}")


def _change_trigger_prefix(app, path: tuple, text: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None:
        return
    try:
        prefix = SR.normalize_prefix(text)
    except ValueError as exc:
        _hint(app, f"前缀不对：{exc}")
        return
    if prefix and str(node.get("kind", "")) == "off":
        _hint(app, "Off 没有参数，先换类型再加前缀")
        return
    if str(node.get("prefix", "") or "") == prefix:
        return
    node["prefix"] = prefix
    _refresh_summary(app)
    app._rules_changed(f"参数前缀：{prefix.upper() or '（无）'}")


def _change_trigger_code(app, path: tuple, text: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None:
        return
    code = SR.parse_code(text)
    if code is None:
        _hint(app, "类型码要写成十六进制，例如 21")
        return
    if node.get("code") == code:
        return
    node["code"] = code
    _refresh_summary(app)
    app._rules_changed(f"类型码：0x{code:02X}")


def _change_seconds(app, path: tuple, text: str, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None:
        return
    seconds = SR.clamp_seconds(text)
    if abs(float(node.get("seconds", 0)) - seconds) < 1e-6:
        return
    node["seconds"] = seconds
    _refresh_summary(app)
    app._rules_changed(f"持续时间：{seconds:g} 秒")


def _add_child(app, path: tuple, source: str) -> None:
    node = _node_at(_tree_of(app, source), path)
    if node is None:
        return
    children = node.setdefault("children", [])
    child = ED.node_default("trigger")
    children.append(child)
    # 追加到末尾不会挪动兄弟节点的路径，所以只建这一行
    local = _append_child_row(
        app, source, path, child, path + ("children", len(children) - 1)
    )
    _refresh_summary(app)
    app._rules_changed("已添加子条件", scopes=() if local else ("detail",))


def _remove_node(app, path: tuple, source: str) -> None:
    tree = _tree_of(app, source)
    if tree is None:
        return
    parent_path = _parent_path(path)
    before = _node_at(tree, parent_path)
    before_type = str(before.get("type", "")) if before is not None else ""
    if not ED.remove_node(tree, path):
        return
    # 删到一个分组空了：那个分组自己会被换成普通信号节点（引用已换新），行内容也变了
    after = _node_at(tree, parent_path)
    collapsed = after is None or str(after.get("type", "")) != before_type
    local = False if collapsed else _refresh_group(app, source, parent_path)
    _refresh_summary(app)
    app._rules_changed("已删除条件", scopes=() if local else ("detail",))


def _fill_empty_slot(app, path: tuple, source: str) -> None:
    tree = _tree_of(app, source)
    if tree is None or not ED.set_node(tree, path, ED.node_default("trigger")):
        return
    local = _refresh_group(app, source, _parent_path(path))
    _refresh_summary(app)
    app._rules_changed("已添加条件", scopes=() if local else ("detail",))


def _node_at(tree: dict | None, path: tuple) -> dict | None:
    if tree is None:
        return None
    node = tree
    for key in path:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None
    return node if isinstance(node, dict) else None


def _commit_on_edit(widget, commit) -> None:
    """输入框：回车或失焦时提交（避免每敲一个字符就写一次盘）。"""
    widget.bind("<Return>", lambda event: commit())
    widget.bind("<FocusOut>", lambda event: commit())


def _hint(app, text: str) -> None:
    label = getattr(app, "_rule_toolbar_hint", None)
    if label is not None:
        label.configure(text=text)


# ---------------------------------------------------------------- 实时灯
def _refresh_lamps(app) -> None:
    """事实灯 + 规则灯：事实看当前真假，规则看「成立 / 已接管的 / 被压住的」。"""
    try:
        snapshot = app._signals.snapshot()
        for fact_id, lamp in getattr(app, "_fact_lamps", {}).items():
            lamp.configure(text_color=T.OK if snapshot.get(fact_id) else T.TEXT_FAINT)
        status = {item.rule_id: item for item in app._rules.status()}
        for rule_id, lamp in getattr(app, "_rule_lamps", {}).items():
            item = status.get(rule_id)
            if item is None:
                color = T.TEXT_FAINT
            elif item.armed:
                color = T.ACCENT
            elif item.blocked:
                color = T.WARN
            elif item.active:
                color = T.OK
            else:
                color = T.TEXT_FAINT
            lamp.configure(text_color=color)
    except Exception:  # noqa: BLE001 - 刷灯失败不能拖垮界面
        pass


def _tick_lamps(app) -> None:
    if getattr(app, "_closed", False) or not window_alive(app):
        app._rule_lamp_job = None
        return
    _refresh_lamps(app)
    try:
        app._rule_lamp_job = app.root.after(
            LAMP_INTERVAL_MS, lambda: _tick_lamps(app)
        )
    except Exception:  # noqa: BLE001 - 关窗时 Tk 已经销毁
        app._rule_lamp_job = None
