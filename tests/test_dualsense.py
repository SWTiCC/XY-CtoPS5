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


class AudioUnlockTests(unittest.TestCase):
    """打开音频/触觉通路的报告内容（纯字节，不碰硬件）。"""

    def _capture(self, transport: str) -> bytes:
        reader = ds.DualSenseReader()
        reader._transport = transport  # noqa: SLF001 - 测试内部状态
        captured = {}

        def fake_write(report):
            captured["report"] = bytes(report)
            return True

        reader._write = fake_write  # noqa: SLF001
        self.assertTrue(reader.unlock_audio())
        return captured["report"]

    def test_usb_report_enables_audio_and_clears_mutes(self):
        report = self._capture("usb")
        # valid_flag0 = 0xF0（只开音频相关，不带马达使能位）
        self.assertEqual(report[1], 0xF0)
        # valid_flag1 需要 allow_audio_mute(0x02)
        self.assertTrue(report[2] & 0x02)
        # 马达字节归零
        self.assertEqual(report[3], 0)
        self.assertEqual(report[4], 0)
        # 音量：耳机 / 扬声器 / 麦克风 = 0x64
        self.assertEqual(report[5], 0x64)
        self.assertEqual(report[6], 0x64)
        self.assertEqual(report[7], 0x64)
        # power_save_mute_control 必须清零（MUTE_SPEAKER 0x20 / MUTE_HAPTIC 0x80）
        self.assertEqual(report[10], 0x00)
        self.assertEqual(report[40], 0x00)  # 触觉低通关闭

    def test_bluetooth_report_is_shifted_by_one(self):
        report = self._capture("bt")
        self.assertEqual(report[0], ds.BT_OUTPUT_REPORT_ID)
        self.assertEqual(report[2], 0xF0)  # BT valid_flag0 在 2
        self.assertEqual(report[3] & 0x02, 0x02)
        self.assertEqual(report[6], 0x64)  # 耳机音量
        self.assertEqual(report[7], 0x64)  # 扬声器音量
        self.assertEqual(report[11], 0x00)  # power_save_mute_control
        self.assertEqual(report[41], 0x00)  # 触觉低通
        self.assertEqual(report[4], 0)
        self.assertEqual(report[5], 0)


class HapticsModeTests(unittest.TestCase):
    """触觉模式：报告里不能带马达使能位，否则音频触觉被静音。"""

    def test_report_has_no_motor_bits_in_haptics_mode(self):
        reader = ds.DualSenseReader()
        reader._transport = "usb"  # noqa: SLF001
        reader.set_haptics_mode(True)
        report, _layout = reader._new_output_report()  # noqa: SLF001
        self.assertEqual(report[1] & 0x03, 0)  # valid_flag0 没有 0x01|0x02
        self.assertEqual(report[3], 0)
        self.assertEqual(report[4], 0)

    def test_report_has_motor_bits_when_haptics_off(self):
        reader = ds.DualSenseReader()
        reader._transport = "usb"  # noqa: SLF001
        reader.set_haptics_mode(False)
        report, _layout = reader._new_output_report()  # noqa: SLF001
        self.assertEqual(report[1] & 0x03, 0x03)

    def test_rumble_is_skipped_in_haptics_mode(self):
        reader = ds.DualSenseReader()
        reader._transport = "usb"  # noqa: SLF001
        reader.set_haptics_mode(True)
        writes = []
        reader._write = lambda report: writes.append(bytes(report)) or True  # noqa: SLF001
        self.assertFalse(reader.rumble(0.5, 0.5))
        self.assertEqual(writes, [])
        self.assertTrue(reader.rumble(0.5, 0.5, force=True))
        self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
