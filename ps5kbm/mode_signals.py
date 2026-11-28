"""信号采集：把主机下发的反馈变成「一个个事实现在真不真」。

这一层只回答「事实」（``signal_rules.FACTS``），不知道模式、不知道规则：

* 扳机效果块（data_type 11）→ 两侧分类 + 每侧类型
* 经典马达震动（data_type 7）→ 0~1 的震动事件
* 触觉 PCM（3 kHz）→ 算 RMS 当能量
* 交互键（本机键盘，默认 f = 三角）→ 按下事件

**为什么扳机是「状态」而震动是「事件」**：主机只在变化时下发扳机效果，进车后可能几分钟
都没有新包，所以扳机的「最后一次上报值」就是当前状态，不能按时间窗口过期；震动 / 触觉 /
按键是「某个瞬间发生过」，只能用时间窗口。

键鼠玩法下这些数据照样会到，但我们只拿它判断，绝不写实体手柄（写手柄仍由
``app._pad_forward_active()`` 那道闸门管）。本模块不 import tkinter / hid，便于单测。
"""

from __future__ import annotations

import math
import struct
import time

from .signal_rules import FACT_HAPTICS, FACT_RUMBLE, sample_conditions

# 扳机效果块第 0 字节的有效类型。主机开车时发 0x21（阻力），有时发 0x05 但带非零
# 参数（HID 里 0x05 是 Off，实机验证它实际表示阻力，见 normalize_trigger_block）；
# 开枪时发 0x25。
TRIGGER_RESISTANCE = 0x21
TRIGGER_SHOOTING = 0x25
# 扳机效果块的固定长度（类型 1 字节 + 参数 10 字节）
TRIGGER_BLOCK_SIZE = 11

# 两种可识别的形态（GTA6 实测：不在车里两侧都是 Off；坐进车里两侧同时变成 0x21 0xFF 0x03）。
# 名字保留“foot/driving”是因为它们是在这个游戏里量出来的，但判定只看字节。
FOOT_TRIGGER_TYPE = 0x05
DRIVING_TRIGGER_PREFIX = bytes((0x21, 0xFF, 0x03))

# 一对扳机块的分类结果。这套分类只是**日志诊断**用（规则引擎按「类型 + 前缀 + 作用侧」
# 自己匹配，不看这个 id）：留它是为了在「该切模式却没切」时，日志里能一眼看出
# 主机这一包下发的到底是不是我们认识的那两种形态。
TRIGGER_PAIR_FOOT = "foot"
TRIGGER_PAIR_DRIVING = "driving"
TRIGGER_PAIR_OTHER = "other"

# 分类的显示名（日志用）。只说信号本身，不说「进车 / 步行」——那是某个游戏的故事，
# 换个游戏同样的 21 FF 03 可能是别的东西。
PAIR_LABELS = {
    TRIGGER_PAIR_FOOT: "两侧无效果 Off",
    TRIGGER_PAIR_DRIVING: "两侧阻力 FF03",
    TRIGGER_PAIR_OTHER: "其它",
}

# 事件型事实的有效期：震动/触觉下发频率远高于 3 Hz，0.4 秒只用来兜住抖动。
EVIDENCE_S = 0.4
# 震动阈值：静音时主机发 0，开车引擎震动常驻；0.12 能滤掉手柄收到的一声「咔」。
RUMBLE_MIN = 0.12
# 触觉 PCM 的归一化 RMS（s16 满量程 = 1.0）：开车时引擎低频持续，静音时接近 0。
HAPTICS_RMS_MIN = 0.02
# 按钮按下后的脉冲宽度：要覆盖「按三角 → 主机回包 → 扳机换成 Off」这段延迟。
BUTTON_PULSE_S = 3.0


# ------------------------------------------------------------------ 解析
def normalize_trigger_block(block: bytes) -> bytes:
    """把主机下发的扳机效果块改成我们实际要写的类型。

    主机在开车/刹车时发 0x05（HID 协议里是 Off）但带非零参数，实际含义是「反馈
    阻力」；实机验证改写成 0x21 后油门/刹车阻尼正常。写手柄与判断事实共用这一份规则。
    """
    if not block or len(block) != TRIGGER_BLOCK_SIZE:
        return bytes(block)
    if block[0] != FOOT_TRIGGER_TYPE or not any(block[1:]):
        return bytes(block)
    return bytes((TRIGGER_RESISTANCE,)) + bytes(block[1:])


def trigger_kind(block: bytes) -> str | None:
    """单块扳机效果是什么类型：``"drive"``（阻力）/ ``"shoot"``（射击）/ ``None``。

    参数全零的 ``0x21`` 视为「没设效果」；``0x05`` + 非零参数先改写成阻力再判断。
    """
    normalized = normalize_trigger_block(block)
    if len(normalized) != TRIGGER_BLOCK_SIZE or not any(normalized[1:]):
        return None
    kind = normalized[0]
    if kind == TRIGGER_RESISTANCE:
        return "drive"
    if kind == TRIGGER_SHOOTING:
        return "shoot"
    return None


def classify_trigger_pair(left: bytes, right: bytes) -> str:
    """把主机这一包下发的左右扳机块归成「两侧无效果 / 两侧阻力 FF03 / 其它」。

    只认两种形态，其它一律算「其它」（举枪、开镜、单侧效果都在这里）：

    * 两侧都是 Off（``0x05``，且改写规则之后参数全零）→ ``foot``
    * 两侧都以 ``0x21 0xFF 0x03`` 开头 → ``driving``

    先过 ``normalize_trigger_block``：主机有时把「阻力」发成 ``0x05`` + 非零参数，
    不先改写就会把有阻力的状态误当成无效果。
    """
    if len(left) != TRIGGER_BLOCK_SIZE or len(right) != TRIGGER_BLOCK_SIZE:
        return TRIGGER_PAIR_OTHER
    norm_left = normalize_trigger_block(left)
    norm_right = normalize_trigger_block(right)
    if norm_left[0] == FOOT_TRIGGER_TYPE and norm_right[0] == FOOT_TRIGGER_TYPE:
        return TRIGGER_PAIR_FOOT
    if norm_left.startswith(DRIVING_TRIGGER_PREFIX) and norm_right.startswith(
        DRIVING_TRIGGER_PREFIX
    ):
        return TRIGGER_PAIR_DRIVING
    return TRIGGER_PAIR_OTHER


def pcm_rms(pcm: bytes, max_samples: int = 256) -> float:
    """触觉 PCM 的能量（s16 小端、4 声道交织），归一化到 0~1。

    只取中间一段算：包边缘可能有淡入淡出，中间更能代表「有没有在震」。
    """
    total_bytes = len(pcm) - len(pcm) % 2
    if total_bytes < 2:
        return 0.0
    samples = total_bytes // 2
    count = min(max_samples, samples)
    start = (samples - count) // 2 * 2
    chunk = struct.unpack_from(f"<{count}h", pcm, start)
    energy = sum(sample * sample for sample in chunk)
    return math.sqrt(energy / count) / 32768.0


# ------------------------------------------------------------------ 事实
class SignalWatcher:
    """事实采集器：谁拿到数据谁喂（协议线程喂扳机/震动，解码线程喂触觉，
    输入线程喂交互键），判定在界面线程做。

    时间一律用 ``time.monotonic()``；测试里直接传 ``now``，不 sleep。
    """

    def __init__(
        self,
        evidence_s: float = EVIDENCE_S,
        button_pulse_s: float = BUTTON_PULSE_S,
    ) -> None:
        self._evidence_s = max(0.0, evidence_s)
        self._button_pulse_s = max(0.0, button_pulse_s)
        # 扳机：最后一次上报的两侧分类（诊断用）与原始块（规则按「类型+前缀+侧」匹配）
        self._pair = TRIGGER_PAIR_OTHER
        self._blocks: dict[str, bytes] = {"left": b"", "right": b""}
        # 事件型事实：最近一次发生的时间
        self._rumble_at = -math.inf
        self._haptics_at = -math.inf
        self._buttons: dict[str, float] = {}

    def reset(self) -> None:
        """会话断开 / 换玩法 / 换预设：全部忘掉，避免陈旧事实跨会话生效。"""
        self._pair = TRIGGER_PAIR_OTHER
        self._blocks = {"left": b"", "right": b""}
        self._rumble_at = -math.inf
        self._haptics_at = -math.inf
        self._buttons: dict[str, float] = {}

    # -------------------------------------------------------------- 采集
    @property
    def pair(self) -> str:
        """最后一次上报的扳机对分类（诊断 / 日志用）。"""
        return self._pair

    def note_button(self, name: str, now: float | None = None) -> None:
        """玩家按下了某个手柄按钮（由映射层翻译后的按钮名，例如 TRIANGLE）。"""
        self._buttons[str(name).strip().upper()] = (
            time.monotonic() if now is None else now
        )

    def button_active(self, name: str, now: float | None = None) -> bool:
        """这个按钮在脉冲窗口内被按过没有。"""
        moment = time.monotonic() if now is None else now
        return (
            moment - self._buttons.get(str(name).strip().upper(), -math.inf)
            <= self._button_pulse_s
        )

    def feed_trigger_effect(self, left: bytes, right: bytes) -> None:
        """喂主机下发的两块扳机效果（各 11 字节）。

        扳机是「最后一次上报的状态」，没有时间戳可记，所以不需要 ``now``。
        两块原样留着：规则里可以按「类型 + 参数前缀 + 作用侧」任意匹配。
        """
        self._pair = classify_trigger_pair(left, right)
        self._blocks["left"] = bytes(left)
        self._blocks["right"] = bytes(right)

    def trigger_blocks(self) -> tuple[bytes, bytes]:
        """最近一次上报的左右扳机块原文（日志诊断用）。"""
        return self._blocks["left"], self._blocks["right"]

    def feed_rumble(self, left: float, right: float, now: float | None = None) -> None:
        """喂主机下发的震动值（0~1）。"""
        if max(float(left), float(right)) < RUMBLE_MIN:
            return
        self._rumble_at = time.monotonic() if now is None else now

    def feed_haptics_pcm(self, pcm: bytes, now: float | None = None) -> None:
        """喂主机下发的触觉 PCM（3 kHz / s16 / 4 声道）。"""
        self.feed_haptics_energy(pcm_rms(pcm), now)

    def feed_haptics_energy(self, energy: float, now: float | None = None) -> None:
        """喂已经算好的触觉能量（0~1）。"""
        if energy < HAPTICS_RMS_MIN:
            return
        self._haptics_at = time.monotonic() if now is None else now

    # -------------------------------------------------------------- 查询
    def trigger_match(
        self,
        kind: str,
        code: int | None = None,
        prefix: str = "",
        side: str = "both",
        now: float | None = None,
    ) -> bool:
        """某一侧（或两侧）扳机现在是不是某种效果。

        ``kind``：``off`` / ``resistance`` / ``shoot`` / ``custom``（用 ``code``）；
        ``prefix``：参数前缀（小写 hex，空 = 不比参数）；
        ``side``：``both`` / ``any`` / ``left`` / ``right``。
        """
        left = self._side_matches(self._blocks["left"], kind, code, prefix)
        right = self._side_matches(self._blocks["right"], kind, code, prefix)
        if side == "both":
            return left and right
        if side == "any":
            return left or right
        if side == "left":
            return left
        if side == "right":
            return right
        return False

    @staticmethod
    def _side_matches(block: bytes, kind: str, code: int | None, prefix: str) -> bool:
        if len(block) != TRIGGER_BLOCK_SIZE:
            return False
        norm = normalize_trigger_block(block)
        # 前缀比的是「参数部分」（第 1 字节起），类型码单独比
        if prefix and not norm[1:].startswith(bytes.fromhex(prefix)):
            return False
        if kind == "off":
            return norm[0] == FOOT_TRIGGER_TYPE and not any(norm[1:])
        if kind == "custom":
            if code is None or norm[0] != code:
                return False
        else:
            expected = TRIGGER_RESISTANCE if kind == "resistance" else TRIGGER_SHOOTING
            if norm[0] != expected:
                return False
        # 只有类型码、参数全零 = 没设效果；带了前缀就以前缀为准
        return bool(any(norm[1:])) or bool(prefix)

    def is_true(self, fact_id: str, now: float | None = None) -> bool:
        """简单事实（震动 / 触觉）现在真不真。"""
        moment = time.monotonic() if now is None else now
        if fact_id == FACT_RUMBLE:
            return moment - self._rumble_at <= self._evidence_s
        if fact_id == FACT_HAPTICS:
            return moment - self._haptics_at <= self._evidence_s
        return False

    def snapshot(self, now: float | None = None) -> dict[str, bool]:
        """界面信号灯用：几条常见信号的当前值（标签 → 真假）。"""
        from . import signal_rules  # 局部导入：避免顶层循环依赖

        moment = time.monotonic() if now is None else now
        values: dict[str, bool] = {}
        for label, node in sample_conditions():
            try:
                values[label] = bool(signal_rules.parse_condition(node).evaluate(self, moment))
            except ValueError:
                values[label] = False
        return values
