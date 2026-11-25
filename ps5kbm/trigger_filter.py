"""L2/R2 扳机值过滤器（PS5 Remote Play 专用）。

参考实现：Veyra-NRVideo 的 `include/veyra/remoteplay/TriggerFilter.h`，
它描述的问题和我们实机遇到的一模一样：

    每次扳机值变化都会生成一条 feedback-history 事件，而每个 history 包
    只带最新的 8 条事件。手柄每 4ms 提交一次，扳机的一两步抖动（扳机磨损
    或游戏的自适应扳机震动）就会刷出连续事件。当一侧松开、另一侧还按着时，
    这股事件流会在约 30ms 内把"松开"挤出 8 条窗口；若那几个包丢了，
    主机就永远看不到松开，会一直认为扳机按着（实机现象：按着 L2 和 R2，
    L2 松不开；再按一下 L2 才松开）。

过滤规则（不改变手感）：
1. **端点吸附**：距 0 或 255 不到 DEADZONE 的读数直接归到端点；
2. **中间区间按步长发送**：与上次发送值相差不到 STEP 就不发；0 / 255 / 首次按下立即发；
3. **松手后短暂抬阈值**：一侧松开后 EDGE_HOLD 时间内，提高另一侧的变化阈值，
   让噪声不会把"松开"挤出 history 窗口；真实行程和两个端点仍然立即发送。

注意：这里的 DEADZONE 刻意取得很小（和参考实现一致），
否则浅踩油门这种小幅模拟量会被吞掉，驾驶手感会变差。
"""

from __future__ import annotations

DEADZONE = 6
STEP = 4
EDGE_HOLD = 0.12


class TriggerFilter:
    """把 0~255 的扳机读数变成"该发给主机"的稳定值。"""

    def __init__(self) -> None:
        self._sent = [0, 0]
        self._hold_until = [0.0, 0.0]

    def reset(self) -> None:
        """焦点丢失 / 设备断开后，下一次从"已松开"开始。"""
        self._sent = [0, 0]
        self._hold_until = [0.0, 0.0]

    @staticmethod
    def _snap(value: int) -> int:
        if value <= DEADZONE:
            return 0
        if value >= 255 - DEADZONE:
            return 255
        return value

    def apply(self, l2: int, r2: int, now: float) -> tuple[int, int]:
        """输入 0~255 的原始读数，返回本次应该发送的 (l2, r2)。"""
        raw = [self._snap(l2), self._snap(r2)]
        for index in (0, 1):
            other = 1 - index
            value = raw[index]
            sent = self._sent[index]
            if value == sent:
                continue
            if value == 0 or value == 255 or sent == 0:
                # 松开、满偏、首次按下：边沿，立即发送
                if value == 0 and sent != 0:
                    self._hold_until[other] = now + EDGE_HOLD
                self._sent[index] = value
                continue
            step = STEP * 2 if now < self._hold_until[index] else STEP
            if abs(value - sent) >= step:
                self._sent[index] = value
        return self._sent[0], self._sent[1]


def to_byte(value: float) -> int:
    """0.0~1.0 的扳机读数 → 0~255。"""
    return max(0, min(255, int(round(float(value) * 255))))
