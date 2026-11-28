"""诊断脚本：量一量「规则编辑面板整页重画」到底花多少毫秒。

做法：造一个假 app（只提供面板要读的字段），用真实预设里的规则建面板，
然后对 refresh_rules_page 计时。不连主机、不写盘。
"""

from __future__ import annotations

import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import customtkinter as ctk  # noqa: E402

from ps5kbm import config, rules_ui  # noqa: E402

ROUNDS = 10
GTA6_PRESET = os.path.join(ROOT, "presets", "gta6.json")


class FakeSignals:
    def snapshot(self) -> dict:
        return {}


class FakeEngine:
    def status(self) -> list:
        return []


class FakeApp:
    """面板只读这几个字段，其余（改数据后的落盘）这里不需要。"""

    def __init__(self, cfg, root):
        self._config = cfg
        self.root = root
        self._closed = False
        self._edit_rule_id = cfg.rules[0].id if cfg.rules else ""
        self._signals = FakeSignals()
        self._rules = FakeEngine()
        self._calls: list[str] = []

    def _mode_label(self, name: str) -> str:
        mode = self._config.modes.get(name)
        return (mode.label if mode and mode.label else name) if mode else name

    def _rule_target_options(self):
        labels, mapping = [], {}
        for name in self._config.modes:
            if name == "default":
                continue
            text = self._mode_label(name)
            labels.append(text)
            mapping[text] = name
        return labels, mapping

    def _rules_changed(self, message: str = "", scopes: tuple = ()) -> None:
        self._calls.append(message)
        # 真实 app 会把重画推迟一拍；这里同步执行，量的就是用户实际等的那一下
        if scopes:
            rules_ui.refresh_rules_page(self, scopes)

    def toggle_auto_switch(self) -> None:
        pass


def main() -> int:
    cfg = config.load_config()
    if not cfg.rules:
        print("当前配置里没有规则，改用 presets/gta6.json")
        cfg = config.preset_to_config(GTA6_PRESET)
    print(f"规则数 = {len(cfg.rules)}，模式 = {list(cfg.modes)}")

    root = ctk.CTk()
    root.geometry("1000x740")
    app = FakeApp(cfg, root)
    win = ctk.CTkToplevel(root)
    win.geometry("980x720")
    app._rules_window = win
    page = rules_ui.build_rules_page(app, win)
    page.pack(fill="both", expand=True)
    root.update()

    samples: list[float] = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        rules_ui.refresh_rules_page(app)
        root.update_idletasks()
        samples.append((time.perf_counter() - start) * 1000)

    print(f"整页重画：{ROUNDS} 次，中位数 {statistics.median(samples):.1f} ms，"
          f"最快 {min(samples):.1f} ms，最慢 {max(samples):.1f} ms")

    def widget_count(widget) -> int:
        total = 1
        for child in widget.winfo_children():
            total += widget_count(child)
        return total

    print(
        "细节窗控件数：列表 {}，详情 {}".format(
            widget_count(app._rule_list), widget_count(app._rule_detail)
        )
    )

    for name, func in (
        ("表头", rules_ui._render_header),
        ("列表", rules_ui._render_list),
        ("详情", rules_ui._render_detail),
    ):
        parts: list[float] = []
        for _ in range(ROUNDS):
            start = time.perf_counter()
            func(app)
            root.update_idletasks()
            parts.append((time.perf_counter() - start) * 1000)
        print(f"  {name}单独重画：中位数 {statistics.median(parts):.1f} ms")

    # 编辑动作：量「改一次数据后用户要等多久」
    rule = app._config.rules[0]
    all_path = _find_group_path(rule.enter)
    actions = [
        ("加一个子条件", lambda: rules_ui._add_child(app, all_path, "enter")),
        ("删掉刚加的子条件", lambda: rules_ui._remove_node(app, all_path + ("children", 1), "enter")),
        ("改前缀（纯数据）", lambda: rules_ui._change_trigger_prefix(
            app, all_path + ("children", 0), "ff03", "enter"
        )),
        ("换节点类型", lambda: rules_ui._change_type(
            app, all_path + ("children", 0), "button", "enter"
        )),
    ]
    for label, func in actions:
        samples_edit: list[float] = []
        for _ in range(3):
            start = time.perf_counter()
            func()
            root.update_idletasks()
            samples_edit.append((time.perf_counter() - start) * 1000)
        print(f"  {label}：中位数 {statistics.median(samples_edit):.1f} ms")

    root.destroy()
    return 0


def _find_group_path(node: dict, path: tuple = ()) -> tuple:
    """找一棵树里第一个 all/any 分组的路径（用来对着它加子条件）。"""
    if str(node.get("type", "")) in ("all", "any"):
        return path
    for _label, child, child_path in rules_ui._child_slots(node, path):
        if child is None:
            continue
        found = _search_group(child, child_path)
        if found is not None:
            return found
    raise SystemExit("预设里没有 all/any 分组，换个预设再量")


def _search_group(node: dict, path: tuple) -> tuple | None:
    if str(node.get("type", "")) in ("all", "any"):
        return path
    for _label, child, child_path in rules_ui._child_slots(node, path):
        if child is None:
            continue
        found = _search_group(child, child_path)
        if found is not None:
            return found
    return None


if __name__ == "__main__":
    raise SystemExit(main())
