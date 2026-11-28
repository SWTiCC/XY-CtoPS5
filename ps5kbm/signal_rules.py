"""条件语言：事实表 + 条件树（节点）+ 解析 / 渲染。

这一层只回答「一组条件现在成不成立」，不知道模式、不知道去抖、不知道配置文件：

1. **事实**（见 ``FACTS``）：扳机 / 震动 / 触觉 / 交互键这些「主机告诉我们的东西」，
   由 ``mode_signals.SignalWatcher`` 采集。本模块只问它「这个事实现在真不真」。
2. **条件树**：``fact`` / ``all`` / ``any`` / ``not`` / ``hold`` / ``latch`` / ``before``
   七种节点，可任意嵌套，纯逻辑、无 IO。

「什么时候切、切到哪」在 ``rule_engine.py``；采集在 ``mode_signals.py``。

为什么不用时间窗口「续命」：主机只在**变化时**下发扳机效果，进车后可能几分钟没有新包。
所以扳机类事实取「最后一次上报的状态」（持久），震动 / 触觉 / 按键才用时间窗口。

本模块不 import tkinter / hid / config，时间一律由调用方传 ``now``（``time.monotonic()``），
便于单测。设计取舍见 ``docs/plans/2026-11-29-信号规则引擎.md``。
"""

from __future__ import annotations

# 去抖默认值：进入要连续成立这么久才切；退出要连续成立这么久才回默认。
# 预设里的 auto_hold / auto_release 会覆盖它们，新规则默认继承这两个值。
DEFAULT_ENTER_HOLD_S = 0.8
DEFAULT_LEAVE_DELAY_S = 1.2

# ---------------------------------------------------------------- 叶子信号
# 叶子按「信号类型」分，不绑定任何具体游戏特征：
#   trigger   扳机效果：类型（Off / 阻力 / 射击 / 自定义码）+ 参数前缀 + 作用侧
#   rumble    主机在震（马达）
#   haptics   主机在推音频触觉
#   button    手柄按钮按下（△ / ✕ / ○ / □ / L1…）
# 所以「GTA6 开车」不是一个特例，而是「阻力 + 前缀 FF 03 + 两侧」这样一条普通条件。
FACT_RUMBLE = "rumble"
FACT_HAPTICS = "haptics"
# 老格式的「交互键按下」：现在翻译成「按钮 △ 按下」
FACT_INTERACT = "interact"

# 简单事实表：id → 界面显示名 + 说明 + 是哪一类（pulse 有时效）
FACTS: dict[str, dict] = {
    FACT_RUMBLE: {
        "label": "震动（马达）",
        "hint": "主机在震动手柄；引擎、撞击、后坐力都算，最容易误判",
        "kind": "pulse",
    },
    FACT_HAPTICS: {
        "label": "触觉震动（音频触觉）",
        "hint": "主机在推 3kHz 触觉音频：开车时通常是持续的引擎低频",
        "kind": "pulse",
    },
}

# 手柄按钮：名字必须和 mapping.VALID_BUTTONS 完全一致（有单测守着，防止两处漂移）
BUTTON_LABELS: dict[str, str] = {
    "CROSS": "✕",
    "CIRCLE": "○",
    "SQUARE": "□",
    "TRIANGLE": "△",
    "L1": "L1",
    "R1": "R1",
    "L2": "L2",
    "R2": "R2",
    "L3": "L3",
    "R3": "R3",
    "UP": "十字↑",
    "DOWN": "十字↓",
    "LEFT": "十字←",
    "RIGHT": "十字→",
    "OPTIONS": "OPTIONS",
    "SHARE": "SHARE",
    "PS": "PS",
    "TOUCHPAD": "触摸板",
}
BUTTON_DEFAULT = "TRIANGLE"

# 扳机效果类型：id → 显示名（自定义时才用 code）
TRIGGER_KINDS: dict[str, str] = {
    "off": "无效果（Off 0x05）",
    "resistance": "阻力（0x21）",
    "shoot": "射击（0x25）",
    "custom": "自定义类型码",
}
# 作用侧：哪几侧要匹配
TRIGGER_SIDES: dict[str, str] = {
    "both": "两侧都要",
    "any": "任一侧",
    "left": "仅左侧（L2）",
    "right": "仅右侧（R2）",
}
TRIGGER_DEFAULT = {"kind": "resistance", "prefix": "", "side": "both"}
# 渲染/日志用的短名
TRIGGER_KIND_SHORT = {
    "off": "无效果",
    "resistance": "阻力",
    "shoot": "射击",
    "custom": "自定义",
}
TRIGGER_SIDE_LABEL = {
    "both": "两侧",
    "any": "任一侧",
    "left": "左侧",
    "right": "右侧",
}

# 节点类型 → 界面显示名（编辑器按这张表生成下拉，新增节点只要加一行）
NODE_LABELS: dict[str, str] = {
    "trigger": "扳机效果",
    "button": "按钮按下",
    "rumble": "震动（马达）",
    "haptics": "触觉震动",
    "all": "全部满足",
    "any": "任一满足",
    "not": "取反",
    "hold": "持续一段时间",
    "latch": "锁存",
    "before": "先后",
}  # 注：前四行是叶子，「全部满足」这类是组合节点

# 老格式：固定的事实 id。只在解析时翻译，写回时一律用新写法。
# 老格式的固定事实 id：只在解析旧配置时用到（写回一律变成参数化叶子）
FACT_TRIGGER_OFF = "trigger.off"
FACT_TRIGGER_VEHICLE = "trigger.vehicle"
FACT_TRIGGER_DRIVE = "trigger.drive"
FACT_TRIGGER_DRIVE_BOTH = "trigger.drive_both"
FACT_TRIGGER_SHOOT = "trigger.shoot"

_LEGACY_FACT_CONDITIONS: dict[str, dict] = {
    FACT_TRIGGER_OFF: {"type": "trigger", "kind": "off", "prefix": "", "side": "both"},
    FACT_TRIGGER_VEHICLE: {
        "type": "trigger",
        "kind": "resistance",
        "prefix": "ff03",
        "side": "both",
    },
    FACT_TRIGGER_DRIVE: {"type": "trigger", "kind": "resistance", "prefix": "", "side": "any"},
    FACT_TRIGGER_DRIVE_BOTH: {
        "type": "trigger",
        "kind": "resistance",
        "prefix": "",
        "side": "both",
    },
    FACT_TRIGGER_SHOOT: {"type": "trigger", "kind": "shoot", "prefix": "", "side": "any"},
    FACT_RUMBLE: {"type": "rumble"},
    FACT_HAPTICS: {"type": "haptics"},
    FACT_INTERACT: {"type": "button", "name": BUTTON_DEFAULT},
}

# 去抖上限：手滑输个 999 秒会让人以为坏了
_MAX_DELAY_S = 10.0


def is_known_fact(fact_id: str) -> bool:
    return fact_id in FACTS


def fact_label(fact_id: str) -> str:
    spec = FACTS.get(fact_id)
    return spec["label"] if spec else fact_id


def fact_hint(fact_id: str) -> str:
    spec = FACTS.get(fact_id)
    return spec["hint"] if spec else ""


def fact_ids() -> list[str]:
    return list(FACTS)


def sample_conditions() -> list[tuple[str, dict]]:
    """实时信号灯要显示哪几条：几条常见的扳机形态 + 三个简单事实。"""
    return [
        (
            "两侧 Off",
            {"type": "trigger", "kind": "off", "prefix": "", "side": "both"},
        ),
        (
            "左侧阻力",
            {"type": "trigger", "kind": "resistance", "prefix": "", "side": "left"},
        ),
        (
            "右侧阻力",
            {"type": "trigger", "kind": "resistance", "prefix": "", "side": "right"},
        ),
        (
            "任一侧射击",
            {"type": "trigger", "kind": "shoot", "prefix": "", "side": "any"},
        ),
        (fact_label(FACT_RUMBLE), {"type": "rumble"}),
        (fact_label(FACT_HAPTICS), {"type": "haptics"}),
        (f"按钮 {BUTTON_LABELS[BUTTON_DEFAULT]} 按下", {"type": "button", "name": BUTTON_DEFAULT}),
    ]


def normalize_prefix(value) -> str:
    """参数前缀统一成小写 hex 字符串：``"FF 03"`` → ``"ff03"``，非法字符直接丢掉。"""
    text = str(value or "").strip().lower().replace(" ", "").replace("0x", "")
    if not text:
        return ""
    if any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"参数前缀只能是十六进制：{value!r}")
    if len(text) > 2 * 10:
        raise ValueError("参数前缀太长（最多 10 字节）")
    return text


# ---------------------------------------------------------------- 条件树
class Condition:
    """条件节点：``evaluate`` 求值，``reset`` 忘掉内部状态（换会话时用）。

    实现约定：**同一 tick 内每个节点只求值一次**，因为 ``hold`` / ``latch`` / ``before``
    都靠 ``evaluate`` 推进状态。组合节点因此不做短路求值（见 ``AllCondition``）。
    """

    def evaluate(self, facts, now: float) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError

    def reset(self) -> None:  # pragma: no cover - 抽象
        pass


class TriggerCondition(Condition):
    """叶子：某一侧（或两侧）扳机是不是某种效果。

    ``kind``：``off`` / ``resistance`` / ``shoot`` / ``custom``（此时用 ``code``）；
    ``prefix``：参数前缀（小写 hex，空 = 不比参数）；
    ``side``：``both`` / ``any`` / ``left`` / ``right``。
    """

    def __init__(
        self,
        kind: str,
        prefix: str = "",
        side: str = "both",
        code: int | None = None,
    ) -> None:
        self.kind = kind
        self.prefix = prefix
        self.side = side
        self.code = code

    def evaluate(self, facts, now: float) -> bool:
        return bool(facts.trigger_match(self.kind, self.code, self.prefix, self.side))

    def label(self) -> str:
        kind = TRIGGER_KIND_SHORT.get(self.kind, self.kind)
        if self.kind == "custom" and self.code is not None:
            kind = f"类型 0x{self.code:02X}"
        head = f"{TRIGGER_SIDE_LABEL.get(self.side, self.side)}{kind}"
        if self.prefix:
            head += f"·{self.prefix.upper()}"
        return f"扳机：{head}"


class SimpleCondition(Condition):
    """叶子：震动 / 触觉这类不带参数的信号。"""

    def __init__(self, fact_id: str) -> None:
        self.fact_id = fact_id

    def evaluate(self, facts, now: float) -> bool:
        return bool(facts.is_true(self.fact_id, now))

    def label(self) -> str:
        return fact_label(self.fact_id)


class ButtonCondition(Condition):
    """叶子：某个手柄按钮最近被按过（脉冲窗口内）。

    用**手柄按钮**而不是键盘键：应用本来就把键盘翻译成按钮，按钮名不会再随键位变化，
    所以规则不用再跟着改键去同步。
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def evaluate(self, facts, now: float) -> bool:
        return bool(facts.button_active(self.name, now))

    def label(self) -> str:
        return f"按钮 {BUTTON_LABELS.get(self.name, self.name)} 按下"


class AllCondition(Condition):
    """全部子条件为真。

    故意**不短路**：后面的 ``hold`` / ``latch`` 也要每 tick 推进状态，否则它们会在
    「前一个条件刚变成真」的那一刻才开始计时，行为会随书写顺序变化。
    """

    def __init__(self, children: list[Condition]) -> None:
        self.children = children

    def evaluate(self, facts, now: float) -> bool:
        results = [child.evaluate(facts, now) for child in self.children]
        return all(results)

    def reset(self) -> None:
        for child in self.children:
            child.reset()


class AnyCondition(Condition):
    """任一子条件为真（同样不短路，理由见 ``AllCondition``）。"""

    def __init__(self, children: list[Condition]) -> None:
        self.children = children

    def evaluate(self, facts, now: float) -> bool:
        results = [child.evaluate(facts, now) for child in self.children]
        return any(results)

    def reset(self) -> None:
        for child in self.children:
            child.reset()


class NotCondition(Condition):
    """取反。"""

    def __init__(self, child: Condition) -> None:
        self.child = child

    def evaluate(self, facts, now: float) -> bool:
        return not self.child.evaluate(facts, now)

    def reset(self) -> None:
        self.child.reset()


class HoldCondition(Condition):
    """子条件连续为真满 ``seconds`` 秒才算成立（去抖）。"""

    def __init__(self, child: Condition, seconds: float) -> None:
        self.child = child
        self.seconds = max(0.0, float(seconds))
        self._since: float | None = None

    def evaluate(self, facts, now: float) -> bool:
        if not self.child.evaluate(facts, now):
            self._since = None
            return False
        if self._since is None:
            self._since = now
        return now - self._since >= self.seconds

    def reset(self) -> None:
        self._since = None
        self.child.reset()


class LatchCondition(Condition):
    """锁存：``set`` 成立后一直为真，直到 ``clear`` 成立。

    **clear 优先**：同一 tick 两者都成立时按清除处理——「按了交互键、扳机也回到 Off」
    这一刻就该下车，不能因为置位也成立又锁回去。
    """

    def __init__(self, set_condition: Condition, clear_condition: Condition | None) -> None:
        self.set_condition = set_condition
        self.clear_condition = clear_condition
        self._state = False

    def evaluate(self, facts, now: float) -> bool:
        want_set = self.set_condition.evaluate(facts, now)
        want_clear = (
            self.clear_condition.evaluate(facts, now)
            if self.clear_condition is not None
            else False
        )
        if want_clear:
            self._state = False
        elif want_set:
            self._state = True
        return self._state

    def reset(self) -> None:
        self._state = False
        self.set_condition.reset()
        if self.clear_condition is not None:
            self.clear_condition.reset()


class BeforeCondition(Condition):
    """先后：``first`` 出现过，之后 ``then`` 为真（每次会话只记一次）。"""

    def __init__(self, first: Condition, then: Condition) -> None:
        self.first = first
        self.then = then
        self._seen = False

    def evaluate(self, facts, now: float) -> bool:
        if self.first.evaluate(facts, now):
            self._seen = True
        return self._seen and bool(self.then.evaluate(facts, now))

    def reset(self) -> None:
        self._seen = False
        self.first.reset()
        self.then.reset()


def parse_condition(raw) -> Condition:
    """把 JSON 节点编译成 ``Condition``；结构不对抛 ``ValueError``。

    配置容错的分界线就在这里：调用方（``parse_rules``）捕获异常并丢弃整条规则，
    绝不吞掉错误继续跑半棵树。
    """
    if not isinstance(raw, dict):
        raise ValueError("条件必须是对象")
    kind = raw.get("type")
    if kind == "fact":  # 老写法：固定事实 id，翻译成参数化叶子
        return parse_condition(_legacy_condition(raw))
    if kind == "trigger":
        return _parse_trigger(raw)
    if kind == "button":
        return ButtonCondition(_parse_button(raw.get("name")))
    if kind == "interact":  # 老写法：交互键 → 按钮 △
        return ButtonCondition(BUTTON_DEFAULT)
    if kind in FACTS:  # rumble / haptics
        return SimpleCondition(kind)
    if kind in ("all", "any"):
        children = raw.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError(f"{kind} 至少要有一个子条件")
        built = [parse_condition(child) for child in children]
        return AllCondition(built) if kind == "all" else AnyCondition(built)
    if kind == "not":
        return NotCondition(parse_condition(raw.get("child")))
    if kind == "hold":
        seconds = raw.get("seconds", 0.0)
        return HoldCondition(parse_condition(raw.get("child")), clamp_seconds(seconds))
    if kind == "latch":
        clear = raw.get("clear")
        return LatchCondition(
            parse_condition(raw.get("set")),
            parse_condition(clear) if clear else None,
        )
    if kind == "before":
        return BeforeCondition(parse_condition(raw.get("first")), parse_condition(raw.get("then")))
    raise ValueError(f"未知节点类型：{kind!r}")


def _legacy_condition(raw) -> dict:
    """老 ``fact`` 节点 → 新写法；不认识的 id 抛 ValueError。"""
    fact_id = str(raw.get("fact", "")).strip()
    replacement = _LEGACY_FACT_CONDITIONS.get(fact_id)
    if replacement is None:
        raise ValueError(f"未知信号：{fact_id!r}")
    return dict(replacement)


def _parse_button(value) -> str:
    name = str(value or "").strip().upper()
    if not name:
        return BUTTON_DEFAULT
    if name not in BUTTON_LABELS:
        raise ValueError(f"未知手柄按钮：{value!r}")
    return name


def _parse_trigger(raw) -> TriggerCondition:
    kind = str(raw.get("kind", TRIGGER_DEFAULT["kind"]) or "").strip().lower()
    if kind not in TRIGGER_KINDS:
        raise ValueError(f"未知扳机类型：{kind!r}")
    side = str(raw.get("side", TRIGGER_DEFAULT["side"]) or "").strip().lower()
    if side not in TRIGGER_SIDES:
        raise ValueError(f"未知作用侧：{side!r}")
    prefix = normalize_prefix(raw.get("prefix"))
    if kind == "off" and prefix:
        raise ValueError("Off 没有参数，前缀要留空")
    code: int | None = None
    if kind == "custom":
        code = parse_code(raw.get("code"))
        if code is None:
            raise ValueError("自定义类型码必须是 0~255 的整数")
    return TriggerCondition(kind=kind, prefix=prefix, side=side, code=code)


def parse_code(value) -> int | None:
    """自定义类型码：接受 33 / "0x21" / "21"（hex）。"""
    if isinstance(value, int):
        return value if 0 <= value <= 255 else None
    text = str(value or "").strip().lower().replace("0x", "")
    if not text:
        return None
    try:
        code = int(text, 16)
    except ValueError:
        return None
    return code if 0 <= code <= 255 else None


def normalize_condition(raw) -> dict:
    """把条件树规范成新写法（老的 ``fact`` 节点会被翻译）。

    写盘前用它：老规则集第一次被保存就会升级成参数化形式，不必让用户手动迁移。
    结构不对会抛 ``ValueError``（与 ``parse_condition`` 一致）。
    """
    parse_condition(raw)  # 先校验，坏结构直接抛
    return _normalize_node(raw)


def _normalize_node(raw) -> dict:
    kind = raw.get("type")
    if kind == "fact":
        return _normalize_node(_legacy_condition(raw))
    if kind == "trigger":
        node = {
            "type": "trigger",
            "kind": str(raw.get("kind", TRIGGER_DEFAULT["kind"]) or "").strip().lower(),
            "prefix": normalize_prefix(raw.get("prefix")),
            "side": str(raw.get("side", TRIGGER_DEFAULT["side"]) or "").strip().lower(),
        }
        if node["kind"] == "custom":
            node["code"] = parse_code(raw.get("code"))
        return node
    if kind == "button":
        return {"type": "button", "name": _parse_button(raw.get("name"))}
    if kind == "interact":
        return {"type": "button", "name": BUTTON_DEFAULT}
    if kind in FACTS:
        return {"type": kind}
    if kind in ("all", "any"):
        return {"type": kind, "children": [_normalize_node(child) for child in raw["children"]]}
    if kind == "not":
        return {"type": "not", "child": _normalize_node(raw["child"])}
    if kind == "hold":
        return {
            "type": "hold",
            "seconds": clamp_seconds(raw.get("seconds", 0.0)),
            "child": _normalize_node(raw["child"]),
        }
    if kind == "latch":
        clear = raw.get("clear")
        return {
            "type": "latch",
            "set": _normalize_node(raw["set"]),
            "clear": _normalize_node(clear) if clear else None,
        }
    if kind == "before":
        return {
            "type": "before",
            "first": _normalize_node(raw["first"]),
            "then": _normalize_node(raw["then"]),
        }
    raise ValueError(f"未知节点类型：{kind!r}")


def describe_condition(raw) -> str:
    """把条件树渲染成一行人话（日志 / 摘要 / 界面提示用）。"""
    if not isinstance(raw, dict):
        return "（空）"
    kind = raw.get("type")
    if kind == "fact":
        return describe_condition(_legacy_condition(raw))
    if kind == "trigger":
        type_label = TRIGGER_KIND_SHORT.get(str(raw.get("kind", "")), "未知")
        if str(raw.get("kind", "")) == "custom":
            code = parse_code(raw.get("code"))
            type_label = f"类型 0x{code:02X}" if code is not None else "类型 ?"
        side_label = TRIGGER_SIDE_LABEL.get(str(raw.get("side", "")), "?")
        text = f"扳机：{side_label}{type_label}"
        prefix = str(raw.get("prefix", "") or "")
        if prefix:
            text += f"·{prefix.upper()}"
        return text
    if kind in ("button", "interact"):
        name = (
            BUTTON_DEFAULT
            if kind == "interact"
            else str(raw.get("name") or BUTTON_DEFAULT).strip().upper()
        )
        return f"按钮 {BUTTON_LABELS.get(name, name)} 按下"
    if kind in FACTS:
        return fact_label(kind)
    if kind in ("all", "any"):
        joiner = " 且 " if kind == "all" else " 或 "
        children = raw.get("children") or []
        inner = joiner.join(describe_condition(child) for child in children)
        return f"({inner})"
    if kind == "not":
        return f"非({describe_condition(raw.get('child'))})"
    if kind == "hold":
        seconds = raw.get("seconds", 0)
        return f"持续 {format_seconds(seconds)}({describe_condition(raw.get('child'))})"
    if kind == "latch":
        clear = raw.get("clear")
        clear_text = describe_condition(clear) if clear else "不解除"
        return f"锁存[置位：{describe_condition(raw.get('set'))} / 清除：{clear_text}]"
    if kind == "before":
        return f"先 {describe_condition(raw.get('first'))} 后 {describe_condition(raw.get('then'))}"
    return "（无效）"


# ---------------------------------------------------------------- 小工具
def clamp_seconds(value) -> float:
    """去抖秒数：非法值用默认，负数归零，过大夹到上限。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_ENTER_HOLD_S
    if seconds != seconds:  # NaN
        return DEFAULT_ENTER_HOLD_S
    return max(0.0, min(_MAX_DELAY_S, seconds))


def format_seconds(value) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "0s"
    return f"{seconds:g}s"
