"""PS5 连接与输入发送层。

职责边界：
- 配对（一次）：把 PSN Account ID + PS5 屏幕上的 8 位 PIN 换成注册凭据；
- 会话：用 playdirector 的 ConsoleController 建立 Remote Play 会话，
  只开输入通道（receiver=None），不接收视频；
- 发送：直接操作底层 pyremoteplay Controller，模拟 DualShock 4。

协议实现来自 pyremoteplay / playdirector（GPL-3.0），本文件只做适配。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Iterable

# 源码运行时，项目内的 netifaces 兼容层必须先于 pyremoteplay 进入 sys.path；
# 打包成 exe 后 netifaces 已作为模块内置，不需要也不该改 sys.path。
if not getattr(sys, "frozen", False):
    _VENDOR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"
    )
    if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
        sys.path.insert(0, _VENDOR)

from playdirector import ConsoleController, ConsoleError, pair_console, scan  # noqa: E402
from pyremoteplay.stream_packets import ControllerState  # noqa: E402

from .config import save_credentials  # noqa: E402

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
        try:
            self._controller.stop()
        except Exception as exc:  # noqa: BLE001 - 停不掉也不该阻止连接
            _LOGGER.warning("停止 controller 后台线程失败：%s", exc)
        _LOGGER.info("已连接到 %s，输入通道就绪（发送统一走事件循环线程）", self.host)

    async def status(self) -> dict:
        return await self._console.status()

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
        if self._controller is None:
            return
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
        if self._controller is None:
            return
        self._controller._last_state = ControllerState()  # noqa: SLF001
        self._controller.update_sticks()
        self._sent += 1

    def set_trigger(self, name: str, value: float) -> None:
        """设置扳机深度（0~1）。

        走 analog button 事件（L2=0x86 / R2=0x87），第三个字节是 0~255
        的压感值——这是 chiaki 协议里的正确路径。
        """
        if self._controller is None:
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
        if self._controller is None:
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
