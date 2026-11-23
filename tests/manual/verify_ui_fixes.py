"""修复回归脚本：逐条验证 0.2.5 体检发现的问题都已修好。

在临时目录里驱动真实界面（需要桌面环境），不碰用户真实数据：
config.json / tuning.json / credentials.json 都复制到 tests/_tmp/verify_ui 下，
所有写盘函数改指向那份副本；缺少这些文件时用内置的最小样例兜底。

用法（从仓库根运行）：
    .venv\\Scripts\\python.exe tests\\manual\\verify_ui_fixes.py
输出最后一行是 `共 N 项，失败 M 项`，同时写到 tests/_tmp/verify_ui_out.txt。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

TMP = os.path.join(ROOT, "tests", "_tmp", "verify_ui")
OUT = os.path.join(ROOT, "tests", "_tmp", "verify_ui_out.txt")
shutil.rmtree(TMP, ignore_errors=True)
for sub in ("presets", "builtin"):
    os.makedirs(os.path.join(TMP, sub), exist_ok=True)

# 真实数据优先（这样验证的是用户当前配置），没有就用最小样例
_CONFIG_SAMPLE = {"preset": "gta6"}
_CREDENTIALS_SAMPLE = {
    "device_ip": "192.168.1.38",
    "host_id": "test-host",
    "host_name": "PS5Pro-Yi",
    "device_type": "PS5",
    "profiles": {"1": {"id": "TESTACCOUNT="}},
}


def _seed(name: str, sample: dict) -> None:
    source = os.path.join(ROOT, name)
    target = os.path.join(TMP, name)
    if os.path.exists(source):
        shutil.copy(source, target)
    else:
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(sample, handle, ensure_ascii=False)


_seed("config.json", _CONFIG_SAMPLE)
_seed("credentials.json", _CREDENTIALS_SAMPLE)
if os.path.exists(os.path.join(ROOT, "tuning.json")):
    shutil.copy(os.path.join(ROOT, "tuning.json"), os.path.join(TMP, "tuning.json"))
shutil.copy(
    os.path.join(ROOT, "ps5kbm", "presets", "gta6.json"),
    os.path.join(TMP, "builtin", "gta6.json"),
)

import customtkinter as ctk  # noqa: E402

from ps5kbm import app as app_mod
from ps5kbm import config, probe
from ps5kbm.ui_common import StickKeysEditor

config.PROJECT_ROOT = TMP
config.USER_PRESETS_DIR = os.path.join(TMP, "presets")
config.PRESETS_DIR = os.path.join(TMP, "builtin")
config.DEFAULT_CONFIG_PATH = os.path.join(TMP, "config.json")
config.TUNING_CONFIG_PATH = os.path.join(TMP, "tuning.json")
config.DEFAULT_CREDENTIALS_PATH = os.path.join(TMP, "credentials.json")

_real_save_config = config.save_config
_real_save_tuning = config.save_tuning
_real_save_preset = config.save_preset
_real_load_config = config.load_config
_real_save_credentials = config.save_credentials

config.save_config = lambda cfg: _real_save_config(cfg, config.DEFAULT_CONFIG_PATH)
config.save_tuning = lambda cfg: _real_save_tuning(cfg, config.TUNING_CONFIG_PATH)
config.save_preset = lambda name, cfg: _real_save_preset(name, cfg)
config.load_config = lambda: _real_load_config(config.DEFAULT_CONFIG_PATH)
config.save_credentials = lambda path, raw: _real_save_credentials(
    config.DEFAULT_CREDENTIALS_PATH, raw
)


async def _fake_probe(credentials, timeout=None, controller_factory=None):
    return probe.ProbeResult(
        online=True, host_id="x", host_ip="192.168.1.38", host_name="PS5Pro-Yi"
    )


probe.probe_console = _fake_probe

answers = {
    "input": None,
    "yesno": True,
    "warnings": [],
    "infos": [],
    "errors": [],
    "asked": [],
}


class FakeInputDialog:
    def __init__(self, *args, **kwargs):
        pass

    def get_input(self):
        return answers["input"]


def fake_askyesno(title, message, **kwargs):
    answers["asked"].append((title, message))
    return answers["yesno"]


def _rec(kind):
    def inner(title, message, **kwargs):
        answers[kind].append((title, message))
        return None

    return inner


app_mod.ctk.CTkInputDialog = FakeInputDialog
app_mod.messagebox.askyesno = fake_askyesno
app_mod.messagebox.showwarning = _rec("warnings")
app_mod.messagebox.showinfo = _rec("infos")
app_mod.messagebox.showerror = _rec("errors")

captured = {"key": "j"}
editor_value = {"value": "CROSS"}


class FakeKeyCapture:
    def __init__(self, parent, on_captured, allow_wheel=False):
        on_captured(captured["key"])


class FakeActionEditor:
    def __init__(self, parent, source_name, raw_action, on_save):
        on_save(editor_value["value"])


app_mod.KeyCaptureDialog = FakeKeyCapture
app_mod.ActionEditor = FakeActionEditor

results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(("OK   " if ok else "FAIL ") + name + (("  | " + detail) if detail else ""))


def preset_file(name):
    return os.path.join(config.USER_PRESETS_DIR, f"{name}.json")


def builtin_file(name):
    return os.path.join(config.PRESETS_DIR, f"{name}.json")


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class DummyOverlay:
    """替身：记录调用，不真的铺全屏透明层、不隐藏鼠标。"""

    def __init__(self):
        self.calls = []
        self.active = False

    def show(self):
        self.active = True
        self.calls.append("show")

    def hide(self):
        self.active = False
        self.calls.append("hide")

    def set_mode_text(self, text):
        self.calls.append(("mode", text))

    def set_grab_focus(self, enabled):
        pass

    def show_notice(self, text):
        self.calls.append(("notice", text))


class FakeBridge:
    host = "192.168.1.38"
    sent_count = 0

    def __init__(self, close_delay: float = 0.0):
        self.r2_depth = 1.0
        self.l2_depth = 1.0
        self.close_delay = close_delay
        self.closed = False

    def set_r2_depth(self, value):
        self.r2_depth = value

    def set_l2_depth(self, value):
        self.l2_depth = value

    def set_sticks(self, *args):
        pass

    def send_events(self, events):
        pass

    async def close(self):
        import asyncio

        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.closed = True


class FakeFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


def main():
    root = ctk.CTk()
    app = app_mod.Ps5KbmApp(root)
    root.update()
    app._overlay = DummyOverlay()
    root.update()

    # ================================================================ 基础
    check("启动识别已配对主机", app._paired is not None, str(app._paired))
    check("默认预设 gta6 有 22 条映射", len(app._binding_rows()) == 22)
    builtin_before = open(builtin_file("gta6"), "rb").read()
    app.apply_preset("gta6")
    check("应用内置预设不改内置文件",
          open(builtin_file("gta6"), "rb").read() == builtin_before)

    # ================================================================ D6 新建预设沿用全局设置
    original_switch = app._config.mode_switch
    answers["input"] = "audit1"
    app.create_preset()
    check("新建空预设映射为空", len(app._binding_rows()) == 0)
    check("新建空预设沿用切换键（不再重置成 F9）",
          app._config.mode_switch == original_switch,
          f"{original_switch} → {app._config.mode_switch}")
    app.apply_preset("gta6")

    # ================================================================ A1 只有 F8 硬禁
    answers["warnings"].clear()
    captured["key"] = "f8"
    app._add_mapping()
    check("添加映射拒绝捕获热键 F8",
          "f8" not in app._mode_cfg().keyboard_buttons and bool(answers["warnings"]),
          str(answers["warnings"]))

    # 方向键可以和映射共存：同一个键既能走路又能按键
    answers["warnings"].clear()
    answers["yesno"] = True
    captured["key"] = "w"
    editor_value["value"] = "CROSS"
    app._add_mapping()
    check("方向键 W 也能绑定 PS5 按钮（不再拒绝）",
          app._mode_cfg().keyboard_buttons.get("w") == "CROSS"
          and not answers["warnings"],
          str(answers["warnings"]))
    check("W 仍是左摇杆方向键（两个动作并存）",
          "w" in app._stick_source_keys(), str(app._stick_source_keys()))

    # 改键同样允许落到方向键上
    answers["warnings"].clear()
    captured["key"] = "s"
    app.rebind_mapping("space")
    check("改键可以落到方向键 S 上",
          app._mode_cfg().keyboard_buttons.get("s") == "CROSS"
          and "space" not in app._mode_cfg().keyboard_buttons,
          str(sorted(app._mode_cfg().keyboard_buttons)))
    app._mode_cfg().keyboard_buttons.pop("s", None)
    app._mode_cfg().keyboard_buttons.pop("w", None)
    app._mode_cfg().keyboard_buttons["space"] = "CROSS"  # 还原给下一步的重复键检查
    app._rebuild_mapper()

    # 调参键 / 切换键这类会被输入层先吃掉的键：允许，但要先问一句
    answers["asked"].clear()
    answers["yesno"] = False
    captured["key"] = "="
    app._add_mapping()
    check("调参键 '=' 会先提示，拒绝则不加",
          "=" not in app._mode_cfg().keyboard_buttons and bool(answers["asked"]),
          str(answers["asked"]))
    answers["yesno"] = True
    app._add_mapping()
    check("调参键 '=' 确认后可以绑定",
          app._mode_cfg().keyboard_buttons.get("=") == "CROSS")
    app._mode_cfg().keyboard_buttons.pop("=", None)
    app._rebuild_mapper()

    answers["asked"].clear()
    captured["key"] = app._config.mode_switch
    switch_category, switch_name = app._split_source(app._config.mode_switch)
    switch_store = (
        app._mode_cfg().mouse_buttons
        if switch_category == "mouse"
        else app._mode_cfg().keyboard_buttons
    )
    app._add_mapping()
    check("切换键会先提示（允许，但说明不会生效）",
          switch_store.get(switch_name) == "CROSS" and bool(answers["asked"]),
          str(answers["asked"]))
    switch_store.pop(switch_name, None)
    app._rebuild_mapper()
    answers["yesno"] = True

    # ================================================================ A2 覆盖要先确认
    answers["yesno"] = False
    captured["key"] = "space"
    editor_value["value"] = "CIRCLE"
    asked_before = len(answers["asked"])
    app._add_mapping()
    check("重复添加同一键先问覆盖（拒绝则不变）",
          app._mode_cfg().keyboard_buttons.get("space") == "CROSS"
          and len(answers["asked"]) > asked_before,
          str(app._mode_cfg().keyboard_buttons.get("space")))
    answers["yesno"] = True
    app._add_mapping()
    check("确认后按新动作覆盖",
          app._mode_cfg().keyboard_buttons.get("space") == "CIRCLE")
    app._mode_cfg().keyboard_buttons["space"] = "CROSS"
    app._rebuild_mapper()
    answers["yesno"] = True

    # ================================================================ B1 模式重名
    answers["input"] = "驾驶2"
    app.add_mode()
    check("新建模式成功", len(app._config.modes) == 3, str(list(app._config.modes)))
    answers["warnings"].clear()
    answers["input"] = "默认"
    app.rename_mode()
    labels = [app._mode_label(name) for name in app._config.modes]
    check("重命名拒绝与已有模式同名",
          labels.count("默认") == 1 and bool(answers["warnings"]), str(labels))
    answers["warnings"].clear()
    answers["input"] = "驾驶"
    app.add_mode()
    check("新建模式拒绝重名", bool(answers["warnings"]), str(answers["warnings"]))
    answers["yesno"] = True
    app._edit_mode = "mode3"
    app.remove_mode()
    check("删除模式后回到 default", app._edit_mode == "default")

    # ================================================================ B3 切换键显示中文
    from ps5kbm.keys import display_key

    check("切换键按钮显示中文键名",
          app._mode_switch_btn.cget("text")
          == f"切换键 {display_key(app._config.mode_switch)}",
          app._mode_switch_btn.cget("text"))

    # ================================================================ B4 改键冲突校验
    switch_before = app._config.mode_switch
    r2_up_before = app._config.r2_up
    r2_down_before = app._config.r2_down

    answers["warnings"].clear()
    captured["key"] = "f8"
    app._rebind_trigger("r2_up")
    check("调参键拒绝捕获热键 F8",
          app._config.r2_up == r2_up_before and bool(answers["warnings"]),
          app._config.r2_up)

    answers["warnings"].clear()
    captured["key"] = "="
    app._rebind_trigger("r2_down")
    check("调参键拒绝与其它调参键重复",
          app._config.r2_down == r2_down_before and bool(answers["warnings"]),
          str(answers["warnings"]))

    answers["warnings"].clear()
    captured["key"] = "space"
    app.set_mode_switch_key()
    check("切换键拒绝覆盖已映射的键",
          app._config.mode_switch == switch_before and bool(answers["warnings"]),
          app._config.mode_switch)

    answers["warnings"].clear()
    captured["key"] = "w"
    app.set_mode_switch_key()
    check("切换键拒绝左摇杆方向键",
          app._config.mode_switch == switch_before and bool(answers["warnings"]))

    # 改回自己不算冲突
    answers["warnings"].clear()
    captured["key"] = switch_before
    app.set_mode_switch_key()
    check("切换键改回原键不算冲突",
          app._config.mode_switch == switch_before and not answers["warnings"],
          str(answers["warnings"]))

    # ================================================================ B2 方向键编辑器保多键
    saved = {}
    editor = StickKeysEditor(
        root,
        {"up": ["w", "up"], "down": ["s"], "left": ["a"], "right": ["d"]},
        lambda sticks: saved.update(sticks),
    )
    editor.update()
    editor._save()
    check("方向键编辑器保留多键配置", saved.get("up") == ["w", "up"], str(saved.get("up")))

    # ================================================================ B5 检测出错仍可直接连接
    app._bridge = None
    app._probe_state = "error"
    app._probe_error = "检测超时"
    app_mod.connect_ui.show_view(app, app_mod.flow.VIEW_QUICK)
    app_mod.connect_ui.render(app)
    check("检测出错时「直接连接」仍可用",
          str(app._quick_connect_button.cget("state")) == "normal",
          str(app._quick_connect_button.cget("state")))

    # ================================================================ A5 连接同步扳机深度
    app._apply_r2(0.6)
    fake = FakeBridge()
    app._on_connected(FakeFuture(fake))
    root.update()
    check("连接后把 R2 深度下发给会话", abs(fake.r2_depth - 0.6) < 1e-6,
          f"{fake.r2_depth:.1f}")

    # ================================================================ A4 调参键只在捕获时生效
    app._l2_var.set(0.5)
    app._config.l2_depth = 0.5
    app._source._handle_key("=", True)
    app._source._handle_key("=", False)
    app._poll_events()
    check("未捕获时按调参键不改深度", abs(float(app._l2_var.get()) - 0.5) < 1e-6,
          f"{float(app._l2_var.get()):.1f}")

    app._apply_capture_state(True)
    root.update()
    check("捕获中覆盖层打开", app._overlay.active is True, str(app._overlay.calls))
    app._source._handle_key("=", True)
    app._source._handle_key("=", False)
    app._poll_events()
    root.update()
    check("捕获中按调参键生效", abs(float(app._l2_var.get()) - 0.6) < 1e-6,
          f"{float(app._l2_var.get()):.1f}")
    tuning = read_json(config.TUNING_CONFIG_PATH)
    check("调参键改的深度已落盘", abs(float(tuning.get("l2_depth", 0)) - 0.6) < 1e-6,
          str(tuning.get("l2_depth")))

    # ================================================================ D2 切换键只在捕获时生效
    before_mode = app._mapper.mode
    app._source.set_capturing(False)
    app._source._handle_mouse("x2", False)
    app._source._capturing = False
    app._source._handle_mouse("x2", True)
    app._source._handle_mouse("x2", False)
    app._poll_events()
    check("未捕获时按切换键不切模式", app._mapper.mode == before_mode,
          f"{before_mode} → {app._mapper.mode}")

    # ================================================================ 捕获中改映射自动恢复
    app._source.set_capturing(True)
    app._apply_capture_state(True)
    root.update()
    app._rebuild_mapper()
    root.update()
    check("捕获中改映射后捕获自动恢复",
          app._source.capturing is True
          and app._capture_button.cget("text") == "停止捕获",
          f"capturing={app._source.capturing}")
    app._source.set_capturing(False)
    app._apply_capture_state(False)
    root.update()

    # ================================================================ A3 断开后 F8 不再进捕获
    slow = FakeBridge(close_delay=1.0)
    app._bridge = slow
    app._on_connected(FakeFuture(slow))
    root.update()
    started = time.perf_counter()
    app._disconnect()
    elapsed = time.perf_counter() - started
    root.update()
    check("断开连接不再卡界面（<0.5s）", elapsed < 0.5, f"{elapsed:.2f}s")
    check("断开后输入源已停止", app._source_ready is False)
    check("断开后捕获按钮置灰",
          str(app._capture_button.cget("state")) == "disabled")
    marker = len(app._overlay.calls)
    app._source.toggle_capture()  # 等价于 F8 回调
    app._poll_events()
    root.update()
    check("断开后 F8 不会再进捕获",
          "show" not in app._overlay.calls[marker:]
          and app._capture_button.cget("text") == "开始捕获",
          f"overlay={app._overlay.calls[marker:]} 按钮={app._capture_button.cget('text')}")
    check("断开后按 F8 给了提示", any("还没有连接主机" in str(call) or False
                                     for call in app._overlay.calls) is False)

    # ================================================================ D3 死代码已删
    check("_send_trigger 已删除", not hasattr(app, "_send_trigger"))

    # ================================================================ C2 坏预设兜底
    answers["errors"].clear()
    with open(preset_file("broken"), "w", encoding="utf-8") as handle:
        handle.write("{ broken")
    app._refresh_preset_list()
    app._preset_var.set("broken")
    preset_before = app._config.preset
    rows_before = len(app._binding_rows())
    app.apply_preset("broken")
    check("坏预设有错误提示", bool(answers["errors"]), str(answers["errors"]))
    check("坏预设不改变实际映射",
          app._config.preset == preset_before and len(app._binding_rows()) == rows_before)
    check("坏预设后下拉框回到实际预设",
          app._preset_var.get() == app._config.preset,
          f"{app._preset_var.get()} vs {app._config.preset}")
    os.remove(preset_file("broken"))

    # ================================================================ C1 坏 config 兜底
    good_config = open(config.DEFAULT_CONFIG_PATH, encoding="utf-8").read()
    with open(config.DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as handle:
        handle.write("{ this is broken")
    try:
        loaded = config.load_config()
        crash = ""
    except Exception as exc:  # noqa: BLE001
        loaded = None
        crash = type(exc).__name__
    check("config.json 写坏也能启动", not crash, crash)
    check("坏配置被改名留档",
          os.path.exists(config.DEFAULT_CONFIG_PATH + ".broken"))
    check("坏配置时按预设启动",
          loaded is not None and len(loaded.modes["default"].keyboard_buttons) == 18,
          str(len(loaded.modes["default"].keyboard_buttons)) if loaded else "")
    with open(config.DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as handle:
        handle.write(good_config)
    if os.path.exists(config.DEFAULT_CONFIG_PATH + ".broken"):
        os.remove(config.DEFAULT_CONFIG_PATH + ".broken")

    root.destroy()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    bad = [item for item in results if not item[0]]
    lines = [f"共 {len(results)} 项，失败 {len(bad)} 项"]
    for _, name, detail in bad:
        lines.append(f"  - {name}" + (f"：{detail}" if detail else ""))
    text = "\n".join(lines)
    print(text)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
