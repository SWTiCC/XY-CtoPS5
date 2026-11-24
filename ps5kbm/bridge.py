"""PS5 连接与输入发送层。

职责边界：
- 配对（一次）：把 PSN Account ID + PS5 屏幕上的 8 位 PIN 换成注册凭据；
- 会话：用 playdirector 的 ConsoleController 建立 Remote Play 会话，
  只开输入通道（receiver=None），不接收视频；
- 发送：直接操作底层 pyremoteplay Controller，模拟 DualShock 4。

协议实现来自 pyremoteplay / playdirector（GPL-3.0），本文件只做适配。
"""

from __future__ import annotations

import array
import logging
import queue
import threading
import time
from typing import Iterable

from ._deps import ensure_vendor_path
# 源码运行时，项目内的 netifaces 兼容层必须先于 pyremoteplay 进入 sys.path；
# 打包成 exe 后 netifaces 已作为模块内置，不需要也不该改 sys.path。
ensure_vendor_path()

from playdirector import ConsoleController, ConsoleError, pair_console, scan  # noqa: E402
from pyremoteplay.stream_packets import ControllerState  # noqa: E402

from .config import save_credentials  # noqa: E402
from . import feedback  # noqa: E402

_LOGGER = logging.getLogger(__name__)

# 扳机模拟量（L2/R2 按压程度 0.0~1.0）。
# pyremoteplay 的 FeedbackState 只打包四个摇杆轴，没有扳机字节，
# 这里在反馈包里补上（chiaki 协议里扳机紧跟摇杆之后）。
_TRIGGER_L2 = 0.0
_TRIGGER_R2 = 0.0


def set_trigger_value(name: str, value: float) -> None:
    """设置扳机深度（name 为 l2/r2），供打包补丁读取。"""
    global _TRIGGER_L2, _TRIGGER_R2
    clamped = max(0.0, min(1.0, float(value)))
    if (name or "").lower() == "r2":
        _TRIGGER_R2 = clamped
    else:
        _TRIGGER_L2 = clamped


def get_trigger_value(name: str) -> float:
    return _TRIGGER_R2 if (name or "").lower() == "r2" else _TRIGGER_L2


def _patch_trigger_bytes() -> None:
    """（已停用）状态包里的扳机字节补丁。

    查 chiaki 源码确认：v12 格式里 0x19/0x1a/0x1b 是固定 0/0/1，
    压根不放扳机深度，这条路从一开始就是错的。真正的扳机深度走
    analog button 事件（见 _patch_event_depth）。
    """
    return


def _patch_event_depth() -> None:
    """让 FeedbackEvent 能携带 0~255 的模拟量深度。

    chiaki 协议里 analog button（L2=0x86 / R2=0x87）的事件第三个字节是
    压感深度（0~255）。pyremoteplay 把 state 写死成 0xFF/0x00，只能全按
    或全松。这里加一个可选覆盖值，不设置时保持原行为。
    """
    try:
        from pyremoteplay.stream_packets import FeedbackEvent

        if getattr(FeedbackEvent, "_ps5kbm_depth_patched", False):
            return

        def state(self) -> int:
            depth = getattr(self, "_depth_override", None)
            if depth is not None:
                return int(max(0, min(255, depth)))
            return 0xFF if self.is_active else 0x00

        FeedbackEvent.state = property(state)
        FeedbackEvent._ps5kbm_depth_patched = True
        _LOGGER.info("已启用扳机模拟量事件（0x86/0x87 深度）")
    except Exception as exc:  # noqa: BLE001 - 补丁失败不影响基本输入
        _LOGGER.warning("扳机事件补丁失败：%s", exc)


_patch_trigger_bytes()
_patch_event_depth()


def _patch_overflowing_packets() -> None:
    """修补 pyremoteplay 的 16 位计数溢出。

    1. FeedbackHeader.sequence：每个反馈包 +1，格式 '!BHxII' 里的 H 只有
       16 位，连发几分钟就超过 65535，抛
           struct.error: 'H' format requires 0 <= number <= 65535
       协议里该字段本来就是 16 位，按回绕处理。
    2. CongestionPacket.received/lost 同理。
    """
    try:
        from pyremoteplay import stream_packets

        header_cls = stream_packets.FeedbackHeader
        if not getattr(header_cls, "_ps5kbm_patched", False):
            original_header_pack = header_cls.pack

            def safe_header_pack(self, buf):
                self.sequence &= 0xFFFF
                return original_header_pack(self, buf)

            header_cls.pack = safe_header_pack
            header_cls._ps5kbm_patched = True
            _LOGGER.info("已修补 FeedbackHeader.sequence 的 16 位溢出")

        packet_cls = stream_packets.CongestionPacket
        if not getattr(packet_cls, "_ps5kbm_patched", False):
            original_pack = packet_cls.pack

            def safe_pack(self, buf):
                self.received &= 0xFFFF
                self.lost &= 0xFFFF
                return original_pack(self, buf)

            packet_cls.pack = safe_pack
            packet_cls._ps5kbm_patched = True
            _LOGGER.info("已修补 CongestionPacket 的 16 位计数溢出")
    except Exception as exc:  # noqa: BLE001 - 修补失败不应阻止连接
        _LOGGER.warning("修补 16 位计数失败：%s", exc)


_patch_overflowing_packets()


# ---------------------------------------------------------------- 抓包诊断
# Remote Play 里主机下发的震动 / 自适应扳机数据走哪条通道还没确认：
# Takion protobuf 的负载类型里没有专门的震动/扳机类型，AV 包头类型里倒是定义了
# RUMBLE_EVENT(0x07) / PAD_EVENT(0x09)，但 pyremoteplay 没有处理它们。
# 这里在「抓包诊断」开关打开时记录：未处理的 protobuf 负载类型、SERVERMESSAGE 载荷、
# 以及非 AV 的原始包（限制每个类型前 20 条，避免刷爆日志）。
# 验证完成后可以把这段整体删掉，或者按结果改成真正的震动/扳机转发。
_DIAGNOSTICS = {"enabled": False, "counts": {}}


def set_diagnostics(enabled: bool) -> None:
    """打开/关闭抓包诊断（排查震动、扳机效果数据）。"""
    _DIAGNOSTICS["enabled"] = bool(enabled)
    if enabled:
        _LOGGER.info("抓包诊断已开启：会记录远端负载类型与非 AV 包")
    else:
        _LOGGER.info("抓包诊断已关闭")


def _install_diagnostics() -> None:
    try:
        from pyremoteplay import protobuf as _pb
        from pyremoteplay import stream as _rp_stream
        from pyremoteplay.stream_packets import Packet as _Packet
    except Exception as exc:  # noqa: BLE001 - 诊断装不上不影响主流程
        _LOGGER.debug("诊断补丁安装失败：%s", exc)
        return
    if getattr(_pb.ProtoHandler, "_ps5kbm_diag", False):
        return
    original_handle = _pb.ProtoHandler.handle
    original_stream_handle = _rp_stream.RPStream.handle

    def handle(self, data):
        if _DIAGNOSTICS["enabled"]:
            try:
                msg = _pb.TakionMessage()
                msg.ParseFromString(data)
                name = _pb.ProtoHandler.get_payload_type(msg)
                counts = _DIAGNOSTICS["counts"]
                key = f"pb:{name}"
                counts[key] = counts.get(key, 0) + 1
                if counts[key] <= 20:
                    _LOGGER.info("【诊断】远端负载 %s（第 %d 次）", name, counts[key])
                if name == "SERVERMESSAGE":
                    payload = bytes(msg.server_message_payload.payload)
                    _LOGGER.info("【诊断】SERVERMESSAGE 载荷 %s", payload[:64].hex())
            except Exception:  # noqa: BLE001 - 诊断解析失败不影响正常处理
                pass
        return original_handle(self, data)

    def stream_handle(self, msg):
        if _DIAGNOSTICS["enabled"] and msg:
            try:
                if not _Packet.is_av(msg[:1]):
                    counts = _DIAGNOSTICS["counts"]
                    key = f"raw:{msg[0]:02X}:{len(msg)}"
                    counts[key] = counts.get(key, 0) + 1
                    if counts[key] <= 20:
                        _LOGGER.info(
                            "【诊断】非 AV 包 type=0x%02X len=%d %s",
                            msg[0],
                            len(msg),
                            msg[:48].hex(),
                        )
            except Exception:  # noqa: BLE001
                pass
        return original_stream_handle(self, msg)

    _pb.ProtoHandler.handle = handle
    _pb.ProtoHandler._ps5kbm_diag = True  # type: ignore[attr-defined]
    _rp_stream.RPStream.handle = stream_handle
    _rp_stream.RPStream._ps5kbm_diag = True  # type: ignore[attr-defined]


_install_diagnostics()


# ---------------------------------------------------------------- 主机反馈
# 主机下发震动 / 自适应扳机走 Takion DATA 块的 data_type（7=震动，11=扳机效果）。
# pyremoteplay 解析这块时会丢掉 data_type，这里补一层，把数据分出来。
_audio_flag_file = None
_audio_flag_count = 0


def _capture_audio_flag(msg: bytes, header_end: int) -> None:
    """记录每个音频包的长度和 haptics 标记字节（上限 3000 条）。"""
    global _audio_flag_file, _audio_flag_count
    if _audio_flag_count >= 3000:
        return
    try:
        import json
        import os

        if _audio_flag_file is None:
            path = os.path.join(os.getcwd(), "tests", "_tmp", "audio_flags.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _audio_flag_file = open(path, "w", encoding="utf-8")
        _audio_flag_file.write(
            json.dumps(
                {"t": round(time.time(), 4), "len": len(msg), "flag": msg[header_end]},
                ensure_ascii=False,
            )
            + "\n"
        )
        _audio_flag_file.flush()
        _audio_flag_count += 1
    except Exception:  # noqa: BLE001
        pass


def _capture_haptics_packet(pcm: bytes) -> None:
    """把触觉包（解密后）写成 jsonl，用于离线分析包节奏。"""
    global _haptics_capture_file, _haptics_capture_count
    if _haptics_capture_count >= _haptics_capture_limit:
        return
    try:
        import json
        import os

        if _haptics_capture_file is None:
            path = os.path.join(os.getcwd(), "tests", "_tmp", "haptics_capture.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _haptics_capture_file = open(path, "w", encoding="utf-8")
            _LOGGER.info("触觉抓包开始：%s", path)
        _haptics_capture_file.write(
            json.dumps(
                {"t": round(time.time(), 4), "len": len(pcm), "hex": pcm.hex()},
                ensure_ascii=False,
            )
            + "\n"
        )
        _haptics_capture_file.flush()
        _haptics_capture_count += 1
    except Exception:  # noqa: BLE001 - 抓包失败不影响主流程
        pass


_feedback_handlers = {"rumble": None, "trigger": None, "haptics": None}
_haptics_pcm_callback = None
_haptics_capture_file = None
_haptics_capture_count = 0
_haptics_capture_limit = 2000
# 调试用：抓包落盘（发布版关闭）
_HAPTICS_DEBUG = False
_feedback_counts = {"rumble": 0, "trigger": 0}
_data_type_counts: dict[int, int] = {}


def set_feedback_handlers(rumble_cb, trigger_cb, haptics_cb=None) -> None:
    """注册主机反馈回调。

    rumble_cb(left: float, right: float)：0~1；
    trigger_cb(left_block: bytes, right_block: bytes)：各 11 字节（效果类型 + 10 参数）。
    """
    _feedback_handlers["rumble"] = rumble_cb
    _feedback_handlers["trigger"] = trigger_cb
    _feedback_handlers["haptics"] = haptics_cb


def _dispatch_feedback(kind: str, body: bytes) -> None:
    counts = _feedback_counts
    counts[kind] = counts.get(kind, 0) + 1
    if counts[kind] == 1:
        _LOGGER.info("收到主机下发的反馈：%s", kind)
    if _DIAGNOSTICS["enabled"] and counts[kind] <= 30:
        _LOGGER.info("【诊断】主机下发 %s：%s", kind, body[:32].hex())
    if kind == "rumble":
        parsed = feedback.parse_rumble(body)
        handler = _feedback_handlers["rumble"]
        if parsed and handler:
            try:
                handler(*parsed)
            except Exception:  # noqa: BLE001 - 反馈失败不影响输入
                pass
    elif kind == "haptics":
        # 触觉音频：body = [0, 左强度, 右强度]（0~255）
        if len(body) >= 3:
            handler = _feedback_handlers["haptics"]
            if handler:
                try:
                    handler(body[1] / 255.0, body[2] / 255.0)
                except Exception:  # noqa: BLE001
                    pass
    elif kind == "trigger":
        parsed = feedback.parse_trigger_effects(body)
        handler = _feedback_handlers["trigger"]
        if parsed and handler:
            try:
                handler(*parsed)
            except Exception:  # noqa: BLE001
                pass


def _patch_takion_feedback() -> None:
    try:
        from pyremoteplay.stream_packets import Chunk
    except Exception as exc:  # noqa: BLE001 - 补丁装不上不影响主流程
        _LOGGER.debug("反馈补丁安装失败：%s", exc)
        return
    # 注意：Packet.parse 走的是 Chunk.PAYLOADS[0x00]（类创建时就捕获了 data 函数），
    # 直接替换 Chunk.data 不会生效，必须替换这个字典项。
    original = Chunk.PAYLOADS.get(0x00)
    if original is None or getattr(original, "_ps5kbm_feedback", False):
        return

    def data(parse=False, **kwargs):
        if parse:
            params = kwargs.get("params") or {}
            payload = params.get("payload")
            if payload is not None and len(payload) > 9:
                data_type = payload[8]
                if data_type == feedback.DATA_TYPE_RUMBLE:
                    _dispatch_feedback("rumble", bytes(payload[9:]))
                elif data_type == feedback.DATA_TYPE_TRIGGER_EFFECTS:
                    _dispatch_feedback("trigger", bytes(payload[9:]))
                elif data_type != feedback.DATA_TYPE_PROTOBUF:
                    # 其它类型（比如 pad info）：先记录下来，方便后续接入
                    if _DIAGNOSTICS["enabled"]:
                        counts = _data_type_counts
                        counts[data_type] = counts.get(data_type, 0) + 1
                        if counts[data_type] <= 5:
                            _LOGGER.info(
                                "【诊断】主机下发 data_type=%d：%s",
                                data_type,
                                bytes(payload[9:])[:32].hex(),
                            )
        return original(parse=parse, **kwargs)

    data._ps5kbm_feedback = True  # type: ignore[attr-defined]
    Chunk.PAYLOADS[0x00] = data


_patch_takion_feedback()


def _patch_haptics_audio() -> None:
    """解析主机的触觉音频流（DualSense 的震动走这里）。

    按 chiaki 的 v12 AV 头解析：音频头 0x13 字节（+可选 3 字节 NALU 信息），
    紧随其后的字节是 haptics 标记（0x02），再往后才是 PCM 数据。
    pyremoteplay 没有 receiver 时会直接丢掉 AV 包，这里在流入口自己解一份。
    """
    try:
        from pyremoteplay.stream import RPStream
        from pyremoteplay.stream_packets import TYPE_PS5
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("触觉音频补丁安装失败：%s", exc)
        return
    if getattr(RPStream, "_ps5kbm_haptics_patched", False):
        return
    original = RPStream.handle

    def handle(self, msg):
        try:
            if msg and (msg[0] & 0x0F) == 3:  # AUDIO
                cipher = getattr(self, "_cipher", None) or getattr(
                    getattr(self, "_av_handler", None), "_cipher", None
                )
                session = getattr(self, "_session", None)
                host_type = getattr(session, "type", TYPE_PS5) or TYPE_PS5
                if cipher is not None and host_type == TYPE_PS5 and len(msg) > 24:
                    # chiaki 的 v12 音频头：base(1) + 0x11 + 1 = 19；
                    # 有 NALU 信息结构时再 +3。之前这里多算了 1 字节，
                    # 读到的“标记”其实是音频数据，触觉包几乎全被漏掉。
                    header_end = 1 + 0x11 + 1
                    # NALU 标志在 base type 字节（msg[0]）的高 4 位，不是 msg[1]
                    if (msg[0] >> 4) & 1:
                        header_end += 3
                    if _HAPTICS_DEBUG:
                        _capture_audio_flag(msg, header_end)
                    if msg[header_end] == 0x02:  # haptics 包（chiaki 定义）
                        key_pos = int.from_bytes(msg[14:18], "big")
                        pcm = cipher.decrypt(bytes(msg[header_end + 1 :]), key_pos)
                        if _HAPTICS_DEBUG:
                            _capture_haptics_packet(pcm)
                        # 只在收包线程排队，解码放独立线程，绝不拖慢输入
                        _ensure_haptics_worker()
                        try:
                            _haptics_queue.put_nowait(pcm)
                        except queue.Full:
                            pass
        except Exception:  # noqa: BLE001 - 触觉解析失败不影响主流程
            pass
        return original(self, msg)

    RPStream.handle = handle
    RPStream._ps5kbm_haptics_patched = True  # type: ignore[attr-defined]


_haptics_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=64)
_haptics_thread = None


def reset_haptics() -> None:
    """新会话开始时清掉解码器状态和积压包。"""
    global _opus_decoder, _opus_errors, _haptics_capture_file, _haptics_capture_count
    _opus_decoder = None
    _opus_errors = 0
    try:
        while True:
            _haptics_queue.get_nowait()
    except queue.Empty:
        pass
    if _haptics_capture_file is not None:
        try:
            _haptics_capture_file.close()
        except Exception:  # noqa: BLE001
            pass
    _haptics_capture_file = None
    _haptics_capture_count = 0


def set_haptics_pcm_handler(callback) -> None:
    """注册触觉 PCM 回调（只在 USB 连接时由 app 转发到 DualSense 音频端点）。"""
    global _haptics_pcm_callback
    _haptics_pcm_callback = callback


def _ensure_haptics_worker() -> None:
    """启动触觉解码线程（只启动一次）。"""
    global _haptics_thread
    if _haptics_thread is not None:
        return
    _haptics_thread = threading.Thread(
        target=_haptics_worker, name="haptics-decode", daemon=True
    )
    _haptics_thread.start()


def _haptics_worker() -> None:
    """解码触觉包 → PCM，交给 app 写到 DualSense 音频端点。"""
    while True:
        data = _haptics_queue.get()
        try:
            pcm = _decode_haptics(data)
        except Exception:  # noqa: BLE001 - 单包失败不影响后续
            pcm = None
        if pcm:
            callback = _haptics_pcm_callback
            if callback:
                try:
                    callback(pcm)
                except Exception:  # noqa: BLE001
                    pass


_opus_decoder = None
_opus_frames_logged = 0
_opus_errors = 0


def _decode_haptics(data: bytes) -> bytes | None:
    """Opus 解码触觉包，返回 48k 立体声 s16 交错 PCM；失败返回 None。"""
    global _opus_decoder, _opus_frames_logged, _opus_errors
    try:
        import av
    except Exception as exc:  # noqa: BLE001
        _opus_errors += 1
        if _opus_errors <= 3:
            _LOGGER.warning("触觉音频解码不可用（缺少 av）：%s", exc)
        return None
    try:
        if _opus_decoder is None:
            _opus_decoder = av.CodecContext.create("opus", "r")
        frames = _opus_decoder.decode(av.Packet(data))
    except Exception as exc:  # noqa: BLE001
        _opus_errors += 1
        if _opus_errors <= 3:
            _LOGGER.warning("触觉音频解码失败：%s", exc)
        return None
    if not frames:
        return None
    if _opus_frames_logged < 3:
        frame = frames[0]
        _opus_frames_logged += 1
        _LOGGER.debug(
            "触觉音频解码成功：format=%s rate=%s channels=%s samples=%s",
            frame.format.name,
            frame.sample_rate,
            frame.layout.name,
            frame.samples,
        )
    chunks = [_frame_to_stereo_s16(frame) for frame in frames]
    pcm = b"".join(chunk for chunk in chunks if chunk)
    return pcm or None


def _frame_to_stereo_s16(frame) -> bytes:
    """把一帧音频转成 48k 立体声 s16 交错字节。"""
    import array
    import struct

    name = frame.format.name
    try:
        planes = [bytes(plane) for plane in frame.planes]
    except Exception:  # noqa: BLE001
        return b""
    if name.startswith("flt") or name.startswith("dbl"):
        fmt = "f" if name.startswith("flt") else "d"
        size = 4 if fmt == "f" else 8
        def read(raw):
            usable = len(raw) - (len(raw) % size)
            return [value * 32767 for value in struct.unpack(f"<{usable // size}{fmt}", raw[:usable])]
    elif name.startswith("s16") or name in ("s16", "s16p"):
        def read(raw):
            usable = len(raw) - (len(raw) % 2)
            return list(array.array("h", raw[:usable]))
    else:
        return b""
    if name.endswith("p") and len(planes) >= 2:
        left = read(planes[0])
        right = read(planes[1])
    elif name.endswith("p"):
        left = right = read(planes[0])
    else:
        values = read(planes[0])
        left = values[0::2]
        right = values[1::2]
    count = min(len(left), len(right))
    output = array.array("h", bytes(count * 4))
    for index in range(count):
        output[2 * index] = max(-32768, min(32767, int(left[index])))
        output[2 * index + 1] = max(-32768, min(32767, int(right[index])))
    return output.tobytes()


# 触觉音频解析（开关由配置 controller.haptics_rumble 控制，默认关）
ENABLE_HAPTICS_AUDIO = True
if ENABLE_HAPTICS_AUDIO:
    _patch_haptics_audio()


def configure_logging(verbose: bool = False) -> None:
    """统一日志格式；pyremoteplay 内部日志在非 verbose 时压到 WARNING。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not verbose:
        logging.getLogger("pyremoteplay").setLevel(logging.WARNING)
        logging.getLogger("playdirector").setLevel(logging.WARNING)


async def discover(timeout: float = 3.0) -> list[dict]:
    """扫描局域网内的 PS4/PS5。"""
    return await scan(timeout=timeout)


async def pair(host: str, account_id: str, pin: str, out_path: str) -> dict:
    """配对主机并保存凭据，返回凭据字典。"""
    credentials = await pair_console(host, account_id, pin)
    # 记录用户输入的原始 account id，便于换网络/换 PIN 时重新配对
    credentials["account_id_input"] = str(account_id)
    save_credentials(out_path, credentials)
    _LOGGER.info("配对成功，凭据已保存：%s", out_path)
    return credentials


async def wake(credentials: dict) -> None:
    """通过 DDP 唤醒待机中的主机（不建立 Remote Play 会话）。

    主机需要开启「远程游玩」，并在待机时保持网络连接，否则唤醒不了。
    """
    controller = ConsoleController(credentials, idle_seconds=0)
    try:
        await controller.wake()
    finally:
        try:
            await controller.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响唤醒结果
            pass


class Ps5Bridge:
    """管理一条输入会话，对外只暴露"设摇杆/发按钮"。"""

    def __init__(self, credentials: dict):
        if not credentials.get("profiles"):
            raise ConsoleError("凭据缺少 profiles，请先执行 pair 配对")
        # idle_seconds=0 关闭空闲自动断线，避免看剧情时被踢
        self._console = ConsoleController(credentials, idle_seconds=0)
        self._controller = None
        self._sent = 0
        self._last_force = 0.0
        # 是否已向主机声明 DualSense 手柄类型（首次发输入时声明一次）
        self._dualsense_declared = False
        # R2 按下时使用的输出深度（滚轮/滑条设定）
        self._r2_depth = 1.0
        # L2 按下时使用的输出深度（键盘 -/= 或滑条设定）
        self._l2_depth = 1.0

    @property
    def sent_count(self) -> int:
        """已发送的摇杆状态包数量，用于确认发送链路是否真的在跑。"""
        return self._sent

    @property
    def host(self) -> str:
        return self._console.host

    @property
    def connected(self) -> bool:
        """会话是否仍然可用（断线后用来触发自动重连）。"""
        return self._console.connected

    async def connect(self) -> None:
        await self._console.ensure_session()
        self._controller = self._console.device.controller
        if not self._controller.ready:
            raise ConsoleError("Remote Play 会话未就绪")
        # 关键：停掉 pyremoteplay 内置的 controller 后台线程。
        # 它会从普通线程直接调用 asyncio transport.sendto，Windows Proactor
        # 不支持跨线程发送，会持续抛
        #   AttributeError: 'NoneType' object has no attribute 'append'
        # 导致所有输入发不出去而主循环仍在跑。改由我们的事件循环线程统一发送
        # （见 set_sticks 里的 update_sticks 调用）。
        reset_haptics()
        try:
            self._controller.stop()
        except Exception as exc:  # noqa: BLE001 - 停不掉也不该阻止连接
            _LOGGER.warning("停止 controller 后台线程失败：%s", exc)
        _LOGGER.info("已连接到 %s，输入通道就绪（发送统一走事件循环线程）", self.host)

    def _declare_dualsense(self) -> None:
        """向主机声明自己是 DualSense 手柄。

        chiaki 在建流后发 CONTROLLERCONNECTION（DUALSENSE=6）告诉主机手柄类型，
        主机才会下发自适应扳机 / 触觉反馈；pyremoteplay 没发这条消息。
        """
        try:
            from pyremoteplay.takion_pb2 import TakionMessage

            msg = TakionMessage()
            msg.type = TakionMessage.PayloadType.CONTROLLERCONNECTION
            msg.controller_connection_payload.connected = True
            try:
                msg.controller_connection_payload.controller_type = 6  # DUALSENSE
            except Exception:  # noqa: BLE001 - 老版 proto 没有这个枚举值时忽略
                pass
            data = msg.SerializeToString()
            self._controller.session.stream.send_data(data, 1, 1, proto=True)
            _LOGGER.info("已向主机声明手柄类型：DualSense")
        except Exception as exc:  # noqa: BLE001 - 声明失败不影响输入
            _LOGGER.warning("声明 DualSense 失败：%s", exc)

    async def status(self) -> dict:
        return await self._console.status()

    @property
    def alive(self) -> bool:
        """会话是否还活着；主机端断开 / 被踢后返回 False。"""
        controller = self._controller
        if controller is None:
            return False
        try:
            session = getattr(controller, "session", None)
            if session is None or getattr(session, "is_stopped", False):
                return False
            return bool(getattr(controller, "ready", False))
        except Exception:  # noqa: BLE001 - 判断失败就当活着，交给发送处兜底
            return True

    def set_sticks(
        self,
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> None:
        """更新两个摇杆并立即发送。

        必须在 asyncio 事件循环线程调用（app 的 tick 协程就在那里）。

        pyremoteplay 的 update_sticks 只在状态变化时发送，状态不变一包都不发，
        PS5 端会表现为“动一下就停”。所以要在状态长时间不变时也强制重发。
        但不能每帧都新建 ControllerState()——60Hz × 长时间运行会造成大量
        对象分配和 GC 压力（长时间使用后崩溃的嫌疑点之一）。改成 100ms
        强制一次，其余帧靠状态变化自然发送。
        """
        if not self.alive:
            return
        # 第一次真正发输入时声明 DualSense（这时流和加密都已就绪）；
        # 不声明的话主机按 DS4 对待，实测输入会失效。
        if not self._dualsense_declared:
            self._dualsense_declared = True
            self._declare_dualsense()
        self._controller.stick("left", point=_clamp_point(left))
        self._controller.stick("right", point=_clamp_point(right))
        now = time.monotonic()
        if now - self._last_force >= 0.1:
            self._last_force = now
            self._controller._last_state = ControllerState()  # noqa: SLF001
        self._controller.update_sticks()
        self._sent += 1

    def force_send_sticks(self) -> None:
        """强制发送一次当前摇杆/扳机状态（扳机深度变化时用）。"""
        if not self.alive:
            return
        self._controller._last_state = ControllerState()  # noqa: SLF001
        self._controller.update_sticks()
        self._sent += 1

    def set_trigger(self, name: str, value: float) -> None:
        """设置扳机深度（0~1）。

        走 analog button 事件（L2=0x86 / R2=0x87），第三个字节是 0~255
        的压感值——这是 chiaki 协议里的正确路径。
        """
        if not self.alive:
            return
        try:
            from pyremoteplay.stream_packets import FeedbackEvent

            button = (
                FeedbackEvent.Type.R2
                if (name or "").lower() == "r2"
                else FeedbackEvent.Type.L2
            )
            depth = int(round(max(0.0, min(1.0, float(value))) * 255))
            event = FeedbackEvent(button, is_active=depth > 0)
            event._depth_override = depth  # noqa: SLF001 - 补丁读取该字段
            self._controller._add_event_buffer(event)  # noqa: SLF001
            self._controller._send_event()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 - 发送失败不影响主流程
            _LOGGER.warning("发送扳机深度失败：%s", exc)

    def set_r2_depth(self, value: float) -> None:
        """设定 R2 按下时使用的输出深度（0~1）。"""
        self._r2_depth = max(0.0, min(1.0, float(value)))

    def set_l2_depth(self, value: float) -> None:
        """设定 L2 按下时使用的输出深度（0~1）。"""
        self._l2_depth = max(0.0, min(1.0, float(value)))

    def send_button(self, name: str, action: str) -> None:
        """发送按钮事件；L2/R2 用各自设定的深度输出，而不是固定满按。"""
        if not self.alive:
            return
        upper = (name or "").upper()
        if upper in ("L2", "R2"):
            depth = self._l2_depth if upper == "L2" else self._r2_depth
            if action == "release":
                self.set_trigger(upper.lower(), 0.0)
            else:
                self.set_trigger(upper.lower(), depth)
            return
        self._controller.button(name, action)

    def send_events(self, events: Iterable[tuple[str, str]]) -> None:
        for name, action in events:
            self.send_button(name, action)

    async def close(self) -> None:
        await self._console.close()
        self._controller = None


def _clamp_point(point: tuple[float, float]) -> tuple[float, float]:
    """摇杆值夹在 [-1, 1]，防止配置写错把协议包弄坏。"""
    x = max(-1.0, min(1.0, float(point[0])))
    y = max(-1.0, min(1.0, float(point[1])))
    return x, y
