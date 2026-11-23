"""映射引擎单元测试：不依赖网络与输入设备。"""

from __future__ import annotations

import unittest

from ps5kbm.config import AppConfig, LeftStickConfig, ModeConfig, MouseConfig
from ps5kbm.mapping import InputMapper, parse_action


def make_config(**mouse_overrides) -> AppConfig:
    # 测试基线不启用反死区（anti_deadzone=0），需要时用 overrides 打开
    mouse = MouseConfig(
        sensitivity=1.0, curve=1.0, deadzone=0.0, anti_deadzone=0.0
    )
    for key, value in mouse_overrides.items():
        setattr(mouse, key, value)
    return AppConfig(
        preset="test",
        hotkey="f8",
        mouse=mouse,
        left_stick=LeftStickConfig(value=1.0, ramp=0.0),
        modes={
            "default": ModeConfig(
                label="测试",
                keyboard_sticks={
                    "up": ["w"],
                    "down": ["s"],
                    "left": ["a"],
                    "right": ["d"],
                },
                keyboard_buttons={"space": "CROSS", "e": "RIGHT", "shift": "CROSS"},
                mouse_buttons={"left": "R2", "right": "L2"},
            )
        },
    )


class MouseStickTests(unittest.TestCase):
    def test_speed_maps_to_stick(self):
        mapper = InputMapper(make_config())
        # 10px / 10ms 窗口 = 1000 像素/秒，基准 2500、灵敏度 1.0 → 0.4
        mapper.on_mouse_delta(10, 0)
        result = mapper.tick(0.010)
        self.assertAlmostEqual(result.right[0], 0.4, places=3)
        self.assertAlmostEqual(result.right[1], 0.0, places=3)

    def test_delta_cleared_after_tick(self):
        mapper = InputMapper(make_config())
        mapper.on_mouse_delta(10, 10)
        mapper.tick(0.010)
        # 下一个窗口没有新位移，立即归零
        last = mapper.tick(0.010)
        self.assertEqual(last.right, (0.0, 0.0))

    def test_deadzone(self):
        mapper = InputMapper(make_config(deadzone=0.2))
        mapper.on_mouse_delta(0.4, 0)  # 40 像素/秒 → 0.016，被死区吃掉
        result = mapper.tick(0.010)
        self.assertEqual(result.right[0], 0.0)

    def test_curve_preserves_sign(self):
        mapper = InputMapper(make_config(curve_type="power", curve=2.0))
        mapper.on_mouse_delta(10, 0)  # 0.4 → 0.4^2 = 0.16
        result = mapper.tick(0.010)
        self.assertAlmostEqual(result.right[0], 0.16, places=3)

    def test_anti_deadzone_lifts_small_input(self):
        # 小输入（0.12）应被抬升到反死区阈值以上，避免被游戏死区吃掉
        mapper = InputMapper(make_config(anti_deadzone=0.2))
        mapper.on_mouse_delta(3, 0)  # 300px/s，基准 2500 → 0.12
        result = mapper.tick(0.010)
        self.assertGreaterEqual(abs(result.right[0]), 0.2 - 1e-6)

    def test_flick_stick_triggers_on_fast_horizontal(self):
        cfg = make_config(
            flick_enabled=True, flick_threshold=1000.0, flick_duration=0.033
        )
        mapper = InputMapper(cfg)
        mapper.on_mouse_delta(200, 0)  # 极快水平甩动
        result = mapper.tick(0.010)
        self.assertAlmostEqual(result.right[0], 1.0, places=3)  # 满偏瞬间转身
        mapper.on_mouse_delta(0, 0)
        later = mapper.tick(0.040)
        self.assertEqual(later.right, (0.0, 0.0))

    def test_two_segment_sensitivity(self):
        # 同样的位移速度，灵敏度倍率 3.0 时摇杆值应是 1.0 时的 3 倍
        slow_cfg = make_config(slow_sensitivity=1.0, fast_sensitivity=1.0)
        fast_cfg = make_config(slow_sensitivity=3.0, fast_sensitivity=3.0)
        slow = InputMapper(slow_cfg)
        fast = InputMapper(fast_cfg)
        slow.on_mouse_delta(5, 0)
        fast.on_mouse_delta(5, 0)
        slow_val = slow.tick(0.010).right[0]
        fast_val = fast.tick(0.010).right[0]
        self.assertAlmostEqual(fast_val, slow_val * 3.0, places=2)

    def test_invert_y(self):
        mapper = InputMapper(make_config(invert_y=True))
        mapper.on_mouse_delta(0, 10)  # 1000 像素/秒 → -0.4
        result = mapper.tick(0.010)
        self.assertAlmostEqual(result.right[1], -0.4, places=3)


class LeftStickTests(unittest.TestCase):
    def test_single_direction(self):
        mapper = InputMapper(make_config())
        mapper.on_key("w", True)
        stick_x, stick_y = mapper.tick(0.004).left
        self.assertAlmostEqual(stick_x, 0.0)
        self.assertAlmostEqual(stick_y, -1.0)

    def test_diagonal_is_normalized(self):
        mapper = InputMapper(make_config())
        mapper.on_key("w", True)
        mapper.on_key("d", True)
        left = mapper.tick(0.004).left
        self.assertAlmostEqual(left[0], 0.7071, places=3)
        self.assertAlmostEqual(left[1], -0.7071, places=3)

    def test_left_value_limits_output(self):
        mapper = InputMapper(make_config())
        mapper.on_key("d", True)
        mapper.set_left_value(0.3)
        left = mapper.tick(0.004).left
        self.assertAlmostEqual(left[0], 0.3, places=3)

    def test_left_value_comes_from_config(self):
        config = make_config()
        config.left_stick.value = 0.25
        mapper = InputMapper(config)
        mapper.on_key("d", True)
        left = mapper.tick(0.004).left
        self.assertAlmostEqual(left[0], 0.25, places=3)

    def test_ramp_gradually_reaches_target(self):
        """斜坡：短按只到小幅度，持续按住才推满。"""
        config = make_config()
        config.left_stick.ramp = 4.0
        mapper = InputMapper(config)
        mapper.on_key("d", True)
        first = mapper.tick(0.01).left[0]  # 0.04
        second = mapper.tick(0.05).left[0]  # 0.24
        full = mapper.tick(0.5).left[0]  # 已到 1.0
        self.assertLess(first, second)
        self.assertLess(second, 1.0)
        self.assertAlmostEqual(full, 1.0, places=3)

    def test_ramp_returns_to_zero_on_release(self):
        """松开后按同样的速度回中，不是瞬间归零。"""
        config = make_config()
        config.left_stick.ramp = 4.0
        mapper = InputMapper(config)
        mapper.on_key("d", True)
        mapper.tick(0.5)
        mapper.on_key("d", False)
        mid = mapper.tick(0.05).left[0]
        end = mapper.tick(0.5).left[0]
        self.assertGreater(mid, 0.0)
        self.assertAlmostEqual(end, 0.0, places=3)


class ButtonTests(unittest.TestCase):
    def test_press_then_release(self):
        mapper = InputMapper(make_config())
        mapper.on_key("space", True)
        first = mapper.tick(0.004)
        self.assertIn(("CROSS", "press"), first.events)

        second = mapper.tick(0.004)
        self.assertEqual(second.events, [])

        mapper.on_key("space", False)
        third = mapper.tick(0.004)
        self.assertIn(("CROSS", "release"), third.events)

    def test_duplicate_binding_is_deduplicated(self):
        mapper = InputMapper(make_config())
        mapper.on_key("space", True)
        mapper.on_key("shift", True)
        events = mapper.tick(0.004).events
        self.assertEqual(events, [("CROSS", "press")])

    def test_mouse_button(self):
        mapper = InputMapper(make_config())
        mapper.on_mouse_button("left", True)
        events = mapper.tick(0.004).events
        self.assertEqual(events, [("R2", "press")])

    def test_unknown_button_is_ignored(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["k"] = "NOT_A_REAL_BUTTON"
        mapper = InputMapper(config)
        mapper.on_key("k", True)
        self.assertEqual(mapper.tick(0.004).events, [])

    def test_release_all(self):
        mapper = InputMapper(make_config())
        mapper.on_key("space", True)
        mapper.on_mouse_button("left", True)
        mapper.tick(0.004)
        events = mapper.release_all()
        self.assertIn(("CROSS", "release"), events)
        self.assertIn(("R2", "release"), events)
        self.assertEqual(mapper.tick(0.004).events, [])


class ActionParseTests(unittest.TestCase):
    def test_parse_plain_string(self):
        action = parse_action("cross")
        self.assertEqual(action.kind, "button")
        self.assertEqual(action.buttons, ["CROSS"])

    def test_parse_chord(self):
        action = parse_action({"chord": ["L1", "r1"]})
        self.assertEqual(action.kind, "chord")
        self.assertEqual(action.buttons, ["L1", "R1"])

    def test_parse_sequence(self):
        action = parse_action({"sequence": [["UP", 0.1], ["CROSS"]]})
        self.assertEqual(action.kind, "sequence")
        self.assertEqual(action.steps, [("UP", 0.1), ("CROSS", 0.05)])

    def test_parse_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_action({"unknown": 1})


class ChordTests(unittest.TestCase):
    def test_chord_presses_all_buttons(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["g"] = {"chord": ["L1", "R1"]}
        mapper = InputMapper(config)
        mapper.on_key("g", True)
        events = mapper.tick(0.004).events
        self.assertIn(("L1", "press"), events)
        self.assertIn(("R1", "press"), events)

        mapper.on_key("g", False)
        events = mapper.tick(0.004).events
        self.assertIn(("L1", "release"), events)
        self.assertIn(("R1", "release"), events)

    def test_chord_and_simple_share_button(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["g"] = {"chord": ["L1", "R1"]}
        mapper = InputMapper(config)
        mapper.on_key("g", True)
        mapper.tick(0.004)
        mapper.on_key("g", False)
        mapper.on_key("space", True)  # CROSS
        events = mapper.tick(0.004).events
        self.assertIn(("L1", "release"), events)
        self.assertIn(("CROSS", "press"), events)


class SequenceTests(unittest.TestCase):
    def _mapper(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["h"] = {"sequence": [["UP", 0.05], ["CROSS", 0.05]]}
        return InputMapper(config)

    def test_sequence_runs_all_steps(self):
        mapper = self._mapper()
        mapper.on_key("h", True)
        first = mapper.tick(0.01).events
        self.assertEqual(first, [("UP", "press")])

        second = mapper.tick(0.05).events
        self.assertEqual(second, [("UP", "release")])

        third = mapper.tick(0.01).events
        self.assertEqual(third, [("CROSS", "press")])

        fourth = mapper.tick(0.05).events
        self.assertEqual(fourth, [("CROSS", "release")])

    def test_sequence_interrupted_releases_old_buttons(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["h"] = {"sequence": [["UP", 0.05], ["CROSS", 0.05]]}
        config.modes["default"].keyboard_buttons["j"] = {"sequence": [["DOWN", 0.05]]}
        mapper = InputMapper(config)
        mapper.on_key("h", True)
        mapper.tick(0.01)  # UP 按下
        mapper.on_key("h", False)
        mapper.on_key("j", True)  # 新序列打断旧序列
        events = mapper.tick(0.01).events
        self.assertIn(("UP", "release"), events)
        self.assertIn(("DOWN", "press"), events)

    def test_release_all_clears_sequence(self):
        mapper = self._mapper()
        mapper.on_key("h", True)
        mapper.tick(0.01)
        events = mapper.release_all()
        self.assertIn(("UP", "release"), events)
        self.assertEqual(mapper.tick(0.01).events, [])


class StickActionTests(unittest.TestCase):
    def test_parse_stick_action(self):
        action = parse_action({"stick": 0.8})
        self.assertEqual(action.kind, "stick")
        self.assertAlmostEqual(action.value, 0.8)

    def test_stick_action_changes_left_value(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["k"] = {"stick": 0.2}
        mapper = InputMapper(config)
        mapper.on_key("k", True)
        self.assertAlmostEqual(mapper.left_value, 0.2)

        mapper.on_key("d", True)
        left = mapper.tick(0.004).left
        self.assertAlmostEqual(left[0], 0.2, places=3)

    def test_stick_cycle_toggles(self):
        config = make_config()
        config.modes["default"].keyboard_buttons["k"] = {"stick": [0.5, 1.0]}
        mapper = InputMapper(config)

        def press() -> None:
            mapper.on_key("k", True)
            mapper.on_key("k", False)

        press()
        self.assertAlmostEqual(mapper.left_value, 0.5)
        press()
        self.assertAlmostEqual(mapper.left_value, 1.0)
        press()
        self.assertAlmostEqual(mapper.left_value, 0.5)


if __name__ == "__main__":
    unittest.main()