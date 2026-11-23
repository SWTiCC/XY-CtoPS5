"""探测层单元测试：用假 controller 模拟在线 / 离线 / 换 IP / 超时，不联网。"""

from __future__ import annotations

import asyncio
import unittest

from ps5kbm import probe


class FakeController:
    """模拟 ConsoleController 里探测用到的三个成员：status / host / credentials / close。"""

    def __init__(
        self,
        status=None,
        host: str = "192.168.1.38",
        credentials: dict | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
    ):
        self.host = host
        self.credentials = credentials or {"device_ip": host}
        self._status = status
        self._error = error
        self._delay = delay
        self.closed = False

    async def status(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._status

    async def close(self):
        self.closed = True


def credentials(**overrides) -> dict:
    base = {"device_ip": "192.168.1.38", "host_id": "C0151BBD7687"}
    base.update(overrides)
    return base


class ProbeConsoleTests(unittest.TestCase):
    def test_online_reports_identity(self):
        controller = FakeController(
            status={
                "status-code": 200,
                "host-id": "C0151BBD7687",
                "host-name": "PS5Pro-Yi",
                "host-type": "PS5",
            }
        )
        result = asyncio.run(
            probe.probe_console(credentials(), controller_factory=lambda _: controller)
        )
        self.assertTrue(result.online)
        self.assertEqual(result.host_id, "C0151BBD7687")
        self.assertEqual(result.host_name, "PS5Pro-Yi")
        self.assertEqual(result.device_type, "PS5")
        self.assertEqual(result.host_ip, "192.168.1.38")
        self.assertFalse(result.ip_changed)
        self.assertEqual(result.error, "")
        self.assertTrue(controller.closed, "探测结束后应释放底层连接")

    def test_online_after_ip_change(self):
        # status() 内部通过扫描找回主机后会把 host 换成新地址
        controller = FakeController(
            status={"status-code": 200, "host-id": "C0151BBD7687", "host-name": "PS5Pro-Yi"},
            host="192.168.1.50",
            credentials={"device_ip": "192.168.1.50"},
        )
        result = asyncio.run(
            probe.probe_console(credentials(), controller_factory=lambda _: controller)
        )
        self.assertTrue(result.online)
        self.assertTrue(result.ip_changed)
        self.assertEqual(result.host_ip, "192.168.1.50")
        self.assertEqual(result.credentials["device_ip"], "192.168.1.50")

    def test_offline_when_status_empty(self):
        controller = FakeController(status={})
        result = asyncio.run(
            probe.probe_console(credentials(), controller_factory=lambda _: controller)
        )
        self.assertFalse(result.online)
        self.assertEqual(result.error, "", "空状态是离线，不是检测出错")
        self.assertEqual(result.host_ip, "192.168.1.38")
        self.assertTrue(controller.closed)

    def test_probe_error_is_reported(self):
        controller = FakeController(error=OSError("网络不可达"))
        result = asyncio.run(
            probe.probe_console(credentials(), controller_factory=lambda _: controller)
        )
        self.assertFalse(result.online)
        self.assertIn("网络不可达", result.error)
        self.assertTrue(controller.closed)

    def test_controller_factory_failure(self):
        def broken(_credentials):
            raise RuntimeError("凭据坏了")

        result = asyncio.run(
            probe.probe_console(credentials(), controller_factory=broken)
        )
        self.assertFalse(result.online)
        self.assertIn("凭据坏了", result.error)

    def test_timeout_is_reported(self):
        controller = FakeController(status={"status-code": 200}, delay=0.2)
        result = asyncio.run(
            probe.probe_console(
                credentials(), timeout=0.01, controller_factory=lambda _: controller
            )
        )
        self.assertFalse(result.online)
        self.assertEqual(result.error, "检测超时")
        self.assertTrue(controller.closed, "超时后也要释放底层连接")


if __name__ == "__main__":
    unittest.main()
