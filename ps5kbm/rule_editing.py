"""规则与条件树的**编辑操作**：新建、复制、挪顺序、按路径换/删节点、校验。

这些函数是「编辑页点了之后改哪份数据」的全部逻辑，纯数据操作（不碰 Tk、不做 IO），
所以能直接单测；``rules_ui.py`` 只负责把按钮接到这里。

路径的表示：从条件树根节点开始的键/下标序列，例如 ``("children", 0)``、
``("set", "children", 1)``、``("child",)``。
"""

from __future__ import annotations

import copy as copy_module

from .rule_engine import Rule
from .signal_rules import BUTTON_DEFAULT, TRIGGER_DEFAULT, parse_condition


# ---------------------------------------------------------------- 编辑操作
# 这些函数给编辑页用，都是纯数据操作（不做 IO、不碰 Tk），所以能单测。
def node_default(node_type: str) -> dict:
    """造一个该类型的默认节点（新建 / 换类型时用）。"""
    if node_type == "trigger":
        return {
            "type": "trigger",
            "kind": TRIGGER_DEFAULT["kind"],
            "prefix": TRIGGER_DEFAULT["prefix"],
            "side": TRIGGER_DEFAULT["side"],
        }
    if node_type == "button":
        return {"type": "button", "name": BUTTON_DEFAULT}
    if node_type in ("rumble", "haptics"):
        return {"type": node_type}
    if node_type in ("all", "any"):
        return {"type": node_type, "children": [node_default("trigger")]}
    if node_type == "not":
        return {"type": "not", "child": node_default("trigger")}
    if node_type == "hold":
        return {"type": "hold", "seconds": 0.5, "child": node_default("trigger")}
    if node_type == "latch":
        return {
            "type": "latch",
            "set": node_default("trigger"),
            "clear": node_default("trigger"),
        }
    if node_type == "before":
        return {
            "type": "before",
            "first": node_default("trigger"),
            "then": node_default("trigger"),
        }
    raise ValueError(f"未知节点类型：{node_type!r}")


def _parent_of(tree: dict, path: tuple):
    """按路径找到父容器（list 或 dict）与该节点自己的键。"""
    if not path:
        return None, None
    node = tree
    for key in path[:-1]:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None, None
    return node, path[-1]


def set_node(tree: dict, path: tuple, node: dict) -> bool:
    """把路径处的节点换成 ``node``；路径不存在返回 False。"""
    parent, key = _parent_of(tree, path)
    if isinstance(parent, list):
        if not isinstance(key, int) or not 0 <= key < len(parent):
            return False
        parent[key] = node
        return True
    if isinstance(parent, dict):
        if key not in parent:
            return False
        parent[key] = node
        return True
    return False


def remove_node(tree: dict, path: tuple) -> bool:
    """删掉路径处的节点。

    只允许删「兄弟列表」里的节点：单槽位（``not`` 的 ``child``、``latch`` 的 ``set``）
    删了树就残了，那种情况该改父节点的类型，而不是把子节点拿走。

    删到一个分组空了（比如「全部满足」只剩一个条件），就把这个分组自己换成普通信号
    节点——空分组编译不过，留着等于留一棵坏树。
    """
    parent, key = _parent_of(tree, path)
    if not isinstance(parent, list) or not isinstance(key, int):
        return False
    if not 0 <= key < len(parent):
        return False
    del parent[key]
    if not parent:
        _collapse_empty_group(tree, path[:-2])
    return True


def _collapse_empty_group(tree: dict, group_path: tuple) -> None:
    """把「子条件被删空」的分组节点换成一个普通信号节点。"""
    replacement = node_default("trigger")
    if not group_path:
        # 根节点就是那个分组：原地替换，让调用方手里的引用继续有效
        tree.clear()
        tree.update(replacement)
        return
    set_node(tree, group_path, replacement)


def _next_rule_id(rules: list[Rule], prefix: str = "rule") -> str:
    existing = {rule.id for rule in rules}
    index = 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def new_rule(rules: list[Rule], target: str, label: str = "") -> Rule:
    """在列表末尾加一条空规则（进入条件默认是「两侧开车特征」）。"""
    rule = Rule(
        id=_next_rule_id(rules),
        label=label or f"规则 {len(rules) + 1}",
        target=target,
        enter=node_default("trigger"),
    )
    rules.append(rule)
    return rule


def clone_rule(rules: list[Rule], rule: Rule) -> Rule:
    """复制一条规则（条件树深拷贝，改副本不影响原件）。"""
    copy = Rule(
        id=_next_rule_id(rules, prefix="copy"),
        label=f"{rule.label}（副本）",
        target=rule.target,
        enabled=rule.enabled,
        enter=copy_module.deepcopy(rule.enter),
        leave=copy_module.deepcopy(rule.leave),
        enter_hold=rule.enter_hold,
        leave_delay=rule.leave_delay,
    )
    rules.append(copy)
    return copy


def clone_rules(rules: list[Rule]) -> list[Rule]:
    """整份深拷贝（复制规则集用）：规则集之间互不引用，id 保持不变。"""
    return [copy_module.deepcopy(rule) for rule in rules]


def move_rule(rules: list[Rule], index: int, delta: int) -> int:
    """上下挪一条规则，返回挪完之后它的下标（越界就原地不动）。"""
    if not 0 <= index < len(rules):
        return index
    target = index + delta
    if not 0 <= target < len(rules):
        return index
    rules[index], rules[target] = rules[target], rules[index]
    return target


def rule_error(rule: Rule) -> str:
    """这条规则现在能不能跑；能跑返回空串，否则返回一句人话。

    编辑时用它做即时提示：坏规则在写盘后会被 ``parse_rules`` 丢掉，
    与其静默消失，不如当场告诉用户哪里不对。
    """
    if not rule.target:
        return "还没有选目标模式"
    try:
        parse_condition(rule.enter)
    except ValueError as exc:
        return f"进入条件无效：{exc}"
    if rule.leave is not None:
        try:
            parse_condition(rule.leave)
        except ValueError as exc:
            return f"退出条件无效：{exc}"
    return ""
