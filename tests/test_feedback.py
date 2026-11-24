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


if __name__ == "__main__":
    unittest.main()
