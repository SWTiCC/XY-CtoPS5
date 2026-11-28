"""冒烟脚本：在真实界面里跑一遍「规则编辑」的增删改，确认数据与画面一致。

只建界面、不连主机；不写盘（app._persist 在临时配置下也会写，跑完把 config 恢复）。
用法：python tools/smoke_rules_ui.py
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import customtkinter as ctk  # noqa: E402

from ps5kbm import rules_ui  # noqa: E402
from ps5kbm.app import Ps5KbmApp  # noqa: E402


def _count_rows(frame) -> int:
    """数一数这个容器里画了几个节点行（每行一个「类型」下拉）。"""
    total = 0
    for child in frame.winfo_children():
        if child.winfo_class() == "Frame" and _has_option_menu(child):
            total += 1
        total += _count_rows(child)
    return total


def _has_option_menu(widget) -> bool:
    for child in widget.winfo_children():
        if type(child).__name__ == "CTkOptionMenu":
            return True
    return False


def _find_group(node: dict, path: tuple = ()):
    if str(node.get("type", "")) in ("all", "any"):
        return path
    for _label, child, child_path in rules_ui._child_slots(node, path):
        if child is None:
            continue
        found = _search(child, child_path)
        if found is not None:
            return found
    return None


def _search(node: dict, path: tuple):
    if str(node.get("type", "")) in ("all", "any"):
        return path
    for _label, child, child_path in rules_ui._child_slots(node, path):
        if child is None:
            continue
        found = _search(child, child_path)
        if found is not None:
            return found
    return None


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass
    cfg_path = os.path.join(ROOT, "config.json")
    backup = cfg_path + ".smoke-bak"
    shutil.copy2(cfg_path, backup)
    try:
        return _run()
    finally:
        shutil.copy2(backup, cfg_path)
        os.remove(backup)


def _run() -> int:
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = Ps5KbmApp(root)
    root.update()
    app.show_page("mapping")
    app.open_rules_editor()
    root.update()

    rule = app._config.rules[0]
    app._edit_rule_id = rule.id
    rules_ui.refresh_rules_page(app)
    root.update()

    group_path = _find_group(rule.enter)
    print(f"分组路径 = {group_path}，进条件 = {json.dumps(rule.enter, ensure_ascii=False)}")
    assert group_path is not None, "预设里没有 all/any 分组"
    node = rules_ui._node_at(rule.enter, group_path)
    before = len(node["children"])
    frame = app._rule_groups[("enter", group_path)]
    rows_before = _count_rows(frame)
    print(f"加之前：数据 {before} 个子条件，画面 {rows_before} 行")

    rules_ui._add_child(app, group_path, "enter")
    root.update()
    node = rules_ui._node_at(rule.enter, group_path)
    frame = app._rule_groups[("enter", group_path)]
    print(f"加之后：数据 {len(node['children'])} 个子条件，画面 {_count_rows(frame)} 行")
    assert len(node["children"]) == before + 1
    assert _count_rows(frame) == rows_before + 1

    rules_ui._remove_node(app, group_path + ("children", before), "enter")
    root.update()
    node = rules_ui._node_at(rule.enter, group_path)
    frame = app._rule_groups[("enter", group_path)]
    print(f"删之后：数据 {len(node['children'])} 个子条件，画面 {_count_rows(frame)} 行")
    assert len(node["children"]) == before
    assert _count_rows(frame) == rows_before

    rules_ui._change_type(app, group_path + ("children", 0), "rumble", "enter")
    root.update()
    node = rules_ui._node_at(rule.enter, group_path)
    print(f"换类型后 children[0] = {node['children'][0]}")
    assert node["children"][0]["type"] == "rumble"

    rules_ui._change_type(app, group_path + ("children", 0), "trigger", "enter")
    root.update()
    rules_ui._change_trigger_prefix(app, group_path + ("children", 0), "ff03", "enter")
    root.update()
    node = rules_ui._node_at(rule.enter, group_path)
    print(f"改前缀后 children[0] = {node['children'][0]}")
    assert node["children"][0]["prefix"] == "ff03"

    rules_ui._add_rule(app)
    root.update()
    rules_ui._delete_rule(app)
    root.update()
    rules_ui._select(app, rule.id)
    root.update()
    print(f"规则数 = {len(app._config.rules)}，读法 = {rule.summary()[:60]}…")

    rules_ui.close_editor(app)
    root.update()
    app._on_close()
    print("冒烟通过：数据与画面一致，无异常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
