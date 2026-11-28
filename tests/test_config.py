"""配置层单元测试：扳机调参键、预设名校验与预设文件生命周期。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from ps5kbm import config, rule_engine, signal_rules

# 不写系统临时目录（部分环境对 %TEMP% 有限制），用仓库内固定目录并在结束后清理
TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")


def make_temp_dir() -> str:
    os.makedirs(TMP_ROOT, exist_ok=True)
    return tempfile.mkdtemp(dir=TMP_ROOT)


def write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


class TriggerKeyTests(unittest.TestCase):
    def test_defaults_when_missing(self):
        cfg = config.build_config({})
        self.assertEqual(
            config.trigger_adjust_keys(cfg),
            {
                "r2_up": "wheel_up",
                "r2_down": "wheel_down",
                "l2_up": "=",
                "l2_down": "-",
            },
        )

    def test_custom_values_and_roundtrip(self):
        cfg = config.build_config(
            {"r2_up": "mouse_x1", "r2_down": "mouse_x2", "l2_up": "]", "l2_down": "["}
        )
        self.assertEqual(config.trigger_adjust_keys(cfg)["r2_up"], "mouse_x1")
        data = config.config_to_dict(cfg)
        self.assertEqual(data["l2_up"], "]")
        self.assertEqual(data["l2_down"], "[")

    def test_blank_value_falls_back(self):
        cfg = config.build_config({"r2_up": "   "})
        self.assertEqual(cfg.r2_up, "wheel_up")


class EmptyPresetTests(unittest.TestCase):
    def test_new_empty_config_has_one_default_mode(self):
        cfg = config.new_empty_config("新预设")
        self.assertEqual(list(cfg.modes), ["default"])
        mode = cfg.modes["default"]
        self.assertEqual(mode.label, "默认")
        self.assertEqual(mode.keyboard_buttons, {})
        self.assertEqual(mode.mouse_buttons, {})
        self.assertEqual(mode.keyboard_sticks, {})

    def test_empty_preset_roundtrip_is_still_empty(self):
        cfg = config.new_empty_config("新预设")
        raw = config.preset_to_dict("新预设", cfg)
        rebuilt = config.build_config(raw)
        mode = rebuilt.modes["default"]
        self.assertEqual(mode.keyboard_buttons, {})
        self.assertEqual(mode.mouse_buttons, {})
        self.assertEqual(mode.keyboard_sticks, {})


class PresetNameTests(unittest.TestCase):
    def test_valid_name(self):
        self.assertEqual(config.check_preset_name("  其他游戏  "), "其他游戏")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            config.check_preset_name("   ")

    def test_path_chars_rejected(self):
        for name in ("a/b", "a\\b", "a:b", "a?b"):
            with self.assertRaises(ValueError):
                config.check_preset_name(name)

    def test_too_long_rejected(self):
        with self.assertRaises(ValueError):
            config.check_preset_name("x" * 41)


class UserPresetFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = make_temp_dir()
        self.preset_dir = os.path.join(self.temp, "presets")
        os.makedirs(self.preset_dir)
        self.patch = mock.patch.object(config, "USER_PRESETS_DIR", self.preset_dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_save_detect_and_delete(self):
        cfg = config.build_config({})
        path = config.save_preset("另一款游戏", cfg)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(config.is_user_preset("另一款游戏"))
        self.assertIn("另一款游戏", config.list_presets())
        config.delete_preset("另一款游戏")
        self.assertFalse(config.is_user_preset("另一款游戏"))
        self.assertNotIn("另一款游戏", config.list_presets())

    def test_delete_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            config.delete_preset("不存在")

    def test_builtin_preset_is_not_user_preset(self):
        self.assertFalse(config.is_user_preset("gta6"))


class MissingPresetFallbackTests(unittest.TestCase):
    def test_load_config_survives_deleted_preset(self):
        temp = make_temp_dir()
        try:
            path = os.path.join(temp, "config.json")
            write_json(path, {"preset": "已经删掉的预设", "hotkey": "f9"})
            cfg = config.load_config(path)
            self.assertEqual(cfg.hotkey, "f9")
            self.assertEqual(cfg.preset, "已经删掉的预设")
        finally:
            shutil.rmtree(temp, ignore_errors=True)


class KeyConflictTests(unittest.TestCase):
    """按键占用判定：映射 / 调参键 / 切换键共用同一份规则。"""

    def test_hotkey(self):
        self.assertEqual(config.key_conflict("f8", hotkey="f8"), "捕获热键")

    def test_mode_switch(self):
        self.assertEqual(config.key_conflict("f9", mode_switch="f9"), "模式切换键")

    def test_trigger_key_mentions_action(self):
        reason = config.key_conflict("wheel_up", trigger_keys={"r2_up": "wheel_up"})
        self.assertIn("R2 加深", reason)

    def test_stick_direction(self):
        self.assertEqual(config.key_conflict("w", stick_keys=["w"]), "左摇杆方向键")

    def test_mapping_source(self):
        self.assertEqual(
            config.key_conflict("space", mapping_sources=["space"]), "已映射的按键"
        )

    def test_ignore_same_trigger(self):
        keys = {"r2_up": "=", "l2_up": "-"}
        self.assertEqual(
            config.key_conflict("=", trigger_keys=keys, ignore_trigger="r2_up"), ""
        )

    def test_ignore_same_mode_switch(self):
        self.assertEqual(
            config.key_conflict("f9", mode_switch="f9", ignore_mode_switch="f9"), ""
        )

    def test_free_key(self):
        self.assertEqual(
            config.key_conflict("j", hotkey="f8", mapping_sources=["k"]), ""
        )

    def test_blank_name(self):
        self.assertEqual(config.key_conflict("   ", hotkey="f8"), "")

    def test_case_insensitive(self):
        self.assertEqual(config.key_conflict("F8", hotkey="f8"), "捕获热键")


class EmptyPresetBaseTests(unittest.TestCase):
    """新建空预设：映射为空，但全局设置沿用当前配置。"""

    def test_inherits_non_mapping_settings(self):
        base = config.build_config(
            {
                "hotkey": "f10",
                "mode_switch": "mouse_x2",
                "target_window": "某游戏窗口",
                "r2_depth": 0.6,
                "l2_depth": 0.3,
                "r2_up": "wheel_up",
            }
        )
        cfg = config.new_empty_config("新预设", base)
        self.assertEqual(cfg.hotkey, "f10")
        self.assertEqual(cfg.mode_switch, "mouse_x2")
        self.assertEqual(cfg.target_window, "某游戏窗口")
        self.assertEqual(cfg.r2_up, "wheel_up")
        self.assertAlmostEqual(cfg.r2_depth, 0.6)
        self.assertAlmostEqual(cfg.l2_depth, 0.3)
        self.assertEqual(cfg.modes["default"].keyboard_buttons, {})
        self.assertEqual(cfg.modes["default"].mouse_buttons, {})

    def test_without_base_keeps_defaults(self):
        cfg = config.new_empty_config("新预设")
        self.assertEqual(cfg.mode_switch, "f9")
        self.assertEqual(cfg.hotkey, "f8")
        self.assertAlmostEqual(cfg.r2_depth, 1.0)


class RobustnessTests(unittest.TestCase):
    """写盘原子性 + 坏文件兜底：坏掉的配置不能让程序打不开。"""

    def setUp(self):
        self.temp = make_temp_dir()
        self.presets = os.path.join(self.temp, "presets")
        os.makedirs(self.presets)
        write_json(
            os.path.join(self.presets, "gta6.json"),
            {"hotkey": "f9", "keyboard_buttons": {"j": "CROSS"}},
        )
        self.patches = [
            mock.patch.object(config, "USER_PRESETS_DIR", self.presets),
            mock.patch.object(config, "PRESETS_DIR", os.path.join(self.temp, "builtin")),
            mock.patch.object(config, "load_tuning", lambda path=None: {}),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_save_config_is_atomic_and_readable(self):
        path = os.path.join(self.temp, "config.json")
        config.save_config(config.build_config({"hotkey": "f10"}), path)
        self.assertFalse(os.path.exists(path + ".tmp"))
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["hotkey"], "f10")

    def test_broken_config_is_backed_up_and_preset_used(self):
        path = os.path.join(self.temp, "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ 这不是 json")
        cfg = config.load_config(path)
        self.assertTrue(os.path.exists(path + ".broken"))
        self.assertEqual(cfg.hotkey, "f9")
        self.assertEqual(cfg.modes["default"].keyboard_buttons, {"j": "CROSS"})

    def test_broken_preset_does_not_block_startup(self):
        path = os.path.join(self.temp, "config.json")
        write_json(path, {"preset": "坏的", "hotkey": "f10"})
        with open(os.path.join(self.presets, "坏的.json"), "w", encoding="utf-8") as handle:
            handle.write("{ 坏掉了")
        cfg = config.load_config(path)
        self.assertEqual(cfg.hotkey, "f10")
        self.assertEqual(cfg.preset, "坏的")

    def test_trigger_depth_persists_through_tuning(self):
        cfg = config.build_config({"r2_depth": 0.4, "l2_depth": 0.25})
        tuning_path = os.path.join(self.temp, "tuning.json")
        config.save_tuning(cfg, tuning_path)
        with mock.patch.object(
            config, "load_tuning", lambda path=None: config._read_json(tuning_path)
        ):
            loaded = config.load_config(os.path.join(self.temp, "missing.json"))
        self.assertAlmostEqual(loaded.r2_depth, 0.4)
        self.assertAlmostEqual(loaded.l2_depth, 0.25)


class ControllerConfigTests(unittest.TestCase):
    """手柄页配置：默认值、读写往返、非法值回落。"""

    def test_defaults(self):
        cfg = config.build_config({})
        self.assertEqual(cfg.controller.mode, "keyboard")
        self.assertTrue(cfg.controller.gyro.enabled)
        self.assertEqual(cfg.controller.gyro.activation, "l2")
        self.assertTrue(cfg.controller.rumble_enabled)
        self.assertTrue(cfg.controller.adaptive_triggers)
        self.assertEqual(list(cfg.controller.gyro.bias), [0.0, 0.0, 0.0])

    def test_roundtrip(self):
        raw = {
            "controller": {
                "mode": "controller",
                "gyro": {
                    "enabled": False,
                    "activation": "l1",
                    "sensitivity_x": 1.5,
                    "sensitivity_y": 0.7,
                    "deadzone": 0.03,
                    "smoothing": 0.4,
                    "invert_x": True,
                    "invert_y": True,
                    "bias": [0.01, -0.02, 0.03],
                },
                "rumble_enabled": False,
                "rumble_gain": 1.5,
                "adaptive_triggers": True,
            }
        }
        cfg = config.build_config(raw)
        self.assertEqual(cfg.controller.mode, "controller")
        self.assertFalse(cfg.controller.gyro.enabled)
        self.assertEqual(cfg.controller.gyro.activation, "l1")
        self.assertAlmostEqual(cfg.controller.gyro.sensitivity_x, 1.5)
        self.assertAlmostEqual(cfg.controller.gyro.bias[1], -0.02)
        self.assertAlmostEqual(cfg.controller.rumble_gain, 1.5)
        self.assertTrue(cfg.controller.adaptive_triggers)

        rebuilt = config.build_config(config.config_to_dict(cfg))
        self.assertEqual(rebuilt.controller.mode, "controller")
        self.assertEqual(rebuilt.controller.gyro.activation, "l1")
        self.assertAlmostEqual(rebuilt.controller.gyro.deadzone, 0.03)
        self.assertAlmostEqual(rebuilt.controller.gyro.bias[2], 0.03)
        self.assertTrue(rebuilt.controller.gyro.invert_x)

    def test_invalid_values_fall_back(self):
        cfg = config.build_config(
            {
                "controller": {
                    "mode": "手柄",
                    "gyro": {
                        "activation": "没有这个键",
                        "sensitivity_x": 99,
                        "sensitivity_y": -5,
                        "deadzone": 9,
                        "smoothing": -1,
                        "bias": "坏数据",
                    },
                    "rumble_gain": 9,
                }
            }
        )
        self.assertEqual(cfg.controller.mode, "keyboard")
        self.assertEqual(cfg.controller.gyro.activation, "l2")
        self.assertAlmostEqual(cfg.controller.gyro.sensitivity_x, 3.0)
        self.assertAlmostEqual(cfg.controller.gyro.sensitivity_y, 0.1)
        self.assertAlmostEqual(cfg.controller.gyro.deadzone, 0.1)
        self.assertAlmostEqual(cfg.controller.gyro.smoothing, 0.0)
        self.assertEqual(list(cfg.controller.gyro.bias), [0.0, 0.0, 0.0])
        self.assertAlmostEqual(cfg.controller.rumble_gain, 2.0)

    def test_custom_activation_button_is_kept(self):
        for name in ("r2", "r1", "cross", "touchpad", "always"):
            cfg = config.build_config(
                {"controller": {"gyro": {"activation": name}}}
            )
            self.assertEqual(cfg.controller.gyro.activation, name)


class RulesConfigTests(unittest.TestCase):
    """规则表：读写往返、旧配置迁移、默认模式不被当目标、非法值回落。"""

    def test_defaults(self):
        cfg = config.build_config({})
        self.assertEqual(cfg.rules, [])
        self.assertAlmostEqual(cfg.auto_hold, rule_engine.DEFAULT_ENTER_HOLD_S)
        self.assertAlmostEqual(cfg.auto_release, rule_engine.DEFAULT_LEAVE_DELAY_S)

    def test_roundtrip(self):
        cfg = config.build_config(
            {
                "auto_hold": 1.5,
                "auto_release": 2.5,
                "auto_switch": False,
                "rules": [
                    {
                        "id": "drive",
                        "label": "开车",
                        "target": "驾驶",
                        "enter": {"type": "trigger", "kind": "resistance", "prefix": "", "side": "any"},
                    }
                ],
                "modes": {"驾驶": {"label": "驾驶"}},
            }
        )
        self.assertAlmostEqual(cfg.auto_hold, 1.5)
        self.assertAlmostEqual(cfg.auto_release, 2.5)
        self.assertFalse(cfg.auto_switch)
        self.assertEqual(len(cfg.rules), 1)
        self.assertEqual(cfg.rules[0].id, "drive")
        # 规则没写去抖就继承预设级默认值
        self.assertAlmostEqual(cfg.rules[0].enter_hold, 1.5)
        self.assertAlmostEqual(cfg.rules[0].leave_delay, 2.5)

        data = config.config_to_dict(cfg)
        self.assertFalse(data["auto_switch"])
        self.assertEqual(len(data["rules"]), 1)
        rebuilt = config.build_config(data)
        self.assertEqual(rebuilt.rules[0].enter, cfg.rules[0].enter)
        self.assertFalse(rebuilt.auto_switch)

    def test_legacy_mode_signal_migrates_to_rule(self):
        """旧配置（模式上直接写 auto_signal）自动变成等价规则。"""
        cfg = config.build_config(
            {
                "modes": {
                    "驾驶": {
                        "label": "驾驶",
                        "auto_signal": "vehicle_entry",
                        "auto_leave": True,
                    }
                }
            }
        )
        self.assertEqual(len(cfg.rules), 1)
        rule = cfg.rules[0]
        self.assertEqual(rule.target, "驾驶")
        self.assertEqual(rule.enter["type"], "latch")
        self.assertIsNotNone(rule.leave)
        # 迁移出来的规则必须能编译，不然等于没迁移
        signal_rules.parse_condition(rule.enter)
        signal_rules.parse_condition(rule.leave)

    def test_legacy_skipped_when_rule_already_targets_mode(self):
        """预设已带规则时不重复迁移（否则同一模式两条规则抢着切）。"""
        cfg = config.build_config(
            {
                "rules": [
                    {
                        "id": "gta6-driving",
                        "target": "driving",
                        "enter": {"type": "fact", "fact": "trigger.vehicle"},
                    }
                ],
                "modes": {
                    "driving": {
                        "label": "驾驶",
                        "auto_signal": "vehicle_entry",
                    }
                },
            }
        )
        self.assertEqual([rule.id for rule in cfg.rules], ["gta6-driving"])

    def test_unknown_legacy_signal_is_ignored(self):
        cfg = config.build_config(
            {"modes": {"驾驶": {"label": "驾驶", "auto_signal": "不存在的信号"}}}
        )
        self.assertEqual(cfg.rules, [])

    def test_default_mode_is_never_a_rule_target(self):
        """默认模式是回退目标：规则指向它会被丢掉，否则进退会互相打架。"""
        cfg = config.build_config(
            {
                "rules": [
                    {
                        "id": "bad",
                        "target": "default",
                        "enter": {"type": "fact", "fact": "rumble"},
                    }
                ],
                "modes": {"default": {"label": "默认", "auto_signal": "rumble"}},
            }
        )
        self.assertEqual(cfg.rules, [])

    def test_broken_rule_is_dropped(self):
        cfg = config.build_config(
            {
                "rules": [
                    {"id": "no-target", "enter": {"type": "fact", "fact": "rumble"}},
                    {
                        "id": "bad-fact",
                        "target": "驾驶",
                        "enter": {"type": "fact", "fact": "不存在的事实"},
                    },
                    {
                        "id": "ok",
                        "target": "驾驶",
                        "enter": {"type": "fact", "fact": "rumble"},
                    },
                ],
                "modes": {"驾驶": {"label": "驾驶"}},
            }
        )
        self.assertEqual([rule.id for rule in cfg.rules], ["ok"])

    def test_invalid_delay_falls_back(self):
        cfg = config.build_config({"auto_hold": "坏数据", "auto_release": 99})
        self.assertAlmostEqual(cfg.auto_hold, rule_engine.DEFAULT_ENTER_HOLD_S)
        self.assertAlmostEqual(cfg.auto_release, 10.0)



class PresetRulesTests(unittest.TestCase):
    """自动切换规则跟按键预设绑在一起（一个游戏一套）。"""

    def test_builtin_preset_carries_gta6_rule(self):
        raw = config.load_preset("gta6")
        self.assertTrue(raw.get("auto_switch"))
        rules = config.build_config({**raw, "preset": "gta6"}).rules
        self.assertEqual([rule.target for rule in rules], ["driving"])
        # 规则已经参数化：不再是写死的游戏特征
        self.assertEqual(rules[0].enter["set"]["type"], "trigger")
        self.assertEqual(rules[0].enter["set"]["prefix"], "ff03")

    def test_auto_switch_can_be_disabled(self):
        cfg = config.build_config({"auto_switch": False, "rules": []})
        self.assertFalse(cfg.auto_switch)
        self.assertFalse(config.config_to_dict(cfg)["auto_switch"])

    def test_legacy_ruleset_file_migrates_into_preset(self):
        """上一版把规则存在 rulesets/<预设名>.json：加载时搬进配置（一次性）。"""
        cases = [
            {
                "id": "old",
                "target": "驾驶",
                "enter": {"type": "trigger", "kind": "resistance", "prefix": "", "side": "any"},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "rulesets"), exist_ok=True)
            with open(
                os.path.join(tmp, "rulesets", "legacy.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"rules": cases}, handle)
            with mock.patch.object(config, "PROJECT_ROOT", tmp):
                cfg = config.build_config({"preset": "legacy", "modes": {"驾驶": {}}})
                self.assertEqual(cfg.rules, [])
                config._migrate_legacy_ruleset(cfg)
                self.assertEqual([rule.id for rule in cfg.rules], ["old"])
                # 预设里已经有规则时不再读老文件
                cfg.rules = [rule for rule in cfg.rules]
                config._migrate_legacy_ruleset(cfg)
                self.assertEqual([rule.id for rule in cfg.rules], ["old"])


if __name__ == "__main__":
    unittest.main()
