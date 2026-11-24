"""陀螺仪 → 右摇杆的纯逻辑测试。"""

from __future__ import annotations

import unittest

from ps5kbm import gyro


class ClampTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(gyro.clamp(2.0), 1.0)
        self.assertEqual(gyro.clamp(-2.0), -1.0)
        self.assertEqual(gyro.clamp(0.3), 0.3)


class DeadzoneTests(unittest.TestCase):
    def test_zero_deadzone_passes_through(self):
        self.assertEqual(gyro.apply_deadzone(0.01, 0.0), 0.01)

    def test_inside_deadzone_is_zero(self):
        self.assertEqual(gyro.apply_deadzone(0.01, 0.02), 0.0)

    def test_outside_deadzone_passes(self):
        self.assertEqual(gyro.apply_deadzone(-0.05, 0.02), -0.05)


class GyroTargetTests(unittest.TestCase):
    def test_yaw_right_gives_positive_x(self):
        # 约定 yaw 向右转为负，取负号后右转 = 摇杆向右
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        x, y = gyro.gyro_stick_target((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), params)
        self.assertGreater(x, 0.0)
        self.assertEqual(y, 0.0)

    def test_pitch_up_gives_negative_y(self):
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        _, y = gyro.gyro_stick_target((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), params)
        self.assertLess(y, 0.0)

    def test_bias_is_subtracted(self):
        params = gyro.GyroParams(deadzone=0.0)
        x, y = gyro.gyro_stick_target((0.5, 0.5, 0.0), (0.5, 0.5, 0.0), params)
        self.assertEqual((x, y), (0.0, 0.0))

    def test_deadzone_silences_small_motion(self):
        params = gyro.GyroParams(deadzone=0.5)
        x, y = gyro.gyro_stick_target((0.2, 0.2, 0.0), (0.0, 0.0, 0.0), params)
        self.assertEqual((x, y), (0.0, 0.0))

    def test_sensitivity_scales_output(self):
        base = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        fast = gyro.GyroParams(deadzone=0.0, smoothing=0.0, sensitivity_x=2.0)
        slow = gyro.GyroParams(deadzone=0.0, smoothing=0.0, sensitivity_x=0.5)
        x_base, _ = gyro.gyro_stick_target((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), base)
        x_fast, _ = gyro.gyro_stick_target((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), fast)
        x_slow, _ = gyro.gyro_stick_target((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), slow)
        self.assertAlmostEqual(x_fast, x_base * 2.0, places=6)
        self.assertAlmostEqual(x_slow, x_base * 0.5, places=6)

    def test_output_is_clamped(self):
        params = gyro.GyroParams(deadzone=0.0, sensitivity_x=3.0)
        x, y = gyro.gyro_stick_target((0.0, 100.0, 0.0), (0.0, 0.0, 0.0), params)
        self.assertEqual((x, y), (-1.0, 0.0))

    def test_invert_switches(self):
        params = gyro.GyroParams(deadzone=0.0, invert_x=True, invert_y=True)
        x, y = gyro.gyro_stick_target((1.0, 1.0, 0.0), (0.0, 0.0, 0.0), params)
        self.assertGreater(x, 0.0)
        self.assertGreater(y, 0.0)

    def test_roll_right_turns_right(self):
        # 实机：向右倾斜时 roll 为负，输出右摇杆向右
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        x, _ = gyro.gyro_stick_target((0.0, 0.0, -1.0), (0, 0, 0), params)
        self.assertGreater(x, 0)

    def test_yaw_and_roll_add_up(self):
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        x_yaw, _ = gyro.gyro_stick_target((0.0, -1.0, 0.0), (0, 0, 0), params)
        x_roll, _ = gyro.gyro_stick_target((0.0, 0.0, -1.0), (0, 0, 0), params)
        x_both, _ = gyro.gyro_stick_target((0.0, -1.0, -1.0), (0, 0, 0), params)
        self.assertAlmostEqual(x_both, x_yaw + x_roll, places=6)


class SmoothingTests(unittest.TestCase):
    def test_zero_smoothing_snaps(self):
        self.assertEqual(gyro.smooth_toward(0.0, 1.0, 0.016, 0.0), 1.0)

    def test_smoothing_moves_partway(self):
        value = gyro.smooth_toward(0.0, 1.0, 0.016, 0.9)
        self.assertGreater(value, 0.0)
        self.assertLess(value, 1.0)

    def test_smoothing_clamped(self):
        self.assertEqual(gyro.smooth_toward(0.0, 1.0, 0.016, 5.0), gyro.smooth_toward(0.0, 1.0, 0.016, 0.95))


class GyroAxisTests(unittest.TestCase):
    def test_inactive_zeroes_output(self):
        axis = gyro.GyroAxis()
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        axis.update((1.0, 1.0, 0.0), (0.0, 0.0, 0.0), params, 0.016, True)
        x, y = axis.update((1.0, 1.0, 0.0), (0.0, 0.0, 0.0), params, 0.016, False)
        self.assertEqual((x, y), (0.0, 0.0))
        self.assertEqual(axis.value, (0.0, 0.0))

    def test_active_reaches_target(self):
        axis = gyro.GyroAxis()
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        x, _ = axis.update((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), params, 0.016, True)
        self.assertGreater(x, 0.0)

    def test_reset(self):
        axis = gyro.GyroAxis()
        params = gyro.GyroParams(deadzone=0.0, smoothing=0.0)
        axis.update((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), params, 0.016, True)
        axis.reset()
        self.assertEqual(axis.value, (0.0, 0.0))


class CalibrationTests(unittest.TestCase):
    def test_empty_samples(self):
        self.assertEqual(gyro.calibrate_bias([]), (0.0, 0.0, 0.0))

    def test_average(self):
        bias = gyro.calibrate_bias([(0.1, 0.2, 0.3), (0.3, 0.4, 0.5)])
        for value, expected in zip(bias, (0.2, 0.3, 0.4)):
            self.assertAlmostEqual(value, expected, places=6)


class ActivationTests(unittest.TestCase):
    def test_always(self):
        self.assertTrue(gyro.activation_pressed("always", set()))

    def test_trigger_threshold(self):
        self.assertFalse(gyro.activation_pressed("l2", {"L2"}, l2=0.1))
        self.assertTrue(gyro.activation_pressed("l2", {"L2"}, l2=0.3))
        self.assertTrue(gyro.activation_pressed("r2", set(), r2=0.5))

    def test_button_press(self):
        self.assertTrue(gyro.activation_pressed("cross", {"CROSS"}))
        self.assertFalse(gyro.activation_pressed("cross", {"SQUARE"}))
        # 大小写不敏感
        self.assertTrue(gyro.activation_pressed("L1", {"l1"}))

    def test_unknown_button_not_pressed(self):
        self.assertFalse(gyro.activation_pressed("mute", set()))


class BiasSpreadTests(unittest.TestCase):
    def test_still_samples_spread_is_tiny(self):
        samples = [(0.001, -0.001, 0.0)] * 50
        self.assertLess(gyro.bias_spread(samples), 1e-6)

    def test_moving_samples_spread_is_big(self):
        samples = [(0.0, 0.0, 0.0), (0.2, 0.0, 0.0)] * 10
        self.assertGreater(gyro.bias_spread(samples), 0.09)

    def test_too_few_samples(self):
        self.assertEqual(gyro.bias_spread([]), 0.0)


class RobustBiasTests(unittest.TestCase):
    def test_outliers_are_trimmed(self):
        samples = [(0.0, 0.0, 0.0)] * 90 + [(0.5, 0.0, 0.0)] * 10
        plain = gyro.calibrate_bias(samples)
        robust = gyro.calibrate_bias_robust(samples)
        self.assertGreater(plain[0], 0.04)
        self.assertAlmostEqual(robust[0], 0.0, places=6)

    def test_empty(self):
        self.assertEqual(gyro.calibrate_bias_robust([]), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
