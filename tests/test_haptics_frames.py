"""触觉帧序号去重（照 chiaki 的 audioreceiver 规则）。

触觉包和普通音频共用一条 AV 帧序号；chiaki 对 haptics 帧只做
`if(frame_index > prev) deliver`。不做这一步时，网络重传/重复包会把同一段触觉
播两遍、乱序旧帧还会插到新帧后面——手感上是「不该震的时候震一下」「连续不规则间断」。
"""

from __future__ import annotations

import unittest

from ps5kbm import bridge


def _payload(units: int, value: int) -> bytes:
    """造 units 个 120 字节单元，每单元用不同字节填充，方便断言取到了哪一段。"""
    out = bytearray()
    for index in range(units):
        out += bytes([(value + index) & 0xFF]) * 120
    return bytes(out)


class FrameSeqTests(unittest.TestCase):
    def setUp(self) -> None:
        bridge._haptics_last_frame = None  # noqa: SLF001
        bridge._haptics_stale = 0  # noqa: SLF001

    def tearDown(self) -> None:
        bridge._haptics_last_frame = None  # noqa: SLF001

    def test_seq16_wraps(self):
        self.assertTrue(bridge._seq16_gt(5, 4))  # noqa: SLF001
        self.assertFalse(bridge._seq16_gt(4, 5))  # noqa: SLF001
        self.assertFalse(bridge._seq16_gt(4, 4))  # noqa: SLF001
        # 环形：65535 → 0 算「更新」
        self.assertTrue(bridge._seq16_gt(0, 65535))  # noqa: SLF001
        self.assertFalse(bridge._seq16_gt(65535, 0))  # noqa: SLF001

    def test_first_frame_passes_then_duplicate_is_dropped(self):
        dword2 = 0x0002_7821  # total=3(0x0002+1), unit=120(0x78), fec=2, src=1
        raw = _payload(3, 0x10)
        first = bridge._take_fresh_haptic_frames(raw, dword2, 100)  # noqa: SLF001
        self.assertEqual(first, raw[:120])
        # 同一帧再来一次（网络重传）：必须丢掉
        again = bridge._take_fresh_haptic_frames(raw, dword2, 100)  # noqa: SLF001
        self.assertEqual(again, b"")
        # 新的一帧：放行
        newer = bridge._take_fresh_haptic_frames(raw, dword2, 101)  # noqa: SLF001
        self.assertEqual(newer, raw[:120])

    def test_out_of_order_old_frame_is_dropped(self):
        dword2 = 0x0002_7821
        raw = _payload(3, 0x20)
        bridge._take_fresh_haptic_frames(raw, dword2, 200)  # noqa: SLF001
        old = bridge._take_fresh_haptic_frames(raw, dword2, 150)  # noqa: SLF001
        self.assertEqual(old, b"")
        self.assertEqual(bridge._haptics_stale, 0)  # noqa: SLF001 - 计数在调用方

    def test_multi_source_units_in_one_packet(self):
        # total=3, unit=120, src=2, fec=0 → dword2 = [total-1][unit][fec][src]
        dword2 = (0x02 << 16) | (120 << 8) | (0 << 4) | 2
        raw = _payload(3, 0x30)
        fresh = bridge._take_fresh_haptic_frames(raw, dword2, 300)  # noqa: SLF001
        # 两个源单元（帧 300、301）都要，且按顺序拼接
        self.assertEqual(fresh, raw[:240])
        self.assertEqual(bridge._haptics_last_frame, 301)  # noqa: SLF001

    def test_bad_header_passes_payload_through(self):
        # unit_size=0 说明头部不可信：原样交给播放层，别把音频吞掉
        raw = _payload(3, 0x40)
        self.assertEqual(
            bridge._take_fresh_haptic_frames(raw, 0x0002_0001, 1),  # noqa: SLF001
            raw,
        )


if __name__ == "__main__":
    unittest.main()
