"""USB 连接时的原生触觉输出。

业界做法（dualsense-companion / Vibepollo / chiaki 架构）：
DualSense 有线连接时是一个 4 声道 48kHz 16bit 的 USB 音频设备，
声道 1-2 是扬声器，声道 3-4 驱动触觉马达。
蓝牙没有音频端点，因此本功能只在 USB 连接时启用；蓝牙只保留自适应扳机。

实现要点：用回调式输出 + FIFO 供数，空的时候补静音。
逐包阻塞写会欠载（每次事件之间断流），听感就是“抽搐一下”。
"""

from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np

_LOGGER = logging.getLogger("ps5kbm.haptics")

_SAMPLE_RATE = 48000
_OUTPUT_CHANNELS = 4


class UsbHaptics:
    """把 haptics PCM（48k 立体声 s16）混到 DualSense 的 3/4 声道并连续输出。"""

    def __init__(self) -> None:
        self._stream = None
        self._lock = threading.Lock()
        self._failed = False
        self._pending: deque[np.ndarray] = deque()
        self._partial: np.ndarray | None = None
        self._partial_offset = 0
        self._last_sample = 0
        self._primed = False
        self._prime_frames = int(_SAMPLE_RATE * 0.10)

    @staticmethod
    def find_device() -> tuple[int, dict] | None:
        """找 DualSense 的音频输出端点（需要 4 声道，优先 48kHz）。"""
        try:
            import sounddevice as sd
        except Exception:  # noqa: BLE001 - 没装 sounddevice 就不可用
            return None
        candidates: list[tuple[int, dict]] = []
        for index, device in enumerate(sd.query_devices()):
            name = (device.get("name") or "").lower()
            if device.get("max_output_channels", 0) < _OUTPUT_CHANNELS:
                continue
            if any(key in name for key in ("dualsense", "wireless controller", "ps5")):
                candidates.append((index, device))
        if not candidates:
            return None
        for index, device in candidates:
            if int(device.get("default_samplerate") or 0) == _SAMPLE_RATE:
                return index, device
        return candidates[0]

    def ensure(self) -> bool:
        """按需打开音频端点；打不开就记住失败，不反复尝试。"""
        if self._stream is not None:
            return True
        if self._failed:
            return False
        found = self.find_device()
        if found is None:
            return False
        index, device = found
        try:
            import sounddevice as sd

            stream = sd.OutputStream(
                samplerate=_SAMPLE_RATE,
                channels=_OUTPUT_CHANNELS,
                dtype="int16",
                device=index,
                blocksize=0,
                latency="low",
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("打开 DualSense USB 音频端点失败：%s", exc)
            self._failed = True
            return False
        with self._lock:
            self._stream = stream
        _LOGGER.info("已打开 DualSense USB 音频端点：%s", device.get("name"))
        return True

    def _callback(self, outdata, frames, _time, _status) -> None:
        """音频回调：从 FIFO 取数据；欠载时保持最后采样一小段，避免爆音。"""
        outdata.fill(0)
        filled = 0
        with self._lock:
            while filled < frames:
                if self._partial is None or self._partial_offset >= len(self._partial):
                    if not self._pending:
                        break
                    self._partial = self._pending.popleft()
                    self._partial_offset = 0
                available = len(self._partial) - self._partial_offset
                take = min(available, frames - filled)
                outdata[filled : filled + take] = self._partial[
                    self._partial_offset : self._partial_offset + take
                ]
                self._partial_offset += take
                filled += take
                self._last_sample = int(self._partial[self._partial_offset - 1, 2])
            if filled < frames:
                # 欠载：保持最后采样 4ms，再做线性收尾，避免“抽搐”感
                hold = min(frames - filled, 192)
                outdata[filled : filled + hold, 2:4] = self._last_sample
                filled += hold

    def feed(self, pcm: bytes) -> None:
        """pcm：48k 立体声 s16 交错；把左右声道送到 3/4，1/2 保持静音。"""
        if not pcm or not self.ensure():
            return
        frames = len(pcm) // 4
        if not frames:
            return
        stereo = np.frombuffer(pcm[: frames * 4], dtype=np.int16).reshape(-1, 2).copy()
        # 固定增益 + 软限幅：保留原始动态（撞击大、环境小），
        # 不要逐包归一化，否则安静/剧烈会被拉成同一个强度。
        # 固定增益 3.5 + 硬限幅：tanh 会把撞击脉冲压成持续的嗡嗡声
        samples = stereo.astype(np.float32) * 3.5
        stereo = np.clip(samples, -32768, 32767).astype(np.int16)
        # 首尾 1ms 淡入淡出，消除包边界上的爆音
        fade = min(48, frames // 2)
        if fade > 0:
            ramp = np.linspace(0.0, 1.0, fade)
            stereo[:fade] = (stereo[:fade] * ramp[:, None]).astype(np.int16)
            stereo[-fade:] = (stereo[-fade:] * ramp[::-1, None]).astype(np.int16)
        block = np.zeros((frames, _OUTPUT_CHANNELS), dtype=np.int16)
        block[:, 2:4] = stereo
        with self._lock:
            if not self._primed:
                queued_now = sum(len(item) for item in self._pending)
                if queued_now + frames < self._prime_frames:
                    self._pending.append(block)
                    return
                self._primed = True
            # 限制积压，最多 0.5 秒，避免延迟越滚越大
            max_frames = _SAMPLE_RATE // 2
            queued = sum(len(item) for item in self._pending)
            if queued + frames > max_frames:
                while self._pending and queued + frames > max_frames:
                    dropped = self._pending.popleft()
                    queued -= len(dropped)
            self._pending.append(block)

    def close(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            self._pending.clear()
            self._partial = None
            self._primed = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
