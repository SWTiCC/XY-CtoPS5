"""DualSense 扳机效果字节生成测试（纯函数，不碰硬件）。"""

from __future__ import annotations

import math
import unittest

from ps5kbm import dualsense as ds


class TriggerEffectTests(unittest.TestCase):
    def test_off(self):
        block = ds.trigger_effect_off()
        self.assertEqual(len(block), 11)
        self.assertEqual(block[0], ds.TRIGGER_MODE_OFF)
        self.assertEqual(block[1:], bytes(10))

    def test_feedback_zones(self):
        block = ds.trigger_effect_feedback(position=6, strength=6)
        self.assertEqual(len(block), 11)
        self.assertEqual(block[0], ds.TRIGGER_MODE_FEEDBACK)
        # 从第 6 档开始到第 9 档都激活
        active = block[1] | (block[2] << 8)
        self.assertEqual(active, 0b1111 << 6)
        # 每档的强度是 strength-1 = 5，3 bit 一档
        force = block[3] | (block[4] << 8) | (block[5] << 16) | (block[6] << 24)
        for zone in range(6, 10):
            self.assertEqual((force >> (3 * zone)) & 0x07, 5)

    def test_feedback_position_clamped(self):
        block = ds.trigger_effect_feedback(position=99, strength=99)
        active = block[1] | (block[2] << 8)
        # position 夹到 9：只剩最后一档
        self.assertEqual(active, 1 << 9)
        force = block[3] | (block[4] << 8) | (block[5] << 16) | (block[6] << 24)
        self.assertEqual((force >> (3 * 9)) & 0x07, 7)  # strength 夹到 8 → 7

    def test_weapon(self):
        block = ds.trigger_effect_weapon(start=2, end=7, strength=6)
        self.assertEqual(block[0], ds.TRIGGER_MODE_WEAPON)
        zones = block[1] | (block[2] << 8)
        self.assertEqual(zones, (1 << 2) | (1 << 7))
        self.assertEqual(block[3], 5)

    def test_weapon_clamped(self):
        block = ds.trigger_effect_weapon(start=0, end=99, strength=99)
        self.assertEqual(block[0], ds.TRIGGER_MODE_WEAPON)
        zones = block[1] | (block[2] << 8)
        # start 夹到 2，end 夹到 8
        self.assertEqual(zones, (1 << 2) | (1 << 8))
        self.assertEqual(block[3], 7)

    def test_vibration(self):
        block = ds.trigger_effect_vibration(position=5, amplitude=6, frequency=30)
        self.assertEqual(block[0], ds.TRIGGER_MODE_VIBRATION)
        self.assertEqual(block[9], 30)
        active = block[1] | (block[2] << 8)
        self.assertEqual(active, 0b11111 << 5)

    def test_bow(self):
        block = ds.trigger_effect_bow(start=2, end=7, strength=5, snap=4)
        self.assertEqual(block[0], ds.TRIGGER_MODE_BOW)
        zones = block[1] | (block[2] << 8)
        self.assertEqual(zones, (1 << 2) | (1 << 7))
        force = block[3] | (block[4] << 8)
        self.assertEqual(force & 0x07, 4)  # strength-1
        self.assertEqual((force >> 3) & 0x07, 3)  # snap-1

    def test_effect_bytes_lookup(self):
        self.assertEqual(ds.effect_bytes("阻力"), ds.trigger_effect_feedback())
        self.assertEqual(ds.effect_bytes("关闭"), ds.trigger_effect_off())
        self.assertEqual(ds.effect_bytes("不认识"), ds.trigger_effect_off())

    def test_all_effects_are_11_bytes(self):
        for name in ds.TRIGGER_EFFECTS:
            self.assertEqual(len(ds.effect_bytes(name)), 11)


    def test_bt_crc_matches_reference(self):
        # 参考值来自 pydualsense 的 checksum.compute（同一份蓝牙报告）
        report = bytes([0x31, 0x02]) + bytes(72)
        self.assertEqual(ds.bt_crc(report), 0xF7E7A126)

    def test_gyro_and_accel_scale(self):
        # 陀螺仪 ±2000°/s 满量程 16 位；加速度 8192 单位 = 1g（实机读数验证过）
        self.assertAlmostEqual(
            ds.GYRO_RAW_TO_RAD, (2000.0 / 32768.0) * (math.pi / 180.0), places=12
        )
        self.assertAlmostEqual(ds.ACCEL_RAW_TO_G, 1.0 / 8192.0, places=12)


if __name__ == "__main__":
    unittest.main()
