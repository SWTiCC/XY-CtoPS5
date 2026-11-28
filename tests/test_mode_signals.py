"""信号采集（事实层）：扳机块解析、两侧分类、事件窗口，以及「判定不碰实体手柄」。

这些用例都是纯逻辑（不建 Tk、不碰 HID），时间一律显式传进 `now`，不 sleep。
最后一个类用 `Ps5KbmApp.__new__` 造一个假实例，验证「键鼠玩法下反馈回调照样喂事实，
但一次都不会写到手柄上」。规则的组合与状态机在 test_signal_rules.py。
"""

from __future__ import annotations

import queue
import struct
import unittest
from collections import deque

from ps5kbm import app as app_module
from ps5kbm import config as config_module
from ps5kbm import mode_signals
from ps5kbm import signal_rules as sr


def block(kind: int, *params: int) -> bytes:
    """造一块 11 字节的扳机效果块。"""
    body = list(params)[:10]
    body += [0] * (10 - len(body))
    return bytes([kind] + body)


def driving_block() -> bytes:
    """GTA6 开车时主机下发的那块（两侧都是它）。"""
    return block(0x21, 0xFF, 0x03)


class NormalizeTriggerBlockTests(unittest.TestCase):
    def test_0x05_with_params_becomes_resistance(self):
        """主机开车时发 0x05 + 非零参数，实际是阻力。"""
        normalized = mode_signals.normalize_trigger_block(block(0x05, 0x01, 0x02))
        self.assertEqual(normalized[0], mode_signals.TRIGGER_RESISTANCE)

    def test_pure_off_is_untouched(self):
        original = block(0x05)
        self.assertEqual(mode_signals.normalize_trigger_block(original), original)

    def test_resistance_is_untouched(self):
        original = block(0x21, 0x01)
        self.assertEqual(mode_signals.normalize_trigger_block(original), original)

    def test_shooting_is_untouched(self):
        original = block(0x25, 0x01)
        self.assertEqual(mode_signals.normalize_trigger_block(original), original)

    def test_empty(self):
        self.assertEqual(mode_signals.normalize_trigger_block(b""), b"")


class TriggerKindTests(unittest.TestCase):
    def test_resistance_is_drive(self):
        self.assertEqual(mode_signals.trigger_kind(block(0x21, 0x01)), "drive")

    def test_0x05_with_params_is_drive(self):
        self.assertEqual(mode_signals.trigger_kind(block(0x05, 0x02)), "drive")

    def test_shooting(self):
        self.assertEqual(mode_signals.trigger_kind(block(0x25, 0x01)), "shoot")

    def test_off_is_nothing(self):
        self.assertIsNone(mode_signals.trigger_kind(block(0x05)))

    def test_resistance_without_params_is_nothing(self):
        """0x21 但参数全零 = 没设效果，不能当证据。"""
        self.assertIsNone(mode_signals.trigger_kind(block(0x21)))

    def test_unknown_type_is_nothing(self):
        self.assertIsNone(mode_signals.trigger_kind(block(0x99, 0x01)))

    def test_bad_length_is_nothing(self):
        self.assertIsNone(mode_signals.trigger_kind(b"\x21"))


class ClassifyTriggerPairTests(unittest.TestCase):
    """一对扳机块 → 步行 / 开车 / 其它。"""

    def test_both_off_is_foot(self):
        self.assertEqual(
            mode_signals.classify_trigger_pair(block(0x05), block(0x05)),
            mode_signals.TRIGGER_PAIR_FOOT,
        )

    def test_driving_prefix_pair(self):
        self.assertEqual(
            mode_signals.classify_trigger_pair(driving_block(), driving_block()),
            mode_signals.TRIGGER_PAIR_DRIVING,
        )

    def test_0x05_with_driving_params_is_driving(self):
        """主机把阻力发成 0x05 + 非零参数：改写后同样是开车特征。"""
        unit = block(0x05, 0xFF, 0x03)
        self.assertEqual(
            mode_signals.classify_trigger_pair(unit, unit),
            mode_signals.TRIGGER_PAIR_DRIVING,
        )

    def test_one_side_is_other(self):
        self.assertEqual(
            mode_signals.classify_trigger_pair(driving_block(), block(0x05)),
            mode_signals.TRIGGER_PAIR_OTHER,
        )

    def test_other_resistance_is_other(self):
        unit = block(0x21, 0x01, 0x02)
        self.assertEqual(
            mode_signals.classify_trigger_pair(unit, unit),
            mode_signals.TRIGGER_PAIR_OTHER,
        )

    def test_bad_length_is_other(self):
        self.assertEqual(
            mode_signals.classify_trigger_pair(b"\x21", b"\x21"),
            mode_signals.TRIGGER_PAIR_OTHER,
        )


class PcmRmsTests(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(mode_signals.pcm_rms(b""), 0.0)

    def test_silence_is_zero(self):
        self.assertEqual(mode_signals.pcm_rms(b"\x00" * 1024), 0.0)

    def test_full_scale_is_one(self):
        pcm = struct.pack("<512h", *([32767] * 512))
        self.assertAlmostEqual(mode_signals.pcm_rms(pcm), 1.0, places=3)

    def test_half_scale_is_half(self):
        pcm = struct.pack("<512h", *([16384] * 512))
        self.assertAlmostEqual(mode_signals.pcm_rms(pcm), 0.5, places=3)

    def test_odd_length_uses_whole_samples(self):
        pcm = struct.pack("<4h", 32767, 32767, 32767, 32767) + b"\x00"
        self.assertAlmostEqual(mode_signals.pcm_rms(pcm), 1.0, places=3)


class TriggerMatchTests(unittest.TestCase):
    """扳机是「最后一次上报的状态」：按类型 + 参数前缀 + 作用侧匹配，不随时间过期。"""

    def setUp(self) -> None:
        self.watcher = mode_signals.SignalWatcher()

    def _feed(self, left, right):
        self.watcher.feed_trigger_effect(left, right)

    def _match(self, kind, prefix="", side="both", code=None, now=None):
        return self.watcher.trigger_match(kind, code, prefix, side, now)

    def test_nothing_reported_matches_nothing(self):
        self.assertFalse(self._match("resistance"))
        self.assertFalse(self._match("off"))
        self.assertFalse(self._match("resistance", side="any"))

    def test_foot_state(self):
        self._feed(block(0x05), block(0x05))
        self.assertTrue(self._match("off"))
        self.assertFalse(self._match("resistance"))
        self.assertFalse(self._match("resistance", side="any"))

    def test_vehicle_state_persists_forever(self):
        """主机只在变化时下发：进车后很久没有新包，状态也必须保持。"""
        self._feed(driving_block(), driving_block())
        self.assertTrue(self._match("resistance", "ff03", "both", now=0.0))
        self.assertTrue(self._match("resistance", "ff03", "both", now=10_000.0))

    def test_prefix_must_match(self):
        """GTA6 开车特征是「阻力 + 参数 FF 03」，别的阻力参数不算。"""
        self._feed(block(0x21, 0x01, 0x02), block(0x21, 0x01, 0x02))
        self.assertTrue(self._match("resistance"))
        self.assertFalse(self._match("resistance", "ff03"))

    def test_single_side_resistance(self):
        self._feed(block(0x21, 0x01), block(0x05))
        self.assertTrue(self._match("resistance", side="any"))
        self.assertTrue(self._match("resistance", side="left"))
        self.assertFalse(self._match("resistance", side="right"))
        self.assertFalse(self._match("resistance", side="both"))
        self.assertFalse(self._match("off"))

    def test_both_sides_resistance(self):
        self._feed(block(0x21, 0x01), block(0x21, 0x02))
        self.assertTrue(self._match("resistance", side="both"))

    def test_0x05_with_params_counts_as_resistance(self):
        """主机把阻力发成 0x05 + 非零参数：改写后照样是阻力。"""
        self._feed(block(0x05, 0xFF, 0x03), block(0x05, 0xFF, 0x03))
        self.assertTrue(self._match("resistance", "ff03"))
        self.assertFalse(self._match("off"))

    def test_shooting(self):
        self._feed(block(0x25, 0x01), block(0x05))
        self.assertTrue(self._match("shoot", side="any"))
        self.assertFalse(self._match("shoot", side="both"))

    def test_custom_code(self):
        self._feed(block(0x21, 0x01), block(0x05))
        self.assertTrue(self._match("custom", side="left", code=0x21))
        self.assertFalse(self._match("custom", side="left", code=0x25))

    def test_resistance_without_params_is_not_an_effect(self):
        """0x21 但参数全零 = 没设效果，不能当阻力。"""
        self._feed(block(0x21), block(0x21))
        self.assertFalse(self._match("resistance"))

    def test_pair_property_tracks_classification(self):
        self.assertEqual(self.watcher.pair, mode_signals.TRIGGER_PAIR_OTHER)
        self._feed(block(0x05), block(0x05))
        self.assertEqual(self.watcher.pair, mode_signals.TRIGGER_PAIR_FOOT)
        self._feed(driving_block(), driving_block())
        self.assertEqual(self.watcher.pair, mode_signals.TRIGGER_PAIR_DRIVING)

    def test_unknown_fact_is_false(self):
        self.assertFalse(self.watcher.is_true("不存在的事实"))


class EventFactTests(unittest.TestCase):
    """震动 / 触觉 / 交互键是事件，按时间窗口过期。"""

    def setUp(self) -> None:
        self.watcher = mode_signals.SignalWatcher(evidence_s=0.4, button_pulse_s=3.0)

    def test_rumble_window(self):
        self.watcher.feed_rumble(0.6, 0.2, now=1.0)
        self.assertTrue(self.watcher.is_true(sr.FACT_RUMBLE, 1.2))
        self.assertFalse(self.watcher.is_true(sr.FACT_RUMBLE, 1.5))

    def test_quiet_rumble_is_not_evidence(self):
        self.watcher.feed_rumble(0.05, 0.05, now=1.0)
        self.assertFalse(self.watcher.is_true(sr.FACT_RUMBLE, 1.0))

    def test_haptics_window(self):
        pcm = struct.pack("<512h", *([20000] * 512))
        self.watcher.feed_haptics_pcm(pcm, now=1.0)
        self.assertTrue(self.watcher.is_true(sr.FACT_HAPTICS, 1.2))
        self.assertFalse(self.watcher.is_true(sr.FACT_HAPTICS, 1.5))

    def test_quiet_haptics_is_not_evidence(self):
        self.watcher.feed_haptics_pcm(b"\x00" * 2048, now=1.0)
        self.assertFalse(self.watcher.is_true(sr.FACT_HAPTICS, 1.0))

    def test_button_pulse(self):
        self.assertFalse(self.watcher.button_active("TRIANGLE", 0.0))
        self.watcher.note_button("TRIANGLE", now=1.0)
        self.assertTrue(self.watcher.button_active("TRIANGLE", 1.0))
        self.assertTrue(self.watcher.button_active("TRIANGLE", 3.9))
        self.assertFalse(self.watcher.button_active("TRIANGLE", 4.1))
        # 别的按钮不受影响
        self.assertFalse(self.watcher.button_active("CROSS", 1.0))


class WatcherResetTests(unittest.TestCase):
    def test_reset_forgets_everything(self):
        watcher = mode_signals.SignalWatcher()
        watcher.feed_trigger_effect(driving_block(), driving_block())
        watcher.feed_rumble(0.9, 0.9, now=1.0)
        watcher.note_button("TRIANGLE", now=1.0)
        watcher.reset()
        self.assertEqual(watcher.pair, mode_signals.TRIGGER_PAIR_OTHER)
        self.assertFalse(watcher.trigger_match("resistance", None, "ff03", "both", 1.0))
        self.assertFalse(watcher.is_true(sr.FACT_RUMBLE, 1.0))
        self.assertFalse(watcher.button_active("TRIANGLE", 1.0))

    def test_snapshot_has_all_facts(self):
        watcher = mode_signals.SignalWatcher()
        snapshot = watcher.snapshot(0.0)
        self.assertEqual(set(snapshot), {label for label, _node in sr.sample_conditions()})


class _FakeController:
    """只记「有没有被写过」，用来证明事实采集不会碰实体手柄。"""

    def __init__(self) -> None:
        self.connected = False
        self.transport = "usb"
        self.calls: list[tuple] = []

    def rumble(self, low, high) -> None:
        self.calls.append(("rumble", low, high))

    def set_trigger_effects(self, left=None, right=None) -> None:
        self.calls.append(("trigger", left, right))

    def set_lightbar(self, rgb) -> None:
        self.calls.append(("led", rgb))


def _stub_app() -> app_module.Ps5KbmApp:
    """造一个只有反馈回调所需属性的实例（键鼠玩法 + 手柄未连接）。"""
    app = app_module.Ps5KbmApp.__new__(app_module.Ps5KbmApp)
    cfg = config_module.AppConfig()
    cfg.controller.mode = "keyboard"
    app._config = cfg
    app._signals = mode_signals.SignalWatcher()
    app._ui_queue = queue.Queue()
    app._trigger_trace = deque(maxlen=8)
    app._controller = _FakeController()
    app._last_trigger_blocks = {}
    app._trigger_mode_counts = {}
    app._trigger_stats_at = 0.0
    app._last_console_rumble = 0.0
    app._haptics_rx = 0
    app._haptics_tx = 0
    app._haptics_peak = 0
    app._haptics_last_size = 0
    app._haptics_stats_at = 0.0
    app._haptics_underruns_prev = 0
    app._usb_haptics = None
    app._haptics_pad_count = 0
    app._last_lightbar = b""
    return app


class FeedbackFeedTests(unittest.TestCase):
    """键鼠玩法下三个回调照样喂事实，但一次都不写实体手柄。"""

    def test_trigger_effect_feeds_facts_only(self):
        app = _stub_app()
        app._on_console_trigger_effect(block(0x21, 0x01), block(0x05))
        self.assertTrue(app._signals.trigger_match("resistance", None, "", "any"))
        self.assertEqual(app._controller.calls, [])

    def test_rumble_feeds_facts_only(self):
        app = _stub_app()
        app._on_console_rumble(0.6, 0.2)
        self.assertTrue(app._signals.is_true(sr.FACT_RUMBLE))
        self.assertEqual(app._controller.calls, [])

    def test_haptics_feeds_facts_only(self):
        app = _stub_app()
        app._on_haptics_pcm(struct.pack("<512h", *([20000] * 512)))
        self.assertTrue(app._signals.is_true(sr.FACT_HAPTICS))
        self.assertEqual(app._controller.calls, [])

    def test_button_press_feeds_fact(self):
        app = _stub_app()
        app._signals.note_button("TRIANGLE")
        self.assertTrue(app._signals.button_active("TRIANGLE"))

    def test_key_event_does_not_feed_buttons(self):
        """键盘事件只刷界面；按钮事实由映射层翻译后的 press 事件提供。"""
        app = _stub_app()
        app._on_key_event("f")
        self.assertFalse(app._signals.button_active("TRIANGLE"))

    def test_trigger_trace_keeps_raw_blocks(self):
        app = _stub_app()
        app._on_console_trigger_effect(block(0x05), block(0x05))
        app._on_console_trigger_effect(driving_block(), driving_block())
        self.assertEqual(len(app._trigger_trace), 2)
        self.assertEqual(app._trigger_trace[-1][1], driving_block())


if __name__ == "__main__":
    unittest.main()
