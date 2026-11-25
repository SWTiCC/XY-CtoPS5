"""主机下发反馈（震动 / 扳机效果）的纯解析测试。"""

from __future__ import annotations

import unittest

from ps5kbm import feedback


class RumbleParseTests(unittest.TestCase):
    def test_parse(self):
        left, right = feedback.parse_rumble(bytes([0xAA, 0x80, 0x40]))
        self.assertAlmostEqual(left, 128 / 255)
        self.assertAlmostEqual(right, 64 / 255)

    def test_too_short(self):
        self.assertIsNone(feedback.parse_rumble(bytes([0x00, 0x10])))


class TriggerParseTests(unittest.TestCase):
    def _payload(self) -> bytes:
        data = bytearray(25)
        data[0] = 0xAA
        data[1] = 0x21  # 左：阻力
        data[2] = 0x25  # 右：开枪
        data[5:15] = bytes(range(10))
        data[15:25] = bytes(range(10, 20))
        return bytes(data)

    def test_parse_blocks(self):
        left, right = feedback.parse_trigger_effects(self._payload())
        self.assertEqual(len(left), 11)
        self.assertEqual(len(right), 11)
        self.assertEqual(left[0], 0x21)
        self.assertEqual(right[0], 0x25)
        self.assertEqual(left[1:], bytes(range(10)))
        self.assertEqual(right[1:], bytes(range(10, 20)))

    def test_too_short(self):
        self.assertIsNone(feedback.parse_trigger_effects(bytes(24)))


class DataTypeTests(unittest.TestCase):
    def test_data_type_offset(self):
        chunk = bytes([0, 0, 0, 1, 0, 1, 0, 0, feedback.DATA_TYPE_RUMBLE, 0, 1, 2])
        self.assertEqual(feedback.data_type_of(chunk), feedback.DATA_TYPE_RUMBLE)
        self.assertEqual(feedback.payload_of(chunk), bytes([0, 1, 2]))

    def test_short_chunk_defaults_to_protobuf(self):
        self.assertEqual(feedback.data_type_of(b"\x00\x01"), feedback.DATA_TYPE_PROTOBUF)


class PadInfoTests(unittest.TestCase):
    def test_long_pad_info(self):
        data = bytes(25)
        data = bytearray(data)
        data[9:12] = bytes([10, 20, 30])
        data[12] = 1
        data[20] = 2
        data[21] = 3
        info = feedback.parse_pad_info(bytes(data))
        self.assertEqual(info["led"], bytes([10, 20, 30]))
        self.assertEqual(info["haptic_intensity"], 2)
        self.assertEqual(info["trigger_intensity"], 3)

    def test_short_pad_info(self):
        data = bytearray(17)
        data[1:4] = bytes([1, 2, 3])
        data[12] = 0
        data[13] = 1
        info = feedback.parse_pad_info(bytes(data))
        self.assertEqual(info["led"], bytes([1, 2, 3]))

    def test_too_short(self):
        self.assertIsNone(feedback.parse_pad_info(bytes(8)))


class AudioUnitsTests(unittest.TestCase):
    """音频 AV 包：只取真实音频单元，丢掉 FEC 校验单元。"""

    @staticmethod
    def _dword2(unit: int, fec: int, src: int, total: int) -> int:
        """按协议拼 dword2：低 16 位 = [unit][fec][src]，高位 = total-1。"""
        low = ((unit & 0xFF) << 8) | ((fec & 0x0F) << 4) | (src & 0x0F)
        return ((total - 1) & 0xFF) << 0x10 | low

    def test_trims_fec_units(self):
        # 360 字节 = 3 个 120 字节单元，只有第 1 个是真实音频
        payload = bytes(i % 251 for i in range(360))
        dword2 = self._dword2(unit=120, fec=2, src=1, total=3)
        pcm, total, src, fec = feedback.audio_units(payload, dword2)
        self.assertEqual((total, src, fec), (3, 1, 2))
        self.assertEqual(len(pcm), 120)
        self.assertEqual(pcm, payload[:120])

    def test_keeps_everything_when_all_units_are_source(self):
        payload = bytes(i % 251 for i in range(360))
        dword2 = self._dword2(unit=120, fec=0, src=3, total=3)
        pcm, total, src, fec = feedback.audio_units(payload, dword2)
        self.assertEqual((total, src, fec), (3, 3, 0))
        self.assertEqual(len(pcm), 360)

    def test_single_unit_packet_untouched(self):
        payload = bytes(120)
        dword2 = self._dword2(unit=120, fec=0, src=1, total=1)
        pcm, total, src, _fec = feedback.audio_units(payload, dword2)
        self.assertEqual((total, src), (1, 1))
        self.assertEqual(len(pcm), 120)

    def test_bogus_fields_return_payload(self):
        payload = bytes(360)
        # unit_size 为 0（字段没填）→ 原样返回
        pcm, _total, _src, _fec = feedback.audio_units(payload, 0)
        self.assertEqual(len(pcm), 360)
        # unit_size 与总长不一致 → 原样返回
        dword2 = self._dword2(unit=200, fec=1, src=1, total=3)
        pcm, _total, _src, _fec = feedback.audio_units(payload, dword2)
        self.assertEqual(len(pcm), 360)


if __name__ == "__main__":
    unittest.main()
