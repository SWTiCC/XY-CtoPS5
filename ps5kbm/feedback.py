"""Remote Play 主机下发的反馈数据解析（Takion data 消息里的 RUMBLE / TRIGGER_EFFECTS）。

协议来自 chiaki-ng（lib/src/takion.c、streamconnection.c）：
- Takion DATA 负载：[seq(4)][channel(2)][zero(2)][data_type(1)][data...]
- data_type = 7（RUMBLE）：data = [unknown, left(0-255), right(0-255)]
- data_type = 11（TRIGGER_EFFECTS）：data 至少 25 字节，
  [1] = 左扳机效果类型，[2] = 右扳机效果类型，
  左参数 10 字节在 [5:15]，右参数 10 字节在 [15:25]。

这里只做纯解析，不碰网络和手柄，方便单测。
"""

from __future__ import annotations

DATA_TYPE_PROTOBUF = 0
DATA_TYPE_RUMBLE = 7
DATA_TYPE_PAD_INFO = 9
DATA_TYPE_TRIGGER_EFFECTS = 11


def parse_pad_info(data: bytes) -> dict | None:
    """手柄信息（data_type 9）→ 灯条颜色 / 强度。

    chiaki-ng 的 stream_connection_takion_data_pad_info 有两种长度：
    - 0x19（25 字节）：[9:12] = 灯条 RGB，[12] = 运动重置，[20] 触觉强度，[21] 扳机强度
    - 0x11（17 字节）：[1:4] = 灯条 RGB，[4] = 运动重置，[12] 触觉强度，[13] 扳机强度
    """
    size = len(data)
    if size >= 0x19:
        led = bytes(data[9:12])
        haptic, trigger = data[20], data[21]
    elif size >= 0x11:
        led = bytes(data[1:4])
        haptic, trigger = data[12], data[13]
    else:
        return None
    return {
        "led": led,
        "haptic_intensity": haptic,
        "trigger_intensity": trigger,
    }


def audio_units(payload: bytes, dword2: int) -> tuple[bytes, int, int, int]:
    """从音频 AV 负载里取出**真实音频单元**，丢掉 FEC 校验单元。

    结构（chiaki-ng takion / audioreceiver 的字段，pyremoteplay 的 AVPacket 同源）：
    - dword2 低 16 位 = [unit_size(8)][fec_units(4)][src_units(4)]
    - (dword2 >> 0x10) & 0xFF 再加 1 = 这一帧的总单元数

    一个单元 = unit_size 字节。触觉流的 unit_size 是 120 字节
    （3kHz 立体声 s16 = 30 帧 = 10ms），也就是说 360 字节的包里只有前 120 字节
    是真实音频，后 240 字节是 FEC 奇偶校验——当音频播出去就是"抽动"声。

    返回 (真实音频, 总单元数, 源单元数, FEC 单元数)；字段不可信时原样返回。
    """
    total = ((dword2 >> 0x10) & 0xFF) + 1
    src = dword2 & 0x0F
    fec = (dword2 >> 4) & 0x0F
    unit = (dword2 & 0xFFFF) >> 8
    if src <= 0 or total <= 1 or unit <= 0 or unit * total > len(payload):
        return payload, total, src, fec
    return payload[: unit * src], total, src, fec


def data_type_of(chunk_payload: bytes) -> int:
    """从 Takion DATA 块负载里取 data_type；长度不够按 protobuf 处理。"""
    if len(chunk_payload) < 9:
        return DATA_TYPE_PROTOBUF
    return chunk_payload[8]


def payload_of(chunk_payload: bytes) -> bytes:
    """取 DATA 块负载里真正的数据部分（跳过 9 字节头）。"""
    return bytes(chunk_payload[9:]) if len(chunk_payload) > 9 else b""


def parse_rumble(data: bytes) -> tuple[float, float] | None:
    """震动数据 → (左马达, 右马达)，0.0~1.0；数据太短返回 None。"""
    if len(data) < 3:
        return None
    return (
        min(1.0, data[1] / 255.0),
        min(1.0, data[2] / 255.0),
    )


def parse_trigger_effects(data: bytes) -> tuple[bytes, bytes] | None:
    """扳机效果 → (左效果块 11 字节, 右效果块 11 字节)；数据太短返回 None。"""
    if len(data) < 25:
        return None
    left = bytes([data[1]]) + bytes(data[5:15])
    right = bytes([data[2]]) + bytes(data[15:25])
    return left, right
