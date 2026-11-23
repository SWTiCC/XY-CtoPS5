"""依赖路径引导：让 pyremoteplay 能找到 vendor/ 里的 netifaces 兼容层。

pyremoteplay 依赖 netifaces，而官方 netifaces 需要编译；本项目用
`vendor/netifaces.py` 纯 Python 实现替代，因此必须在 import playdirector /
pyremoteplay 之前把 vendor 目录插到 sys.path 最前面。

打包成 exe 后 netifaces 已作为模块内置，不需要也不该改 sys.path。
"""

from __future__ import annotations

import os
import sys


def ensure_vendor_path() -> None:
    """源码运行时注入 vendor 目录；打包运行时不做任何事。"""
    if getattr(sys, "frozen", False):
        return
    vendor_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"
    )
    if os.path.isdir(vendor_dir) and vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)
