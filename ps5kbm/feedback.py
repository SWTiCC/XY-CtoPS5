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
