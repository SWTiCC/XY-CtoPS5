"""USB 触觉输出（haptics_usb）的纯软件测试：不需要真的 DualSense。

用假的 sounddevice 模块替换设备枚举与流打开，验证三件容易出错的事：
1. 端点选择：多主机 API 重名时按优先级取一个，同 API 下多个就放弃；
2. 采样率：优先设备原生率，失败才退回 3kHz，插值后帧数与时间轴对齐；
3. 输入校验与队列上限：对齐/长度/溢出清空的规则和参考实现一致。
"""

from __future__ import annotations

import math
import sys
import types
import unittest

import numpy as np

from ps5kbm import haptics_usb


class FakeStream:
    """假音频流：只记录参数，不产生回调。"""

    instances: list["FakeStream"] = []

    def __init__(self, **kwargs):
        self.samplerate = kwargs["samplerate"]
        self.channels = kwargs["channels"]
        self.device = kwargs["device"]
        self.callback = kwargs["callback"]
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def make_device(name: str, channels: int, hostapi: int, rate: int = 48000) -> dict:
    """构造 query_devices() 里的一个设备条目。"""
    return {
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": 0,
        "max_output_channels": channels,
        "default_samplerate": rate,
    }


class FakeSoundDevice:
    """假的 sounddevice 模块。"""

    def __init__(self, devices, hostapis, fail_rates=()):
        self.devices = devices
        self.hostapis = [{"name": name} for name in hostapis]
        self.fail_rates = set(fail_rates)
        self.query_count = 0
        self.opened = []

    def query_devices(self):
        self.query_count += 1
        return self.devices

    def query_hostapis(self):
        return self.hostapis

    def OutputStream(self, **kwargs):  # noqa: N802 - 与 sounddevice 同名
        rate = kwargs["samplerate"]
        if rate in self.fail_rates:
            raise RuntimeError(f"不支持 {rate} Hz")
        stream = FakeStream(**kwargs)
        FakeStream.instances.append(stream)
        self.opened.append(rate)
        return stream


class HapticsTestBase(unittest.TestCase):
    """统一安装/卸载假 sounddevice。"""

    def setUp(self) -> None:
        FakeStream.instances = []
        self._saved = sys.modules.get("sounddevice")

    def tearDown(self) -> None:
        if self._saved is None:
            sys.modules.pop("sounddevice", None)
        else:
            sys.modules["sounddevice"] = self._saved
        FakeStream.instances = []

    def install(self, fake: FakeSoundDevice) -> FakeSoundDevice:
        sys.modules["sounddevice"] = fake
        return fake

    def unit(self) -> haptics_usb.UsbHaptics:
        return haptics_usb.UsbHaptics()


class FindDeviceTests(HapticsTestBase):
    def test_picks_wasapi_when_endpoint_listed_by_two_host_apis(self):
        fake = self.install(
            FakeSoundDevice(
                devices=[
                    make_device("扬声器 (Wireless Controller)", 4, 0),
                    make_device("扬声器 (Wireless Controller)", 4, 2),
                ],
                hostapis=["MME", "Windows DirectSound", "Windows WASAPI"],
            )
        )
        found = haptics_usb.UsbHaptics.find_device()
        self.assertIsNotNone(found)
        index, device, api_name = found
        self.assertEqual(index, 1)
        self.assertEqual(api_name, "Windows WASAPI")
        self.assertEqual(device["name"], "扬声器 (Wireless Controller)")
        self.assertEqual(fake.query_count, 1)

    def test_ambiguous_same_host_api_fails_closed(self):
        self.install(
            FakeSoundDevice(
                devices=[
                    make_device("DualSense A", 4, 2),
                    make_device("DualSense B", 4, 2),
                ],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        self.assertIsNone(haptics_usb.UsbHaptics.find_device())

    def test_stereo_endpoint_is_ignored(self):
        self.install(
            FakeSoundDevice(
                devices=[make_device("扬声器 (Wireless Controller)", 2, 2)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        self.assertIsNone(haptics_usb.UsbHaptics.find_device())

    def test_other_endpoints_are_ignored(self):
        self.install(
            FakeSoundDevice(
                devices=[make_device("扬声器 (Realtek Audio)", 8, 2)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        self.assertIsNone(haptics_usb.UsbHaptics.find_device())

    def test_missing_sounddevice_returns_none(self):
        # sys.modules 里放 None 会让 import sounddevice 抛 ImportError
        # （直接 pop 不行：包装好了，再 import 还会成功）
        saved = sys.modules.get("sounddevice")
        sys.modules["sounddevice"] = None
        try:
            self.assertIsNone(haptics_usb.UsbHaptics.find_device())
        finally:
            if saved is None:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = saved


class EnsureTests(HapticsTestBase):
    def _one_device(self, fail_rates=(), rate=48000):
        return self.install(
            FakeSoundDevice(
                devices=[make_device("Wireless Controller", 4, 2, rate)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
                fail_rates=fail_rates,
            )
        )

    def test_opens_device_native_rate_first(self):
        self._one_device()
        unit = self.unit()
        self.assertTrue(unit.ensure())
        self.assertEqual(FakeStream.instances[0].samplerate, 48000)
        self.assertEqual(unit._stream_rate, 48000)  # noqa: SLF001 - 测试内部状态
        # 起播被推迟到「攒够预缓冲」之后（避免主机节奏略慢就饿死回调）
        self.assertFalse(FakeStream.instances[0].started)
        unit.feed(bytes(360))
        unit.feed(bytes(360))
        unit.feed(bytes(360))
        self.assertTrue(FakeStream.instances[0].started)
        self.assertEqual(FakeStream.instances[0].channels, 4)
        unit.close()
        self.assertTrue(FakeStream.instances[0].closed)

    def test_falls_back_to_source_rate(self):
        self._one_device(fail_rates=(48000,))
        unit = self.unit()
        self.assertTrue(unit.ensure())
        self.assertEqual(unit._stream_rate, haptics_usb._SOURCE_RATE)  # noqa: SLF001
        self.assertEqual(len(FakeStream.instances), 1)

    def test_all_rates_failing_reports_failure_and_backs_off(self):
        fake = self._one_device(fail_rates=(48000, 3000))
        unit = self.unit()
        self.assertFalse(unit.ensure())
        self.assertEqual(fake.query_count, 1)
        # 退避期内不再枚举设备
        self.assertFalse(unit.ensure())
        self.assertEqual(fake.query_count, 1)

    def test_missing_endpoint_backs_off_instead_of_scanning_per_packet(self):
        fake = self.install(FakeSoundDevice(devices=[], hostapis=["MME"]))
        unit = self.unit()
        for _ in range(20):
            self.assertFalse(unit.ensure())
        self.assertEqual(fake.query_count, 1)

    def test_close_allows_reopen(self):
        fake = self._one_device()
        unit = self.unit()
        self.assertTrue(unit.ensure())
        unit.close()
        self.assertTrue(unit.ensure())
        self.assertEqual(fake.query_count, 2)
        self.assertEqual(len(FakeStream.instances), 2)


class FeedTests(HapticsTestBase):
    def _open(self, rate=48000):
        self.install(
            FakeSoundDevice(
                devices=[make_device("Wireless Controller", 4, 2, rate)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        unit = self.unit()
        self.assertTrue(unit.ensure())
        return unit

    def test_oversized_packet_rejected_without_opening_device(self):
        self.install(
            FakeSoundDevice(
                devices=[make_device("Wireless Controller", 4, 2)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        unit = self.unit()
        unit.feed(bytes(1600))
        self.assertEqual(FakeStream.instances, [])
        self.assertEqual(unit._queued_frames, 0)  # noqa: SLF001

    def test_unaligned_packet_rejected(self):
        unit = self._open()
        unit.feed(bytes(361))
        self.assertEqual(unit._queued_frames, 0)  # noqa: SLF001

    def test_packet_is_resampled_to_device_rate(self):
        unit = self._open(48000)
        unit.feed(bytes(360))  # 90 帧 @3kHz = 30ms
        # 跨包连续插值会给下一包留 1 个输出样本（89 * 16 = 1424），延迟仅 0.02ms
        self.assertEqual(unit._queued_frames, 1424)  # noqa: SLF001

    def test_direct_source_rate_keeps_frame_count(self):
        unit = self._open(3000)
        unit.feed(bytes(360))
        self.assertEqual(unit._queued_frames, 90)  # noqa: SLF001

    def test_queue_cap_clears_backlog(self):
        """缓冲上限：超了整段清空（Veyra 的 100ms 规则），不是越积越多。"""
        unit = self._open(48000)
        max_frames = int(48000 * haptics_usb._QUEUE_SECONDS)
        for _ in range(30):
            unit.feed(bytes(360))
        self.assertLessEqual(unit._queued_frames, max_frames)  # noqa: SLF001

    def test_callback_fills_only_haptic_channels(self):
        unit = self._open(3000)
        stereo = np.arange(90 * 2, dtype=np.int16).reshape(-1, 2)
        packet = stereo[:30]  # 一包 = 30 帧 @3kHz
        for _ in range(4):  # 攒够 40ms 预缓冲（120 帧）
            unit.feed(packet.tobytes())
        out = np.zeros((90, 4), dtype=np.int16)
        stream = FakeStream.instances[0]
        stream.callback(out, 90, None, None)
        self.assertTrue((out[:, 0] == 0).all())
        self.assertTrue((out[:, 1] == 0).all())
        np.testing.assert_array_equal(out[:, 2:4], np.tile(packet, (3, 1)))

    def test_plays_after_prebuffer(self):
        """攒够预缓冲（3000Hz 下 40ms = 120 帧 = 4 包）就起播。"""
        unit = self._open(3000)
        for _ in range(4):
            unit.feed((np.full((30, 2), 1000, dtype=np.int16)).tobytes())
        self.assertTrue(unit._started)  # noqa: SLF001
        out = np.zeros((30, 4), dtype=np.int16)
        stream = FakeStream.instances[0]
        stream.callback(out, 30, None, None)
        self.assertTrue((out[:, 2] == 1000).all())


class ReferenceBehaviourTests(HapticsTestBase):
    """输出策略：chiaki + Veyra 的做法，外加一小段抖动缓冲。

    实机抓包：主机送包是突发式的（中位间隔 4.8ms、p90 17.7ms、p99 38.7ms），
    平均 74~100 包/秒。完全没有缓冲时队列只有 0~10ms，每串包之间都会欠载
    （实测约 1 次/秒）——那就是「不断抽动」。Veyra 靠 SDL 音频流自带的缓冲兜住，
    所以这里也攒够 30ms 再播、欠载后攒回 30ms 再继续；不调速率、不保持样本。
    """

    def _open(self, rate=48000):
        self.install(
            FakeSoundDevice(
                devices=[make_device("Wireless Controller", 4, 2, rate)],
                hostapis=["MME", "DirectSound", "Windows WASAPI"],
            )
        )
        unit = self.unit()
        self.assertTrue(unit.ensure())
        return unit

    @staticmethod
    def _pcm(frames=30, value=1000):
        return np.full((frames, 2), value, dtype=np.int16).tobytes()

    def _prefill(self, unit):
        """喂到起播（48000Hz 下 40ms ≈ 1920 帧；首包因跨包插值少 16 帧，所以是 5 包左右）。"""
        for _ in range(10):
            if unit._started:  # noqa: SLF001
                break
            unit.feed(self._pcm())
        self.assertTrue(unit._started)  # noqa: SLF001
        return FakeStream.instances[0]

    def test_waits_for_prebuffer_then_plays(self):
        unit = self._open(48000)
        for _ in range(2):
            unit.feed(self._pcm())
        self.assertFalse(unit._started)  # noqa: SLF001 - 要先攒够预缓冲
        for _ in range(6):
            if unit._started:  # noqa: SLF001
                break
            unit.feed(self._pcm())
        self.assertTrue(unit._started)  # noqa: SLF001
        self.assertTrue(FakeStream.instances[0].started)

    def test_callback_before_any_data_is_silent(self):
        unit = self._open(48000)
        stream = FakeStream.instances[0]
        out = np.full((480, 4), 7, dtype=np.int16)
        stream.callback(out, 480, None, None)
        self.assertTrue((out == 0).all())

    def test_underrun_outputs_silence_not_held_sample(self):
        unit = self._open(48000)
        stream = self._prefill(unit)
        # 一次要 200ms，把队列抽空
        out = np.zeros((9600, 4), dtype=np.int16)
        stream.callback(out, 9600, None, None)
        self.assertEqual(unit.stats()[0], 1)
        self.assertEqual(int(out[-1, 2]), 0)  # 尾巴淡出到 0，不是保持满幅
        again = np.full((480, 4), 7, dtype=np.int16)
        stream.callback(again, 480, None, None)
        self.assertTrue((again == 0).all())

    def test_refills_before_resuming(self):
        unit = self._open(48000)
        stream = self._prefill(unit)
        stream.callback(np.zeros((9600, 4), dtype=np.int16), 9600, None, None)
        self.assertTrue(unit._starved)  # noqa: SLF001
        # 只喂一包不够：恢复也要攒够预缓冲
        unit.feed(self._pcm())
        held = np.full((480, 4), 7, dtype=np.int16)
        stream.callback(held, 480, None, None)
        self.assertTrue((held == 0).all())
        self.assertTrue(unit._starved)  # noqa: SLF001
        # 攒够后恢复，且立刻能播出数据
        for _ in range(8):
            if not unit._starved:  # noqa: SLF001
                break
            unit.feed(self._pcm())
        self.assertFalse(unit._starved)  # noqa: SLF001
        self.assertGreaterEqual(unit.stats()[2], 1)
        out = np.zeros((480, 4), dtype=np.int16)
        stream.callback(out, 480, None, None)
        self.assertTrue((out[:, 2] == 1000).all())

    def test_queue_overflow_clears_instead_of_adapting(self):
        unit = self._open(48000)
        max_frames = int(48000 * haptics_usb._QUEUE_SECONDS)
        for _ in range(40):
            unit.feed(self._pcm())  # 不消费：队列涨到上限后整段清空
        self.assertLessEqual(unit.stats()[1], max_frames)
        unit.feed(self._pcm())
        out = np.zeros((480, 4), dtype=np.int16)
        FakeStream.instances[0].callback(out, 480, None, None)
        self.assertTrue(unit.stats()[0] >= 0)


class BlockTests(unittest.TestCase):
    def test_resample_keeps_constant_level(self):
        stereo = np.full((90, 2), 12000, dtype=np.int16)
        block = haptics_usb.UsbHaptics()._to_block(stereo, 48000)  # noqa: SLF001
        self.assertEqual(len(block), 1424)
        self.assertTrue((block[:, 2:4] == 12000).all())
        self.assertTrue((block[:, 0:2] == 0).all())

    def test_blocks_join_without_step(self):
        """跨包连续插值：接缝处不能出现「最后一个样本重复十几次」的平台。"""
        unit = haptics_usb.UsbHaptics()
        first = (np.arange(30, dtype=np.float32) * 100).astype(np.int16)
        second = (np.arange(30, 60, dtype=np.float32) * 100).astype(np.int16)
        block_a = unit._to_block(np.stack([first, first], axis=1), 48000)  # noqa: SLF001
        block_b = unit._to_block(np.stack([second, second], axis=1), 48000)  # noqa: SLF001
        merged = np.concatenate([block_a[:, 2], block_b[:, 2]]).astype(np.int32)
        # 单调上升的斜坡：重采样后每步应该接近 100/16 ≈ 6~7，不能有大跳变或长平台
        self.assertGreater(len(merged), 900)
        steps = np.diff(merged)
        self.assertGreaterEqual(int(steps.min()), 0)
        self.assertLessEqual(int(steps.max()), 10)
        plateau = sum(1 for value in steps if value == 0)
        self.assertLess(plateau, 30)

    def test_odd_device_rate_is_resampled_linearly(self):
        stereo = np.full((90, 2), -8000, dtype=np.int16)
        block = haptics_usb.UsbHaptics()._to_block(stereo, 44100)  # noqa: SLF001
        self.assertEqual(len(block), math.ceil(89 * 44100 / 3000))
        self.assertTrue((block[:, 2:4] == -8000).all())


class TestToneTests(unittest.TestCase):
    def test_chunks_are_within_packet_limits(self):
        chunks = haptics_usb.test_tone_chunks(0.6)
        self.assertEqual(len(chunks), 20)  # 600ms / 30ms
        for chunk in chunks:
            self.assertEqual(len(chunk) % 4, 0)
            self.assertLessEqual(len(chunk), haptics_usb._MAX_PACKET_BYTES)
        self.assertEqual(sum(len(chunk) for chunk in chunks), 3000 * 0.6 * 4)

    def test_tone_is_audible(self):
        pcm = np.frombuffer(b"".join(haptics_usb.test_tone_chunks(0.1)), dtype=np.int16)
        self.assertGreater(int(np.abs(pcm).max()), 1000)


if __name__ == "__main__":
    unittest.main()
