"""USB 连接时的原生触觉输出（对齐参考实现 Veyra-NRVideo / chiaki-ng）。

对照来源与结论：

- `Veyra src/remoteplay/ControllerInput.cpp` 的 haptics 段：触觉数据是**原始
  3kHz 立体声 s16 PCM**，不做解码、不做低通、不做增益；输出到 DualSense 的
  **四声道**端点，声道 1/2 保持静音、3/4 装触觉；队列上限 100ms，超了整段清空；
  端点名字必须含 "Wireless Controller" / "DualSense" 且是四声道，不唯一就放弃；
- `chiaki-ng streamsession.cpp` 的 `PushHapticsFrame`：把 3kHz 数据自己升到
  48kHz 再送设备（SDL 的转换是线性插值），所以我们这里也用线性插值；
- `chiaki-ng takion.c / audioreceiver.c`：触觉包在 AV 层就是一个单元一个包，
  单位就是 3kHz 立体声帧，直接当 PCM 用。

Windows 侧的两个坑（本机实测）：

1. PortAudio 会把同一个物理端点在多个主机 API 下各列一次（本机 97 个设备里
   有 24 个重名），所以"找到 1 个四声道端点"必须是**按主机 API 优先**
   挑出来的 1 个，否则会一直判成歧义、永远不输出；
2. WASAPI 共享模式不接受设备混音格式以外的采样率（PortAudio 没有开
   AUTOCONVERTPCM），所以优先按设备原生率打开，再自行线性插值到设备率。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque

import numpy as np

_LOGGER = logging.getLogger("ps5kbm.haptics")

# 每个线程只初始化一次 COM（PortAudio 的 WASAPI 后端要求调用线程已初始化 COM）
_thread_state = threading.local()


def _ensure_com_initialized() -> None:
    """在调用线程初始化 COM。

    实测（本机 WASAPI 4 声道端点）：
    - 主线程打开流 → 正常；
    - 后台线程不初始化 COM 打开流 → `Error starting stream:
      Unanticipated host error -9999`，两个采样率都失败；
    - 后台线程先 CoInitializeEx(MTA 或 STA) → 正常。
    所以「触觉解码线程」必须先做这一步，否则震动永远不生效。
    """
    if getattr(_thread_state, "com_ready", False):
        return
    _thread_state.com_ready = True
    try:
        import ctypes

        # 返回 S_OK / S_FALSE / RPC_E_CHANGED_MODE 都算「COM 已可用」，忽略返回码
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
    except Exception:  # noqa: BLE001 - 失败就让 PortAudio 自己报错
        pass

# 触觉源固定是 3kHz 立体声 s16（chiaki 与参考实现都是这个格式）
_SOURCE_RATE = 3000
# DualSense 音频端点原生率（块传输模式下的混音格式）
_DEVICE_RATE = 48000
_OUTPUT_CHANNELS = 4
# 参考实现的输入校验：1200 字节 = 300 帧 = 100ms
_MAX_PACKET_BYTES = _SOURCE_RATE // 10 * 4

# 输出策略：照抄 chiaki + Veyra，只补一个必要的小抖动缓冲。
#   - chiaki 的 audioreceiver 对 haptics 帧只做「帧序号更新才播」，收到就立刻交给 sink；
#   - Veyra 把每帧原样塞进 SDL 音频流，队列超过 2400 字节（100ms）时整段清空；
#   - 两者都不调速率、不保持样本：没数据就输出静音（等于主机没给触觉）。
# 实机抓包补充：主机送包是**突发式**的（中位间隔 4.8ms、p90 17.7ms、p99 38.7ms），
# 平均帧率在 74~100 包/秒之间变。完全不给缓冲时队列 0~10ms，每一串包之间都会欠载
# （实测约 1 次/秒）——这就是「不断抽动」。Veyra 靠 SDL 音频流自带的缓冲兜住了这一段，
# 我们也需要等量的缓冲：攒够 40ms 再播，掉空后同样攒回 40ms 再继续。
_QUEUE_SECONDS = 0.10  # 队列上限：超过就整段清空（Veyra 的 SDL_GetAudioStreamQueued > 2400）
_PREBUFFER_SECONDS = 0.04  # 起播/欠载后恢复的缓冲量：覆盖抓到的 p99 突发间隔（38.7ms）
# 欠载时只在这个长度内淡出到 0（约 2ms @48k），避免满幅直接跳 0 的咔哒声
_FADE_FRAMES = 96
# 端点/打开失败后的重试退避（插拔 USB 线后能自动恢复）
_RETRY_SECONDS = 3.0
_RETRY_MAX_SECONDS = 30.0
# 端点名字线索（Windows 下 USB 音频端点名字取自 USB 产品串，中文系统也是英文）
_NAME_HINTS = ("dualsense", "wireless controller", "ps5")
# 主机 API 优先级：WASAPI 最稳、延迟最低；MME 是 PortAudio 默认但延迟高
_HOSTAPI_PREFERENCE = ("wasapi", "wdm-ks", "directsound", "mme")


class UsbHaptics:
    """把触觉 PCM 混到 DualSense 的 3/4 声道并连续输出。"""

    def __init__(self) -> None:
        self._stream = None
        self._stream_rate = 0
        self._lock = threading.Lock()
        self._pending: deque[np.ndarray] = deque()
        self._partial: np.ndarray | None = None
        self._partial_offset = 0
        self._queued_frames = 0
        # 跨包连续插值：上一包最后一个样本 + 「下一个输出样本对应的源位置」浮点游标
        self._last_source: np.ndarray | None = None
        self._src_total = 0
        self._next_out_src = 0.0
        # 队列上限（帧）：超过就整段清空，和 Veyra 的 100ms 规则一致
        self._max_frames = 0
        # 起播 / 欠载后恢复的缓冲量（帧）：补上 SDL 音频流自带的那一小段缓冲
        self._prebuffer_frames = 0
        # 播放速率：参考实现不做自适应，这里固定 1.0，只保留字段给诊断日志
        self._ratio_scale = 1.0
        # 起播标记：第一帧到了就播；没数据就输出静音
        self._started = False
        self._starved = False
        self._last_sample: np.ndarray | None = None
        # 欠载次数（回调没数据）、恢复次数：诊断用
        self._underruns = 0
        self._refills = 0
        # 打不开端点时的退避：避免每个触觉包都去枚举一遍音频设备
        self._retry_at = 0.0
        self._retry_delay = _RETRY_SECONDS
        self._missing_logged = False
        self._open_failed_logged = False

    # ------------------------------------------------------------ 设备
    @staticmethod
    def find_device() -> tuple[int, dict, str] | None:
        """找 DualSense 的四声道输出端点；有歧义就返回 None（失败关闭）。

        同一个物理端点会在多个主机 API 下重名出现，所以先按主机 API 优先级
        排序，只认优先级最高的那一组；那一组里仍不唯一才算歧义。
        """
        try:
            import sounddevice as sd
        except Exception:  # noqa: BLE001 - 没装 sounddevice 就不可用
            return None
        try:
            devices = sd.query_devices()
            hostapis = [api.get("name") or "" for api in sd.query_hostapis()]
        except Exception as exc:  # noqa: BLE001 - 没有音频设备时会抛异常
            _LOGGER.debug("枚举音频端点失败：%s", exc)
            return None

        candidates: list[tuple[int, dict, str]] = []
        for index, device in enumerate(devices):
            name = (device.get("name") or "").lower()
            if int(device.get("max_output_channels") or 0) < _OUTPUT_CHANNELS:
                continue
            if not any(hint in name for hint in _NAME_HINTS):
                continue
            api_index = int(device.get("hostapi") or 0)
            api_name = hostapis[api_index] if api_index < len(hostapis) else ""
            candidates.append((index, device, api_name))
        if not candidates:
            return None

        def rank(item: tuple[int, dict, str]) -> int:
            api = item[2].lower()
            for position, preferred in enumerate(_HOSTAPI_PREFERENCE):
                if preferred in api:
                    return position
            return len(_HOSTAPI_PREFERENCE)

        candidates.sort(key=rank)
        best = rank(candidates[0])
        pool = [item for item in candidates if rank(item) == best]
        if len(pool) != 1:
            _LOGGER.warning(
                "找到 %d 个候选触觉端点（%s），无法确定是哪一个，触觉不路由",
                len(pool),
                "、".join(f"{item[1].get('name')}@{item[2]}" for item in pool),
            )
            return None
        return pool[0]

    def ensure(self) -> bool:
        """按需打开音频端点；优先设备原生率，失败再试 3kHz。"""
        if self._stream is not None:
            return True
        now = time.monotonic()
        if now < self._retry_at:
            return False
        # 后台线程必须先初始化 COM，否则 WASAPI 打开流一定失败（见函数注释）
        _ensure_com_initialized()
        found = self.find_device()
        if found is None:
            # 蓝牙 / 没插线时这是常态：退避后自动重试，别每个包都枚举设备
            self._retry_at = now + self._retry_delay
            self._retry_delay = min(self._retry_delay * 2, _RETRY_MAX_SECONDS)
            if not self._missing_logged:
                self._missing_logged = True
                _LOGGER.info(
                    "没找到 DualSense 的四声道音频端点，触觉暂不输出"
                    "（插上 USB 线后会自动重试）"
                )
            return False

        index, device, api_name = found
        import sounddevice as sd

        # 优先设备原生率（WASAPI 共享模式只认混音格式），再退回 3kHz 直出
        rates: list[int] = []
        default_rate = int(device.get("default_samplerate") or 0)
        if default_rate > 0:
            rates.append(default_rate)
        for rate in (_DEVICE_RATE, _SOURCE_RATE):
            if rate not in rates:
                rates.append(rate)

        for rate in rates:
            try:
                stream = sd.OutputStream(
                    samplerate=rate,
                    channels=_OUTPUT_CHANNELS,
                    dtype="int16",
                    device=index,
                    blocksize=0,
                    latency="low",
                    callback=self._callback,
                )
                # 先别起播：等队列攒到 _PREBUFFER_SECONDS 再 start()，
                # 否则第一包就对 10ms 的音频块，主机节奏一抖就饿死回调（听感是断续）
            except Exception as exc:  # noqa: BLE001 - 换下一个采样率
                _LOGGER.debug("打开 %d Hz 触觉流失败：%s", rate, exc)
                continue
            with self._lock:
                self._stream = stream
                self._stream_rate = rate
                self._started = False
                self._starved = False
                # 参考实现的队列上限：100ms，超了整段清空（不做速率补偿）
                self._max_frames = max(1, int(rate * _QUEUE_SECONDS))
                # 起播 / 欠载后恢复需要的缓冲量（等价于 SDL 音频流自带的抖动缓冲）
                self._prebuffer_frames = max(1, int(rate * _PREBUFFER_SECONDS))
                self._ratio_scale = 1.0
                self._last_sample = None
            self._missing_logged = False
            self._open_failed_logged = False
            self._retry_delay = _RETRY_SECONDS
            self._retry_at = 0.0
            _LOGGER.info(
                "已打开 DualSense 触觉端点：%s（%s / %d Hz，%d 声道）",
                device.get("name"),
                api_name or "默认音频 API",
                rate,
                _OUTPUT_CHANNELS,
            )
            return True

        self._retry_at = now + self._retry_delay
        self._retry_delay = min(self._retry_delay * 2, _RETRY_MAX_SECONDS)
        if not self._open_failed_logged:
            self._open_failed_logged = True
            _LOGGER.warning(
                "打开 DualSense 音频端点失败（试过 %s Hz）",
                "/".join(str(rate) for rate in rates),
            )
        return False

    def is_open(self) -> bool:
        """当前是否已经打开端点（界面/日志判断用）。"""
        with self._lock:
            return self._stream is not None

    # ------------------------------------------------------------ 输出
    def _callback(self, outdata, frames, _time, _status) -> None:
        """音频回调：有数据就播，没数据就输出静音（照 chiaki / Veyra 的做法）。

        参考实现都不做「保持上一个样本」「攒够再播」这类缓冲策略：
        chiaki 把每一帧立刻交给 haptics sink，Veyra 原样塞进 SDL 音频流，
        没有数据时 SDL 自然输出静音。我们唯一保留的是一小段淡出（约 2ms），
        避免从满幅直接跳到 0 的咔哒声。
        """
        outdata.fill(0)
        with self._lock:
            if self._starved or not self._started:
                self._last_sample = None
                return
            filled = 0
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
                # 队列级别按「还没播出去的帧数」算：包含正在播的那块剩下的部分，
                # 否则一个 480 帧的块被弹出来就会让级别瞬间掉 480。
                self._queued_frames -= take
            if self._partial is not None and self._partial_offset >= len(self._partial):
                self._partial = None
                self._partial_offset = 0
            if filled < frames:
                self._underruns += 1
                self._starved = True
                tail = min(frames - filled, _FADE_FRAMES)
                if self._last_sample is not None and tail > 0:
                    ramp = np.linspace(1.0, 0.0, tail, dtype=np.float32)[:, None]
                    outdata[filled : filled + tail] = (
                        self._last_sample[None, :].astype(np.float32) * ramp
                    ).astype(np.int16)
                self._last_sample = None
            elif filled > 0:
                self._last_sample = outdata[filled - 1].copy()
            if self._queued_frames < 0:
                self._queued_frames = 0

    def stats(self) -> tuple[int, int, int, int]:
        """诊断用：(欠载次数, 当前队列帧数, 欠载恢复次数, 播放速率修正是千分之几)。

        「欠载」= 回调要数据时队列空了（参考实现里就是输出静音）；
        「恢复」= 欠载后又有数据继续播。速率修正恒为 0——参考实现不做速率补偿。
        """
        with self._lock:
            return (
                self._underruns,
                self._queued_frames,
                self._refills,
                int(round((self._ratio_scale - 1.0) * 1000)),
            )

    def target_frames(self) -> int:
        """队列上限（帧）：日志里对照「当前队列 / 上限」，判断有没有堆积。"""
        with self._lock:
            return self._max_frames

    def _to_block(self, stereo: np.ndarray, rate: int) -> np.ndarray:
        """3kHz 立体声 → 设备率四声道（声道 3/4 装触觉，1/2 静音）。

        跨包连续插值：每包单独插值会在块尾被 np.interp 夹住（最后一个样本被重复
        十几次）再接下一包的跳变，10ms 一次的台阶听起来就是「细碎抽动」。
        这里用「下一个设备样本对应的源位置」当浮点游标（`_next_out_src`），
        每包从游标开始按固定速率往前走，块尾那不到一个源样本的区间留给下一包，
        接缝处天然连续（速率固定 = 参考实现的做法）。
        """
        frames = len(stereo)
        if rate == _SOURCE_RATE:
            block = np.zeros((frames, _OUTPUT_CHANNELS), dtype=np.int16)
            block[:, 2:4] = stereo
            self._last_source = None
            self._src_total += frames
            self._next_out_src = float(self._src_total)
            return block
        source = stereo.astype(np.float32)
        ratio = rate / _SOURCE_RATE
        p0 = self._src_total
        start = 1 if self._last_source is not None else 0
        padded = (
            np.vstack([self._last_source[None, :], source]) if start else source
        )
        self._last_source = source[-1].copy()
        self._src_total += frames
        end_src = float(p0 + max(0, frames - 1))
        remaining = end_src - self._next_out_src
        if remaining <= 0 or ratio <= 0:
            if remaining < 0:
                self._next_out_src = end_src
            return np.zeros((1, _OUTPUT_CHANNELS), dtype=np.int16)
        count = int(math.ceil(remaining * ratio))
        indexes = np.arange(len(padded), dtype=np.float64)
        positions = (
            self._next_out_src - p0 + start
            + np.arange(count, dtype=np.float64) / ratio
        )
        block = np.zeros((count, _OUTPUT_CHANNELS), dtype=np.int16)
        for channel in range(2):
            values = np.interp(positions, indexes, padded[:, channel])
            block[:, 2 + channel] = np.clip(values, -32768, 32767).astype(np.int16)
        self._next_out_src += count / ratio
        return block

    def feed(self, pcm: bytes) -> None:
        """pcm：3kHz 立体声 s16 交错；送到 3/4 声道，1/2 保持静音。

        照 Veyra：来了就排队（不预缓冲、不调速率），队列超过 100ms 就整段清空。
        """
        if not pcm:
            return
        # 参考实现的输入校验先做，避免为一个坏包去打开设备
        if len(pcm) % 4 or len(pcm) > _MAX_PACKET_BYTES:
            return
        frames = len(pcm) // 4
        if not frames:
            return
        if not self.ensure():
            return
        stereo = np.frombuffer(pcm[: frames * 4], dtype=np.int16).reshape(-1, 2)
        with self._lock:
            rate = self._stream_rate
        if rate <= 0:
            return
        block = self._to_block(stereo, rate)
        with self._lock:
            max_frames = self._max_frames
            # 参考实现的规则：缓冲一旦超过上限就整段清空，重新开始
            if self._queued_frames + len(block) > max_frames:
                self._pending.clear()
                self._partial = None
                self._partial_offset = 0
                self._queued_frames = 0
            if len(block) > max_frames:
                block = block[-max_frames:]
            self._pending.append(block)
            self._queued_frames += len(block)
            stream = self._stream
            need_start = (
                not self._started
                and stream is not None
                and self._queued_frames >= self._prebuffer_frames
            )
            if need_start:
                # 攒够一小段再起播（等价于 SDL 音频流的抖动缓冲）：主机送包是突发的，
                # 完全没有余量时每一串包之间都会欠载，听感就是不断抽动。
                self._started = True
                self._starved = False
            elif self._starved and self._queued_frames >= self._prebuffer_frames:
                # 欠载后先攒回同样多的缓冲再继续播，避免"来一包播一包"的连续抖动
                self._starved = False
                self._refills += 1
        if need_start:
            try:
                stream.start()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("启动触觉流失败：%s", exc)

    def close(self) -> None:
        with self._lock:
            has_stream = self._stream is not None
        # 只有真的要关 PortAudio 流时才需要 COM；键鼠玩法下 close() 会被反复调用，
        # 没打开过就别白初始化一次 COM。
        if has_stream:
            _ensure_com_initialized()
        with self._lock:
            stream, self._stream = self._stream, None
            self._stream_rate = 0
            self._pending.clear()
            self._partial = None
            self._partial_offset = 0
            self._queued_frames = 0
            self._last_source = None
            self._src_total = 0
            self._next_out_src = 0.0
            self._started = False
            self._starved = False
            self._max_frames = 0
            self._ratio_scale = 1.0
            self._last_sample = None
            self._underruns = 0
            self._refills = 0
            self._retry_at = 0.0
            self._retry_delay = _RETRY_SECONDS
            self._missing_logged = False
            self._open_failed_logged = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass


def test_tone_chunks(
    seconds: float = 0.6, frequency: float = 60.0, amplitude: int = 6000
) -> list[bytes]:
    """生成一段 3kHz 立体声正弦，切成 30ms 的小包（试震动用）。

    一次送完整段会超过队列上限被清空，所以要由调用方按 30ms 节奏逐包喂。
    """
    total = int(_SOURCE_RATE * max(0.03, min(2.0, float(seconds))))
    chunk = max(1, _SOURCE_RATE * 30 // 1000)
    phase = 2.0 * np.pi * float(frequency) / _SOURCE_RATE
    wave = (np.sin(np.arange(total, dtype=np.float64) * phase) * amplitude).astype(
        np.int16
    )
    stereo = np.stack([wave, wave], axis=1)
    return [
        np.ascontiguousarray(stereo[start : start + chunk]).tobytes()
        for start in range(0, total, chunk)
    ]


def describe_environment() -> str:
    """启动时记一行触觉输出能力，用来区分「没插线」和「依赖缺失」。"""
    try:
        import sounddevice  # noqa: F401 - 只探测可用性
    except Exception as exc:  # noqa: BLE001
        return f"sounddevice 不可用（{exc}），USB 震动无法输出"
    found = UsbHaptics.find_device()
    if found is None:
        return "sounddevice 可用，当前没有 DualSense 四声道音频端点（插 USB 线后出现）"
    _index, device, api_name = found
    return f"sounddevice 可用，端点 {device.get('name')}（{api_name}）"
