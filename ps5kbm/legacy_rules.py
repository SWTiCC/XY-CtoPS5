"""把旧配置（每个模式配一个 ``auto_signal``）迁移成等价规则。

旧版本没有规则表：模式上直接写「出现哪个手柄信号就切到这个模式」+「信号消失是否回默认」。
新版本统一成 ``rule_engine.Rule``，这里负责把旧字段翻译过去，**一次性**用：

* 只有「这个模式还没有规则指向它」时才补，所以迁移后写回的配置不会被重复迁移；
* 翻译规则与旧语义逐条对应（见 ``_legacy_condition`` 的说明）；
* 不认识的信号 id 直接跳过并留 warning，不影响其它规则。

等用户配置全部换成 ``rules`` 之后，本模块可以整份删掉。
"""

from __future__ import annotations

import logging

from .rule_engine import DEFAULT_ENTER_HOLD_S, DEFAULT_LEAVE_DELAY_S, Rule

LOGGER = logging.getLogger(__name__)


def _trigger(kind: str, side: str, prefix: str = "") -> dict:
    return {"type": "trigger", "kind": kind, "prefix": prefix, "side": side}


def _legacy_condition(signal_id: str) -> tuple[dict, dict] | None:
    """旧信号 id → (进入条件, 退出条件)；不认识的返回 None。

    等价关系：

    * 旧的「信号连续热 0.8 秒 → 切」= 规则自带的 ``enter_hold``；
    * 旧的「信号冷 1.2 秒 → 回默认」= 退出条件写成进入条件取反 + ``leave_delay``；
    * 旧的 ``vehicle_entry`` 是锁存信号：进车锁住、按交互键下车才解除。
    """
    if signal_id == "trigger_drive":
        enter = _trigger("resistance", "any")
        return enter, {"type": "not", "child": enter}
    if signal_id == "trigger_shoot":
        enter = _trigger("shoot", "any")
        return enter, {"type": "not", "child": enter}
    if signal_id in ("rumble", "haptics"):
        enter = {"type": signal_id}
        return enter, {"type": "not", "child": enter}
    if signal_id == "feedback_any":
        enter = {
            "type": "any",
            "children": [
                _trigger("resistance", "any"),
                _trigger("shoot", "any"),
                {"type": "rumble"},
                {"type": "haptics"},
            ],
        }
        return enter, {"type": "not", "child": enter}
    if signal_id == "vehicle_entry":
        leave = {
            "type": "all",
            "children": [
                {"type": "interact"},
                _trigger("off", "both"),
            ],
        }
        enter = {
            "type": "latch",
            "set": _trigger("resistance", "both", "ff03"),
            "clear": leave,
        }
        return enter, leave
    return None


def migrate_legacy_modes(
    modes_raw,
    hold: float = DEFAULT_ENTER_HOLD_S,
    delay: float = DEFAULT_LEAVE_DELAY_S,
    existing: list[Rule] | None = None,
) -> list[Rule]:
    """把旧配置里的 ``modes.*.auto_signal`` 变成等价规则。"""
    taken = {rule.target for rule in (existing or [])}
    migrated: list[Rule] = []
    for name, raw in (modes_raw or {}).items():
        name = str(name)
        if name == "default" or name in taken or not isinstance(raw, dict):
            continue
        signal_id = str(raw.get("auto_signal", "") or "").strip().lower()
        if not signal_id or signal_id == "none":
            continue
        built = _legacy_condition(signal_id)
        if built is None:
            LOGGER.warning("模式 %s 的旧信号 %s 不认识，已跳过迁移", name, signal_id)
            continue
        enter, leave = built
        auto_leave = bool(raw.get("auto_leave", True))
        label = str(raw.get("label", "") or name)
        migrated.append(
            Rule(
                id=f"legacy-{name}",
                label=f"{label}（旧配置迁移）",
                target=name,
                enter=enter,
                leave=leave if auto_leave else None,
                enter_hold=hold,
                leave_delay=delay,
            )
        )
        taken.add(name)
    return migrated
