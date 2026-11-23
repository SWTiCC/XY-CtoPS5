"""按键名规范化：把 pynput 的按键对象转成配置里使用的字符串。

配置里的键名约定：
- 字母/数字：小写，如 w、1
- 特殊键：space、shift、ctrl、alt、tab、esc、enter、up、down、left、right、f1~f12
- 鼠标：mouse_left、mouse_right、mouse_middle、mouse_x1、mouse_x2
"""

from __future__ import annotations

from pynput import keyboard


def key_name(key) -> str:
    """键盘按键对象 → 配置键名。"""
    if isinstance(key, keyboard.Key):
        return key.name.lower()
    char = getattr(key, "char", None)
    if char:
        return char.lower()
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"vk{vk}"
    return str(key).lower()


def mouse_button_name(button) -> str:
    """鼠标按键对象 → 配置键名（带 mouse_ 前缀）。"""
    return f"mouse_{str(getattr(button, 'name', button)).lower()}"
