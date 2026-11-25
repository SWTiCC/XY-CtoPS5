"""玩法隔离测试：切换键鼠 / 手柄玩法时，旧的一侧必须整套拆掉，新的一侧再重建。

这些用例直接对 `Ps5KbmApp` 的「玩法隔离」方法做黑白盒验证（用 `__new__` 造一个不带
Tk 的实例 + 假对象），因为真机跑不起来：pynput 钩子、HID 句柄、音频端点都不该进单测。
"""

from __future__ import annotations

import queue
import unittest
from unittest import mock

from ps5kbm import app as app_module
from ps5kbm import config as config_module
from ps5kbm import trigger_filter


class FakeSource:
    """假的 InputSource：只记调用顺序，不起监听器、不碰系统。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.capturing = False
        self.listening = True
        self.raw_mouse_ok = True
        self.start_count = 0
        self.stop_count = 0

    def set_capture_callback(self, callback) -> None:
        self.events.append("kb.wire_capture")

    def set_key_callback(self, callback) -> None:
        self.events.append("kb.wire_key")

    def set_mode_switch(self, name: str, callback) -> None:
        self.events.append("kb.wire_mode_switch")

    def set_trigger_adjust(self, keys, callback) -> None:
        self.events.append("kb.wire_trigger_adjust")

    def start(self) -> bool:
        self.start_count += 1
        self.events.append("kb.start")
        return True

    def stop(self) -> None:
        self.stop_count += 1
        self.events.append("kb.stop")

    def set_capturing(self, value: bool) -> None:
        self.capturing = bool(value)
        self.events.append(f"kb.capturing={bool(value)}")

    def release_cursor(self) -> None:
        self.events.append("kb.release_cursor")

    def lock_cursor(self) -> None:
        self.events.append("kb.lock_cursor")

    def poll_mouse_delta(self):
        return 0, 0

    def pressed_keys(self):
        return set()

    def raw_mouse_stats(self):
        return 0, 0

    def pump_mouse_messages(self) -> None:
        self.events.append("kb.pump")


class FakeController:
    """假的 DualSenseReader。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.connected = False
        self.transport = "usb"
        self.device_label = ""
        self.error = ""
        self.haptics_mode = False
        self._alive = False

    def start_reader(self) -> None:
        self.events.append("pad.start_reader")
        self._alive = True

    def stop(self) -> None:
        self.events.append("pad.stop")
        self._alive = False
        self.connected = False
        self.haptics_mode = False

    def is_alive(self) -> bool:
        return self._alive

    def snapshot(self):
        return None

    def set_haptics_mode(self, enabled: bool) -> None:
        self.haptics_mode = bool(enabled)
        self.events.append(f"pad.haptics_mode={bool(enabled)}")

    def rumble(self, low: float, high: float, force: bool = False) -> bool:
        self.events.append("pad.rumble")
        return True

    def set_trigger_effects(self, left=None, right=None) -> bool:
        self.events.append("pad.triggers_off")
        return True

    def set_lightbar(self, rgb, player=None) -> bool:
        self.events.append("pad.lightbar")
        return True


class FakeHaptics:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.opened = False

    def close(self) -> None:
        self.events.append("haptics.close")
        self.opened = False

    def is_open(self) -> bool:
        return self.opened

    def stats(self):
        return 0, 0

    def feed(self, pcm: bytes) -> None:
        self.events.append("haptics.feed")


class FakeBridge:
    """假会话：只关心「有没有把按住的键松开」。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.releases = 0

    def send_events(self, events) -> None:
        self.events.append("bridge.send_events")
        self.releases += 1


class FakeOverlay:
    def __init__(self) -> None:
        self.visible = False

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def set_grab_focus(self, value: bool) -> None:
        pass

    def set_mode_text(self, text: str) -> None:
        pass

    def show_notice(self, text: str) -> None:
        pass


class FakeWidget:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def insert(self, *args, **kwargs) -> None:
        pass

    def delete(self, *args, **kwargs) -> None:
        pass

    def see(self, *args, **kwargs) -> None:
        pass

    def index(self, *args, **kwargs) -> str:
        return "1.0"


class FakeRoot:
    def __init__(self) -> None:
        self.jobs: dict[str, int] = {}
        self.cancelled: list[str] = []
        self._next = 0

    def after(self, delay: int, callback=None):
        self._next += 1
        job = f"job-{self._next}"
        self.jobs[job] = delay
        return job

    def after_cancel(self, job) -> None:
        self.cancelled.append(job)
        self.jobs.pop(job, None)


class FakeMapper:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.mode = "default"
        self.left_value = 0.5

    def release_all(self):
        self.events.append("mapper.release_all")
        return []

    def drop_missing(self, keys) -> None:
        self.events.append("mapper.drop_missing")

    def set_left_value(self, value) -> None:
        self.left_value = value


def _make_app(mode: str):
    """造一个只有「玩法隔离」所需属性的 Ps5KbmApp（不建 Tk、不碰硬件）。"""
    app = app_module.Ps5KbmApp.__new__(app_module.Ps5KbmApp)
    events: list[str] = []
    cfg = config_module.AppConfig()
    cfg.controller.mode = mode
    cfg.modes = {"default": config_module.ModeConfig(label="默认")}
    app._config = cfg
    app._events = events
    app._mapper = FakeMapper(events)
    app._source = None
    app._source_ready = False
    app._bridge = None
    app._controller = FakeController(events)
    app._usb_haptics = FakeHaptics(events)
    app._overlay = FakeOverlay()
    app.root = FakeRoot()
    app._log_text = FakeWidget()
    app._capture_button = FakeWidget()
    app._input_state_label = FakeWidget()
    app._status_text = FakeWidget()
    app._status_dot = FakeWidget()
    app._run_title = FakeWidget()
    app._run_subtitle = FakeWidget()
    app._log_queue = queue.Queue()
    app._ui_queue = queue.Queue()
    app._poll_job = None
    app._pump_job = None
    app._logged_keys = {"w", "a"}
    app._controller_buttons_sent = {"X"}
    app._last_trigger_sent = {"r2": 255}
    app._last_ctrl_sticks = ((0.5, 0.0), (0.0, 0.0))
    app._last_ctrl_send = 123.0
    app._pending_controller_release = True
    app._last_trigger_blocks = {"l": b"\x05" * 11}
    app._trigger_mode_counts = {0x21: 3}
    app._trigger_filter = trigger_filter.TriggerFilter()
    app._last_lightbar = b"\x01\x02\x03"
    app._gyro_axis = app_module.gyro.GyroAxis()
    app._gyro_output = (0.3, 0.4)
    app._haptics_pad_count = 1
    app._haptics_multi_logged = True
    app._haptics_env_logged = False
    app._lifecycle_logged = False
    app._haptics_underruns_prev = 0
    app._haptic_tone_chunks = [b"\x00\x01"]
    app._mode_warned = True
    app._controller_was_connected = True
    return app


class ModeIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources: list[FakeSource] = []
        self._events: list[str] = []
        patcher = mock.patch.object(app_module, "InputSource", self._make_source)
        patcher.start()
        self.addCleanup(patcher.stop)
        counter = mock.patch.object(
            app_module.Ps5KbmApp, "_update_haptics_pad_count", lambda self: None
        )
        counter.start()
        self.addCleanup(counter.stop)
        env = mock.patch.object(
            app_module.haptics_usb, "describe_environment", lambda: "测试环境"
        )
        env.start()
        self.addCleanup(env.stop)

    def _make_source(self, mapper, hotkey):
        source = FakeSource(self._events)
        self.sources.append(source)
        return source

    def _app(self, mode: str):
        app = _make_app(mode)
        self._events = app._events
        return app

    # ---------------------------------------------------------- 键鼠玩法
    def test_keyboard_mode_releases_controller_side(self):
        app = self._app("keyboard")
        app._controller.connected = True
        app._controller._alive = True
        app._sync_input_lifecycle()

        events = app._events
        self.assertIn("pad.stop", events)
        self.assertLess(events.index("haptics.close"), events.index("pad.stop"))
        # 键鼠玩法下绝不能往手柄写马达/扳机（那是手柄侧的事）
        self.assertNotIn("pad.rumble", events)
        self.assertNotIn("pad.triggers_off", events)
        # 手柄侧的本地记录也一并清空
        self.assertEqual(app._controller_buttons_sent, set())
        self.assertEqual(app._last_trigger_sent, {})
        self.assertEqual(app._last_trigger_blocks, {})
        self.assertEqual(app._haptics_pad_count, 0)
        self.assertIsNone(app._poll_job)
        self.assertFalse(app._controller.is_alive())

    def test_leaving_controller_mode_releases_effects_before_closing_handle(self):
        app = self._app("controller")
        app._controller.connected = True
        app._controller._alive = True
        app._release_controller_side()

        events = app._events
        # 先写释放报告（马达归零 + 两边扳机 Off），再关 HID 句柄
        self.assertLess(events.index("pad.rumble"), events.index("pad.stop"))
        self.assertLess(events.index("pad.triggers_off"), events.index("pad.stop"))
        self.assertLess(events.index("haptics.close"), events.index("pad.stop"))
        self.assertFalse(app._controller.is_alive())

    def test_keyboard_mode_instantiates_source_without_starting(self):
        app = self._app("keyboard")
        app._sync_input_lifecycle()

        self.assertIsNotNone(app._source)
        self.assertEqual(len(self.sources), 1)
        self.assertEqual(self.sources[0].start_count, 0)
        self.assertFalse(app._source_ready)
        # 没会话时不排 Raw Input 消息泵（否则每秒 125 次空转）
        self.assertIsNone(app._pump_job)

    def test_keyboard_mode_starts_source_when_connected(self):
        app = self._app("keyboard")
        app._bridge = object()
        app._sync_input_lifecycle()

        self.assertEqual(self.sources[0].start_count, 1)
        self.assertTrue(app._source_ready)
        self.assertIsNotNone(app._pump_job)

    # ---------------------------------------------------------- 手柄玩法
    def test_controller_mode_releases_keyboard_side(self):
        app = self._app("controller")
        leftover = FakeSource(app._events)
        leftover.capturing = True
        app._source = leftover
        app._source_ready = True
        app._pump_job = "job-y"
        bridge = FakeBridge(app._events)
        app._bridge = bridge  # 有会话也不能在切换后继续发键鼠
        app._sync_input_lifecycle()

        events = app._events
        self.assertIn("kb.capturing=False", events)
        self.assertIn("kb.release_cursor", events)
        self.assertIn("kb.stop", events)
        # 切走前把按住的键松开，否则主机会一直以为键按着
        self.assertEqual(bridge.releases, 1)
        self.assertIsNone(app._source)
        self.assertFalse(app._source_ready)
        self.assertIsNone(app._pump_job)
        self.assertIn("job-y", app.root.cancelled)
        self.assertEqual(app._logged_keys, set())

    def test_controller_mode_starts_reader_and_poll(self):
        app = self._app("controller")
        app._sync_input_lifecycle()

        self.assertIn("pad.start_reader", app._events)
        self.assertTrue(app._controller.is_alive())
        self.assertIsNotNone(app._poll_job)
        self.assertIsNone(app._source)

    # ---------------------------------------------------------- 来回切换
    def test_switch_keeps_only_one_side_alive(self):
        app = self._app("controller")
        app._sync_input_lifecycle()
        self.assertTrue(app._controller.is_alive())
        self.assertIsNone(app._source)

        # 手柄 → 键鼠
        app._config.controller.mode = "keyboard"
        app._sync_input_lifecycle()
        self.assertFalse(app._controller.is_alive())
        self.assertIsNotNone(app._source)
        self.assertIsNone(app._poll_job)
        first_source = app._source

        # 键鼠 → 手柄：键鼠对象整台扔掉（不是留着复用）
        app._config.controller.mode = "controller"
        app._sync_input_lifecycle()
        self.assertIsNone(app._source)
        self.assertTrue(app._controller.is_alive())
        self.assertEqual(first_source.stop_count, 1)

    def test_repeated_sync_is_idempotent(self):
        app = self._app("keyboard")
        app._bridge = object()
        app._sync_input_lifecycle()
        source = app._source
        app._sync_input_lifecycle()

        # 同一侧重复收敛：不重复建对象、不重复 start（否则钩子装两遍）
        self.assertIs(app._source, source)
        self.assertEqual(source.start_count, 1)
        self.assertEqual(len(self.sources), 1)

    # ---------------------------------------------------------- 兜底
    def test_apply_capture_state_without_source_is_safe(self):
        app = self._app("keyboard")
        app._source = None
        app._apply_capture_state(False)  # 不能抛 AttributeError
        self.assertEqual(app._capture_button.text, "开始捕获")
        self.assertEqual(app._input_state_label.text, "输入：未捕获")

    def test_rebuild_mapper_keeps_controller_mode_clean(self):
        app = self._app("controller")
        app._sync_input_lifecycle()
        old_mapper = app._mapper
        app._rebuild_mapper()

        self.assertIsNot(app._mapper, old_mapper)
        self.assertIsNone(app._source)  # 手柄玩法下不能顺手把键鼠对象建出来

    def test_pump_loop_stops_in_controller_mode(self):
        app = self._app("controller")
        app._source = FakeSource(app._events)
        app._source_ready = True
        app._pump_job = "job-z"
        app._pump_raw_messages()  # 手柄玩法下不 pump、不续期

        self.assertNotIn("kb.pump", app._events)
        self.assertIsNone(app._pump_job)


if __name__ == "__main__":
    unittest.main()
