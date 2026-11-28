"""编辑面板用到的纯数据操作：默认节点、路径替换/删除、规则增删改、校验。

面板本身要 Tk，测不了；这些函数才是「点了之后数据对不对」的关键，所以单独测。
"""

from __future__ import annotations

import unittest

from ps5kbm import rule_editing as ED
from ps5kbm import rule_engine as RE
from ps5kbm import signal_rules as SR


def trigger(kind: str = "resistance", prefix: str = "", side: str = "both") -> dict:
    return {"type": "trigger", "kind": kind, "prefix": prefix, "side": side}


def rule(rule_id: str = "r1", target: str = "driving") -> RE.Rule:
    return RE.Rule(id=rule_id, label=rule_id, target=target, enter=trigger())


class NodeDefaultTests(unittest.TestCase):
    """每种类型的默认节点都必须能编译——否则「加一个节点」当场就坏。"""

    def test_every_type_compiles(self):
        for node_type in SR.NODE_LABELS:
            with self.subTest(node_type=node_type):
                node = ED.node_default(node_type)
                self.assertEqual(node["type"], node_type)
                SR.parse_condition(node)

    def test_trigger_default(self):
        node = ED.node_default("trigger")
        self.assertEqual(node["kind"], SR.TRIGGER_DEFAULT["kind"])
        self.assertEqual(node["side"], SR.TRIGGER_DEFAULT["side"])
        self.assertEqual(node["prefix"], "")

    def test_latch_has_both_slots(self):
        node = ED.node_default("latch")
        self.assertEqual(node["set"]["type"], "trigger")
        self.assertEqual(node["clear"]["type"], "trigger")

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            ED.node_default("magic")


class SetRemoveNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = {
            "type": "all",
            "children": [trigger(), trigger(side="left")],
        }

    def test_set_child_in_list(self):
        self.assertTrue(ED.set_node(self.tree, ("children", 1), trigger(side="right")))
        self.assertEqual(self.tree["children"][1]["side"], "right")

    def test_set_child_in_slot(self):
        tree = {"type": "not", "child": trigger()}
        self.assertTrue(ED.set_node(tree, ("child",), trigger(side="any")))
        self.assertEqual(tree["child"]["side"], "any")

    def test_set_missing_path_fails(self):
        self.assertFalse(ED.set_node(self.tree, ("children", 9), trigger()))
        self.assertFalse(ED.set_node(self.tree, ("set",), trigger()))
        self.assertFalse(ED.set_node(self.tree, (), trigger()))

    def test_remove_child(self):
        self.assertTrue(ED.remove_node(self.tree, ("children", 0)))
        self.assertEqual(len(self.tree["children"]), 1)

    def test_removing_last_child_collapses_group(self):
        """「全部满足」的条件被删光时，分组自己降级成一个普通叶子（空树编译不过）。"""
        self.assertTrue(ED.remove_node(self.tree, ("children", 0)))
        self.assertTrue(ED.remove_node(self.tree, ("children", 0)))
        self.assertEqual(self.tree["type"], "trigger")
        SR.parse_condition(self.tree)

    def test_cannot_remove_single_slot(self):
        tree = {"type": "not", "child": trigger()}
        self.assertFalse(ED.remove_node(tree, ("child",)))
        self.assertIn("child", tree)

    def test_nested_set_and_remove(self):
        tree = {
            "type": "latch",
            "set": {"type": "any", "children": [trigger()]},
            "clear": trigger(kind="off"),
        }
        path = ("set", "children", 0)
        self.assertTrue(ED.set_node(tree, path, trigger(prefix="ff03")))
        self.assertEqual(tree["set"]["children"][0]["prefix"], "ff03")
        self.assertTrue(ED.remove_node(tree, path))


class RuleEditingTests(unittest.TestCase):
    def test_new_rule_has_unique_id(self):
        rules = [rule("rule-1")]
        created = ED.new_rule(rules, "driving")
        self.assertEqual(created.id, "rule-2")
        self.assertEqual(len(rules), 2)
        SR.parse_condition(created.enter)

    def test_new_rule_label_increments(self):
        rules = []
        self.assertEqual(ED.new_rule(rules, "driving").label, "规则 1")
        self.assertEqual(ED.new_rule(rules, "shoot").label, "规则 2")

    def test_clone_is_deep_copy(self):
        original = rule("gta6", "driving")
        original.enter = {"type": "all", "children": [trigger(side="left")]}
        rules = [original]
        copy = ED.clone_rule(rules, original)
        self.assertNotEqual(copy.id, original.id)
        self.assertIn("副本", copy.label)
        self.assertEqual(copy.enter, original.enter)
        copy.enter["children"][0]["side"] = "right"
        self.assertEqual(original.enter["children"][0]["side"], "left")

    def test_clone_rules_for_ruleset_copy(self):
        rules = [rule("a"), rule("b")]
        copies = ED.clone_rules(rules)
        self.assertEqual([item.id for item in copies], ["a", "b"])
        copies[0].enter["side"] = "right"
        self.assertEqual(rules[0].enter["side"], "both")

    def test_move_rule(self):
        rules = [rule("a"), rule("b"), rule("c")]
        self.assertEqual(ED.move_rule(rules, 0, 1), 1)
        self.assertEqual([item.id for item in rules], ["b", "a", "c"])
        self.assertEqual(ED.move_rule(rules, 0, -1), 0)  # 已经最前
        self.assertEqual([item.id for item in rules], ["b", "a", "c"])
        self.assertEqual(ED.move_rule(rules, 2, 1), 2)  # 已经最后
        self.assertEqual(ED.move_rule(rules, 99, 1), 99)  # 越界

    def test_rule_error_reports_problems(self):
        good = rule()
        self.assertEqual(ED.rule_error(good), "")

        no_target = rule()
        no_target.target = ""
        self.assertIn("目标模式", ED.rule_error(no_target))

        bad_enter = rule()
        bad_enter.enter = {"type": "magic"}
        self.assertIn("进入条件", ED.rule_error(bad_enter))

        bad_leave = rule()
        bad_leave.leave = {"type": "magic"}
        self.assertIn("退出条件", ED.rule_error(bad_leave))

    def test_new_rule_error_is_clean(self):
        rules: list[RE.Rule] = []
        created = ED.new_rule(rules, "driving")
        self.assertEqual(ED.rule_error(created), "")


if __name__ == "__main__":
    unittest.main()
