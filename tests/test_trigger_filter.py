"""扳机过滤器的单元测试（对照参考实现 TriggerFilterTests 的用例）。"""

from __future__ import annotations

import unittest
from collections import deque

from ps5kbm.trigger_filter import TriggerFilter, to_byte


class SnapAndStepTests(unittest.TestCase):
    def test_ends_snap(self):
        f = TriggerFilter()
        left, right = f.apply(3, 252, 0.0)
        self.assertEqual((left, right), (0, 255))

    def test_step_held_then_sent(self):
        f = TriggerFilter()
        f.apply(100, 0, 0.0)
        a = f.apply(102, 0, 0.004)
        b = f.apply(104, 0, 0.008)
        self.assertEqual(a[0], 100)
        self.assertEqual(b[0], 104)

    def test_release_and_first_press_immediate(self):
        f = TriggerFilter()
        f.apply(150, 0, 0.0)
        left, _ = f.apply(0, 0, 0.004)
        self.assertEqual(left, 0)
        left, _ = f.apply(40, 0, 0.008)
        self.assertEqual(left, 40)

    def test_pressing_trigger_is_never_held(self):
        f = TriggerFilter()
        f.apply(0, 0, 0.0)
        f.apply(30, 0, 0.004)
        left, _ = f.apply(90, 0, 0.008)
        self.assertEqual(left, 90)


class EdgeHoldTests(unittest.TestCase):
    def test_noise_held_after_other_release(self):
        f = TriggerFilter()
        f.apply(200, 120, 0.0)
        f.apply(0, 120, 0.004)  # L2 松开
        right = f.apply(0, 125, 0.040)[1]
        self.assertEqual(right, 120, "松开后另一侧的小噪声应被挡住")
        right = f.apply(0, 160, 0.050)[1]
        self.assertEqual(right, 160, "真实行程仍然立即发送")
        right = f.apply(0, 255, 0.060)[1]
        self.assertEqual(right, 255, "满偏在保持期内也立即发送")
        right = f.apply(0, 160, 0.200)[1]
        self.assertEqual(right, 160, "保持期结束后追上真实值")

    def test_reset_starts_released(self):
        f = TriggerFilter()
        f.apply(200, 200, 0.0)
        f.reset()
        left, _ = f.apply(100, 0, 0.004)
        self.assertEqual(left, 100)


class HistoryWindowTests(unittest.TestCase):
    """复现参考实现里的模型：history 只带最新 8 条，松手后丢 40ms 的包。"""

    @staticmethod
    def _console_sees_l2_release(source) -> bool:
        window: deque = deque(maxlen=8)
        console_l2 = 0
        prev = (0, 0)
        for tick in range(150):
            now = tick * 0.004
            l2 = 200 if tick < 50 else 0
            r2 = 180 + (tick % 3) - 1
            out = source(l2, r2, now)
            pushed = False
            if out[0] != prev[0]:
                window.append((0, out[0]))
                pushed = True
            if out[1] != prev[1]:
                window.append((1, out[1]))
                pushed = True
            prev = out
            lost = 50 <= tick < 60
            tail_resend = not pushed and tick in (55, 62, 75, 100)
            if (pushed or tail_resend) and not lost:
                for trigger, value in window:
                    if trigger == 0:
                        console_l2 = value
        return console_l2 == 0

    def test_model_reproduces_stuck_trigger_without_filter(self):
        self.assertFalse(
            self._console_sees_l2_release(lambda l2, r2, _now: (l2, r2))
        )

    def test_filter_makes_release_visible(self):
        f = TriggerFilter()
        self.assertTrue(
            self._console_sees_l2_release(lambda l2, r2, now: f.apply(l2, r2, now))
        )


class ToByteTests(unittest.TestCase):
    def test_clamps(self):
        self.assertEqual(to_byte(0.0), 0)
        self.assertEqual(to_byte(1.0), 255)
        self.assertEqual(to_byte(1.5), 255)
        self.assertEqual(to_byte(-1), 0)
        self.assertEqual(to_byte(0.5), 128)


if __name__ == "__main__":
    unittest.main()
