"""键鼠 → 手柄输入的纯映射引擎。

这一层不碰网络、不碰输入设备，只做状态合成，方便单元测试：
- 键盘方向键合成左摇杆（对角归一化，避免斜向更快）；
- 鼠标累积位移合成右摇杆（按速度映射，带曲线、死区、平滑）；
- 按键动作支持三种：单按钮、组合键（同时按）、序列（依次按）。

动作配置格式：
    "space": "CROSS"                                # 单按钮（旧格式）
    "g":     {"chord": ["L1", "R1"]}                # 组合键：按下时同时按
    "h":     {"sequence": [["UP", 0.05], ["CROSS"]]}  # 序列宏：依次按，第二项是保持秒数
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field

from .config import AppConfig

_LOGGER = logging.getLogger(__name__)

# pyremoteplay 支持的按钮名（FeedbackEvent.Type），超出的名字会被发送层忽略
VALID_BUTTONS = frozenset(
    {
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "CROSS",
        "CIRCLE",
        "TRIANGLE",
        "SQUARE",
        "L1",
        "R1",
        "L2",
        "R2",
        "L3",
        "R3",
        "OPTIONS",
        "SHARE",
        "PS",
        "TOUCHPAD",
    }
)

# 鼠标速度到摇杆的基准：速度达到该值时，摇杆满偏（再乘 sensitivity）
# 2500 px/s 约等于正常瞄准移动；5000 时正常移动只能推出 0.2，视角几乎不动。
SPEED_BASE_PX_PER_SEC = 2500.0

# 鼠标位移换算窗口（秒）：和 Raw Input 消息泵的批量节奏对齐
MOUSE_WINDOW_SECONDS = 0.010

# 序列步骤的默认保持时长（秒）
DEFAULT_STEP_HOLD = 0.05


@dataclass
class Action:
    """一个按键触发的动作。

    kind：
        button   单按钮
        chord    组合键（同时按多个按钮）
        sequence 序列宏（依次按）
        stick    调整左摇杆幅度；values 有一个值时每次设为该值，
                 有多个值时每按一次按顺序循环切到下一个（从当前值往后走，
                 所以默认 1.0 + 档位 [1.0, 0.3] 时第一下就是 0.3）
    """

    kind: str
    buttons: list[str] = field(default_factory=list)
    steps: list[tuple[str, float]] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    cycle_index: int = 0

    @property
    def value(self) -> float:
        return self.values[0] if self.values else 0.0

    def is_simple(self) -> bool:
        return self.kind in ("button", "chord")


@dataclass
class TickResult:
    """一次 tick 的输出：两个摇杆位置 + 按钮事件。"""

    left: tuple[float, float] = (0.0, 0.0)
    right: tuple[float, float] = (0.0, 0.0)
    events: list[tuple[str, str]] = field(default_factory=list)


def parse_action(raw) -> Action:
    """把配置里的动作值解析成 Action，兼容字符串与字典两种写法。"""
    if isinstance(raw, str):
        return Action(kind="button", buttons=[raw.strip().upper()])
    if not isinstance(raw, dict):
        raise ValueError(f"无法识别的动作：{raw!r}")
    if "chord" in raw:
        buttons = [str(item).strip().upper() for item in raw["chord"]]
        return Action(kind="chord", buttons=buttons)
    if "sequence" in raw:
        steps: list[tuple[str, float]] = []
        for step in raw["sequence"]:
            if isinstance(step, (list, tuple)) and step:
                button = str(step[0]).strip().upper()
                hold = float(step[1]) if len(step) > 1 else DEFAULT_STEP_HOLD
            else:
                button = str(step).strip().upper()
                hold = DEFAULT_STEP_HOLD
            steps.append((button, hold))
        return Action(kind="sequence", steps=steps)
    if "stick" in raw:
        raw_values = raw["stick"]
        if isinstance(raw_values, (int, float)):
            candidates = [float(raw_values)]
        elif isinstance(raw_values, (list, tuple)):
            candidates = [float(item) for item in raw_values]
        else:
            raise ValueError(f"无法识别的摇杆幅度：{raw_values!r}")
        values = [max(0.05, min(1.0, item)) for item in candidates]
        if not values:
            raise ValueError("摇杆幅度不能为空")
        return Action(kind="stick", values=values)
    if "button" in raw:
        return Action(kind="button", buttons=[str(raw["button"]).strip().upper()])
    raise ValueError(f"无法识别的动作：{raw!r}")


# 键名别名：Win32 钩子区分左右键（ctrl_l/ctrl_r），而用户配置里常写 ctrl。
# 精确匹配优先，找不到再按别名回落，避免“按了 Ctrl 但没反应”。
KEY_ALIASES = {
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt_l": "alt",
    "alt_r": "alt",
    "shift_r": "shift",
    "cmd": "win",
    "cmd_r": "win",
}


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _move_toward(current: float, target: float, step: float) -> float:
    """把 current 朝 target 移动 step，不越过目标（左摇杆斜坡用）。"""
    if current < target:
        return min(current + step, target)
    return max(current - step, target)


def _resolve_curve(value: float, curve: float) -> float:
    """把线性速度套上响应曲线，保留符号（power 曲线用）。"""
    if value == 0.0:
        return 0.0
    magnitude = abs(value) ** curve
    return math.copysign(min(magnitude, 1.0), value)


def _apply_curve(value: float, curve_type: str, power: float) -> float:
    """按曲线类型做响应变换（业界常见：线性 / 二次 / 三次 / 幂）。"""
    if value == 0.0:
        return 0.0
    kind = (curve_type or "linear").lower()
    if kind == "quadratic":
        return value * abs(value)
    if kind == "cubic":
        return value * value * value
    if kind == "power":
        return _resolve_curve(value, max(0.1, power))
    return value


def _apply_anti_deadzone(value: float, deadzone: float, anti_deadzone: float) -> float:
    """反死区：把非零输入抬升到 anti_deadzone 以上。

    游戏对右摇杆有自己的死区（通常 0.1~0.2），我们输出的小值会被它吃掉，
    表现就是“小幅移动拖不动”。抬升后最小的输入也能被游戏看到，
    同时保留线性区间（DS4Windows / JoyShockMapper 的 anti-deadzone）。
    """
    if value == 0.0 or anti_deadzone <= 0.0:
        return value
    sign = 1.0 if value > 0 else -1.0
    magnitude = abs(value)
    span = max(1e-6, 1.0 - deadzone)
    normalized = max(0.0, min(1.0, (magnitude - deadzone) / span))
    return sign * (anti_deadzone + normalized * (1.0 - anti_deadzone))


def _segment_sensitivity(speed: float, mouse) -> float:
    """两段灵敏度插值：慢转和快转用不同灵敏度，中间线性过渡。

    这是 JoyShockMapper 的核心做法——慢速瞄准要精细，快速转身要够快。
    """
    slow_speed = float(mouse.slow_speed)
    fast_speed = max(float(mouse.fast_speed), slow_speed + 1.0)
    slow_sens = float(mouse.slow_sensitivity)
    fast_sens = float(mouse.fast_sensitivity)
    if speed <= slow_speed:
        return slow_sens
    if speed >= fast_speed:
        return fast_sens
    ratio = (speed - slow_speed) / (fast_speed - slow_speed)
    return slow_sens + (fast_sens - slow_sens) * ratio


class InputMapper:
    """把键鼠状态合成为手柄状态。

    使用方法：
        mapper.on_key("w", True)
        mapper.on_mouse_delta(3, -2)
        result = mapper.tick(dt_seconds)
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._lock = threading.RLock()
        self._keys: set[str] = set()
        self._mouse_buttons: set[str] = set()
        self._accum_dx = 0
        self._accum_dy = 0
        self._right_x = 0.0
        self._right_y = 0.0
        self._pressed: set[str] = set()
        # 位移换算窗口：Raw Input 的消息泵约 10ms 一批把位移送进来，
        # 按固定窗口累积再换算，速度才稳定（按 4ms 帧换算会放大 2.5 倍）
        self._accum_time = 0.0
        # Flick Stick 状态：满偏剩余时间与方向
        self._flick_remaining = 0.0
        self._flick_dir = 0.0
        self._left_value = max(0.05, min(1.0, config.left_stick.value))
        self._left_x = 0.0
        self._left_y = 0.0
        self._sequence = None
        self._sequence_buttons: set[str] = set()
        # 每个模式一套已解析的映射
        self._modes: dict[str, dict] = {}
        for name, mode in config.modes.items():
            self._modes[name] = {
                "keyboard_buttons": self._parse_binding_map(mode.keyboard_buttons),
                "mouse_buttons": self._parse_binding_map(mode.mouse_buttons),
                "keyboard_sticks": {
                    direction: {str(key).lower() for key in keys}
                    for direction, keys in mode.keyboard_sticks.items()
                },
            }
        if not self._modes:
            self._modes["default"] = {
                "keyboard_buttons": {},
                "mouse_buttons": {},
                "keyboard_sticks": {},
            }
        start_mode = (
            config.current_mode
            if config.current_mode in self._modes
            else "default"
        )
        self._apply_mode(start_mode)

    def _apply_mode(self, name: str) -> None:
        data = self._modes[name]
        self._keyboard_actions: dict[str, Action] = data["keyboard_buttons"]
        self._mouse_actions: dict[str, Action] = data["mouse_buttons"]
        self._stick_keys: dict[str, set[str]] = data["keyboard_sticks"]
        self._current_mode = name

    @property
    def mode(self) -> str:
        with self._lock:
            return self._current_mode

    @property
    def mode_names(self) -> list[str]:
        return list(self._modes)

    def set_mode(self, name: str, carry_movement: bool = False) -> bool:
        """切换映射模式；切换前清空按下的键，避免卡键。

        carry_movement：把「正按着的移动键」带到新模式里。自动切入驾驶时要用——
        你正按着 W 跑过去按 F 上车，切换瞬间把 W 松掉的话油门会掉一拍，
        玩家得抬手重按。只带目标模式的方向键（WASD 这类），不带其它按键，
        免得切换时把某个宏或按钮顺手点出来。
        """
        with self._lock:
            if name not in self._modes or name == self._current_mode:
                return False
            carried: set[str] = set()
            if carry_movement:
                movement: set[str] = set()
                for keys in self._modes[name]["keyboard_sticks"].values():
                    movement.update(keys)
                carried = self._keys & movement
            self._keys.clear()
            self._mouse_buttons.clear()
            self._sequence = None
            self._sequence_buttons.clear()
            self._apply_mode(name)
            # 移交给新模式后再放回按键集合：持续型按钮（油门 R2）下一帧就会接着按，
            # 松开时照常从这里移除
            self._keys.update(carried)
            return True

    @staticmethod
    def _parse_binding_map(raw_map: dict) -> dict[str, Action]:
        result: dict[str, Action] = {}
        for source, raw in raw_map.items():
            try:
                result[str(source).lower()] = parse_action(raw)
            except (ValueError, TypeError) as exc:
                _LOGGER.warning("忽略非法映射 %s = %r：%s", source, raw, exc)
        return result

    # ------------------------------------------------------------------ 输入
    def _canonical_key(self, name: str) -> str:
        """把钩子给出的键名折算成配置里实际使用的名字。"""
        if name in self._keyboard_actions:
            return name
        alias = KEY_ALIASES.get(name)
        if alias and alias in self._keyboard_actions:
            return alias
        return name

    def on_key(self, name: str, pressed: bool) -> None:
        name = self._canonical_key(name.lower())
        with self._lock:
            if pressed:
                if name in self._keys:
                    return  # 过滤键盘自动重复
                self._keys.add(name)
                self._dispatch_action(self._keyboard_actions.get(name), name)
            else:
                self._keys.discard(name)

    def on_mouse_button(self, name: str, pressed: bool) -> None:
        name = name.lower()
        with self._lock:
            if pressed:
                if name in self._mouse_buttons:
                    return
                self._mouse_buttons.add(name)
                self._dispatch_action(self._mouse_actions.get(name), name)
            else:
                self._mouse_buttons.discard(name)

    def _dispatch_action(self, action: Action | None, trigger: str) -> None:
        """按键按下的瞬间触发非持续型动作（序列 / 摇杆幅度）。"""
        if action is None:
            return
        if action.kind == "sequence":
            self._begin_sequence(action, trigger)
        elif action.kind == "stick" and action.values:
            self._left_value = self._next_stick_value(action)

    def _next_stick_value(self, action: Action) -> float:
        """按一下「摇杆幅度」键之后的新幅度。

        多档时以**当前值**为锚点往后走：默认 1.0、档位写成 ``[1.0, 0.3]``，第一下直接
        切到 0.3，不会先「设成 1.0」白按一次。当前值不在档位里（被别的按键或旧预设改过）
        才退回按轮转下标取下一个。
        """
        values = action.values
        try:
            current = values.index(self._left_value)
        except ValueError:
            # 不知道现在在哪一档：按顺序从第一个开始，和旧行为一致
            index = action.cycle_index % len(values)
            action.cycle_index = (index + 1) % len(values)
            return values[index]
        index = (current + 1) % len(values)
        action.cycle_index = index
        return values[index]

    def on_mouse_delta(self, dx: int, dy: int) -> None:
        with self._lock:
            self._accum_dx += dx
            self._accum_dy += dy

    def set_left_value(self, value: float) -> float:
        """设置左摇杆最大输出幅度（0.05~1.0），返回实际生效值。"""
        with self._lock:
            self._left_value = max(0.05, min(1.0, float(value)))
            return self._left_value

    @property
    def left_value(self) -> float:
        with self._lock:
            return self._left_value

    # ------------------------------------------------------------------ 输出
    def tick(self, dt_seconds: float) -> TickResult:
        """合成一帧输出。dt_seconds 用于鼠标速度换算与序列推进。"""
        # 下限 2ms：某帧 sleep 提前返回时 dt 过小会把速度放大成满偏
        dt = max(dt_seconds, 0.002)
        with self._lock:
            left = self._compute_left_stick(dt)
            right = self._compute_right_stick(dt)
            self._advance_sequence(dt)
            events = self._compute_button_events()
        return TickResult(left=left, right=right, events=events)

    def drop_missing(self, active: set[str]) -> None:
        """清理不在 active 里的残留按键。

        多路监听偶发丢失 keyup 时，_keys 会残留某个键（表现为“按 A 却向右走”）。
        由上层定期传入真正的按下集合来校正。
        """
        with self._lock:
            stale = self._keys - active
            if not stale:
                return
            for key in stale:
                self._keys.discard(key)
                _LOGGER.debug("清理残留按键：%s", key)

    def release_all(self) -> list[tuple[str, str]]:
        """清空所有输入并返回需要释放的按钮事件（关闭捕获时用）。"""
        with self._lock:
            self._keys.clear()
            self._mouse_buttons.clear()
            self._accum_dx = 0
            self._accum_dy = 0
            self._right_x = 0.0
            self._right_y = 0.0
            self._sequence = None
            self._sequence_buttons.clear()
            events = [(name, "release") for name in sorted(self._pressed)]
            self._pressed.clear()
        return events

    @property
    def pressed_buttons(self) -> set[str]:
        with self._lock:
            return set(self._pressed)

    # -------------------------------------------------------------- 内部实现
    def _compute_left_stick(self, dt: float) -> tuple[float, float]:
        x = float(self._pressed_direction("right") - self._pressed_direction("left"))
        y = float(self._pressed_direction("down") - self._pressed_direction("up"))
        if x and y:
            x /= math.sqrt(2.0)
            y /= math.sqrt(2.0)
        target_x = x * self._left_value
        target_y = y * self._left_value
        # 斜坡过渡：短按只到小幅度，长按才推满。ramp=0 时退化为瞬时到位。
        ramp = self._config.left_stick.ramp
        if ramp <= 0.0:
            self._left_x, self._left_y = target_x, target_y
        else:
            step = ramp * dt
            self._left_x = _move_toward(self._left_x, target_x, step)
            self._left_y = _move_toward(self._left_y, target_y, step)
        return self._left_x, self._left_y

    def _pressed_direction(self, direction: str) -> bool:
        return any(key in self._keys for key in self._stick_keys.get(direction, ()))

    def _compute_right_stick(self, dt: float) -> tuple[float, float]:
        mouse = self._config.mouse
        if not mouse.enabled:
            # 鼠标视角总开关关闭：右摇杆保持中位，其他输入不受影响
            self._accum_dx = 0
            self._accum_dy = 0
            self._accum_time = 0.0
            self._right_x = 0.0
            self._right_y = 0.0
            return 0.0, 0.0
        # 按固定窗口累积位移再换算：Raw Input 约 10ms 一批，窗口对齐后
        # 速度稳定；窗口未满时保持上一次的摇杆值。
        self._accum_time += dt
        if self._accum_time < MOUSE_WINDOW_SECONDS:
            return self._right_x, self._right_y
        span = self._accum_time
        speed_x = self._accum_dx / span
        speed_y = self._accum_dy / span
        self._accum_dx = 0
        self._accum_dy = 0
        self._accum_time = 0.0

        # Flick Stick：水平速度超过阈值就满偏一小段，产生“瞬间转身”
        # （Jibb Smart 的思路——绕开摇杆的速度控制特性）
        if mouse.flick_enabled and abs(speed_x) >= mouse.flick_threshold:
            self._flick_dir = 1.0 if speed_x > 0 else -1.0
            self._flick_remaining = mouse.flick_duration
        if self._flick_remaining > 0.0:
            self._flick_remaining -= dt
            if self._flick_remaining > 0.0:
                self._right_x = self._flick_dir
                self._right_y = 0.0
                return self._right_x, self._right_y
            # 时间到，落到下面的正常换算

        # 两段灵敏度：按合速度插值出当前应有的灵敏度倍率
        speed = math.hypot(speed_x, speed_y)
        segment = _segment_sensitivity(speed, mouse)
        gain = (mouse.sensitivity * segment) / SPEED_BASE_PX_PER_SEC
        target_x = _clamp(speed_x * gain)
        target_y = _clamp(speed_y * gain)
        if mouse.invert_y:
            target_y = -target_y

        target_x = _apply_curve(target_x, mouse.curve_type, mouse.curve)
        target_y = _apply_curve(target_y, mouse.curve_type, mouse.curve)
        if abs(target_x) < mouse.deadzone:
            target_x = 0.0
        if abs(target_y) < mouse.deadzone:
            target_y = 0.0
        target_x = _apply_anti_deadzone(
            target_x, mouse.deadzone, mouse.anti_deadzone
        )
        target_y = _apply_anti_deadzone(
            target_y, mouse.deadzone, mouse.anti_deadzone
        )

        if mouse.smoothing > 0:
            alpha = 1.0 - min(mouse.smoothing, 0.95)
            self._right_x += (target_x - self._right_x) * alpha
            self._right_y += (target_y - self._right_y) * alpha
        else:
            self._right_x, self._right_y = target_x, target_y
        return self._right_x, self._right_y

    def _compute_button_events(self) -> list[tuple[str, str]]:
        target: set[str] = set(self._sequence_buttons)
        for key in self._keys:
            action = self._keyboard_actions.get(key)
            if action is not None and action.is_simple():
                target.update(action.buttons)
        for button in self._mouse_buttons:
            action = self._mouse_actions.get(button)
            if action is not None and action.is_simple():
                target.update(action.buttons)
        target = {name for name in target if name in VALID_BUTTONS}

        events: list[tuple[str, str]] = []
        for name in sorted(target - self._pressed):
            events.append((name, "press"))
        for name in sorted(self._pressed - target):
            events.append((name, "release"))
        self._pressed = target
        return events

    def _begin_sequence(self, action: Action, trigger: str) -> None:
        """开始执行序列宏；新序列会打断旧序列并释放其残留按钮。"""
        if not action.steps:
            return
        self._sequence = {
            "steps": action.steps,
            "index": 0,
            "elapsed": 0.0,
            "entered": False,
            "trigger": trigger,
        }
        self._sequence_buttons.clear()

    def _advance_sequence(self, dt: float) -> None:
        sequence = self._sequence
        if sequence is None:
            return
        sequence["elapsed"] += dt
        button, hold = sequence["steps"][sequence["index"]]
        if not sequence["entered"]:
            self._sequence_buttons.add(button)
            sequence["entered"] = True
        if sequence["elapsed"] < hold:
            return
        self._sequence_buttons.discard(button)
        sequence["index"] += 1
        sequence["elapsed"] = 0.0
        sequence["entered"] = False
        if sequence["index"] >= len(sequence["steps"]):
            self._sequence = None
