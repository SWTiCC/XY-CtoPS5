"""探测已配对主机是否在当前局域网（只读身份，不建立会话）。

官方能力优先：复用 `playdirector.ConsoleController.status()`。它已经处理好
三件麻烦事，不需要在这里重写 DDP 协议：

1. 先向 `credentials["device_ip"]` 请求主机状态（DDP 只读，不占用会话）；
2. 状态不通时用 `scan()` 广播扫描局域网，按 `host-id` 找回同一台主机
   （PS5 换了 IP 的常见情形），并验证身份后再采用新地址；
3. 顺手把凭据迁移成新格式 / 新 IP（`controller.credentials`）。

整个过程不创建 Remote Play 会话，所以不会和"正式连接"抢 PS5 唯一的那条会话。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ._deps import ensure_vendor_path

ensure_vendor_path()

from playdirector import ConsoleController  # noqa: E402

# ConsoleController.status() 最坏耗时约 5（读状态）+ 3（扫描）+ 5（验证）秒，
# 留一点余量；超时按"检测出错"处理，界面可以重试。
DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class ProbeResult:
    """一次探测的结论。

    online=True 时 host_ip 是当前可用地址（可能已由扫描找回），
    credentials 是迁移后的凭据副本；online=False 且 error 为空表示"没找到
    主机"，error 非空表示"检测本身出了问题"。
    """

    online: bool
    host_id: str = ""
    host_ip: str = ""
    host_name: str = ""
    device_type: str = ""
    ip_changed: bool = False
    credentials: dict = field(default_factory=dict)
    error: str = ""


def _default_controller_factory(credentials: dict) -> ConsoleController:
    # idle_seconds=0：探测只读状态，不需要空闲自动断线
    return ConsoleController(credentials, idle_seconds=0)


async def _quiet_close(controller) -> None:
    """释放探测用的底层连接；收尾失败不影响已经得出的结论。"""
    try:
        await asyncio.wait_for(controller.close(), 5)
    except Exception:  # noqa: BLE001 - 清理失败无需上报
        pass


async def probe_console(
    credentials: dict,
    timeout: float = DEFAULT_TIMEOUT,
    controller_factory=None,
) -> ProbeResult:
    """检查已配对主机是否在线。

    `controller_factory` 仅供测试注入假 controller，正常调用不传。
    """
    payload = dict(credentials or {})
    previous_ip = str(payload.get("device_ip") or "")
    factory = controller_factory or _default_controller_factory
    controller = None
    try:
        controller = factory(payload)
        status = await asyncio.wait_for(controller.status(), timeout)
        if not status:
            return ProbeResult(online=False, host_ip=previous_ip)
        host_ip = str(getattr(controller, "host", "") or previous_ip)
        return ProbeResult(
            online=True,
            host_id=str(status.get("host-id") or ""),
            host_ip=host_ip,
            host_name=str(status.get("host-name") or ""),
            device_type=str(status.get("host-type") or ""),
            ip_changed=host_ip != previous_ip,
            credentials=dict(getattr(controller, "credentials", {}) or {}),
        )
    except asyncio.TimeoutError:
        return ProbeResult(online=False, host_ip=previous_ip, error="检测超时")
    except Exception as exc:  # noqa: BLE001 - 探测失败要让界面拿到原因而不是崩掉
        return ProbeResult(
            online=False,
            host_ip=previous_ip,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if controller is not None:
            await _quiet_close(controller)
