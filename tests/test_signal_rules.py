"""规则引擎：条件树、规则解析、旧配置迁移、状态机。全是纯逻辑，时间显式传入。"""

from __future__ import annotations

import unittest

from ps5kbm import config as config_module
from ps5kbm import legacy_rules
from ps5kbm import mode_signals
from ps5kbm import rule_engine as re_
from ps5kbm import signal_rules as sr


def trigger(kind: str = "resistance", prefix: str = "", side: str = "both") -> dict:
    return {"type": "trigger", "kind": kind, "prefix": prefix, "side": side}


def simple(fact_id: str) -> dict:
    return {"type": fact_id}


def button(name: str = "TRIANGLE") -> dict:
    return {"type": "button", "name": name}


def trig_key(kind: str = "resistance", prefix: str = "", side: str = "both") -> str:
    """FakeFacts 里表示「这一侧/这两侧是这种效果」的键。"""
    return f"trigger:{kind}:{prefix}:{side}"


class FakeFacts:
    """手动开关的事实表：规则引擎只依赖 is_true / trigger_match。"""

    def __init__(self, facts=(), triggers=(), buttons=()) -> None:
        self.facts = set(facts)
        self.triggers = set(triggers)
        self.buttons = set(buttons)

    def set(self, fact_id: str, value: bool) -> None:
        if value:
            self.facts.add(fact_id)
        else:
            self.facts.discard(fact_id)

    def set_trigger(self, key: str, value: bool) -> None:
        if value:
            self.triggers.add(key)
        else:
            self.triggers.discard(key)

    def press(self, name: str) -> None:
        self.buttons.add(name)

    def release(self, name: str) -> None:
        self.buttons.discard(name)

    def is_true(self, fact_id: str, now: float | None = None) -> bool:
        return fact_id in self.facts

    def button_active(self, name: str, now: float | None = None) -> bool:
        return name in self.buttons

    def trigger_match(self, kind, code=None, prefix="", side="both", now=None):
        return trig_key(kind, prefix, side) in self.triggers


def make_rule(
    rule_id: str = "r1",
    target: str = "driving",
    enter: dict | None = None,
    leave: dict | None = None,
    hold: float = 0.0,
    delay: float = 0.0,
    enabled: bool = True,
) -> re_.Rule:
    return re_.Rule(
        id=rule_id,
        label=rule_id,
        target=target,
        enabled=enabled,
        enter=enter or trigger(),
        leave=leave,
        enter_hold=hold,
        leave_delay=delay,
    )


class CountingCondition(sr.Condition):
    """记「被求值了几次」的条件，用来证明组合节点不短路。"""

    def __init__(self, value: bool) -> None:
        self.value = value
        self.calls = 0

    def evaluate(self, facts, now: float) -> bool:
        self.calls += 1
        return self.value


class DescribeConditionTests(unittest.TestCase):
    def test_trigger_renders_kind_side_prefix(self):
        text = sr.describe_condition(trigger(prefix="ff03"))
        self.assertIn("两侧", text)
        self.assertIn("阻力", text)
        self.assertIn("FF03", text)

    def test_trigger_any_side_and_off(self):
        self.assertIn("任一侧", sr.describe_condition(trigger(side="any")))
        self.assertIn("无效果", sr.describe_condition(trigger(kind="off")))

    def test_custom_code(self):
        text = sr.describe_condition(
            {"type": "trigger", "kind": "custom", "code": 33, "prefix": "", "side": "left"}
        )
        self.assertIn("0x21", text)

    def test_simple_facts_use_labels(self):
        self.assertEqual(sr.describe_condition(simple("rumble")), sr.fact_label("rumble"))

    def test_legacy_fact_is_translated(self):
        text = sr.describe_condition({"type": "fact", "fact": "trigger.vehicle"})
        self.assertIn("FF03", text)

    def test_all_and_any_joiners(self):
        node = {"type": "all", "children": [trigger(), button()]}
        self.assertIn("且", sr.describe_condition(node))
        node = {"type": "any", "children": [trigger(), button()]}
        self.assertIn("或", sr.describe_condition(node))

    def test_latch_and_hold_and_before(self):
        latch = {"type": "latch", "set": trigger(), "clear": button()}
        self.assertIn("锁存", sr.describe_condition(latch))
        hold = {"type": "hold", "seconds": 0.5, "child": simple("rumble")}
        self.assertIn("持续 0.5s", sr.describe_condition(hold))
        before = {"type": "before", "first": button(), "then": trigger()}
        self.assertIn("先", sr.describe_condition(before))

    def test_garbage(self):
        self.assertEqual(sr.describe_condition(None), "（空）")
        self.assertEqual(sr.describe_condition({"type": "???"}), "（无效）")


class ParseConditionTests(unittest.TestCase):
    def test_trigger(self):
        cond = sr.parse_condition(trigger(side="any", prefix="ff03"))
        self.assertIsInstance(cond, sr.TriggerCondition)
        self.assertEqual(cond.side, "any")
        self.assertEqual(cond.prefix, "ff03")
        self.assertEqual(cond.kind, "resistance")

    def test_prefix_is_normalized(self):
        cond = sr.parse_condition(trigger(prefix="FF 03"))
        self.assertEqual(cond.prefix, "ff03")
        cond = sr.parse_condition(trigger(prefix="0xFF03"))
        self.assertEqual(cond.prefix, "ff03")

    def test_bad_prefix_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(trigger(prefix="zz"))

    def test_off_with_prefix_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(trigger(kind="off", prefix="ff"))

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(trigger(kind="magic"))

    def test_unknown_side_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(trigger(side="middle"))

    def test_custom_needs_code(self):
        with self.assertRaises(ValueError):
            sr.parse_condition({"type": "trigger", "kind": "custom", "code": None})
        cond = sr.parse_condition(
            {"type": "trigger", "kind": "custom", "code": "21", "prefix": "", "side": "both"}
        )
        self.assertEqual(cond.code, 0x21)

    def test_simple_facts(self):
        for fact_id in ("rumble", "haptics"):
            cond = sr.parse_condition(simple(fact_id))
            self.assertIsInstance(cond, sr.SimpleCondition)

    def test_button_leaf(self):
        cond = sr.parse_condition(button())
        self.assertIsInstance(cond, sr.ButtonCondition)
        self.assertEqual(cond.name, "TRIANGLE")
        self.assertEqual(sr.parse_condition(button("cross")).name, "CROSS")

    def test_unknown_button_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(button("BUTTON_X"))

    def test_legacy_fact_still_parses(self):
        cond = sr.parse_condition({"type": "fact", "fact": "trigger.vehicle"})
        self.assertIsInstance(cond, sr.TriggerCondition)
        self.assertEqual(cond.prefix, "ff03")

    def test_unknown_legacy_fact_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition({"type": "fact", "fact": "不存在"})

    def test_empty_all_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition({"type": "all", "children": []})

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition({"type": "magic"})

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition(["not", "a", "dict"])

    def test_broken_child_raises(self):
        with self.assertRaises(ValueError):
            sr.parse_condition({"type": "not", "child": {"type": "magic"}})


class NormalizeConditionTests(unittest.TestCase):
    def test_legacy_fact_becomes_trigger(self):
        node = sr.normalize_condition({"type": "fact", "fact": "trigger.vehicle"})
        self.assertEqual(
            node, {"type": "trigger", "kind": "resistance", "prefix": "ff03", "side": "both"}
        )

    def test_simple_fact_stays_simple(self):
        self.assertEqual(sr.normalize_condition({"type": "fact", "fact": "rumble"}), {"type": "rumble"})

    def test_nested_normalization(self):
        node = sr.normalize_condition(
            {
                "type": "latch",
                "set": {"type": "fact", "fact": "trigger.vehicle"},
                "clear": {
                    "type": "all",
                    "children": [
                        {"type": "fact", "fact": "interact"},
                        {"type": "fact", "fact": "trigger.off"},
                    ],
                },
            }
        )
        self.assertEqual(node["set"]["type"], "trigger")
        self.assertEqual(node["clear"]["children"][1]["kind"], "off")
        sr.parse_condition(node)

    def test_hold_seconds_are_clamped(self):
        node = sr.normalize_condition(
            {"type": "hold", "seconds": "999", "child": {"type": "rumble"}}
        )
        self.assertAlmostEqual(node["seconds"], 10.0)


class ConditionBehaviourTests(unittest.TestCase):
    def test_hold_needs_continuous_time(self):
        cond = sr.HoldCondition(sr.SimpleCondition(sr.FACT_RUMBLE), 0.5)
        facts = FakeFacts(facts=[sr.FACT_RUMBLE])
        self.assertFalse(cond.evaluate(facts, 0.0))
        self.assertFalse(cond.evaluate(facts, 0.4))
        self.assertTrue(cond.evaluate(facts, 0.5))
        # 断了就重新计时
        facts.set(sr.FACT_RUMBLE, False)
        self.assertFalse(cond.evaluate(facts, 0.6))
        facts.set(sr.FACT_RUMBLE, True)
        self.assertFalse(cond.evaluate(facts, 0.7))
        self.assertTrue(cond.evaluate(facts, 1.2))

    def test_hold_zero_is_immediately_true(self):
        cond = sr.HoldCondition(sr.SimpleCondition(sr.FACT_RUMBLE), 0.0)
        self.assertTrue(cond.evaluate(FakeFacts(facts=[sr.FACT_RUMBLE]), 5.0))

    def test_latch_sticks_until_clear(self):
        cond = sr.parse_condition(
            {
                "type": "latch",
                "set": trigger(prefix="ff03"),
                "clear": button(),
            }
        )
        facts = FakeFacts(triggers=[trig_key(prefix="ff03")])
        self.assertTrue(cond.evaluate(facts, 0.0))
        facts.set_trigger(trig_key(prefix="ff03"), False)
        self.assertTrue(cond.evaluate(facts, 100.0))
        facts.press("TRIANGLE")
        self.assertFalse(cond.evaluate(facts, 101.0))

    def test_latch_clear_wins_same_tick(self):
        cond = sr.parse_condition(
            {"type": "latch", "set": button(), "clear": simple("rumble")}
        )
        facts = FakeFacts(facts=["interact", "rumble"])
        self.assertFalse(cond.evaluate(facts, 0.0))

    def test_latch_without_clear_never_resets(self):
        cond = sr.parse_condition({"type": "latch", "set": button()})
        facts = FakeFacts(buttons=["TRIANGLE"])
        self.assertTrue(cond.evaluate(facts, 0.0))
        facts.release("TRIANGLE")
        self.assertTrue(cond.evaluate(facts, 99.0))

    def test_before_needs_first_to_happen(self):
        cond = sr.parse_condition(
            {"type": "before", "first": button(), "then": trigger()}
        )
        facts = FakeFacts(triggers=[trig_key()])
        self.assertFalse(cond.evaluate(facts, 0.0))
        facts.press("TRIANGLE")
        cond.evaluate(facts, 1.0)
        facts.release("TRIANGLE")
        self.assertTrue(cond.evaluate(facts, 2.0))

    def test_not(self):
        cond = sr.NotCondition(sr.SimpleCondition(sr.FACT_RUMBLE))
        self.assertTrue(cond.evaluate(FakeFacts(), 0.0))
        self.assertFalse(cond.evaluate(FakeFacts(facts=[sr.FACT_RUMBLE]), 0.0))

    def test_all_does_not_short_circuit(self):
        """后面的节点也要每 tick 求值，否则 hold / latch 的计时会随书写顺序变化。"""
        first = CountingCondition(False)
        second = CountingCondition(True)
        cond = sr.AllCondition([first, second])
        self.assertFalse(cond.evaluate(FakeFacts(), 0.0))
        self.assertEqual(second.calls, 1)

    def test_any_does_not_short_circuit(self):
        first = CountingCondition(True)
        second = CountingCondition(False)
        cond = sr.AnyCondition([first, second])
        self.assertTrue(cond.evaluate(FakeFacts(), 0.0))
        self.assertEqual(second.calls, 1)

    def test_reset_forgets_state(self):
        latch = sr.parse_condition({"type": "latch", "set": button()})
        facts = FakeFacts(buttons=["TRIANGLE"])
        self.assertTrue(latch.evaluate(facts, 0.0))
        latch.reset()
        facts.release("TRIANGLE")
        self.assertFalse(latch.evaluate(facts, 1.0))

    def test_trigger_condition_uses_side(self):
        cond = sr.parse_condition(trigger(side="left"))
        self.assertTrue(cond.evaluate(FakeFacts(triggers=[trig_key(side="left")]), 0.0))
        self.assertFalse(cond.evaluate(FakeFacts(triggers=[trig_key(side="right")]), 0.0))


class ParseRulesTests(unittest.TestCase):
    def test_parses_valid_rule(self):
        rules = re_.parse_rules(
            [
                {
                    "id": "r",
                    "label": "开车",
                    "target": "driving",
                    "enter": trigger(),
                    "enter_hold": 1.0,
                    "leave_delay": 2.0,
                }
            ]
        )
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].label, "开车")
        self.assertAlmostEqual(rules[0].enter_hold, 1.0)
        self.assertAlmostEqual(rules[0].leave_delay, 2.0)
        self.assertIsNone(rules[0].leave)

    def test_legacy_nodes_are_upgraded_on_parse(self):
        """老 fact 写法解析后就变成参数化叶子，下次保存直接写新格式。"""
        rules = re_.parse_rules(
            [
                {
                    "id": "old",
                    "target": "driving",
                    "enter": {"type": "fact", "fact": "trigger.vehicle"},
                }
            ]
        )
        self.assertEqual(rules[0].enter["type"], "trigger")
        self.assertEqual(rules[0].enter["prefix"], "ff03")

    def test_nested_legacy_nodes_are_upgraded(self):
        rules = re_.parse_rules(
            [
                {
                    "id": "old",
                    "target": "driving",
                    "enter": {
                        "type": "all",
                        "children": [
                            {"type": "fact", "fact": "interact"},
                            {"type": "fact", "fact": "trigger.off"},
                        ],
                    },
                }
            ]
        )
        children = rules[0].enter["children"]
        self.assertEqual(children[0], {"type": "button", "name": "TRIANGLE"})
        self.assertEqual(children[1]["kind"], "off")

    def test_missing_id_gets_generated(self):
        rules = re_.parse_rules([{"target": "driving", "enter": trigger()}])
        self.assertEqual(rules[0].id, "rule-1")

    def test_duplicate_id_keeps_first(self):
        rules = re_.parse_rules(
            [
                {"id": "same", "target": "a", "enter": trigger()},
                {"id": "same", "target": "b", "enter": trigger()},
            ]
        )
        self.assertEqual([rule.target for rule in rules], ["a"])

    def test_missing_target_dropped(self):
        self.assertEqual(re_.parse_rules([{"enter": trigger()}]), [])

    def test_bad_enter_dropped(self):
        self.assertEqual(re_.parse_rules([{"target": "a", "enter": {"type": "magic"}}]), [])

    def test_bad_leave_is_dropped_but_rule_kept(self):
        rules = re_.parse_rules(
            [{"target": "a", "enter": trigger(), "leave": {"type": "magic"}}]
        )
        self.assertEqual(len(rules), 1)
        self.assertIsNone(rules[0].leave)

    def test_defaults_come_from_preset(self):
        rules = re_.parse_rules([{"target": "a", "enter": trigger()}], 2.0, 3.0)
        self.assertAlmostEqual(rules[0].enter_hold, 2.0)
        self.assertAlmostEqual(rules[0].leave_delay, 3.0)

    def test_huge_delay_is_clamped(self):
        rules = re_.parse_rules(
            [{"target": "a", "enter": trigger(), "enter_hold": 999}]
        )
        self.assertAlmostEqual(rules[0].enter_hold, 10.0)

    def test_negative_delay_is_zero(self):
        rules = re_.parse_rules(
            [{"target": "a", "enter": trigger(), "leave_delay": -5}]
        )
        self.assertAlmostEqual(rules[0].leave_delay, 0.0)

    def test_rule_dict_roundtrip(self):
        rules = re_.parse_rules(
            [
                {
                    "id": "r",
                    "target": "a",
                    "enter": trigger(side="any"),
                    "leave": {"type": "not", "child": button()},
                }
            ]
        )
        rebuilt = re_.parse_rules(re_.rules_to_dict(rules))
        self.assertEqual(rebuilt[0].enter, rules[0].enter)
        self.assertEqual(rebuilt[0].leave, rules[0].leave)


class MigrationTests(unittest.TestCase):
    LEGACY_MODES = {
        "default": {"label": "默认"},
        "driving": {"label": "驾驶", "auto_signal": "vehicle_entry", "auto_leave": True},
    }

    def test_vehicle_entry_becomes_latching_rule(self):
        rules = legacy_rules.migrate_legacy_modes(self.LEGACY_MODES, 0.8, 1.2)
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.target, "driving")
        self.assertEqual(rule.id, "legacy-driving")
        self.assertEqual(rule.enter["type"], "latch")
        self.assertEqual(rule.enter["set"]["prefix"], "ff03")
        self.assertEqual(rule.enter["set"]["side"], "both")
        self.assertEqual(rule.leave["type"], "all")
        self.assertEqual(rule.leave["children"][1]["kind"], "off")
        sr.parse_condition(rule.enter)
        sr.parse_condition(rule.leave)

    def test_auto_leave_false_means_no_exit(self):
        modes = {
            "shoot": {"label": "射击", "auto_signal": "trigger_shoot", "auto_leave": False}
        }
        rules = legacy_rules.migrate_legacy_modes(modes, 0.8, 1.2)
        self.assertEqual(len(rules), 1)
        self.assertIsNone(rules[0].leave)

    def test_auto_leave_true_means_negated_condition(self):
        modes = {"shoot": {"label": "射击", "auto_signal": "trigger_shoot"}}
        rules = legacy_rules.migrate_legacy_modes(modes, 0.8, 1.2)
        self.assertEqual(rules[0].leave, {"type": "not", "child": rules[0].enter})

    def test_skip_when_target_already_has_rule(self):
        existing = [make_rule(rule_id="gta6-driving", target="driving")]
        rules = legacy_rules.migrate_legacy_modes(self.LEGACY_MODES, 0.8, 1.2, existing)
        self.assertEqual(rules, [])

    def test_unknown_legacy_signal_skipped(self):
        modes = {"x": {"label": "X", "auto_signal": "不存在的信号"}}
        self.assertEqual(legacy_rules.migrate_legacy_modes(modes, 0.8, 1.2), [])

    def test_default_mode_never_migrated(self):
        modes = {"default": {"label": "默认", "auto_signal": "rumble"}}
        self.assertEqual(legacy_rules.migrate_legacy_modes(modes, 0.8, 1.2), [])


class RuleEngineEnterTests(unittest.TestCase):
    MODES = {"default", "driving"}

    def test_enters_after_hold(self):
        engine = re_.RuleEngine([make_rule(hold=0.5)])
        facts = FakeFacts(triggers=[trig_key()])
        self.assertIsNone(engine.update(0.0, "default", facts, self.MODES))
        self.assertIsNone(engine.update(0.2, "default", facts, self.MODES))
        decision = engine.update(0.5, "default", facts, self.MODES)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.mode, "driving")
        self.assertFalse(decision.leaving)
        self.assertEqual(engine.armed, "r1")

    def test_hold_restarts_when_condition_drops(self):
        engine = re_.RuleEngine([make_rule(hold=0.5)])
        facts = FakeFacts(triggers=[trig_key()])
        engine.update(0.0, "default", facts, self.MODES)
        facts.set_trigger(trig_key(), False)
        engine.update(0.3, "default", facts, self.MODES)
        facts.set_trigger(trig_key(), True)
        self.assertIsNone(engine.update(0.4, "default", facts, self.MODES))
        self.assertIsNone(engine.update(0.8, "default", facts, self.MODES))
        self.assertIsNotNone(engine.update(0.9, "default", facts, self.MODES))

    def test_no_switch_when_target_mode_missing(self):
        engine = re_.RuleEngine([make_rule()])
        facts = FakeFacts(triggers=[trig_key()])
        self.assertIsNone(engine.update(0.0, "default", facts, {"default"}))
        self.assertIsNone(engine.armed)

    def test_already_in_target_only_arms(self):
        engine = re_.RuleEngine([make_rule()])
        facts = FakeFacts(triggers=[trig_key()])
        self.assertIsNone(engine.update(0.0, "driving", facts, self.MODES))
        self.assertEqual(engine.armed, "r1")

    def test_first_rule_wins(self):
        first = make_rule(
            rule_id="a", target="driving", enter=trigger(kind="resistance", side="any")
        )
        second = make_rule(rule_id="b", target="shoot", enter=trigger(kind="shoot", side="any"))
        engine = re_.RuleEngine([first, second])
        facts = FakeFacts(
            triggers=[
                trig_key(side="any"),
                trig_key(kind="shoot", side="any"),
            ]
        )
        decision = engine.update(0.0, "default", facts, {"default", "driving", "shoot"})
        self.assertEqual(decision.mode, "driving")

    def test_disabled_rule_never_fires(self):
        engine = re_.RuleEngine([make_rule(enabled=False)])
        facts = FakeFacts(triggers=[trig_key()])
        self.assertIsNone(engine.update(0.0, "default", facts, self.MODES))

    def test_broken_rule_is_skipped(self):
        broken = make_rule()
        broken.enter = {"type": "magic"}
        engine = re_.RuleEngine([broken, make_rule(rule_id="ok")])
        facts = FakeFacts(triggers=[trig_key()])
        decision = engine.update(0.0, "default", facts, self.MODES)
        self.assertEqual(decision.rule_id, "ok")


class RuleEngineLeaveTests(unittest.TestCase):
    MODES = {"default", "driving"}

    def _enter(self, engine, facts, now=0.0):
        decision = engine.update(now, "default", facts, self.MODES)
        self.assertIsNotNone(decision)

    def test_leaves_after_delay(self):
        engine = re_.RuleEngine([make_rule(leave=button(), delay=1.0)])
        facts = FakeFacts(triggers=[trig_key()])
        self._enter(engine, facts, 0.0)
        self.assertIsNone(engine.update(0.5, "driving", facts, self.MODES))
        facts.press("TRIANGLE")
        self.assertIsNone(engine.update(1.0, "driving", facts, self.MODES))
        self.assertIsNone(engine.update(1.5, "driving", facts, self.MODES))
        decision = engine.update(2.0, "driving", facts, self.MODES)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.leaving)
        self.assertEqual(decision.mode, "default")
        self.assertIsNone(engine.armed)

    def test_no_exit_without_leave_condition(self):
        """没配退出条件 = 永不自动回默认，但规则仍然算「管着这个模式」。"""
        engine = re_.RuleEngine([make_rule()])
        facts = FakeFacts(triggers=[trig_key()])
        self._enter(engine, facts, 0.0)
        self.assertIsNone(engine.update(1.0, "driving", facts, self.MODES))
        self.assertEqual(engine.armed, "r1")

    def test_already_in_target_is_managed_for_exit(self):
        """切进去之后已经在目标模式里：规则照样接管退出判定。"""
        engine = re_.RuleEngine([make_rule(leave=button(), delay=0.0)])
        facts = FakeFacts(triggers=[trig_key()])
        self.assertIsNone(engine.update(0.0, "driving", facts, self.MODES))
        self.assertEqual(engine.armed, "r1")
        facts.press("TRIANGLE")
        decision = engine.update(1.0, "driving", facts, self.MODES)
        self.assertTrue(decision.leaving)

    def test_exit_delay_keeps_accruing_while_already_in_mode(self):
        """「已经在目标模式里」每 tick 都会重新 arm，不能因此把退出计时清零。"""
        engine = re_.RuleEngine([make_rule(leave=button(), delay=1.0)])
        facts = FakeFacts(triggers=[trig_key()], buttons=["TRIANGLE"])
        self.assertIsNone(engine.update(0.0, "driving", facts, self.MODES))
        self.assertIsNone(engine.update(0.5, "driving", facts, self.MODES))
        decision = engine.update(1.0, "driving", facts, self.MODES)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.leaving)

    def test_rule_removed_while_armed(self):
        engine = re_.RuleEngine([make_rule(leave=button(), delay=0.0)])
        facts = FakeFacts(triggers=[trig_key()])
        self._enter(engine, facts, 0.0)
        engine.set_rules([])
        self.assertIsNone(engine.armed)
        self.assertIsNone(engine.update(1.0, "driving", facts, self.MODES))

    def test_reset_forgets_everything(self):
        engine = re_.RuleEngine([make_rule(leave=button())])
        facts = FakeFacts(triggers=[trig_key()])
        self._enter(engine, facts, 0.0)
        engine.reset()
        self.assertIsNone(engine.armed)

    def test_status_reports_live_flags(self):
        engine = re_.RuleEngine([make_rule(leave=button())])
        facts = FakeFacts(triggers=[trig_key()])
        self._enter(engine, facts, 0.0)
        status = engine.status()[0]
        self.assertTrue(status.active)
        self.assertTrue(status.armed)
        self.assertFalse(status.blocked)


class ManualSwitchTests(unittest.TestCase):
    MODES = {"default", "driving"}

    def test_hot_rule_is_held_off_until_cold(self):
        engine = re_.RuleEngine([make_rule()])
        facts = FakeFacts(triggers=[trig_key()])
        engine.update(0.0, "default", facts, self.MODES)  # 自动切成 driving
        engine.notify_manual_switch(0.1, facts)
        self.assertIsNone(engine.update(0.2, "default", facts, self.MODES))
        self.assertTrue(engine.status()[0].blocked)
        facts.set_trigger(trig_key(), False)
        self.assertIsNone(engine.update(0.3, "default", facts, self.MODES))
        self.assertFalse(engine.status()[0].blocked)
        facts.set_trigger(trig_key(), True)
        decision = engine.update(0.4, "default", facts, self.MODES)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.mode, "driving")


class ButtonTableTests(unittest.TestCase):
    def test_button_names_match_mapping(self):
        """按钮叶子能选的名字必须和映射层支持的一致，否则选了也发不出去。"""
        from ps5kbm import mapping

        self.assertEqual(set(sr.BUTTON_LABELS), set(mapping.VALID_BUTTONS))

    def test_default_button_is_a_valid_one(self):
        self.assertIn(sr.BUTTON_DEFAULT, sr.BUTTON_LABELS)


class Gta6RulesetTests(unittest.TestCase):
    """拿内置规则集里那条真实规则跑一遍上下车，确认行为与手工实现一致。

    这条用例的价值：规则集 JSON 改了（或引擎语义改了、扳机匹配写错了）会立刻红，
    不用上真机才发现。
    """

    MODES = {"default", "driving"}

    def setUp(self) -> None:
        raw = config_module.load_preset("gta6")
        rules = re_.parse_rules(raw.get("rules"))
        self.assertEqual(len(rules), 1, "gta6 预设里应该正好一条自动切换规则")
        self.rule = rules[0]
        self.assertEqual(self.rule.target, "driving")
        self.watcher = mode_signals.SignalWatcher()
        self.engine = re_.RuleEngine(rules)
        self.current = "default"

    def _tick(self, now: float):
        decision = self.engine.update(now, self.current, self.watcher, self.MODES)
        if decision is not None:
            self.current = decision.mode
        return decision

    def _foot(self):
        self.watcher.feed_trigger_effect(mode_signals_block(0x05), mode_signals_block(0x05))

    def _in_car(self):
        unit = mode_signals_block(0x21, 0xFF, 0x03)
        self.watcher.feed_trigger_effect(unit, unit)

    def _run_until_switch(self, start: float, limit: float = 5.0):
        now = start
        while now <= start + limit:
            decision = self._tick(now)
            if decision is not None:
                return decision, now
            now = round(now + 0.1, 3)
        return None, now

    def test_enter_vehicle_switches_to_driving(self):
        self._foot()
        self._tick(0.0)
        self.assertIsNone(self._tick(0.1))
        self._in_car()
        decision, moment = self._run_until_switch(0.2)
        self.assertIsNotNone(decision, "进车后应该自动切驾驶")
        self.assertEqual(decision.mode, "driving")
        self.assertLess(moment, 1.6, "进车去抖 0.8 秒，不该拖太久")

    def test_parked_off_does_not_leave(self):
        """车里静止收到 Off（没按交互键）：不能切回默认。"""
        self._foot()
        self._tick(0.0)
        self._in_car()
        decision, _ = self._run_until_switch(0.1)
        self.assertEqual(decision.mode, "driving")
        self._foot()
        for step in range(30):
            self.assertIsNone(self._tick(round(1.0 + step * 0.1, 3)))
        self.assertEqual(self.current, "driving")

    def test_interact_and_off_returns_to_default(self):
        self._foot()
        self._tick(0.0)
        self._in_car()
        decision, moment = self._run_until_switch(0.1)
        self.assertEqual(decision.mode, "driving")
        self.watcher.note_button("TRIANGLE", moment + 0.1)
        self._foot()
        decision, moment2 = self._run_until_switch(moment + 0.2)
        self.assertIsNotNone(decision, "按键 + Off 之后应该回默认")
        self.assertTrue(decision.leaving)
        self.assertEqual(decision.mode, "default")
        self.assertLess(moment2 - moment, 3.0)

    def test_spamming_interact_never_switches(self):
        """连按交互键（fffff）但不进车：一次都不切。"""
        self._foot()
        for step in range(40):
            now = round(step * 0.1, 3)
            if step % 3 == 0:
                self.watcher.note_button("TRIANGLE", now)
            self.assertIsNone(self._tick(now))
        self.assertEqual(self.current, "default")

    def test_get_in_then_out_immediately(self):
        """刚上车就要下车（两次按键都赶在进车确认之前）：能自己回到默认。"""
        self._foot()
        self.watcher.note_button("TRIANGLE", 0.0)
        self._tick(0.0)
        self.watcher.note_button("TRIANGLE", 0.1)
        self._in_car()
        decision, moment = self._run_until_switch(0.2)
        self.assertEqual(decision.mode, "driving")
        self._foot()
        decision, _ = self._run_until_switch(moment + 0.1)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.mode, "default")


def mode_signals_block(kind: int, *params: int) -> bytes:
    """造一块 11 字节的扳机效果块。"""
    body = list(params)[:10]
    body += [0] * (10 - len(body))
    return bytes([kind] + body)


if __name__ == "__main__":
    unittest.main()
