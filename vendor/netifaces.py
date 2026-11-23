"""netifaces 的最小纯 Python 兼容实现（shim）。

为什么需要它：
    pyremoteplay 的 ddp.py 硬依赖 `netifaces`，但 netifaces 0.11 在 Python 3.12
    上只提供源码包、需要本地 C 编译器。官方未为 3.12 提供 wheel，编译环境
    又不保证可用，因此用一个纯 Python 实现覆盖 pyremoteplay 实际用到的接口：

        netifaces.interfaces()
        netifaces.ifaddresses(ifname)
        netifaces.AF_INET / AF_INET6

    底层用 psutil.net_if_addrs() 拿网卡与地址，语义与 netifaces 一致。

限制：
    只实现了 pyremoteplay 用到的部分。gateways() 返回空字典，因为
    pyremoteplay 不调用它。
"""

from __future__ import annotations

import ipaddress
import socket

import psutil

AF_INET = socket.AF_INET
AF_INET6 = socket.AF_INET6
AF_LINK = getattr(socket, "AF_LINK", -1)


def interfaces() -> list[str]:
    """返回本机所有网络接口名。"""
    return list(psutil.net_if_addrs().keys())


def ifaddresses(interface: str) -> dict[int, list[dict[str, str]]]:
    """返回指定接口的地址表，结构对齐 netifaces。

    返回形如：
        {
            AF_INET: [{"addr": "192.168.1.10", "netmask": "255.255.255.0",
                       "broadcast": "192.168.1.255"}],
            AF_INET6: [{"addr": "fe80::1", "netmask": "ffff:..."}],
        }
    """
    result: dict[int, list[dict[str, str]]] = {}
    for addr_info in psutil.net_if_addrs().get(interface, []):
        if addr_info.family == socket.AF_INET:
            entry: dict[str, str] = {"addr": addr_info.address}
            if addr_info.netmask:
                entry["netmask"] = addr_info.netmask
            broadcast = addr_info.broadcast
            if not broadcast and addr_info.netmask:
                # Windows 上 psutil 不一定给 broadcast，这里用掩码算出来
                network = ipaddress.IPv4Network(
                    f"{addr_info.address}/{addr_info.netmask}", strict=False
                )
                broadcast = str(network.broadcast_address)
            if broadcast:
                entry["broadcast"] = broadcast
            result.setdefault(AF_INET, []).append(entry)
        elif addr_info.family == socket.AF_INET6:
            entry = {"addr": addr_info.address}
            if addr_info.netmask:
                entry["netmask"] = addr_info.netmask
            result.setdefault(AF_INET6, []).append(entry)
    return result


def gateways() -> dict:
    """占位实现：pyremoteplay 不使用。"""
    return {}
