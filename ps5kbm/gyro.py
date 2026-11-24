"""陀螺仪 → 右摇杆：纯计算，方便单测（不依赖 Tk / HID）。

坐标约定与 mapping.py 一致：x 正 = 右，y 正 = 下。
DualSense 陀螺仪给的是角速度（rad/s），这里按「角速度 → 摇杆偏转」换算：
转得越快摇杆推得越远，停下就回中，和 Steam 的 Gyro to Joystick 同思路。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 满偏对应的角速度（rad/s）。约 200°/s：转这么快时摇杆推到 1.0。
# 灵敏度是它的倍率，调到 0.5 就是需要 400°/s 才满偏。
FULL_DEFLECTION_RAD = 3.5
# 扳机按下多少算“按住”（L2/R2 既能当模拟量也能当激活键）
TRIGGER_PRESS_THRESHOLD = 0.2


def activation_pressed(
    activation: str,
    buttons: set[str] | frozenset[str],
    l2: float = 0.0,
    r2: float = 0.0,
) -> bool:
    """当前是否满足陀螺仪激活条件（纯函数，方便单测）。

    activation 可以是 "always" 或手柄按键名（l2 / l1 / r1 / cross…），
    按键名大小写不敏感；L2/R2 用模拟量阈值判断，其余看按钮位。
    """
    name = str(activation or "l2").strip().lower()
    if name == "always":
        return True
    if name == "l2":
        return l2 >= TRIGGER_PRESS_THRESHOLD
    if name == "r2":
        return r2 >= TRIGGER_PRESS_THRESHOLD
    return any(name == str(item).strip().lower() for item in buttons)


@dataclass(frozen=True)
class GyroParams:
    sensitivity_x: float = 1.0
    sensitivity_y: float = 1.0
    # 死区（rad/s）：小于它的角速度当 0，抵消手抖与静止漂移
    deadzone: float = 0.02
    # 一阶平滑：0 = 立刻到位，越大越顺但越滞后
    smoothing: float = 0.3
    invert_x: bool = False
    invert_y: bool = False


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    if deadzone <= 0.0:
        return value
    return 0.0 if abs(value) < deadzone else value


def smooth_toward(current: float, target: float, dt: float, smoothing: float) -> float:
    """一阶平滑：smoothing=0 立刻到位，越大越慢（时间常数 10ms~260ms）。"""
    smoothing = max(0.0, min(0.95, smoothing))
    if smoothing <= 0.0:
        return target
    tau = 0.01 + smoothing * 0.25
    alpha = 1.0 - math.exp(-max(dt, 0.0) / tau)
    return current + (target - current) * alpha


def gyro_stick_target(
    gyro: tuple[float, float, float] | list[float],
    bias: tuple[float, float, float] | list[float],
    params: GyroParams,
) -> tuple[float, float]:
    """角速度（rad/s）→ 右摇杆目标值。

    DualSense 的三轴：gyro[0]=pitch（前后），gyro[1]=yaw（左右），gyro[2]=roll（忽略）。
    实机标定（2026-11-24）：向右转 yaw 为负、抬头 pitch 为正，
    所以两个轴都取负号，方向才和"右转看右、抬头看上"一致。
    符号不确定时把 invert_x / invert_y 打开即可反向。
    """
    yaw = apply_deadzone(float(gyro[1]) - float(bias[1]), params.deadzone)
    pitch = apply_deadzone(float(gyro[0]) - float(bias[0]), params.deadzone)
    roll = apply_deadzone(float(gyro[2]) - float(bias[2]), params.deadzone)
    # 水平转向 = 水平转身(yaw) + 左右倾斜(roll)：
    # 有人习惯像摇头一样转身，有人习惯像转方向盘一样左右倾斜，两种都算。
    # 实机标定：向右转身 yaw 为负、向右倾斜 roll 为负（roll 与 yaw 同向），
    # 所以两项都取负号才对得上「右转 = 视角向右」。
    turn = -yaw - roll
    x = (turn / FULL_DEFLECTION_RAD) * params.sensitivity_x
    y = -(pitch / FULL_DEFLECTION_RAD) * params.sensitivity_y
    if params.invert_x:
        x = -x
    if params.invert_y:
        y = -y
    return clamp(x), clamp(y)


class GyroAxis:
    """有状态的平滑器：每帧 update 一次，返回本帧右摇杆贡献。

    active=False（比如没按住 L2）时立即归零，避免松手后视角还在漂。
    """

    def __init__(self) -> None:
        self._x = 0.0
        self._y = 0.0

    def reset(self) -> None:
        self._x = 0.0
        self._y = 0.0

    @property
    def value(self) -> tuple[float, float]:
        return self._x, self._y

    def update(
        self,
        gyro: tuple[float, float, float] | list[float],
        bias: tuple[float, float, float] | list[float],
        params: GyroParams,
        dt: float,
        active: bool,
    ) -> tuple[float, float]:
        if not active:
            self._x = 0.0
            self._y = 0.0
            return 0.0, 0.0
        target_x, target_y = gyro_stick_target(gyro, bias, params)
        self._x = clamp(smooth_toward(self._x, target_x, dt, params.smoothing))
        self._y = clamp(smooth_toward(self._y, target_y, dt, params.smoothing))
        return self._x, self._y


def calibrate_bias(
    samples: list[tuple[float, float, float]] | list[list[float]],
) -> tuple[float, float, float]:
    """多帧静止采样求零偏（取平均）。没有样本时返回 0。"""
    if not samples:
        return (0.0, 0.0, 0.0)
    count = float(len(samples))
    return (
        sum(float(item[0]) for item in samples) / count,
        sum(float(item[1]) for item in samples) / count,
        sum(float(item[2]) for item in samples) / count,
    )


def calibrate_bias_robust(
    samples: list[tuple[float, float, float]] | list[list[float]],
    trim: float = 0.2,
) -> tuple[float, float, float]:
    """稳健零偏：每轴去掉两端各 trim 比例的样本再平均，避免偶发抖动拉偏。"""
    if not samples:
        return (0.0, 0.0, 0.0)
    cut = int(len(samples) * max(0.0, min(0.45, trim)))
    means = []
    for axis in range(3):
        values = sorted(float(item[axis]) for item in samples)
        if cut:
            values = values[cut:-cut]
        means.append(sum(values) / len(values))
    return (means[0], means[1], means[2])


def bias_spread(samples: list[tuple[float, float, float]] | list[list[float]]) -> float:
    """采样期间的抖动程度：三轴标准差取最大，用来判断校准是否放稳。"""
    if len(samples) < 2:
        return 0.0
    mean = calibrate_bias(samples)
    count = float(len(samples))
    variance = [
        sum((float(item[axis]) - mean[axis]) ** 2 for item in samples) / count
        for axis in range(3)
    ]
    return max(math.sqrt(value) for value in variance)
