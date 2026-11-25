"""配置模型、预设合并与 JSON 读写。

设计要点：
- 预设（presets/*.json）只提供默认值，用户 config.json 覆盖它；
- 所有数值型调参集中在 MouseConfig/LeftStickConfig，避免散落魔法数；
- 路径以项目根为基准，保证从任意工作目录启动都能找到文件。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from dataclasses import dataclass, field, fields

_LOGGER = logging.getLogger(__name__)


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

# 捕获时调整扳机输出深度的按键：动作 → 默认键名。
# 键名约定同映射（见 keys.py），另外支持 wheel_up / wheel_down（鼠标滚轮）。
TRIGGER_KEY_DEFAULTS = {
    "r2_up": "wheel_up",
    "r2_down": "wheel_down",
    "l2_up": "=",
    "l2_down": "-",
}

# 四个调参动作的界面名：日志、按钮、冲突提示共用一份，避免各写一遍
TRIGGER_LABELS = {
    "r2_up": "R2 加深",
    "r2_down": "R2 减浅",
    "l2_up": "L2 加深",
    "l2_down": "L2 减浅",
}


def trigger_adjust_keys(cfg: "AppConfig") -> dict[str, str]:
    """返回当前配置的四个调参键；空值回落到默认，顺序固定便于匹配。"""
    return {
        name: str(getattr(cfg, name, "") or "").strip().lower()
        or default
        for name, default in TRIGGER_KEY_DEFAULTS.items()
    }


def _normalize_key(name: object) -> str:
    return str(name or "").strip().lower()


def key_conflict(
    name: str,
    *,
    hotkey: str = "",
    mode_switch: str = "",
    trigger_keys: dict[str, str] | None = None,
    stick_keys: tuple[str, ...] | list[str] = (),
    mapping_sources: tuple[str, ...] | list[str] = (),
    ignore_mode_switch: str = "",
    ignore_trigger: str = "",
) -> str:
    """按键是否已被别处占用：被占用返回中文原因，可用返回空串。

    所有「占一个键」的地方（映射、调参键、切换键）共用这份判定，
    以后新增占用类型只改这里。判定顺序固定：热键 → 切换键 → 调参键 →
    方向键 → 已映射按键。

    `ignore_*` 用于「改键改回自己」时不算冲突。
    """

    key = _normalize_key(name)
    if not key:
        return ""
    if hotkey and key == _normalize_key(hotkey):
        return "捕获热键"
    if mode_switch:
        current = _normalize_key(mode_switch)
        if key == current and key != _normalize_key(ignore_mode_switch):
            return "模式切换键"
    for action, value in (trigger_keys or {}).items():
        if action == ignore_trigger:
            continue
        if key == _normalize_key(value):
            return f"扳机调参键（{TRIGGER_LABELS.get(action, action)}）"
    if key in {_normalize_key(item) for item in stick_keys}:
        return "左摇杆方向键"
    if key in {_normalize_key(item) for item in mapping_sources}:
        return "已映射的按键"
    return ""


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
class GyroConfig:
    """DualSense 陀螺仪 → 右摇杆的参数（见 ps5kbm/gyro.py）。"""

    enabled: bool = True
    # 激活方式：always 或手柄按键名（l2 / l1 / r1 / cross…）
    activation: str = "l2"
    sensitivity_x: float = 1.0
    sensitivity_y: float = 1.0
    deadzone: float = 0.02
    smoothing: float = 0.3
    invert_x: bool = False
    invert_y: bool = False
    # 校准得到的零偏（rad/s），保存下来省得每次重开都重新校准
    bias: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class ControllerConfig:
    """手柄页的全局设置（不随预设切换）。"""

    # 输入模式：keyboard = 键鼠映射；controller = DualSense 直通
    mode: str = "keyboard"
    gyro: GyroConfig = field(default_factory=GyroConfig)
    rumble_enabled: bool = True
    # USB 连接时的原生触觉（写入 DualSense 音频端点 3/4 声道）
    haptics_usb: bool = True
    rumble_gain: float = 1.0
    adaptive_triggers: bool = True


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
    # 捕获时调扳机深度的四个键（默认沿用旧行为：滚轮调 R2，- / = 调 L2）
    r2_up: str = TRIGGER_KEY_DEFAULTS["r2_up"]
    r2_down: str = TRIGGER_KEY_DEFAULTS["r2_down"]
    l2_up: str = TRIGGER_KEY_DEFAULTS["l2_up"]
    l2_down: str = TRIGGER_KEY_DEFAULTS["l2_down"]
    ps5_host: str = ""
    account_id: str = ""
    credentials_path: str = DEFAULT_CREDENTIALS_PATH
    mouse: MouseConfig = field(default_factory=MouseConfig)
    left_stick: LeftStickConfig = field(default_factory=LeftStickConfig)
    # 开始捕获时自动切到前台的窗口标题（空 = 不切换，由透明层保持焦点）
    target_window: str = ""
    # 按下扳机时输出的深度（0~1）：运行页滑条/调参键改的就是它，存 tuning.json
    r2_depth: float = 1.0
    l2_depth: float = 1.0
    # 手柄直通 / 陀螺仪 / 震动（手柄页）
    controller: ControllerConfig = field(default_factory=ControllerConfig)
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


def new_empty_config(preset_name: str, base: AppConfig | None = None) -> AppConfig:
    """新建预设用的空配置：只有一个「默认」模式，三组映射都为空。

    传入 base 时沿用它的**非映射**设置（热键 / 切换键 / 调参键 / 目标窗口 /
    手感与扳机深度）。否则新建一个预设会把用户的切换键悄悄重置成默认 F9。
    """
    cfg = AppConfig(
        preset=str(preset_name),
        modes={"default": ModeConfig(label="默认")},
    )
    if base is not None:
        cfg.hotkey = base.hotkey
        cfg.mode_switch = base.mode_switch
        cfg.r2_up = base.r2_up
        cfg.r2_down = base.r2_down
        cfg.l2_up = base.l2_up
        cfg.l2_down = base.l2_down
        cfg.target_window = base.target_window
        cfg.r2_depth = base.r2_depth
        cfg.l2_depth = base.l2_depth
        cfg.mouse = copy.deepcopy(base.mouse)
        cfg.left_stick = copy.deepcopy(base.left_stick)
    return cfg


def _write_json(path: str, data: dict) -> None:
    """原子写：先写临时文件再替换。

    直接 open(path, "w") 写到一半断电/崩溃会留下半截 JSON，
    下次启动直接解析失败（用户看到的就是「程序打不开」）。
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_preset(name: str, cfg: AppConfig) -> str:
    """把当前配置写回用户预设目录，返回写入路径。"""
    name = check_preset_name(name)
    os.makedirs(USER_PRESETS_DIR, exist_ok=True)
    path = os.path.join(USER_PRESETS_DIR, f"{name}.json")
    _write_json(path, preset_to_dict(name, cfg))
    return path


_INVALID_PRESET_CHARS = set('\\/:*?"<>|')


def check_preset_name(raw: str) -> str:
    """校验预设名：不能为空、不能含路径字符；返回去空格后的名字。"""
    name = str(raw or "").strip()
    if not name:
        raise ValueError("预设名不能为空")
    if len(name) > 40:
        raise ValueError("预设名太长（最多 40 个字符）")
    if any(char in _INVALID_PRESET_CHARS for char in name):
        raise ValueError('预设名不能包含 \\ / : * ? " < > |')
    return name


def user_preset_path(name: str) -> str:
    return os.path.join(USER_PRESETS_DIR, f"{check_preset_name(name)}.json")


def is_user_preset(name: str) -> bool:
    """是否已经存在同名的用户预设（内置预设不可覆盖 / 删除）。"""
    try:
        return os.path.exists(user_preset_path(name))
    except ValueError:
        return False


def delete_preset(name: str) -> str:
    """删除用户预设文件；内置预设没有用户文件，调用方应先判断。"""
    path = user_preset_path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"用户预设 {name} 不存在")
    os.remove(path)
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


def _clamp01(value: object, default: float = 1.0) -> float:
    """0~1 的浮点参数：越界夹紧，非法值用默认。"""
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _build_mouse(raw: dict) -> MouseConfig:
    return build_mouse(raw)


def _build_left_stick(raw: dict) -> LeftStickConfig:
    return build_left_stick(raw)


GYRO_ACTIVATIONS = ("always",) + tuple(
    name.lower()
    for name in (
        "L2",
        "L1",
        "R2",
        "R1",
        "L3",
        "R3",
        "SQUARE",
        "CROSS",
        "CIRCLE",
        "TRIANGLE",
        "SHARE",
        "OPTIONS",
        "TOUCHPAD",
        "MUTE",
        "PS",
    )
)
CONTROLLER_MODES = ("keyboard", "controller")


def _clamp(value: object, low: float, high: float, default: float) -> float:
    """任意浮点参数：越界夹紧，非法值用默认。"""
    try:
        return max(low, min(high, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _build_gyro(raw: dict) -> GyroConfig:
    raw = raw or {}
    activation = str(raw.get("activation", "l2")).strip().lower()
    if activation not in GYRO_ACTIVATIONS:
        activation = "l2"
    bias_raw = raw.get("bias") or [0.0, 0.0, 0.0]
    try:
        bias = [float(item) for item in bias_raw][:3]
    except (TypeError, ValueError):
        bias = []
    bias += [0.0] * (3 - len(bias))
    return GyroConfig(
        enabled=bool(raw.get("enabled", True)),
        activation=activation,
        sensitivity_x=_clamp(raw.get("sensitivity_x", 1.0), 0.1, 3.0, 1.0),
        sensitivity_y=_clamp(raw.get("sensitivity_y", 1.0), 0.1, 3.0, 1.0),
        deadzone=_clamp(raw.get("deadzone", 0.02), 0.0, 0.1, 0.02),
        smoothing=_clamp(raw.get("smoothing", 0.3), 0.0, 0.9, 0.3),
        invert_x=bool(raw.get("invert_x", False)),
        invert_y=bool(raw.get("invert_y", False)),
        bias=bias,
    )


def _build_controller(raw: dict) -> ControllerConfig:
    raw = raw or {}
    mode = str(raw.get("mode", "keyboard")).strip().lower()
    if mode not in CONTROLLER_MODES:
        mode = "keyboard"
    return ControllerConfig(
        mode=mode,
        gyro=_build_gyro(raw.get("gyro") or {}),
        rumble_enabled=bool(raw.get("rumble_enabled", True)),
        haptics_usb=bool(raw.get("haptics_usb", True)),
        rumble_gain=_clamp(raw.get("rumble_gain", 1.0), 0.0, 2.0, 1.0),
        adaptive_triggers=bool(raw.get("adaptive_triggers", True)),
    )


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
        r2_up=_key_or(raw.get("r2_up"), TRIGGER_KEY_DEFAULTS["r2_up"]),
        r2_down=_key_or(raw.get("r2_down"), TRIGGER_KEY_DEFAULTS["r2_down"]),
        l2_up=_key_or(raw.get("l2_up"), TRIGGER_KEY_DEFAULTS["l2_up"]),
        l2_down=_key_or(raw.get("l2_down"), TRIGGER_KEY_DEFAULTS["l2_down"]),
        ps5_host=str(raw.get("ps5_host", "")),
        account_id=str(raw.get("account_id", "")),
        credentials_path=str(raw.get("credentials_path", DEFAULT_CREDENTIALS_PATH)),
        mouse=_build_mouse(raw.get("mouse", {})),
        left_stick=_build_left_stick(raw.get("left_stick", {})),
        target_window=str(raw.get("target_window", "")),
        r2_depth=_clamp01(raw.get("r2_depth", 1.0)),
        l2_depth=_clamp01(raw.get("l2_depth", 1.0)),
        controller=_build_controller(raw.get("controller") or {}),
        modes=modes,
        current_mode=current,
    )


def _key_or(value: object, default: str) -> str:
    """配置里的键名：去空格转小写，空值用默认。"""
    return str(value or "").strip().lower() or default


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
        "r2_depth": cfg.r2_depth,
        "l2_depth": cfg.l2_depth,
    }


def save_tuning(cfg: AppConfig, path: str = TUNING_CONFIG_PATH) -> None:
    """保存摇杆/鼠标手感参数（改动即时落盘）。"""
    _write_json(path, tuning_to_dict(cfg))


def load_tuning(path: str = TUNING_CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _backup_broken(path: str) -> None:
    """把读不动的文件改名留档，避免下一次保存把它彻底覆盖掉。"""
    try:
        os.replace(path, f"{path}.broken")
    except OSError:
        pass


def load_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """加载配置：预设打底，再用 config.json 覆盖。

    注意：映射类字段（按键/鼠标/方向键/modes）在用户配置里出现时**整体替换**，
    不做逐键合并。否则用户在界面里删掉的键会被预设补回来。

    容错：config.json 或预设文件解析失败时不让程序打不开——坏文件改名留档，
    按能读到的那部分启动（日志里说明原因）。
    """
    user_raw: dict = {}
    if os.path.exists(path):
        try:
            user_raw = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            _LOGGER.warning("配置文件读取失败，已改名留档并按预设启动：%s", exc)
            _backup_broken(path)
            user_raw = {}
    preset_name = str(user_raw.get("preset", "gta6"))
    try:
        preset_raw = load_preset(preset_name)
    except FileNotFoundError:
        # 预设文件被删了也能启动：只用用户配置本身，不至于卡在启动
        preset_raw = {}
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("预设 %s 读取失败，先只用用户配置启动：%s", preset_name, exc)
        preset_raw = {}
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
        for depth_key in ("r2_depth", "l2_depth"):
            if depth_key in tuning:
                merged[depth_key] = tuning[depth_key]
    return build_config(merged)


def save_default_config(path: str = DEFAULT_CONFIG_PATH) -> None:
    """写出默认配置（预设内容打底），方便用户直接改。"""
    preset_raw = load_preset("gta6")
    data = _deep_merge(preset_raw, {"preset": "gta6"})
    data.setdefault("ps5_host", "")
    _write_json(path, data)


def load_credentials(path: str) -> dict:
    return _read_json(path)


def save_credentials(path: str, credentials: dict) -> None:
    _write_json(path, credentials)


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
        "r2_up": cfg.r2_up,
        "r2_down": cfg.r2_down,
        "l2_up": cfg.l2_up,
        "l2_down": cfg.l2_down,
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
        "r2_depth": cfg.r2_depth,
        "l2_depth": cfg.l2_depth,
        "controller": {
            "mode": cfg.controller.mode,
            "gyro": {
                "enabled": cfg.controller.gyro.enabled,
                "activation": cfg.controller.gyro.activation,
                "sensitivity_x": cfg.controller.gyro.sensitivity_x,
                "sensitivity_y": cfg.controller.gyro.sensitivity_y,
                "deadzone": cfg.controller.gyro.deadzone,
                "smoothing": cfg.controller.gyro.smoothing,
                "invert_x": cfg.controller.gyro.invert_x,
                "invert_y": cfg.controller.gyro.invert_y,
                "bias": list(cfg.controller.gyro.bias),
            },
            "rumble_enabled": cfg.controller.rumble_enabled,
            "haptics_usb": cfg.controller.haptics_usb,
            "rumble_gain": cfg.controller.rumble_gain,
            "adaptive_triggers": cfg.controller.adaptive_triggers,
        },
        # 同时写顶层的 default 映射（兼容旧版读取）和多模式结构
        "keyboard_sticks": default_mode.keyboard_sticks,
        "keyboard_buttons": default_mode.keyboard_buttons,
        "mouse_buttons": default_mode.mouse_buttons,
        "modes": modes_to_dict(cfg),
    }


def save_config(cfg: AppConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    _write_json(path, config_to_dict(cfg))
