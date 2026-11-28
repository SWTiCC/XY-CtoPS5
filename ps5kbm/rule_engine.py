"""规则层：规则表 + 条件树状态机 + 旧配置迁移。

一条规则 = 进入条件树 + 目标模式 + 退出条件树 + 去抖。条件语言（事实、节点、解析、
渲染）在 ``signal_rules.py``，本模块负责「什么时候切、切到哪」：

* ``Rule``：一条规则的纯数据（``enter`` / ``leave`` 存原始 JSON，写盘与编辑共用一份）
* ``parse_rules`` / ``rules_to_dict``：配置读写与容错
* ``migrate_legacy_modes``：把旧配置（每个模式配一个信号）迁移成等价规则
* ``RuleEngine``：每 100ms 被调一次的状态机，返回「切到哪个模式」或「回默认」

时间一律由调用方传入 ``now``（``time.monotonic()``），便于单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .signal_rules import (
    DEFAULT_ENTER_HOLD_S,
    DEFAULT_LEAVE_DELAY_S,
    clamp_seconds,
    describe_condition,
    normalize_condition,
    parse_condition,
)

LOGGER = logging.getLogger(__name__)

# 「不用规则集」在下拉里的显示名（映射页与编辑页共用）
RULESET_OFF_LABEL = "关闭（不自动切换）"


# ---------------------------------------------------------------- 规则
@dataclass
class Rule:
    """一条自动切换规则：进什么条件、切到哪个模式、什么时候退回去。

    ``enter`` / ``leave`` 都存**原始 JSON 节点**（不存编译后的对象）：写盘与界面编辑
    都用同一份数据，引擎启动时再编译，避免两套表示互相漂移。
    """

    id: str
    label: str
    target: str
    enabled: bool = True
    enter: dict = field(default_factory=dict)
    leave: dict | None = None
    enter_hold: float = DEFAULT_ENTER_HOLD_S
    leave_delay: float = DEFAULT_LEAVE_DELAY_S

    def summary(self) -> str:
        """一行摘要，日志与磁盘阅读都靠它。"""
        text = f"进入：{describe_condition(self.enter)}"
        if self.leave is not None:
            text += f"；退出：{describe_condition(self.leave)}"
        return text


@dataclass(frozen=True)
class RuleDecision:
    """一次自动切换的结果。``leaving=True`` 表示条件结束、要回默认模式。"""

    rule_id: str
    rule_label: str
    mode: str
    leaving: bool = False


@dataclass
class RuleStatus:
    """某条规则此刻的状态（界面灯 / 诊断用）。"""

    rule_id: str
    label: str
    target: str
    active: bool  # 进入条件现在成立
    armed: bool  # 当前模式是它切进去的
    blocked: bool  # 手动切换后被压住，等它冷掉


def rule_to_dict(rule: Rule) -> dict:
    """规则 → 可写盘的字典（空的可选项不写）。"""
    data: dict = {
        "id": rule.id,
        "label": rule.label,
        "enabled": bool(rule.enabled),
        "target": rule.target,
        "enter_hold": round(float(rule.enter_hold), 3),
        "leave_delay": round(float(rule.leave_delay), 3),
        "enter": rule.enter,
    }
    if rule.leave is not None:
        data["leave"] = rule.leave
    return data


def rules_to_dict(rules: list[Rule]) -> list[dict]:
    return [rule_to_dict(rule) for rule in rules]


def parse_rules(
    raw_list,
    hold: float = DEFAULT_ENTER_HOLD_S,
    delay: float = DEFAULT_LEAVE_DELAY_S,
) -> list[Rule]:
    """把配置里的 ``rules`` 解析成 ``Rule`` 列表；坏规则丢弃并留 warning。"""
    rules: list[Rule] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_list or [], start=1):
        if not isinstance(raw, dict):
            LOGGER.warning("规则 #%d 不是对象，已忽略", index)
            continue
        target = str(raw.get("target", "")).strip()
        if not target:
            LOGGER.warning("规则 #%d 没有目标模式，已忽略", index)
            continue
        enter = raw.get("enter")
        try:
            parse_condition(enter)
        except ValueError as exc:
            LOGGER.warning("规则 #%d 的进入条件无效，已忽略：%s", index, exc)
            continue
        leave = raw.get("leave")
        if leave is not None:
            try:
                parse_condition(leave)
            except ValueError as exc:
                LOGGER.warning("规则 #%d 的退出条件无效，已忽略退出条件：%s", index, exc)
                leave = None
        rule_id = str(raw.get("id", "")).strip() or f"rule-{index}"
        if rule_id in seen:
            LOGGER.warning("规则 id 重复：%s，已忽略后一条", rule_id)
            continue
        seen.add(rule_id)
        rules.append(
            Rule(
                id=rule_id,
                label=str(raw.get("label", "") or rule_id),
                target=target,
                enabled=bool(raw.get("enabled", True)),
                # 存规范化之后的条件树：老 fact 写法在这里自动升级，下次保存就写回新格式
                enter=normalize_condition(enter),
                leave=normalize_condition(leave) if isinstance(leave, dict) else None,
                enter_hold=clamp_seconds(raw.get("enter_hold", hold)),
                leave_delay=clamp_seconds(raw.get("leave_delay", delay)),
            )
        )
    return rules


# ---------------------------------------------------------------- 引擎
class _CompiledRule:
    """规则 + 编译后的条件树 + 计时状态。"""

    __slots__ = ("rule", "enter", "leave", "enter_since", "leave_since", "active")

    def __init__(self, rule: Rule) -> None:
        self.rule = rule
        self.enter = parse_condition(rule.enter)
        self.leave = parse_condition(rule.leave) if rule.leave else None
        self.enter_since: float | None = None
        self.leave_since: float | None = None
        self.active = False


class RuleEngine:
    """规则表的状态机：条件树 → 切模式 / 回默认。

    规则按列表顺序遍历，先满足的先生效；只有「自己切进去的那条规则」才可能自动退出。
    """

    def __init__(
        self,
        rules: list[Rule],
        default_mode: str = "default",
    ) -> None:
        self._default = default_mode
        self._compiled: list[_CompiledRule] = []
        self._by_id: dict[str, _CompiledRule] = {}
        self._armed: str | None = None
        self._held_off: set[str] = set()
        self.set_rules(rules)

    def set_rules(self, rules: list[Rule]) -> None:
        """整体换一套规则（预设切换 / 编辑后重建都走这里）。"""
        self._compiled = []
        self._by_id = {}
        for rule in rules:
            if not rule.enabled:
                continue
            try:
                compiled = _CompiledRule(rule)
            except ValueError as exc:
                LOGGER.warning("规则 %s 条件无效，已跳过：%s", rule.id, exc)
                continue
            self._compiled.append(compiled)
            self._by_id[rule.id] = compiled
        self.reset()

    @property
    def rules(self) -> list[Rule]:
        return [compiled.rule for compiled in self._compiled]

    @property
    def armed(self) -> str | None:
        """当前被自动切换管理的规则 id（None = 不管理）。"""
        return self._armed

    def reset(self) -> None:
        """换会话 / 换玩法 / 换预设：规则状态与条件树内部状态全部清空。"""
        self._armed = None
        self._held_off.clear()
        for compiled in self._compiled:
            compiled.enter_since = None
            compiled.leave_since = None
            compiled.active = False
            compiled.enter.reset()
            if compiled.leave is not None:
                compiled.leave.reset()

    def notify_manual_switch(self, now: float, facts) -> None:
        """玩家自己切了模式：不再自动退出，并把当前正成立的规则压到它冷掉为止。"""
        self._armed = None
        self._held_off.clear()
        for compiled in self._compiled:
            compiled.enter_since = None
            compiled.leave_since = None
            compiled.active = compiled.enter.evaluate(facts, now)
            if compiled.active:
                self._held_off.add(compiled.rule.id)

    def update(self, now: float, current: str, facts, modes) -> RuleDecision | None:
        """判一次；要切模式时返回决定，否则 None。"""
        decision = self._enter(now, current, facts, modes)
        if decision is not None:
            return decision
        return self._leave(now, current, facts)

    def status(self) -> list[RuleStatus]:
        """每条规则此刻的状态（取最近一次 update 的结果，不重复求值）。"""
        return [
            RuleStatus(
                rule_id=compiled.rule.id,
                label=compiled.rule.label,
                target=compiled.rule.target,
                active=compiled.active,
                armed=compiled.rule.id == self._armed,
                blocked=compiled.rule.id in self._held_off,
            )
            for compiled in self._compiled
        ]

    # ------------------------------------------------------------ 内部
    def _enter(self, now: float, current: str, facts, modes) -> RuleDecision | None:
        for compiled in self._compiled:
            hot = compiled.enter.evaluate(facts, now)
            compiled.active = hot
            if not hot:
                compiled.enter_since = None
                self._held_off.discard(compiled.rule.id)
                continue
            if compiled.enter_since is None:
                compiled.enter_since = now
            if compiled.rule.id in self._held_off:
                continue
            if compiled.rule.target not in modes:
                continue
            if now - compiled.enter_since < compiled.rule.enter_hold:
                continue
            if compiled.rule.target == current:
                # 已经在这个模式里：只 arm，不重复切（但要记住是我管理的，好自动退出）。
                # 这里必须停：不然后面那条也成立的规则会把当前模式抢走。
                self._arm(compiled)
                break
            self._arm(compiled)
            return RuleDecision(
                rule_id=compiled.rule.id,
                rule_label=compiled.rule.label,
                mode=compiled.rule.target,
            )
        return None

    def _leave(self, now: float, current: str, facts) -> RuleDecision | None:
        if self._armed is None:
            return None
        compiled = self._by_id.get(self._armed)
        if compiled is None or compiled.rule.target != current:
            # 规则被删 / 当前模式已经不是它管的那个（手动切走）：不再管理
            self._armed = None
            return None
        if compiled.leave is None:
            # 没配退出条件 = 永不自动退出（但仍然算「这条规则管的模式」，界面要能看出来）
            return None
        if not compiled.leave.evaluate(facts, now):
            compiled.leave_since = None
            return None
        if compiled.leave_since is None:
            compiled.leave_since = now
        if now - compiled.leave_since < compiled.rule.leave_delay:
            return None
        decision = RuleDecision(
            rule_id=compiled.rule.id,
            rule_label=compiled.rule.label,
            mode=self._default,
            leaving=True,
        )
        self.reset()
        return decision

    def _arm(self, compiled: _CompiledRule) -> None:
        """记下「这个模式是这条规则切的」。

        注意只在**换了一条规则**时清退出计时：每 tick 都清的话，退出延时永远攒不满
        （「已经在目标模式里」这种情况每 tick 都会重新 arm 一次）。
        """
        if self._armed != compiled.rule.id:
            compiled.leave_since = None
        self._armed = compiled.rule.id
