"""配置模型、预设合并与 JSON 读写。

设计要点：
- 预设（presets/*.json）只提供默认值，用户 config.json 覆盖它；
- 所有数值型调参集中在 MouseConfig/LeftStickConfig，避免散落魔法数；
- 路径以项目根为基准，保证从任意工作目录启动都能找到文件。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass, field, fields


def _app_root() -> str:
    """数据目录：源码运行时是项目根，打包成 exe 后是程序目录或它的上一级。

    onedir 打包后 exe 在 app\\ 子目录里，而 config.json / credentials.json
    留在项目根（重新打包不会覆盖数据）。所以这里优先找上一级：
    上一级存在 credentials.json 就用上一级，否则才用 exe 所在目录。
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        parent = os.path.dirname(exe_dir)
        if os.path.exists(os.path.join(parent, "credentials.json")):
            return parent
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _package_dir() -> str:
    """包内资源目录：打包后资源解压在 sys._MEIPASS 下。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(meipass, "ps5kbm")
    return os.path.dirname(os.path.abspath(__file__))


PROJECT_ROOT = _app_root()
PACKAGE_DIR = _package_dir()
PRESETS_DIR = os.path.join(PACKAGE_DIR, "presets")
# 用户自己保存的预设放项目根，优先于打包内置的预设，重新打包不会丢
USER_PRESETS_DIR = os.path.join(PROJECT_ROOT, "presets")

DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
# 摇杆/鼠标手感参数单独存这个文件：改一下就保存，应用预设时也不会被覆盖
TUNING_CONFIG_PATH = os.path.join(PROJECT_ROOT, "tuning.json")
DEFAULT_CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "credentials.json")


@dataclass
class MouseConfig:
    """鼠标→右摇杆参数。

    sensitivity 的含义：鼠标速度达到基准（2500 像素/秒）时摇杆满偏再乘
    sensitivity。它作为全局倍率，会乘在两段灵敏度插值结果上。

    两段灵敏度（业界做法，参考 JoyShockMapper）：
        鼠标速度 <= slow_speed 时用 slow_sensitivity，
        >= fast_speed 时用 fast_sensitivity，中间线性插值。
        想退化成单段，把两个灵敏度设成相同值即可。

    curve_type：响应曲线类型 linear / quadratic / cubic / power。
    curve：仅 power 类型使用，指数（1.0 线性，>1 慢速更精细）。
    deadzone：小于该偏移量的摇杆值归零，抵消手抖。
    smoothing：0~0.95，越大越平滑但越滞后。
    """

    sensitivity: float = 1.0
    curve: float = 1.0
    curve_type: str = "linear"
    deadzone: float = 0.02
    # 鼠标视角总开关：关掉后鼠标不再驱动右摇杆（键盘/左摇杆/按键不受影响）
    enabled: bool = True
    # 反死区：把任何非零输入抬升到该值以上，跳过游戏自身的摇杆死区，
    # 解决“小幅移动拖不动”（DS4Windows / JoyShockMapper 的 anti-deadzone）
    anti_deadzone: float = 0.15
    invert_y: bool = False
    smoothing: float = 0.0
    slow_speed: float = 600.0
    slow_sensitivity: float = 1.0
    fast_speed: float = 2500.0
    fast_sensitivity: float = 1.0
    # Flick Stick：水平快速甩动时摇杆瞬间满偏一小段，模拟“瞬间转身”
    flick_enabled: bool = False
    flick_threshold: float = 1800.0  # 触发速度（px/s）
    flick_duration: float = 0.033  # 满偏持续秒数（约 30fps 一帧）


@dataclass
class LeftStickConfig:
    """键盘→左摇杆的默认幅度。

    value：启动时的左摇杆最大输出（0.05~1.0），WASD 推到底就是这个幅度。
           运行中可以用「摇杆幅度」类型的映射动作改（见 mapping.parse_action）。
    ramp：摇杆从 0 推到目标值的速度（每秒变化量）。0 表示瞬时到位；
          有斜坡时短按只到小幅度、长按才到满偏，转弯手感更自然。
    """

    value: float = 1.0
    ramp: float = 4.0


@dataclass
class ModeConfig:
    """一套完整的按键映射（一个“模式”）。

    label：界面上显示的名字（显示在透明窗口右上角）。
    三组映射在每个模式下都是完整的；没单独设置的模式用 default 的内容。
    """

    label: str = ""
    keyboard_sticks: dict[str, list[str]] = field(default_factory=dict)
    keyboard_buttons: dict[str, object] = field(default_factory=dict)
    mouse_buttons: dict[str, object] = field(default_factory=dict)


@dataclass
class AppConfig:
    """完整运行配置。"""

    preset: str = "gta6"
    hotkey: str = "f8"
    mode_switch: str = "f9"
    ps5_host: str = ""
    account_id: str = ""
    credentials_path: str = DEFAULT_CREDENTIALS_PATH
    mouse: MouseConfig = field(default_factory=MouseConfig)
    left_stick: LeftStickConfig = field(default_factory=LeftStickConfig)
    # 开始捕获时自动切到前台的窗口标题（空 = 不切换，由透明层保持焦点）
    target_window: str = ""
    # 多模式映射：键是模式 id，至少包含 "default"
    modes: dict[str, ModeConfig] = field(default_factory=dict)
    current_mode: str = "default"


def build_mode(raw: dict, fallback: ModeConfig | None = None) -> ModeConfig:
    """解析单个模式；缺失的字段用 fallback 补齐。"""
    fallback = fallback or ModeConfig()
    return ModeConfig(
        label=str(raw.get("label", fallback.label)),
        keyboard_sticks=dict(raw.get("keyboard_sticks", fallback.keyboard_sticks)),
        keyboard_buttons=dict(raw.get("keyboard_buttons", fallback.keyboard_buttons)),
        mouse_buttons=dict(raw.get("mouse_buttons", fallback.mouse_buttons)),
    )


def list_presets() -> list[str]:
    """返回可用预设名：用户目录与内置目录合并，同名以用户目录为准。"""
    names: set[str] = set()
    for directory in (USER_PRESETS_DIR, PRESETS_DIR):
        if not os.path.isdir(directory):
            continue
        names.update(
            item[:-5] for item in os.listdir(directory) if item.endswith(".json")
        )
    return sorted(names)


def load_preset(name: str) -> dict:
    """按名字加载预设；用户目录优先，其次内置预设。"""
    if not name:
        return {}
    for directory in (USER_PRESETS_DIR, PRESETS_DIR):
        path = os.path.join(directory, f"{name}.json")
        if os.path.exists(path):
            return _read_json(path)
    available = list_presets()
    raise FileNotFoundError(f"预设 {name} 不存在，可用预设：{', '.join(available)}")


def preset_to_dict(name: str, cfg: AppConfig) -> dict:
    """只保留预设相关字段，用于把当前配置回写成预设文件。"""
    default_mode = cfg.modes.get("default") or ModeConfig()
    return {
        "preset": name,
        "hotkey": cfg.hotkey,
        "mode_switch": cfg.mode_switch,
        "target_window": cfg.target_window,
        "mouse": {
            "sensitivity": cfg.mouse.sensitivity,
            "curve": cfg.mouse.curve,
            "deadzone": cfg.mouse.deadzone,
            "invert_y": cfg.mouse.invert_y,
            "smoothing": cfg.mouse.smoothing,
        },
        "left_stick": {"value": cfg.left_stick.value, "ramp": cfg.left_stick.ramp},
        "keyboard_sticks": default_mode.keyboard_sticks,
        "keyboard_buttons": default_mode.keyboard_buttons,
        "mouse_buttons": default_mode.mouse_buttons,
        "modes": modes_to_dict(cfg),
    }


def save_preset(name: str, cfg: AppConfig) -> str:
    """把当前配置写回用户预设目录，返回写入路径。"""
    os.makedirs(USER_PRESETS_DIR, exist_ok=True)
    path = os.path.join(USER_PRESETS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(preset_to_dict(name, cfg), handle, ensure_ascii=False, indent=2)
    return path


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base，列表与标量直接替换。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def build_mouse(raw: dict) -> MouseConfig:
    allowed = {item.name for item in fields(MouseConfig)}
    return MouseConfig(**{key: value for key, value in raw.items() if key in allowed})


def build_left_stick(raw: dict) -> LeftStickConfig:
    """解析左摇杆配置；旧版本里的 presets 字段会被忽略。"""
    try:
        value = float(raw.get("value", 1.0))
    except (TypeError, ValueError):
        value = 1.0
    try:
        ramp = float(raw.get("ramp", 4.0))
    except (TypeError, ValueError):
        ramp = 4.0
    return LeftStickConfig(
        value=max(0.05, min(1.0, value)),
        ramp=max(0.0, min(50.0, ramp)),
    )


def _build_mouse(raw: dict) -> MouseConfig:
    return build_mouse(raw)


def _build_left_stick(raw: dict) -> LeftStickConfig:
    return build_left_stick(raw)


def build_config(raw: dict) -> AppConfig:
    """把合并后的字典转成 AppConfig。

    兼容旧格式：顶层 keyboard_buttons / mouse_buttons / keyboard_sticks
    会被当成 default 模式；新格式用 modes 字段描述多套映射。
    """
    raw = raw or {}
    default_mode = build_mode(
        {
            "label": raw.get("mode_label") or "默认",
            "keyboard_sticks": raw.get("keyboard_sticks", {}),
            "keyboard_buttons": raw.get("keyboard_buttons", {}),
            "mouse_buttons": raw.get("mouse_buttons", {}),
        }
    )
    modes: dict[str, ModeConfig] = {"default": default_mode}
    for name, mode_raw in (raw.get("modes") or {}).items():
        if not isinstance(mode_raw, dict):
            continue
        modes[str(name)] = build_mode(mode_raw, default_mode)
    # 启动时始终从 default 模式开始：运行时按切换键切到的模式只在本次运行
    # 内有效，避免下次启动还停在“驾驶”这种非默认模式上。
    current = "default"
    if current not in modes:
        current = "default"
    return AppConfig(
        preset=str(raw.get("preset", "gta6")),
        hotkey=str(raw.get("hotkey", "f8")).lower(),
        mode_switch=str(raw.get("mode_switch", "f9")).lower(),
        ps5_host=str(raw.get("ps5_host", "")),
        account_id=str(raw.get("account_id", "")),
        credentials_path=str(raw.get("credentials_path", DEFAULT_CREDENTIALS_PATH)),
        mouse=_build_mouse(raw.get("mouse", {})),
        left_stick=_build_left_stick(raw.get("left_stick", {})),
        target_window=str(raw.get("target_window", "")),
        modes=modes,
        current_mode=current,
    )


def tuning_to_dict(cfg: AppConfig) -> dict:
    """摇杆/鼠标手感参数（单独保存的那部分）。"""
    mouse = cfg.mouse
    return {
        "mouse": {
            "sensitivity": mouse.sensitivity,
            "curve": mouse.curve,
            "curve_type": mouse.curve_type,
            "deadzone": mouse.deadzone,
            "anti_deadzone": mouse.anti_deadzone,
            "enabled": mouse.enabled,
            "invert_y": mouse.invert_y,
            "smoothing": mouse.smoothing,
            "slow_speed": mouse.slow_speed,
            "slow_sensitivity": mouse.slow_sensitivity,
            "fast_speed": mouse.fast_speed,
            "fast_sensitivity": mouse.fast_sensitivity,
            "flick_enabled": mouse.flick_enabled,
            "flick_threshold": mouse.flick_threshold,
            "flick_duration": mouse.flick_duration,
        },
        "left_stick": {
            "value": cfg.left_stick.value,
            "ramp": cfg.left_stick.ramp,
        },
    }


def save_tuning(cfg: AppConfig, path: str = TUNING_CONFIG_PATH) -> None:
    """保存摇杆/鼠标手感参数（改动即时落盘）。"""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(tuning_to_dict(cfg), handle, ensure_ascii=False, indent=2)


def load_tuning(path: str = TUNING_CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def load_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """加载配置：预设打底，再用 config.json 覆盖。

    注意：映射类字段（按键/鼠标/方向键/modes）在用户配置里出现时**整体替换**，
    不做逐键合并。否则用户在界面里删掉的键会被预设补回来。
    """
    user_raw: dict = _read_json(path) if os.path.exists(path) else {}
    preset_name = str(user_raw.get("preset", "gta6"))
    preset_raw = load_preset(preset_name)
    merged = _deep_merge(preset_raw, user_raw)
    for field_name in (
        "keyboard_buttons",
        "mouse_buttons",
        "keyboard_sticks",
        "modes",
    ):
        if field_name in user_raw:
            merged[field_name] = copy.deepcopy(user_raw[field_name])
    merged["preset"] = preset_name
    # 摇杆/鼠标手感参数单独存 tuning.json，优先级最高：
    # 满足“单独保存、改动即存、应用预设不覆盖”
    tuning = load_tuning()
    if tuning:
        tuning_mouse = tuning.get("mouse") or {}
        if tuning_mouse:
            merged["mouse"] = {**(merged.get("mouse") or {}), **tuning_mouse}
        tuning_stick = tuning.get("left_stick") or {}
        if tuning_stick:
            merged["left_stick"] = {
                **(merged.get("left_stick") or {}),
                **tuning_stick,
            }
    return build_config(merged)


def save_default_config(path: str = DEFAULT_CONFIG_PATH) -> None:
    """写出带注释的默认配置，方便用户直接改。"""
    preset_raw = load_preset("gta6")
    data = _deep_merge(preset_raw, {"preset": "gta6"})
    data.setdefault("ps5_host", "")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def load_credentials(path: str) -> dict:
    return _read_json(path)


def save_credentials(path: str, credentials: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(credentials, handle, ensure_ascii=False, indent=2)


def modes_to_dict(cfg: AppConfig) -> dict:
    """把 modes 序列化成可写盘的字典。"""
    return {
        name: {
            "label": mode.label,
            "keyboard_sticks": mode.keyboard_sticks,
            "keyboard_buttons": mode.keyboard_buttons,
            "mouse_buttons": mode.mouse_buttons,
        }
        for name, mode in cfg.modes.items()
    }


def config_to_dict(cfg: AppConfig) -> dict:
    """把 AppConfig 序列化成可写盘的字典。"""
    default_mode = cfg.modes.get("default") or ModeConfig()
    return {
        "preset": cfg.preset,
        "hotkey": cfg.hotkey,
        "mode_switch": cfg.mode_switch,
        "current_mode": cfg.current_mode,
        "target_window": cfg.target_window,
        "ps5_host": cfg.ps5_host,
        "account_id": cfg.account_id,
        "mouse": {
            "sensitivity": cfg.mouse.sensitivity,
            "curve": cfg.mouse.curve,
            "deadzone": cfg.mouse.deadzone,
            "invert_y": cfg.mouse.invert_y,
            "smoothing": cfg.mouse.smoothing,
        },
        "left_stick": {
            "value": cfg.left_stick.value,
            "ramp": cfg.left_stick.ramp,
        },
        # 同时写顶层的 default 映射（兼容旧版读取）和多模式结构
        "keyboard_sticks": default_mode.keyboard_sticks,
        "keyboard_buttons": default_mode.keyboard_buttons,
        "mouse_buttons": default_mode.mouse_buttons,
        "modes": modes_to_dict(cfg),
    }


def save_config(cfg: AppConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config_to_dict(cfg), handle, ensure_ascii=False, indent=2)
