"""按键名规范化与显示。

配置里的键名约定：
- 字母/数字：小写，如 w、1
- 特殊键：space、shift、ctrl、alt、tab、esc、enter、up、down、left、right、f1~f12
- 鼠标：mouse_left、mouse_right、mouse_middle、mouse_x1、mouse_x2
- 滚轮（仅调参键）：wheel_up、wheel_down
"""

from __future__ import annotations

from pynput import keyboard

# 界面上比原始键名更好懂的写法
_DISPLAY = {
    "wheel_up": "滚轮上",
    "wheel_down": "滚轮下",
    "space": "空格",
    "esc": "ESC",
    "enter": "回车",
    "tab": "Tab",
    "caps_lock": "CapsLock",
    "backspace": "退格",
    "delete": "Del",
    "insert": "Ins",
    "pageup": "PgUp",
    "pagedown": "PgDn",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
    "shift": "Shift",
    "ctrl_l": "左Ctrl",
    "ctrl_r": "右Ctrl",
    "alt_l": "左Alt",
    "alt_r": "右Alt",
    "mouse_left": "鼠标左键",
    "mouse_right": "鼠标右键",
    "mouse_middle": "鼠标中键",
    "mouse_x1": "鼠标侧键1",
    "mouse_x2": "鼠标侧键2",
}


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


def display_key(name: str) -> str:
    """配置键名 → 界面显示名（带兜底的大写）。"""
    key = str(name or "").strip().lower()
    if not key:
        return "—"
    if key in _DISPLAY:
        return _DISPLAY[key]
    if key.startswith("mouse_"):
        return "鼠标 " + key[len("mouse_"):]
    return key.upper()
