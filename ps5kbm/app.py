"""ps5-kbm 图形界面：连接、映射、运行三合一。

线程模型：
- 界面主线程（customtkinter）：所有控件操作；
- 后台 asyncio 线程：Remote Play 会话、配对、扫描、输入发送循环；
- pynput / Raw Input 线程：由 InputSource 内部管理。
界面与后台通过 root.after 与队列通信，不在后台线程碰 Tk 组件。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import queue
import threading
import time
import tkinter as tk
from collections import Counter
from tkinter import messagebox

import customtkinter as ctk

from . import (
    bridge,
    config,
    connect_ui,
    controller_ui,
    dualsense,
    gyro,
    gyro_calib_ui,
    haptics_usb,
    mapping_ui,
    probe,
    run_tuning_ui,
    run_ui,
    trigger_filter,
    ui_pages,
    windows,
)
from . import connect_flow as flow
from . import theme as T
from .input_source import InputSource
from .keys import display_key
from .mapping import InputMapper
from .overlay import CaptureOverlay
from .ui_common import (
    ActionEditor,
    KeyCaptureDialog,
    QueueLogHandler,
    StickKeysEditor,
    describe_action,
)

TICK_SECONDS = 1.0 / 250.0
# 日志面板最多保留的行数：长时间挂着不会无限变长
LOG_MAX_LINES = 800


class Ps5KbmApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        ctk.set_appearance_mode("dark")
        root.title("XY-CtoPS5")
        root.geometry(f"{T.WINDOW_WIDTH}x{T.WINDOW_HEIGHT}")
        root.configure(fg_color=T.BG)

        self._log_queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()
        self._setup_logging()
        # 连接页状态（先声明，_state_vars 会按凭据填 _paired）
        self._paired: flow.PairedConsole | None = None
        self._probe_state = flow.STATE_UNPAIRED
        self._probe_pending = False
        self._probe_error = ""
        self._connect_error = ""
        self._connecting = False
        # 用户是否主动切到完整流程（点过「换 ID 连接」）；是的话检测结果不再把人拽回去
        self._manual_full = False
        # 上一个会话是否还在后台关闭：重连前要等它收尾，避免 PS5 上残留两条会话
        self._closing = False
        # 模式下拉框：显示文本 → 模式 id（重名时显示文本会带上 id）
        self._mode_option_map: dict[str, str] = {}
        # 当前内存里的 modes 是从哪个预设加载的：只有和 _config.preset 一致时才允许自动写回预设文件，
        # 避免「删掉当前预设后回落到别的预设」时把旧内容覆盖到另一个预设上。
        self._preset_owner = ""
        self._state_vars()

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        self._bridge: bridge.Ps5Bridge | None = None
        self._tick_task = None
        self._running = False
        self._devices: list[dict] = []
        # 键鼠侧输入层：只在键鼠玩法下存在；手柄玩法恒为 None（见「玩法隔离」一节）
        self._source: InputSource | None = None
        self._source_ready = False
        self._page_name = "connect"
        self._logged_keys: set[str] = set()
        self._last_trace = 0.0
        self._overlay = CaptureOverlay(self.root, self._toggle_capture)

        # 手柄（DualSense）：后台线程读，界面/主循环只拿快照
        self._controller = dualsense.DualSenseReader()
        self._usb_haptics = haptics_usb.UsbHaptics()
        self._gyro_axis = gyro.GyroAxis()
        self._gyro_bias = tuple(self._config.controller.gyro.bias)
        self._gyro_output = (0.0, 0.0)
        self._gyro_calibrated = any(abs(value) > 1e-6 for value in self._gyro_bias)
        # 自定义陀螺仪激活键：捕获期间等手柄出现"新按下"的按键
        self._gyro_capture = False
        self._gyro_capture_deadline = 0.0
        self._gyro_prev_buttons: set[str] = set()
        self._gyro_trace_last = 0.0
        self._last_ui_sticks = 0.0
        self._controller_buttons_sent: set[str] = set()
        self._last_trigger_sent: dict[str, float] = {}
        self._last_ctrl_sticks = ((0.0, 0.0), (0.0, 0.0))
        self._last_ctrl_send = 0.0
        self._controller_was_connected = False
        self._mode_warned = False
        self._pending_controller_release = False
        # 主机下发的反馈：手柄页上的开关控制是否转发
        self._last_console_rumble = 0.0
        self._last_trigger_blocks: dict[str, bytes] = {}
        self._haptic_tone_chunks: list[bytes] = []
        self._trigger_filter = trigger_filter.TriggerFilter()
        self._last_lightbar = b""
        # 触觉端点必须唯一才能路由（分不清是哪只的音频端点）
        self._haptics_pad_count = 0
        self._haptics_multi_logged = False
        # 触觉输出能力只探测/记录一次
        self._haptics_env_logged = False
        # 玩法隔离状态只在启动时写一条 INFO
        self._lifecycle_logged = False
        # 触觉流诊断计数（默认只在异常时写 INFO，常态走 DEBUG，避免刷屏）
        self._haptics_rx = 0
        self._haptics_tx = 0
        self._haptics_peak = 0
        self._haptics_last_size = 0
        self._haptics_stats_at = 0.0
        self._haptics_underruns_prev = 0
        # 扳机效果类型统计（仅 DEBUG：排查「主机有没有下发某类效果」时用）
        self._trigger_mode_counts: dict[int, int] = {}
        self._trigger_stats_at = 0.0
        bridge.set_feedback_handlers(
            self._on_console_rumble,
            self._on_console_trigger_effect,
            None,
            self._on_console_led,
        )
        bridge.set_haptics_pcm_handler(self._on_haptics_pcm)
        # 手柄页轮询定时器 id（关窗时取消）；键鼠玩法下不跑
        self._poll_job: str | None = None
        # Raw Input 消息泵定时器 id；手柄玩法下不跑
        self._pump_job: str | None = None

        self._build_ui()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 玩法隔离：只把当前玩法那一侧建起来。键鼠玩法不实例化手柄读取线程/触觉端点，
        # 手柄玩法不实例化键鼠监听/钩子/全局热键/Raw Input 窗口。
        self._sync_input_lifecycle()

    def _pump_raw_messages(self) -> None:
        """主线程定时排空 Raw Input 窗口消息（非阻塞）。

        手柄玩法下不存在 Raw Input 窗口，这里也不再自我续期——省掉每秒 125 次空转。
        """
        self._pump_job = None
        source = self._source
        if source is None or not self._source_ready or self._controller_mode():
            return
        try:
            source.pump_mouse_messages()
        except Exception:  # noqa: BLE001 - 消息泵异常不能中断 UI
            pass
        # 间隔 8ms：消息泵本身约 10ms 一批，再密只是空转 Tk 定时器
        self._pump_job = self.root.after(8, self._pump_raw_messages)

    def _ensure_pump_loop(self) -> None:
        """确保 Raw Input 消息泵在跑（只有键鼠侧已启动、有 Raw Input 窗口时才需要）。"""
        if self._pump_job is not None or self._source is None:
            return
        if not self._source_ready or self._controller_mode():
            return
        self._pump_job = self.root.after(8, self._pump_raw_messages)

    def _stop_pump_loop(self) -> None:
        """停掉 Raw Input 消息泵（手柄玩法 / 断开 / 关窗）。"""
        job = self._pump_job
        self._pump_job = None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:  # noqa: BLE001 - 关窗时 Tk 可能已经销毁
                pass

    # ------------------------------------------------------------ 初始化
    def _state_vars(self) -> None:
        cfg = self._reload_config()
        # 已配对过的话，凭据里的地址与账号更权威（可能被探测更新过 IP）
        self._paired = self._read_paired()
        host = (self._paired.host_ip if self._paired else "") or cfg.ps5_host
        account_id = (self._paired.account_id if self._paired else "") or cfg.account_id
        self._host_var = tk.StringVar(value=host or "192.168.1.38")
        self._account_var = tk.StringVar(value=account_id)
        self._pin_var = tk.StringVar()
        self._preset_var = tk.StringVar(value=cfg.preset)
        self._preset_values = config.list_presets()
        # 启动时内存里的 modes 就来自 config.preset 记录的那套
        self._preset_owner = cfg.preset

    def _read_paired(self) -> flow.PairedConsole | None:
        """从 credentials.json 提炼「已配对主机」；文件缺失或损坏都当作没配对。"""
        path = self._config.credentials_path
        if not os.path.exists(path):
            return None
        try:
            raw = config.load_credentials(path)
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("读取配对凭据失败：%s", exc)
            return None
        return flow.summarize_credentials(raw)

    def _refresh_paired(self) -> None:
        """配对 / 连接成功后重新读凭据，刷新快捷视图显示的主机身份。"""
        paired = self._read_paired()
        if paired is not None:
            self._paired = paired

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers.clear()
        root_logger.addHandler(QueueLogHandler(self._log_queue))
        # 文件日志：出问题时可直接读 E:\...\ps5-kbm\ps5kbm.log，不需要用户复述。
        # 用轮转 handler 限制体积——长时间运行 + 高频诊断日志会把文件撑到
        # 几十 MB，持续写盘会拖死 UI，甚至表现为“跑久了崩溃”。
        try:
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                os.path.join(config.PROJECT_ROOT, "ps5kbm.log"),
                maxBytes=4 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            root_logger.addHandler(file_handler)
        except OSError:
            pass
        for name in ("pyremoteplay", "playdirector"):
            logging.getLogger(name).setLevel(logging.WARNING)
        # controller 线程出异常时，pyremoteplay 只有该 logger 为 DEBUG 才会打印
        # 完整 traceback（写到 stdout.log），否则只剩一行 error 摘要
        logging.getLogger("pyremoteplay.controller").setLevel(logging.DEBUG)

    def _trace(self, message: str) -> None:
        """输入链路追踪，写进日志文件。"""
        logging.getLogger("ps5kbm.input").info(message)

    def _reload_config(self) -> config.AppConfig:
        self._config = config.load_config()
        self._mapper = InputMapper(self._config)
        self._mapper.set_left_value(self._config.left_stick.value)
        self._edit_mode = self._config.current_mode
        # 键鼠侧对象不在这里建：由 _sync_input_lifecycle 按当前玩法决定要不要实例化，
        # 手柄玩法下这台机器上不该存在任何键鼠监听对象。
        self._source = None
        self._source_ready = False
        return self._config

    def _mode_label(self, name: str) -> str:
        mode = self._config.modes.get(name)
        return (mode.label if mode and mode.label else name) if mode else name

    # ------------------------------------------------------------ 模式管理
    def _mode_option_labels(self) -> tuple[list[str], dict[str, str]]:
        """模式下拉框的显示文本与「文本 → 模式 id」映射。

        正常情况显示的就是 label；老配置里可能已经出现两个同名模式，
        这时补上内部 id 消歧，否则第二个模式永远选不中。
        """
        counts = Counter(self._mode_label(name) for name in self._config.modes)
        labels: list[str] = []
        mapping: dict[str, str] = {}
        for name in self._config.modes:
            label = self._mode_label(name)
            text = label if counts[label] == 1 else f"{label}（{name}）"
            labels.append(text)
            mapping[text] = name
        return labels, mapping

    def _mode_option_for(self, name: str) -> str:
        """模式 id → 下拉框里对应的显示文本。"""
        for text, mode_id in self._mode_option_labels()[1].items():
            if mode_id == name:
                return text
        return self._mode_label(name)

    def _mode_label_taken(self, label: str, exclude: str = "") -> bool:
        """同一个预设里是否已经有别的模式用了这个显示名。"""
        return any(
            self._mode_label(name) == label
            for name in self._config.modes
            if name != exclude
        )

    def choose_mode(self, label: str) -> None:
        """下拉框选择要编辑的模式。"""
        name = self._mode_option_map.get(label)
        if name is None:
            # 兜底：按显示名直接找（兼容没有维护映射表的调用路径）
            for candidate in self._config.modes:
                if self._mode_label(candidate) == label:
                    name = candidate
                    break
        if name is None:
            return
        self._edit_mode = name
        mapping_ui.refresh_mapping_list(self)
        mapping_ui.refresh_stick_keys(self)

    def add_mode(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="新模式名称（会显示在透明窗口右上角）", title="新建模式"
        )
        label = (dialog.get_input() or "").strip()
        if not label:
            return
        if self._mode_label_taken(label):
            messagebox.showwarning(
                "模式重名", f"已经有一个模式叫「{label}」了，换个名字吧。"
            )
            return
        name = f"mode{len(self._config.modes) + 1}"
        while name in self._config.modes:
            name += "_"
        base = self._mode_cfg()
        self._config.modes[name] = config.ModeConfig(
            label=label,
            keyboard_sticks=copy.deepcopy(base.keyboard_sticks),
            keyboard_buttons=copy.deepcopy(base.keyboard_buttons),
            mouse_buttons=copy.deepcopy(base.mouse_buttons),
        )
        self._edit_mode = name
        self._refresh_mode_ui()
        self._rebuild_mapper()
        self._persist()
        self._append_log(f"已新建模式：{label}")

    def rename_mode(self) -> None:
        mode = self._mode_cfg()
        dialog = ctk.CTkInputDialog(text="新的模式名称", title="重命名模式")
        label = (dialog.get_input() or "").strip()
        if not label:
            return
        if self._mode_label_taken(label, exclude=self._edit_mode):
            messagebox.showwarning(
                "模式重名", f"已经有一个模式叫「{label}」了，换个名字吧。"
            )
            return
        mode.label = label
        self._refresh_mode_ui()
        self._persist()

    def remove_mode(self) -> None:
        name = self._edit_mode
        if name == "default":
            messagebox.showwarning("提示", "默认模式不能删除")
            return
        if not messagebox.askyesno(
            "确认删除", f"删除模式「{self._mode_label(name)}」？"
        ):
            return
        del self._config.modes[name]
        self._edit_mode = "default"
        self._rebuild_mapper()
        self._refresh_mode_ui()
        self._persist()
        self._append_log("模式已删除")

    def set_mode_switch_key(self) -> None:
        """用按键捕获框设置模式切换键。"""

        def on_captured(name: str | None) -> None:
            if not name:
                return
            reason = self._global_key_conflict(
                name, ignore_mode_switch=self._config.mode_switch
            )
            if reason:
                messagebox.showwarning(
                    "这个键不能用",
                    f"{display_key(name)} 是{reason}，换一个键吧。",
                )
                return
            self._config.mode_switch = name
            if self._source is not None:
                self._source.set_mode_switch(name, self._on_mode_switch)
            self._refresh_mode_ui()
            self._persist()
            self._append_log(f"模式切换键已设为：{display_key(name)}")

        KeyCaptureDialog(self.root, on_captured)

    def _refresh_mode_ui(self) -> None:
        mapping_ui.refresh_mode_ui(self)
        mapping_ui.refresh_mapping_list(self)
        mapping_ui.refresh_stick_keys(self)

    def _on_mode_switch(self) -> None:
        """模式切换键：循环切到下一个模式（只在捕获时生效，由输入层保证）。"""
        names = list(self._config.modes)
        if len(names) <= 1:
            return
        current = self._mapper.mode
        index = names.index(current) if current in names else 0
        nxt = names[(index + 1) % len(names)]
        if self._mapper.set_mode(nxt):
            self._config.current_mode = nxt
            # 本方法跑在监听线程上：界面刷新与日志都丢回主线程做
            self._ui_queue.put(("mode", nxt))

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ------------------------------------------------------------ 界面搭建
    def _build_ui(self) -> None:
        ui_pages.build_topbar(self, self.root)

        body = ctk.CTkFrame(self.root, fg_color=T.BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=T.S6, pady=(T.S2, 0))
        ui_pages.build_sidebar(self, body)

        content = ctk.CTkFrame(body, fg_color=T.BG, corner_radius=0)
        content.pack(side="left", fill="both", expand=True, padx=(T.S4, 0))
        self._pages = {
            "connect": connect_ui.build_connect_page(self, content),
            "controller": controller_ui.build_controller_page(self, content),
            "mapping": mapping_ui.build_mapping_page(self, content),
            "run": run_ui.build_run_page(self, content),
        }
        for page in self._pages.values():
            page.pack_forget()

        ui_pages.build_log_panel(self, self.root)
        mapping_ui.refresh_mapping_list(self)
        self.show_page("connect")
        # 已配对 → 先进快捷视图并立刻检测局域网；没配对 → 保持完整流程
        self._probe_state = (
            flow.STATE_CHECKING if self._paired is not None else flow.STATE_UNPAIRED
        )
        connect_ui.show_view(self, flow.initial_view(self._paired))
        connect_ui.render(self)
        if self._paired is not None:
            # 等界面画完再发探测，避免首帧卡在加载状态
            self.root.after(120, self._start_probe)
        # 未连接时只显示「连接」页签
        self._update_nav()
        # 页面是固定布局（不滚动），窗口缩得比默认尺寸小会把下面内容裁掉
        self._lock_min_window_size()

    def _lock_min_window_size(self) -> None:
        """把最小窗口尺寸锁在默认尺寸，避免缩放后固定布局被裁。

        注意传的是逻辑尺寸：CTk 的 minsize 会再乘一次窗口缩放，
        传物理像素会导致最小尺寸被放大 1.5 倍（窗口反而被撑大）。
        """
        try:
            self.root.minsize(T.WINDOW_WIDTH, T.WINDOW_HEIGHT)
        except tk.TclError:
            pass

    def _visible_pages(self) -> set[str]:
        """当前该显示哪些页签。

        手柄玩法：手柄页**始终显示**（先接手柄、看电量和设置，再去连 PS5 唤醒）；
        键鼠玩法：映射 / 运行页要 PS5 连上才有意义。
        """
        pages = {"connect"}
        if self._config.controller.mode == "controller":
            pages.add("controller")
        elif self._bridge is not None:
            pages.update({"mapping", "run"})
        return pages

    def _update_nav(self) -> None:
        """按连接状态与玩法刷新侧栏页签；当前页被隐藏时退回「连接」页。"""
        pages = self._visible_pages()
        try:
            ui_pages.set_nav_visible(self, pages)
        except Exception:  # noqa: BLE001 - 侧栏还没建好时忽略
            return
        if self._page_name not in pages:
            self.show_page("connect")

    def show_page(self, name: str) -> None:
        if name not in self._pages:
            return
        if name not in self._visible_pages():
            name = "connect"
        for page in self._pages.values():
            page.pack_forget()
        self._pages[name].pack(fill="both", expand=True)
        self._page_name = name
        ui_pages.set_nav_state(self, name)

    # ------------------------------------------------------------ 状态显示
    def _set_pill(self, text: str, color: str) -> None:
        self._status_text.configure(text=text)
        self._status_dot.configure(text_color=color)

    def _set_run_state(self, title: str, subtitle: str, color: str = T.TEXT) -> None:
        self._run_title.configure(text=title, text_color=color)
        self._run_subtitle.configure(text=subtitle)

    def _apply_capture_state(self, capturing: bool) -> None:
        source = self._source
        if self._controller_mode() or source is None:
            # 手柄玩法 / 键鼠侧还没建起来：这里根本不存在"捕获"这回事。
            # 旧代码在这里无条件 set_capturing(False) + release_cursor()，
            # 手柄玩法下 _source 为 None 会直接 AttributeError。
            if source is not None:
                source.set_capturing(False)
                source.release_cursor()
            self._overlay.hide()
            self._capture_button.configure(text="开始捕获")
            if self._controller_mode():
                # 手柄玩法不需要"捕获"：手柄输入一直在转发，键鼠/光标必须保持可用，
                # 否则会锁光标 + 吞键盘 + 铺透明层，等于把电脑的鼠标键盘抢走。
                self._input_state_label.configure(text="输入：手柄直通（键鼠不受影响）")
                if self._bridge is not None:
                    self._set_pill(f"手柄直通 · {self._bridge.host}", T.OK)
                    self._set_run_state("手柄直通", "手柄输入已接管；键鼠照常可用")
                return
            self._input_state_label.configure(text="输入：未捕获")
            if self._bridge is not None:
                self._set_pill(f"已连接 · {self._bridge.host}", T.OK)
                self._set_run_state("已连接", "点「开始捕获」把键鼠交给 PS5")
            else:
                self._set_pill("未连接", T.TEXT_FAINT)
                self._set_run_state("未连接主机", "先到「连接」页建立会话，再回到这里开始捕获")
            return
        if capturing and self._bridge is None:
            # 没有会话时不允许进捕获：F8 在断开后仍可能被按到，必须挡住，
            # 否则会铺一层全屏透明层 + 藏鼠标，却没有地方发送输入。
            source.set_capturing(False)
            self._append_log("还没有连接主机，先到「连接」页建立会话")
            return
        # 界面状态是唯一事实来源：不管从哪条路径进来，输入层都对齐到这里
        source.set_capturing(capturing)
        self._capture_button.configure(text="停止捕获" if capturing else "开始捕获")
        self._trace(f"capture = {capturing}")
        if capturing:
            self._logged_keys.clear()
            source.lock_cursor()
            self._overlay.set_grab_focus(not bool(self._config.target_window))
            self._overlay.set_mode_text(self._mode_label(self._mapper.mode))
            self._overlay.show()
            if self._config.target_window:
                # 透明层已让出焦点，稍等窗口就绪后把焦点切到目标窗口
                self.root.after(150, self._activate_target_window)
            self._set_pill("捕获中", T.CAPTURE)
            self._set_run_state("捕获中", "键鼠已接管：F8 或按钮可停止", T.CAPTURE)
            listening = "监听正常" if source.listening else "监听异常"
            mouse_mode = (
                "鼠标已拦截" if source.full_capture else "鼠标降级（锁光标读位移）"
            )
            self._input_state_label.configure(
                text=f"输入：捕获中 | {listening} | {mouse_mode} | 按 WASD 看这里"
            )
        else:
            source.release_cursor()
            self._overlay.hide()
            self._input_state_label.configure(text="输入：未捕获")
            if self._bridge is not None:
                self._set_pill(f"已连接 · {self._bridge.host}", T.OK)
                self._set_run_state("已连接", "点「开始捕获」把键鼠交给 PS5")
            else:
                self._set_pill("未连接", T.TEXT_FAINT)
                self._set_run_state("未连接主机", "先到「连接」页建立会话，再回到这里开始捕获")

    def _apply_key_state(self, name: str) -> None:
        source = self._source
        if source is None:
            return
        listening = "监听正常" if source.listening else "监听异常"
        self._input_state_label.configure(
            text=f"输入：捕获中 | {listening} | 最近按键 {name.upper()}"
        )
        # 每个键第一次收到时提示一条（不在热路径上写文件日志）
        if name not in self._logged_keys:
            self._logged_keys.add(name)
            self._append_log(f"按键已收到：{name.upper()}")

    def _apply_stick_pair(self, pair) -> None:
        left, right = pair
        self._stick_state_label.configure(
            text=(
                f"摇杆  左 ({left[0]:+.2f}, {left[1]:+.2f})   "
                f"右 ({right[0]:+.2f}, {right[1]:+.2f})"
            )
        )

    # ------------------------------------------------------------ 已配对主机（快捷连接）
    def _start_probe(self) -> None:
        """检测已配对主机是否在当前局域网。

        只读主机身份，不建立 Remote Play 会话，因此不会占用 PS5 那条唯一的会话。
        探测任务跑在后台 asyncio 线程，结果经 _ui_queue 回主线程渲染。
        """
        if self._paired is None:
            self._probe_state = flow.STATE_UNPAIRED
            connect_ui.render(self)
            return
        if self._probe_pending or self._connecting or self._bridge is not None:
            return
        try:
            credentials = config.load_credentials(self._config.credentials_path)
        except (OSError, ValueError) as exc:
            self._append_log(f"读取配对凭据失败：{exc}")
            self._paired = None
            self._probe_state = flow.STATE_UNPAIRED
            connect_ui.render(self)
            return
        self._probe_pending = True
        self._probe_state = flow.STATE_CHECKING
        self._probe_error = ""
        self._connect_error = ""
        connect_ui.render(self)
        self._append_log(f"正在检测局域网里的已配对主机：{self._paired.display_name}……")
        future = asyncio.run_coroutine_threadsafe(
            probe.probe_console(credentials), self._loop
        )
        future.add_done_callback(self._on_probe_finished)

    def _on_probe_finished(self, future) -> None:
        """探测结束（在 asyncio 线程执行）：把结果丢进队列，绝不在这里碰 Tk。"""
        if not future.cancelled():
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - probe 内部已兜底，这里只防万一
                result = probe.ProbeResult(
                    online=False, error=f"{type(exc).__name__}: {exc}"
                )
            self._ui_queue.put(("probe", result))

    def _apply_probe_result(self, result) -> None:
        self._probe_pending = False
        self._probe_error = result.error
        if result.online:
            self._probe_state = flow.STATE_ONLINE
            self._apply_probe_identity(result)
            self._append_log(
                f"已配对主机在线：{result.host_name or result.host_ip}（{result.host_ip}）"
            )
            # 用户主动切到完整流程时不打扰；否则回到一键连接
            if self._bridge is None and not self._manual_full:
                connect_ui.show_view(self, flow.VIEW_QUICK)
        else:
            self._probe_state = flow.STATE_ERROR if result.error else flow.STATE_OFFLINE
            self._manual_full = False
            name = self._paired.display_name if self._paired else "已配对主机"
            if result.error:
                self._append_log(f"检测已配对主机失败：{result.error}")
            else:
                self._append_log(f"没有在当前局域网发现已配对主机：{name}")
            connect_ui.show_view(self, flow.VIEW_FULL)
        connect_ui.render(self)

    def _apply_probe_identity(self, result) -> None:
        """用探测结果刷新主机身份；PS5 换了 IP 时把新地址写回凭据。"""
        paired = self._paired
        if paired is None:
            return
        host_ip = result.host_ip or paired.host_ip
        ip_changed = bool(host_ip) and host_ip != paired.host_ip
        self._paired = flow.PairedConsole(
            host_id=result.host_id or paired.host_id,
            host_name=result.host_name or paired.host_name,
            host_ip=host_ip,
            account_id=paired.account_id,
            device_type=result.device_type or paired.device_type,
        )
        if not ip_changed or not result.credentials:
            return
        try:
            config.save_credentials(self._config.credentials_path, result.credentials)
        except OSError as exc:
            self._append_log(f"保存新 IP 失败：{exc}")
            return
        self._config.ps5_host = host_ip
        self._host_var.set(host_ip)
        self._persist()
        self._append_log(f"主机 IP 已更新为 {host_ip}")

    def _quick_connect(self) -> None:
        """快捷视图的「直接连接」：用已保存凭据建立会话，不再要求任何输入。"""
        if self._bridge is not None or self._connecting:
            return
        self._manual_full = False
        self._connect()

    def _switch_account(self) -> None:
        """「换 ID 连接」：回到完整流程，可改 Account ID 或配对新主机。"""
        self._manual_full = True
        connect_ui.show_view(self, flow.VIEW_FULL)
        connect_ui.render(self)
        self._append_log("已切到完整连接流程：可改 Account ID，或扫描后配对新主机")
        try:
            self._account_entry.focus_set()
        except Exception:  # noqa: BLE001 - 焦点设置失败不影响流程
            pass

    def _use_quick_view(self) -> None:
        """从完整流程回到已配对主机的快捷视图。"""
        if self._paired is None:
            return
        self._manual_full = False
        connect_ui.show_view(self, flow.VIEW_QUICK)
        connect_ui.render(self)

    # ------------------------------------------------------------ 完整流程（扫描 / 配对 / 连接）
    def _scan_devices(self) -> None:
        self._append_log("开始扫描局域网……")
        future = asyncio.run_coroutine_threadsafe(bridge.discover(timeout=3.0), self._loop)
        future.add_done_callback(lambda fut: self.root.after(0, self._on_scan_done, fut))

    def _on_scan_done(self, future) -> None:
        try:
            devices = future.result()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"扫描失败：{exc}")
            return
        self._devices = devices
        for child in self._device_list.winfo_children():
            child.destroy()
        if not devices:
            ctk.CTkLabel(
                self._device_list,
                text="没有发现主机，确认 PS5 已开机且同网段",
                font=ui_pages.font(T.XS),
                text_color=T.TEXT_FAINT,
            ).pack(anchor="w", padx=T.S2, pady=T.S2)
            self._append_log("扫描完成，没有发现主机")
            return
        for device in devices:
            ip = device.get("host-ip", "?")
            name = device.get("host-name", "?")
            button = ctk.CTkButton(
                self._device_list,
                text=f"{name}    {ip}",
                anchor="w",
                height=30,
                corner_radius=T.R_XS,
                fg_color="transparent",
                hover_color=T.BORDER,
                text_color=T.TEXT_DIM,
                font=ui_pages.font(T.XS, mono=True),
                command=lambda value=ip: self._host_var.set(value),
            )
            button.pack(fill="x", padx=T.S1, pady=1)
        self._append_log(f"扫描完成，发现 {len(devices)} 台主机")

    def _pair_console(self) -> None:
        host = self._host_var.get().strip()
        account_id = self._account_var.get().strip()
        pin = self._pin_var.get().strip()
        if not host or not account_id or len(pin) != 8:
            messagebox.showwarning("提示", "请填写 IP、Account ID 和 8 位 PIN")
            return
        self._append_log(f"开始配对 {host}……")
        future = asyncio.run_coroutine_threadsafe(
            bridge.pair(host, account_id, pin, self._config.credentials_path), self._loop
        )
        future.add_done_callback(lambda fut: self.root.after(0, self._on_pair_done, fut))

    def _on_pair_done(self, future) -> None:
        try:
            credentials = future.result()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"配对失败：{exc}")
            return
        self._append_log(
            f"配对成功：{credentials.get('host_name') or credentials['device_ip']}"
        )
        self._refresh_paired()
        if self._paired is None:
            return
        # 刚配对成功说明主机就在线，直接进快捷视图，不用再等一轮检测
        self._probe_state = flow.STATE_ONLINE
        self._probe_error = ""
        self._connect_error = ""
        self._manual_full = False
        self._host_var.set(self._paired.host_ip)
        self._account_var.set(self._paired.account_id)
        connect_ui.show_view(self, flow.VIEW_QUICK)
        connect_ui.render(self)

    def _wake_console(self) -> None:
        """唤醒待机中的 PS5（DDP 唤醒，不需要先建立会话）。"""
        if self._bridge is not None:
            self._append_log("已经连上了，不用唤醒")
            return
        if not os.path.exists(self._config.credentials_path):
            self._append_log("还没有配对凭据：先在完整流程里配对一次")
            return
        credentials = config.load_credentials(self._config.credentials_path)
        self._append_log(
            "正在唤醒 PS5…（待机唤醒通常 20~40 秒，主机启动后再点「直接连接」）"
        )
        for button in getattr(self, "_wake_buttons", []):
            try:
                button.configure(state="disabled")
            except Exception:  # noqa: BLE001
                pass
        future = asyncio.run_coroutine_threadsafe(bridge.wake(credentials), self._loop)
        future.add_done_callback(
            lambda fut: self.root.after(0, self._on_wake_done, fut)
        )

    def _on_wake_done(self, future) -> None:
        for button in getattr(self, "_wake_buttons", []):
            try:
                button.configure(state="normal")
            except Exception:  # noqa: BLE001
                pass
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - 唤醒失败给提示
            self._append_log(
                f"唤醒失败：{exc}（确认 PS5 已开启「远程游玩」，待机时保持网络连接）"
            )
            return
        self._append_log("唤醒指令已发送，等主机启动后点「直接连接」")
        self.root.after(8000, self._start_probe)

    def _connect(self) -> None:
        if self._bridge is not None or self._connecting:
            return
        self._connecting = True
        self._connect_error = ""
        connect_ui.render(self)
        self._append_log("正在建立 Remote Play 会话……")
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self._loop)
        future.add_done_callback(lambda fut: self.root.after(0, self._on_connected, fut))

    async def _connect_async(self) -> bridge.Ps5Bridge:
        # 上一个会话可能还在后台关闭：等它收尾再连，避免 PS5 上残留两条会话
        for _ in range(80):
            if not self._closing:
                break
            await asyncio.sleep(0.1)
        if not os.path.exists(self._config.credentials_path):
            raise FileNotFoundError(
                f"找不到配对凭据：{self._config.credentials_path}\n"
                "请先在「连接」页填 Account ID 和 PIN 完成配对"
            )
        credentials = config.load_credentials(self._config.credentials_path)
        ps5 = bridge.Ps5Bridge(credentials)
        await ps5.connect()
        return ps5

    def _on_connected(self, future) -> None:
        self._connecting = False
        try:
            self._bridge = future.result()
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).strip()
            if not detail:
                # 超时之类异常 str() 是空的，界面上会只显示「连接失败：」，这里补人话
                if isinstance(exc, TimeoutError):
                    detail = (
                        "连接超时：会话能建立但主机没继续握手。常见原因：\n"
                        "· PS5 停在登录 / 输入密码界面 —— 先在主机上完成登录，"
                        "并到「设置 → 用户与账户 → 登录设置」打开自动登录；\n"
                        "· PS5 在待机 / 关机，或没开启「远程游玩」、待机时没保持网络连接；\n"
                        "· 主机上还有官方 Remote Play 客户端占着会话。\n\n"
                        "处理完再点「直接连接」；待机唤醒可点「唤醒主机」。"
                    )
                else:
                    detail = f"{type(exc).__name__}（没有更多错误信息）"
            self._connect_error = detail
            self._append_log(f"连接失败：{detail}")
            # 之前只写日志，用户点了按钮看不到任何反馈；这里显式弹窗
            if "Another Remote Play session" in detail:
                messagebox.showwarning(
                    "主机被占用",
                    "PS5 上还有一个 Remote Play 会话没有断开。\n\n"
                    "解决办法：在 PS5 上把「启用远程游玩」关掉再打开"
                    "（或重启主机），然后重新连接。",
                )
            else:
                messagebox.showerror("连接失败", detail)
            connect_ui.render(self)
            return
        self._probe_state = flow.STATE_ONLINE
        self._probe_error = ""
        self._refresh_paired()
        # 界面上的扳机深度是连接前就调好的，连上后要下发给新会话，
        # 否则滑条显示 0.6、实际按 R2 还是满按。
        self._bridge.set_r2_depth(float(self._config.r2_depth))
        self._bridge.set_l2_depth(float(self._config.l2_depth))
        self._set_pill(f"已连接 · {self._bridge.host}", T.OK)
        self._set_run_state("已连接", "点「开始捕获」把键鼠交给 PS5")
        self._capture_button.configure(state="normal")
        connect_ui.show_view(self, flow.VIEW_QUICK)
        connect_ui.render(self)
        # 连上了才显示对应的页签（键鼠：映射/运行；手柄：手柄）
        self._update_nav()
        # 玩法隔离：按当前玩法把对应那一侧拉起来（键鼠：装监听/钩子/热键；手柄：起读取线程），
        # 另一侧这时一定不存在，再由这里兜一次
        self._sync_input_lifecycle()
        self._running = True
        self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self._loop)
        self._append_log("输入通道就绪，按 F8 或点按钮开始捕获")

    def _disconnect(self) -> None:
        ps5 = self._bridge
        self._running = False
        self._stop_tick_loop()
        # 照参考实现 releaseEffects()：会话结束时把马达、扳机效果和触觉一起放掉，
        # 否则断开后扳机还是硬的、马达还在转、音频端点还占着
        self._release_controller_effects()
        # 会话没了，手柄发出去的状态也不用再补发释放包，直接清空本地记录
        self._pending_controller_release = False
        self._controller_buttons_sent.clear()
        self._last_trigger_sent.clear()
        self._trigger_filter.reset()
        # 灯条记录也清掉：下次连上第一帧 pad_info 才会重新写颜色
        self._last_lightbar = b""
        self._usb_haptics.close()
        self._haptic_tone_chunks.clear()
        self._gyro_axis.reset()
        # 键鼠侧整套停掉（解钩子/热键/监听、销毁 Raw Input 窗口、松键、藏覆盖层）。
        # 放在 _bridge 置空前：捕获中按住的键还能补一包释放给主机。
        self._release_keyboard_side()
        self._bridge = None
        self._connecting = False
        self._connect_error = ""
        self._apply_capture_state(False)
        self._set_run_state("会话已断开", "回「连接」页重新连接")
        self._capture_button.configure(state="disabled")
        # 断开后回到该回的位置：配对过就回一键连接，否则留在完整流程
        self._manual_full = False
        connect_ui.show_view(self, flow.initial_view(self._paired))
        connect_ui.render(self)
        # 断开后只剩「连接」页签
        self._update_nav()
        self._append_log("已断开")
        if ps5 is not None:
            # 关闭会话本身放到后台：在界面线程等它会把窗口卡住好几秒
            self._closing = True
            future = asyncio.run_coroutine_threadsafe(
                self._close_session(ps5), self._loop
            )
            future.add_done_callback(self._on_session_closed)

    async def _close_session(self, ps5) -> None:
        """后台关闭会话，失败只记日志（本方法跑在 asyncio 线程）。"""
        logger = logging.getLogger(__name__)
        try:
            await asyncio.wait_for(ps5.close(), 12)
        except Exception as exc:  # noqa: BLE001 - 关闭失败不影响本地状态
            logger.warning("关闭会话时出错：%s", exc)

    def _on_session_closed(self, _future) -> None:
        """会话关闭完成（asyncio 线程）：只改标志与日志，不碰界面。"""
        self._closing = False
        logging.getLogger(__name__).info("会话已关闭")

    # ------------------------------------------------------------ 运行循环
    async def _tick_loop(self) -> None:
        last = time.perf_counter()
        was_capturing = False
        last_stick_value = self._mapper.left_value
        last_ui = 0.0
        last_heartbeat = 0.0
        last_send = 0.0
        last_left = (0.0, 0.0)
        last_key_sync = 0.0
        mouse_frames = 0
        mouse_motion = 0
        mouse_peak = 0.0
        last_mouse_log = 0.0
        while self._running:
            await asyncio.sleep(TICK_SECONDS)
            now = time.perf_counter()
            dt = now - last
            last = now
            try:
                if now - last_heartbeat >= 30.0:
                    last_heartbeat = now
                    # 心跳不在本线程碰 Tk：这里跑在 asyncio 线程，
                    # 直接 configure 会和界面线程的 Tk 调用抢锁，实测会卡死。
                    sent = self._bridge.sent_count if self._bridge else 0
                    self._ui_queue.put(("heartbeat", sent))
                # 不在循环里检查 connected：pyremoteplay 的 is_running 在心跳
                # 间隙可能短暂为 False，之前据此退出循环会把输入直接停掉。
                if self._bridge is None:
                    self._running = False
                    break
                if not self._bridge.alive:
                    # 主机端把会话踢了 / 网络断了：交给界面线程收尾，别继续空转发包
                    self._ui_queue.put(("session_lost", None))
                    self._running = False
                    break
                # 手柄模式：不走键鼠映射，直接转发手柄 + 陀螺仪
                if self._controller_mode():
                    started = time.perf_counter()
                    self._tick_controller(dt, now)
                    elapsed = time.perf_counter() - started
                    if elapsed > 0.05:
                        logging.getLogger("ps5kbm.tick").warning(
                            "手柄帧耗时 %.0f ms（可能卡顿）", elapsed * 1000
                        )
                    was_capturing = False
                    continue
                source = self._source
                if source is None:
                    # 键鼠侧不存在（刚切到别的玩法 / 还没建起来）：本帧不转发键鼠输入
                    was_capturing = False
                    continue
                if source.capturing:
                    # 只调用 poll：它读位移后会把光标拉回中心。
                    dx, dy = source.poll_mouse_delta()
                    # 无条件喂（含 0）：滑动平均需要每帧一个样本
                    self._mapper.on_mouse_delta(dx, dy)
                    if dx or dy:
                        mouse_frames += 1
                        mouse_motion += abs(dx) + abs(dy)
                    # 每 0.5 秒校正一次按键状态：多路监听偶尔会丢 keyup，
                    # 残留的键会让左摇杆方向错乱（按 A 却向右走）
                    if now - last_key_sync >= 0.5:
                        last_key_sync = now
                        self._mapper.drop_missing(source.pressed_keys())
                elif was_capturing:
                    source.release_cursor()
                    self._bridge.send_events(self._mapper.release_all())
                was_capturing = source.capturing
                result = self._mapper.tick(dt)
                # 鼠标诊断：捕获期间每 2 秒一条（仅 DEBUG，默认不写日志面板；
                # 排鼠标问题时把日志级别开到 DEBUG 就能看）
                if source.capturing and now - last_mouse_log >= 2.0:
                    last_mouse_log = now
                    raw_count, raw_motion = source.raw_mouse_stats()
                    logging.getLogger("ps5kbm.raw_mouse").debug(
                        "鼠标诊断：Raw %d 帧/%d 位移 → 映射 %d 帧/%d 位移；"
                        "右摇杆峰值 %.2f 当前 (%+.2f,%+.2f)；raw_ok=%s",
                        raw_count,
                        raw_motion,
                        mouse_frames,
                        mouse_motion,
                        mouse_peak,
                        result.right[0],
                        result.right[1],
                        source.raw_mouse_ok,
                    )
                    mouse_frames = 0
                    mouse_motion = 0
                    mouse_peak = 0.0
                if abs(result.right[0]) > mouse_peak:
                    mouse_peak = abs(result.right[0])
                if abs(result.right[1]) > mouse_peak:
                    mouse_peak = abs(result.right[1])
                # 回到 60Hz 发送：和 PS5 输入采样对齐，左摇杆变化时立即发
                left_changed = result.left != last_left
                last_left = result.left
                if left_changed or now - last_send >= 0.0166:
                    last_send = now
                    self._bridge.set_sticks(result.left, result.right)
                if result.events:
                    self._bridge.send_events(result.events)
                # 「摇杆幅度」映射动作会改变 left_value，这里同步到界面显示
                value = self._mapper.left_value
                if value != last_stick_value:
                    last_stick_value = value
                    self._ui_queue.put(("stick", value))
                # 摇杆实际输出节流显示，方便判断按键是否真的产生了位移
                if now - last_ui >= 0.15:
                    last_ui = now
                    self._ui_queue.put(("sticks", (result.left, result.right)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单帧异常不应终止整个循环
                import traceback

                detail = traceback.format_exc()
                self._append_log(f"输入循环异常：{type(exc).__name__}: {exc}")
                self._trace(f"输入循环异常：{detail}")
                await asyncio.sleep(0.2)

    def _stop_tick_loop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None

    def _toggle_capture(self) -> None:
        if self._bridge is None:
            self._append_log("还没有连接主机，先到「连接」页建立会话")
            return
        if self._controller_mode():
            # 手柄玩法：手柄一直在转发，不需要捕获，也不该抢键盘鼠标
            self._append_log("手柄玩法不需要捕获：手柄输入一直在转发，键鼠照常可用")
            return
        source = self._source
        if source is None:
            # 键鼠侧不存在（例如刚切到别的玩法）：没有捕获可言
            return
        previous = source.capturing
        state = source.toggle_capture()
        if previous:
            # 参考实现：失去焦点就松开手柄效果，避免扳机一直硬着 / 马达一直转
            self._release_controller_effects()
        self._apply_capture_state(state)

    def _on_capture_changed(self, capturing: bool) -> None:
        self._ui_queue.put(("capture", capturing))

    def _on_key_event(self, name: str) -> None:
        self._ui_queue.put(("key", name))

    # ------------------------------------------------------------ 手柄页
    def _controller_mode(self) -> bool:
        return self._config.controller.mode == "controller"

    def controller_snapshot(self):
        """手柄页用的当前状态（没连接返回 None）。"""
        return self._controller.snapshot() if self._controller.connected else None

    # ------------------------------------------------- 玩法隔离：键鼠侧 / 手柄侧
    # 两个玩法不共享任何本机输入对象：同一时刻只有一侧被实例化、被启动。
    #   键鼠玩法：_source（pynput 监听 + 键鼠钩子 + 全局热键 + Raw Input 窗口）、8ms 消息泵
    #   手柄玩法：_controller 读取线程（HID 句柄）、_usb_haptics 音频端点、100ms 页面轮询
    # 共用的只有远程会话这一层：bridge 的反馈回调常驻注册，但全部经 _pad_forward_active()
    # 闸门，键鼠玩法下不会写到实体手柄上。
    # 所有入口（启动 / 切换玩法 / 连接 / 断开 / 重建映射 / 关窗）都只走这一组方法，
    # 不允许在别处零散地 start/stop，否则等于又退回「两份对象都活着，靠闸门兜底」。

    def _current_side(self) -> str:
        """当前玩法 id：controller / keyboard。"""
        return "controller" if self._controller_mode() else "keyboard"

    def _new_input_source(self) -> InputSource:
        """按当前映射器造一套键鼠输入对象，回调 / 模式键 / 调参键一次接好。"""
        source = InputSource(self._mapper, hotkey=self._config.hotkey)
        source.set_capture_callback(self._on_capture_changed)
        source.set_key_callback(self._on_key_event)
        source.set_mode_switch(self._config.mode_switch, self._on_mode_switch)
        source.set_trigger_adjust(
            config.trigger_adjust_keys(self._config), self._on_adjust
        )
        return source

    def _init_keyboard_side(self) -> None:
        """建起键鼠侧：没有会话时只实例化对象，不装钩子（保持「连上才装」的旧行为）。"""
        if self._controller_mode():
            return  # 手柄玩法不持有任何键鼠对象
        if self._source is None:
            self._source = self._new_input_source()
        if self._bridge is not None and not self._source_ready:
            try:
                self._source.start()
                self._source_ready = True
            except Exception as exc:  # noqa: BLE001 - 起不来就别留半套钩子
                logging.getLogger(__name__).warning("启动键鼠输入层失败：%s", exc)
                self._release_keyboard_side()
                return
        self._ensure_pump_loop()

    def _release_keyboard_side(self) -> None:
        """拆掉键鼠侧整套：松键 → 停捕获 → 解钩子 / 注销热键 / 停监听 / 销毁 Raw Input 窗口。"""
        self._stop_pump_loop()
        self._overlay.hide()
        self._capture_button.configure(text="开始捕获")
        source = self._source
        if source is None:
            return
        try:
            if source.capturing:
                source.set_capturing(False)
                if self._bridge is not None:
                    # 别把键留在按下状态，否则主机会一直以为还按着
                    self._bridge.send_events(self._mapper.release_all())
            source.release_cursor()
        except Exception as exc:  # noqa: BLE001 - 释放失败也不能挡住后面的拆解
            logging.getLogger(__name__).warning("停止键鼠捕获时出错：%s", exc)
        try:
            source.stop()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("释放键鼠输入层失败：%s", exc)
        self._source = None
        self._source_ready = False
        self._logged_keys.clear()
        self._mapper.drop_missing(set())

    def _init_controller_side(self) -> None:
        """建起手柄侧：启动 HID 读取线程、数手柄、按连接方式决定触觉模式。"""
        self._controller_buttons_sent.clear()
        self._last_trigger_sent.clear()
        self._last_ctrl_sticks = ((0.0, 0.0), (0.0, 0.0))
        self._last_ctrl_send = 0.0
        self._pending_controller_release = False
        self._last_trigger_blocks.clear()
        self._trigger_mode_counts.clear()
        self._trigger_filter.reset()
        self._last_lightbar = b""
        self._gyro_axis.reset()
        self._gyro_output = (0.0, 0.0)
        self._haptics_pad_count = 0
        self._haptics_multi_logged = False
        self._mode_warned = False
        self._controller_was_connected = self._controller.connected
        # 触觉输出能力只在本次运行第一次进手柄玩法时探测一次：键鼠玩法下连 PortAudio 都不初始化
        if not self._haptics_env_logged:
            self._haptics_env_logged = True
            logging.getLogger("ps5kbm.haptics").info(
                "触觉输出：%s", haptics_usb.describe_environment()
            )
        self._controller.start_reader()
        self._update_haptics_pad_count()
        self._update_haptics_mode()
        self._ensure_controller_poll()

    def _release_controller_side(self) -> None:
        """拆掉手柄侧整套：先写释放报告（扳机 / 马达），再关触觉端点与 HID 句柄。"""
        # 顺序很重要：释放报告要靠还开着的 HID 句柄，触觉模式也要在旧玩法下判断
        self._release_controller_effects()
        try:
            self._usb_haptics.close()
        except Exception as exc:  # noqa: BLE001 - 关端点失败不影响后续拆解
            logging.getLogger(__name__).warning("关闭触觉端点失败：%s", exc)
        self._haptic_tone_chunks.clear()
        self._last_trigger_blocks.clear()
        self._trigger_mode_counts.clear()
        self._controller_buttons_sent.clear()
        self._last_trigger_sent.clear()
        self._last_ctrl_sticks = ((0.0, 0.0), (0.0, 0.0))
        self._pending_controller_release = False
        self._last_lightbar = b""
        self._trigger_filter.reset()
        self._haptics_pad_count = 0
        self._haptics_multi_logged = False
        self._stop_controller_poll()
        try:
            self._controller.stop()  # 关 HID 句柄、结束读取线程、复位触觉模式
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("停止手柄读取失败：%s", exc)
        self._controller_was_connected = False
        self._mode_warned = False

    def _leave_input_side(self, side: str) -> None:
        if side == "controller":
            self._release_controller_side()
        else:
            self._release_keyboard_side()

    def _enter_input_side(self, side: str) -> None:
        if side == "controller":
            self._init_controller_side()
        else:
            self._init_keyboard_side()

    def _sync_input_lifecycle(self) -> None:
        """按当前玩法收敛两侧状态：先拆另一侧，再建当前侧（启动 / 连接 / 切换都走这里）。"""
        side = self._current_side()
        self._leave_input_side("keyboard" if side == "controller" else "controller")
        self._enter_input_side(side)
        # 只在本次运行第一次写 INFO（启动时一行足够）；连接/断开等后续变化走 DEBUG
        logger = logging.getLogger(__name__)
        logger.log(
            logging.INFO if not self._lifecycle_logged else logging.DEBUG,
            "玩法隔离：当前 %s；键鼠侧=%s 手柄侧=%s",
            "手柄直通" if side == "controller" else "键鼠映射",
            "已实例化" if self._source is not None else "未实例化",
            "读取线程在跑" if self._controller.is_alive() else "已停止",
        )
        self._lifecycle_logged = True

    def set_input_mode(self, label: str) -> None:
        """切换玩法：先把旧玩法整侧拆掉，再把新玩法整侧建起来。"""
        mode = controller_ui.MODE_LABELS.get(label, "keyboard")
        if self._bridge is not None:
            messagebox.showwarning(
                "已经连上了", "先断开连接，再切换玩法（键鼠 / 手柄）。"
            )
            self._input_mode_var.set(
                controller_ui.MODE_LABELS_REVERSE.get(
                    self._config.controller.mode, "键鼠"
                )
            )
            return
        if mode == self._config.controller.mode:
            self._input_mode_var.set(label)
            return
        previous = self._current_side()
        # 先在旧玩法下释放：扳机 / 马达的释放报告要靠旧玩法仍生效、HID 还开着
        self._leave_input_side(previous)
        self._config.controller.mode = mode
        self._input_mode_var.set(label)
        self._enter_input_side(mode)
        self._apply_capture_state(False)
        self._update_nav()
        self._persist()
        self._append_log(
            "玩法："
            + (
                "手柄（手柄页用于查看 / 设置手柄连接）"
                if mode == "controller"
                else "键鼠（连上 PS5 后显示映射 / 运行）"
            )
            + f" · 已释放{'手柄侧' if previous == 'controller' else '键鼠侧'}，"
            f"已初始化{'手柄侧' if mode == 'controller' else '键鼠侧'}"
        )

    def refresh_controller(self) -> None:
        """页面上的「重新检测」：让后台线程立刻再试一次。"""
        if not self._controller_mode():
            return  # 键鼠玩法不持有手柄读取线程
        self._controller.start_reader()
        self._append_log("正在重新检测手柄……")

    def _update_haptics_pad_count(self) -> None:
        """数一下当前接了几个 Sony 手柄（参考实现要求唯一才路由触觉）。

        只在手柄连接状态变化时枚举一次：HID 枚举是原生调用，别放在每帧路径上。
        """
        try:
            paths = {bytes(info.path or b"") for info in dualsense.list_devices()}
            self._haptics_pad_count = len(paths)
        except Exception:  # noqa: BLE001 - 枚举失败就当没有
            self._haptics_pad_count = 0
        if self._haptics_pad_count > 1 and not self._haptics_multi_logged:
            self._haptics_multi_logged = True
            self._append_log(
                f"检测到 {self._haptics_pad_count} 个 Sony 手柄，"
                "USB 触觉暂不路由（参考实现同样要求手柄唯一）"
            )

    def _poll_controller(self) -> None:
        """界面轮询：刷新手柄页状态、处理断连、跑陀螺仪校准采样。"""
        try:
            state = self._controller.snapshot()
            connected = state is not None
            if connected != self._controller_was_connected:
                self._controller_was_connected = connected
                if connected:
                    self._append_log(
                        f"手柄已连接：{self._controller.device_label or 'DualSense'}"
                    )
                    # 新手柄（或刚插线）灯条是固件默认色，清掉记录让 pad_info 重新写
                    self._last_lightbar = b""
                    self._trigger_filter.reset()
                    self._update_haptics_pad_count()
                    self._update_haptics_mode()
                else:
                    self._append_log("手柄已断开")
                    # 参考实现：手柄不再被读取时，触觉流和扳机效果一起放掉，
                    # 否则音频端点会一直占着一个已经不存在的设备
                    self._usb_haptics.close()
                    self._haptic_tone_chunks.clear()
                    self._trigger_filter.reset()
                    self._last_trigger_blocks.clear()
                    self._last_lightbar = b""
                    self._haptics_pad_count = 0
                    if self._controller_mode():
                        self._pending_controller_release = True
            if self._controller_mode() and not connected and not self._mode_warned:
                self._mode_warned = True
                self._append_log("手柄模式下没有检测到手柄，接上 USB 线后会自动开始")
            if connected:
                self._mode_warned = False
            # 自定义陀螺仪激活键：抓"新按下"的按键，超时自动取消
            if self._gyro_capture:
                if state is not None:
                    new_buttons = set(state.buttons) - self._gyro_prev_buttons
                    if new_buttons:
                        self._finish_gyro_capture(sorted(new_buttons)[0])
                    elif (
                        self._gyro_capture_deadline
                        and time.monotonic() >= self._gyro_capture_deadline
                    ):
                        self._gyro_capture = False
                        self._gyro_capture_deadline = 0.0
                        self._append_log("没等到按键，陀螺仪激活键没改")
                        controller_ui.refresh_activation(self)
            if state is not None:
                self._gyro_prev_buttons = set(state.buttons)
        except Exception as exc:  # noqa: BLE001 - 界面轮询不能中断 Tk 定时器
            logging.getLogger(__name__).warning("手柄页刷新失败：%s", exc)
        finally:
            try:
                controller_ui.refresh(self)
            except Exception:  # noqa: BLE001 - 页面还没建好时忽略
                pass
            # 键鼠玩法下不再自我续期：手柄侧不存在，轮询也该停
            if self._controller_mode():
                self._poll_job = self.root.after(100, self._poll_controller)
            else:
                self._poll_job = None

    def _ensure_controller_poll(self) -> None:
        """确保手柄页轮询在跑（只有手柄玩法需要）。"""
        if self._poll_job is not None or not self._controller_mode():
            return
        self._poll_job = self.root.after(120, self._poll_controller)

    def _stop_controller_poll(self) -> None:
        """停掉手柄页轮询（切到键鼠玩法 / 关窗）。"""
        job = self._poll_job
        self._poll_job = None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:  # noqa: BLE001 - 关窗时 Tk 可能已经销毁
                pass

    # ------------------------------------------------------------ 陀螺仪
    def _gyro_params(self) -> gyro.GyroParams:
        cfg = self._config.controller.gyro
        return gyro.GyroParams(
            sensitivity_x=cfg.sensitivity_x,
            sensitivity_y=cfg.sensitivity_y,
            deadzone=cfg.deadzone,
            smoothing=cfg.smoothing,
            invert_x=cfg.invert_x,
            invert_y=cfg.invert_y,
        )

    def _gyro_active(self, state) -> bool:
        cfg = self._config.controller.gyro
        return gyro.activation_pressed(
            cfg.activation, state.buttons, state.l2, state.r2
        )

    def _toggle_gyro(self) -> None:
        enabled = bool(self._gyro_var.get())
        self._config.controller.gyro.enabled = enabled
        self._append_log("陀螺仪：" + ("开启" if enabled else "关闭"))
        self._persist()

    def set_gyro_activation(self, choice: str) -> None:
        """激活键：常开 / 预设按键 / 自定义（按手柄上的键来捕获）。"""
        if choice == controller_ui.CUSTOM_CHOICE:
            self._gyro_capture = True
            self._gyro_capture_deadline = time.monotonic() + 6.0
            state = self._controller.snapshot()
            self._gyro_prev_buttons = set(state.buttons) if state else set()
            self._gyro_activation_var.set(controller_ui.CAPTURE_HINT)
            self._append_log("请按住手柄上想用来触发陀螺仪的按键（6 秒内）")
            return
        self._config.controller.gyro.activation = controller_ui.activation_value(choice)
        self._persist()
        self._append_log(f"陀螺仪激活键：{choice}")

    def _finish_gyro_capture(self, button: str) -> None:
        """自定义激活键捕获完成：写回配置并刷新下拉框。"""
        self._gyro_capture = False
        self._gyro_capture_deadline = 0.0
        self._config.controller.gyro.activation = button.strip().lower()
        self._persist()
        self._append_log(f"陀螺仪激活键：按住 {controller_ui.button_label(button)}")
        controller_ui.refresh_activation(self)

    def _apply_gyro_sens_x(self, value: float) -> None:
        sens = max(0.1, min(3.0, float(value)))
        self._config.controller.gyro.sensitivity_x = sens
        self._gyro_sens_x_label.configure(text=f"水平灵敏度 {sens:.2f}")

    def _apply_gyro_sens_y(self, value: float) -> None:
        sens = max(0.1, min(3.0, float(value)))
        self._config.controller.gyro.sensitivity_y = sens
        self._gyro_sens_y_label.configure(text=f"垂直灵敏度 {sens:.2f}")

    def _apply_gyro_deadzone(self, value: float) -> None:
        deadzone = max(0.0, min(0.1, float(value)))
        self._config.controller.gyro.deadzone = deadzone
        self._gyro_deadzone_label.configure(text=f"死区 {deadzone:.3f}")

    def _apply_gyro_smoothing(self, value: float) -> None:
        smoothing = max(0.0, min(0.9, float(value)))
        self._config.controller.gyro.smoothing = smoothing
        self._gyro_smoothing_label.configure(text=f"平滑 {smoothing:.2f}")

    def _toggle_gyro_invert_x(self) -> None:
        enabled = bool(self._gyro_invert_x_var.get())
        self._config.controller.gyro.invert_x = enabled
        self._append_log("陀螺仪水平方向：" + ("反向" if enabled else "正向"))

    def _toggle_gyro_invert_y(self) -> None:
        enabled = bool(self._gyro_invert_y_var.get())
        self._config.controller.gyro.invert_y = enabled
        self._append_log("陀螺仪垂直方向：" + ("反向" if enabled else "正向"))

    def calibrate_gyro(self) -> None:
        """打开游戏式校准窗口：放稳 → 倒计时 → 采样 → 结果。"""
        gyro_calib_ui.open_dialog(self)

    def apply_gyro_bias(self, bias: tuple[float, float, float]) -> None:
        """校准窗口算出的零偏写回配置并保存。"""
        self._gyro_bias = (float(bias[0]), float(bias[1]), float(bias[2]))
        self._config.controller.gyro.bias = list(self._gyro_bias)
        self._gyro_calibrated = True
        self._gyro_axis.reset()
        self._persist()
        self._append_log(
            "陀螺仪已校准：偏置 "
            f"({self._gyro_bias[0]:+.4f}, {self._gyro_bias[1]:+.4f}, {self._gyro_bias[2]:+.4f}) rad/s"
        )

    # ------------------------------------------------------------ 震动 / 扳机
    # 震动方式三选一：音频触觉（USB 独占，马达位会让它静音）/ 经典马达 / 关闭
    VIBRATION_MODE_LABELS = ("音频触觉（USB）", "经典马达", "关闭")
    _VIBRATION_MODE_KEYS = {
        "音频触觉（USB）": "haptics",
        "经典马达": "motors",
        "关闭": "off",
    }

    def vibration_mode(self) -> str:
        """当前震动方式：haptics / motors / off。"""
        if self._config.controller.haptics_usb:
            return "haptics"
        if self._config.controller.rumble_enabled:
            return "motors"
        return "off"

    def vibration_mode_label(self) -> str:
        mode = self.vibration_mode()
        for label, key in self._VIBRATION_MODE_KEYS.items():
            if key == mode:
                return label
        return "经典马达"

    def vibration_hint_text(self) -> str:
        """手柄页那行说明：随连接方式和当前选择变化。"""
        mode = self.vibration_mode()
        connected = self._controller.connected
        usb = connected and self._controller.transport == "usb"
        if mode == "off":
            return "震动已关闭：主机下发的震动与触觉都不再写入手柄"
        if mode == "motors":
            return "经典马达：主机震动值驱动两个马达，USB / 蓝牙都能用，手感较粗"
        if not connected:
            return "音频触觉：最接近原生的细碎手感，需要 USB 连接（插线后自动生效）"
        if not usb:
            return "当前是蓝牙：音频触觉用不了（蓝牙没有触觉通道），想有震动请选「经典马达」"
        return "音频触觉：主机触觉音频直达手柄执行器，手感最接近原生（USB 独占）"

    def set_vibration_mode(self, label: str) -> None:
        """切换震动方式并落盘（音频触觉与经典马达互斥）。"""
        mode = self._VIBRATION_MODE_KEYS.get(str(label), "motors")
        cfg = self._config.controller
        cfg.haptics_usb = mode == "haptics"
        cfg.rumble_enabled = mode == "motors"
        if not cfg.haptics_usb:
            # 关掉音频触觉就释放音频端点
            self._usb_haptics.close()
            self._haptic_tone_chunks.clear()
        self._update_haptics_mode()
        if hasattr(self, "_vibration_mode_var"):
            self._vibration_mode_var.set(self.vibration_mode_label())
        message = "震动方式：" + self.vibration_mode_label()
        if mode == "haptics" and self._controller.connected and self._controller.transport != "usb":
            message += "（音频触觉需要 USB，当前是蓝牙）"
        self._append_log(message)
        self._persist()

    def _apply_rumble_gain(self, value: float) -> None:
        gain = max(0.0, min(2.0, float(value)))
        self._config.controller.rumble_gain = gain
        self._rumble_gain_label.configure(text=f"{gain:.2f}")

    def test_rumble(self) -> None:
        if not self._controller.connected:
            self._append_log("先接上手柄再试震动")
            return
        # 触觉模式与经典马达互斥（马达使能位会让音频触觉静音）：
        # 先临时切回马达通道，300ms 后自动恢复音频触觉
        haptics_active = self._controller.haptics_mode
        if haptics_active:
            self._controller.set_haptics_mode(False)
        self._controller.rumble(0.8, 0.8, force=True)
        self.root.after(250, lambda: self._controller.rumble(0.0, 0.0, force=True))
        if haptics_active:

            def restore_haptics() -> None:
                self._controller.set_haptics_mode(True)
                self._controller.unlock_audio()

            self.root.after(350, restore_haptics)
        # USB 下同时给 3/4 声道送一段 60Hz 触觉波形，单独验证原生触觉通道。
        # 触觉源固定 3kHz、单包上限 100ms，所以按 30ms 节奏逐包喂，
        # 一次性塞 0.6 秒会被队列上限整段清空（等于没声音）。
        if self._controller.transport == "usb" and self._config.controller.haptics_usb:
            self._haptic_tone_chunks = haptics_usb.test_tone_chunks(0.6)
            self._haptic_tone_tick()
            if self._usb_haptics.is_open():
                self._append_log("试震动：马达 + USB 触觉波形（3/4 声道，约 0.6 秒）")
            else:
                self._append_log(
                    "试震动：马达已发；USB 触觉端点没打开"
                    "（确认手柄插在 PC 的 USB 口上，日志里有打开失败的原因）"
                )
            return
        self._append_log("试震动：马达（USB 连接才会有原生触觉）")

    def _haptic_tone_tick(self) -> None:
        """按 30ms 节奏把试震动波形喂给触觉端点（跑在界面线程）。"""
        chunks = self._haptic_tone_chunks
        if not chunks:
            return
        self._usb_haptics.feed(chunks.pop(0))
        self.root.after(30, self._haptic_tone_tick)

    def _on_rumble(self, low: float, high: float) -> None:
        """主机下发的震动 → 本地手柄（协议层验证后再接进来）。"""
        cfg = self._config.controller
        if not cfg.rumble_enabled:
            return
        gain = cfg.rumble_gain
        self._controller.rumble(low * gain, high * gain)

    # ------------------------------------------------- 主机下发反馈（后台线程）
    def _pad_forward_active(self) -> bool:
        """只有「手柄玩法 + 手柄已连接」才允许碰实体手柄。

        键鼠玩法下主机照样会把震动/扳机/灯条/触觉推下来，但那时实体手柄不该被我们
        占用（否则一直在写它的马达/灯条，还会把它切到触觉模式）。两个玩法彻底隔断。
        """
        return self._controller_mode() and self._controller.connected

    def _release_controller_effects(self) -> None:
        """照参考实现的 releaseEffects()：马达归零 + 两边扳机释放 + 清本地记录。

        参考实现（Veyra ControllerInput.cpp）在失去焦点、手柄断开、会话结束时都调它：
        不清的话扳机会一直硬着、马达会一直转，音频端点也还占着。
        """
        self._last_trigger_blocks.clear()
        if not self._controller_mode() or not self._controller.connected:
            return
        try:
            # 先让马达归零：之后写的扳机/灯条报告会带着缓存值，不归零会继续转
            self._controller.rumble(0.0, 0.0)
            # 两边扳机一次写成 Off（模式 0x05），不会互相覆盖
            self._controller.set_trigger_effects()
        except Exception:  # noqa: BLE001 - 放掉效果失败不影响主流程
            pass
    def _update_haptics_mode(self) -> None:
        """USB + 开关打开 + 已连接 + 手柄玩法 → 走音频触觉，此时不再发经典马达。

        实机结论：输出报告里只要带上马达使能位（valid_flag0 的 0x01|0x02），
        手柄就切到「兼容震动」模式，音频触觉立刻静音——这就是游戏里一点震动都没有的原因。
        """
        active = (
            self._config.controller.haptics_usb
            and self._controller_mode()
            and self._controller.connected
            and self._controller.transport == "usb"
        )
        self._controller.set_haptics_mode(active)

    def _on_console_rumble(self, left: float, right: float) -> None:
        """主机下发的震动值（0~1，跑在协议线程）：转发到本地手柄。"""
        cfg = self._config.controller
        if not self._pad_forward_active():
            return
        if not cfg.rumble_enabled:
            return
        if self._controller.haptics_mode:
            # 触觉模式下马达通道是关的（发了会静音触觉），直接跳过
            return
        now = time.monotonic()
        if now - self._last_console_rumble < 0.02:
            return
        self._last_console_rumble = now
        gain = cfg.rumble_gain
        self._controller.rumble(
            min(1.0, left * gain),
            min(1.0, right * gain),
        )

    def _on_haptics_pcm(self, pcm: bytes) -> None:
        """主机下发的触觉 PCM（跑在解码线程）：只有手柄玩法 + USB 才写到手柄音频端点。"""
        if not self._pad_forward_active():
            # 键鼠玩法完全不碰实体手柄：连日志都不记，避免看起来像"还在收触觉流"
            return
        # 诊断计数：每 5 秒记一行，用来判断「主机有没有发、数据是不是静音、写到哪一步停了」
        now = time.monotonic()
        self._haptics_rx += 1
        self._haptics_last_size = len(pcm)
        if len(pcm) >= 4:
            middle = len(pcm) // 2
            sample = int.from_bytes(pcm[middle : middle + 2], "little", signed=True)
            self._haptics_peak = max(self._haptics_peak, abs(sample))
        if now - self._haptics_stats_at >= 5.0:
            self._haptics_stats_at = now
            underruns, queued, refills, _ratio = self._usb_haptics.stats()
            # 常态只写 DEBUG（不刷日志面板）；只有出现「新的欠载」时才写一条 INFO，
            # 这样日志里只看得到真正需要关注的事件。
            new_underruns = underruns - self._haptics_underruns_prev
            self._haptics_underruns_prev = underruns
            logger = logging.getLogger("ps5kbm.haptics")
            level = logging.INFO if new_underruns > 0 else logging.DEBUG
            logger.log(
                level,
                "触觉流：收到 %d 包 / 写入 %d 包 / 峰值 %d / 包长 %d"
                " / 欠载 %d（新 %d）/ 恢复 %d / 队列 %d/%d 帧（上限）"
                "（transport=%s connected=%s 流=%s 开关=%s 多手柄=%d 触觉模式=%s）",
                self._haptics_rx,
                self._haptics_tx,
                self._haptics_peak,
                self._haptics_last_size,
                underruns,
                new_underruns,
                refills,
                queued,
                self._usb_haptics.target_frames(),
                self._controller.transport,
                self._controller.connected,
                self._usb_haptics.is_open(),
                self._config.controller.haptics_usb,
                self._haptics_pad_count,
                self._controller.haptics_mode,
            )
            self._haptics_rx = 0
            self._haptics_tx = 0
            self._haptics_peak = 0
        if not self._config.controller.haptics_usb:
            return
        if self._controller.transport != "usb":
            return
        if self._haptics_pad_count > 1:
            # 四声道端点 + 手柄都必须唯一，否则不路由（分不清是哪只的端点）
            return
        self._usb_haptics.feed(pcm)
        self._haptics_tx += 1

    def _on_console_led(self, rgb: bytes) -> None:
        """主机下发的灯条颜色（data_type 9，跑在协议线程）：同步到手柄灯条。"""
        if not self._pad_forward_active():
            return
        if rgb == self._last_lightbar:
            return
        self._last_lightbar = rgb
        self._controller.set_lightbar(rgb)

    def _on_console_trigger_effect(self, left: bytes, right: bytes) -> None:
        """主机下发的扳机效果块（各 11 字节，跑在协议线程）。

        照 chiaki / Veyra 的做法：左右两块合成**一份报告**一起写。
        分开写会让后一份报告覆盖前一份，只有最后一侧生效。
        另一侧没变化时沿用上一次的块，不会把已有效果清掉。
        """
        cfg = self._config.controller
        if not self._pad_forward_active():
            return
        if not cfg.adaptive_triggers:
            return
        changed = False
        for side, block in (("l", left), ("r", right)):
            if not block or len(block) != 11:
                continue
            # 主机在开车/刹车时发 0x05（HID 里是 Off）但带非零参数，
            # 实际含义是「反馈阻力」；实机验证改写成 0x21 后油门/刹车阻尼正常。
            block = bytearray(block)
            if block[0] == 0x05 and any(block[1:]):
                block[0] = 0x21
            block = bytes(block)
            if self._last_trigger_blocks.get(side) == block:
                continue
            self._last_trigger_blocks[side] = block
            self._trigger_mode_counts[block[0]] = (
                self._trigger_mode_counts.get(block[0], 0) + 1
            )
            now = time.monotonic()
            if now - self._trigger_stats_at >= 5.0:
                self._trigger_stats_at = now
                summary = " ".join(
                    f"0x{mode:02X}×{count}"
                    for mode, count in sorted(self._trigger_mode_counts.items())
                )
                logging.getLogger("ps5kbm.trigger").debug(
                    "扳机效果类型（近 5 秒，已写入手柄）：%s", summary or "无"
                )
                self._trigger_mode_counts.clear()
            logging.getLogger("ps5kbm.trigger").debug(
                "扳机效果 %s 类型 0x%02X：%s", side, block[0], block.hex()
            )
            changed = True
        if changed:
            self._controller.set_trigger_effects(
                self._last_trigger_blocks.get("l"),
                self._last_trigger_blocks.get("r"),
            )

    def stop_trigger_effect(self) -> None:
        """立刻停掉两边的扳机效果（不受开关影响，任何时候都能放掉）。"""
        if not self._controller.connected:
            self._append_log("手柄没连上，没法停扳机效果")
            return
        self._controller.clear_trigger_effect()
        self._last_trigger_blocks.clear()
        self._trigger_effect_var.set("关闭")
        self._append_log("已停止扳机效果（R2 / L2）")

    def _toggle_adaptive_triggers(self) -> None:
        enabled = bool(self._adaptive_trigger_var.get())
        self._config.controller.adaptive_triggers = enabled
        if not enabled:
            # 关掉开关时顺手把已经写进去的效果放掉，避免扳机一直硬着
            self._release_controller_effects()
        self._append_log(
            "自适应扳机：" + ("开启" if enabled else "关闭")
        )
        self._persist()

    def _toggle_diagnostics(self) -> None:
        """抓包诊断：记录远端下发的负载类型，用来确认震动 / 扳机数据走哪条通道。"""
        enabled = bool(self._diagnostics_var.get())
        bridge.set_diagnostics(enabled)
        self._append_log(
            "抓包诊断："
            + ("开启（日志里会记录非 AV 包与负载类型，连一局游戏即可采到）" if enabled else "关闭")
        )

    def apply_trigger_effect(self) -> None:
        """本地测试自适应扳机效果（写入手柄，不依赖主机下发）。"""
        if not self._config.controller.adaptive_triggers:
            self._append_log("先打开「自适应扳机」开关，再试效果")
            return
        if not self._controller.connected:
            self._append_log("先接上手柄再试扳机效果")
            return
        name = self._trigger_effect_var.get()
        side = self._trigger_side_var.get()
        sides = ("r", "l") if side == "双" else (("r",) if side == "R2" else ("l",))
        if name == "关闭":
            self._controller.clear_trigger_effect()
            self._append_log("已关闭扳机效果" + ("（双）" if side == "双" else f"（{side}）"))
            return
        effect = dualsense.effect_bytes(name)
        left_effect = effect if "l" in sides else None
        right_effect = effect if "r" in sides else None
        ok = self._controller.set_trigger_effects(left_effect, right_effect)
        self._append_log(
            f"扳机效果：{name}"
            + ("（双）" if side == "双" else f"（{side}）")
            + ("" if ok else " · 写入失败")
        )

    # ------------------------------------------------------------ 手柄发送
    def _tick_controller(self, dt: float, now: float) -> None:
        """手柄模式的一帧：直通按键/摇杆/扳机 + 叠加陀螺仪。"""
        if self._pending_controller_release:
            self._pending_controller_release = False
            self._release_controller_inputs()
        state = self._controller.snapshot()
        if state is None:
            return
        left, right = self._compose_controller_sticks(state, dt)
        changed = (left, right) != self._last_ctrl_sticks
        if changed or now - self._last_ctrl_send >= 0.0166:
            self._last_ctrl_send = now
            self._last_ctrl_sticks = (left, right)
            self._bridge.set_sticks(left, right)
        # 扳机：先过滤抖动再发（参考实现 TriggerFilter）。
        # 每个值变化都会生成一条 history 事件，而每个包只带最新 8 条；
        # 一侧松开、另一侧还按着并抖动时，松开会被挤出窗口，主机就认为没松。
        l2_byte, r2_byte = self._trigger_filter.apply(
            trigger_filter.to_byte(state.l2), trigger_filter.to_byte(state.r2), now
        )
        for name, byte_value in (("l2", l2_byte), ("r2", r2_byte)):
            last = self._last_trigger_sent.get(name)
            if last == byte_value:
                continue
            self._last_trigger_sent[name] = byte_value
            self._bridge.set_trigger(name, byte_value / 255.0)
            if byte_value == 0 and last:
                # 松开时清掉陀螺仪残留，避免右摇杆被带着漂
                self._gyro_axis.reset()
                self._gyro_output = (0.0, 0.0)
        pressed = {name for name in state.buttons if name not in ("L2", "R2")}
        events: list[tuple[str, str]] = []
        for name in sorted(pressed - self._controller_buttons_sent):
            events.append((name, "press"))
        for name in sorted(self._controller_buttons_sent - pressed):
            events.append((name, "release"))
        if events:
            self._controller_buttons_sent = set(pressed)
            self._bridge.send_events(events)
        # 陀螺仪排查：激活期间每 0.5 秒记一行原始值 + 输出值
        if self._config.controller.gyro.enabled and self._gyro_active(state):
            if now - self._gyro_trace_last >= 0.5:
                self._gyro_trace_last = now
                logging.getLogger("ps5kbm.gyro").debug(
                    "陀螺仪 gyro=(%+.2f,%+.2f,%+.2f) out=(%+.2f,%+.2f) 右摇杆=(%+.2f,%+.2f)",
                    state.gyro[0],
                    state.gyro[1],
                    state.gyro[2],
                    self._gyro_output[0],
                    self._gyro_output[1],
                    right[0],
                    right[1],
                )
        # 界面读数限速：tick 是 250Hz，每帧都发会把界面线程压死（实测会“未响应”）
        if now - self._last_ui_sticks >= 0.05:
            self._last_ui_sticks = now
            self._ui_queue.put(("sticks", (left, right)))

    def _compose_controller_sticks(self, state, dt: float):
        """手柄摇杆 + 陀螺仪贡献（按住激活键时）。"""
        left = (state.lx, state.ly)
        right_x, right_y = state.rx, state.ry
        cfg = self._config.controller.gyro
        if cfg.enabled:
            gx, gy = self._gyro_axis.update(
                state.gyro,
                self._gyro_bias,
                self._gyro_params(),
                dt,
                self._gyro_active(state),
            )
            self._gyro_output = (gx, gy)
            right_x = gyro.clamp(right_x + gx)
            right_y = gyro.clamp(right_y + gy)
        else:
            self._gyro_output = (0.0, 0.0)
        return left, (right_x, right_y)

    def _release_controller_inputs(self) -> None:
        """松开手柄发出去的所有输入（切模式/断连时调用，跑在事件循环线程）。"""
        if self._bridge is None:
            self._controller_buttons_sent.clear()
            self._last_trigger_sent.clear()
            self._trigger_filter.reset()
            return
        events = [(name, "release") for name in sorted(self._controller_buttons_sent)]
        self._controller_buttons_sent.clear()
        if events:
            self._bridge.send_events(events)
        for name in ("l2", "r2"):
            self._bridge.set_trigger(name, 0.0)
        self._last_trigger_sent.clear()
        self._trigger_filter.reset()
        self._bridge.set_sticks((0.0, 0.0), (0.0, 0.0))
        self._gyro_axis.reset()
        self._gyro_output = (0.0, 0.0)
        self._last_ctrl_sticks = ((0.0, 0.0), (0.0, 0.0))

    # ------------------------------------------------------------ 映射编辑
    def _mode_cfg(self, name: str | None = None) -> config.ModeConfig:
        """取当前编辑中的模式配置（找不到时退回 default）。"""
        target = name or self._edit_mode
        return self._config.modes.get(target) or self._config.modes["default"]

    def _binding_rows(self) -> list[tuple[str, object]]:
        mode = self._mode_cfg()
        rows: list[tuple[str, object]] = []
        for key, value in mode.keyboard_buttons.items():
            rows.append((str(key), value))
        for button, value in mode.mouse_buttons.items():
            rows.append((f"mouse_{button}", value))
        return sorted(rows)

    @staticmethod
    def _split_source(source: str) -> tuple[str, str]:
        if source.startswith("mouse_"):
            return "mouse", source[len("mouse_"):]
        return "keyboard", source

    def edit_mapping(self, source: str) -> None:
        category, name = self._split_source(source)
        mode = self._mode_cfg()
        store = mode.mouse_buttons if category == "mouse" else mode.keyboard_buttons
        if name not in store:
            return

        def save(value) -> None:
            store[name] = value
            self._rebuild_mapper()
            self._persist()
            mapping_ui.refresh_mapping_list(self)

        ActionEditor(self.root, source, store[name], save)

    def remove_mapping(self, source: str) -> None:
        category, name = self._split_source(source)
        mode = self._mode_cfg()
        store = mode.mouse_buttons if category == "mouse" else mode.keyboard_buttons
        store.pop(name, None)
        self._rebuild_mapper()
        self._persist()
        mapping_ui.refresh_mapping_list(self)

    def rebind_mapping(self, source: str) -> None:
        """把一条映射的来源键换成新捕获的键（动作保持不变）。"""
        category, name = self._split_source(source)
        mode = self._mode_cfg()
        store = mode.mouse_buttons if category == "mouse" else mode.keyboard_buttons
        if name not in store:
            return

        def on_captured(new_source: str | None) -> None:
            if not new_source or new_source == source:
                return
            reason = self._hotkey_reason(new_source)
            if reason:
                messagebox.showwarning(
                    "这个键不能用",
                    f"{display_key(new_source)} 是{reason}，换一个键吧。",
                )
                return
            blocked = self._mapping_key_conflict(new_source)
            if blocked and not messagebox.askyesno(
                "这个键会被抢占",
                f"{display_key(new_source)} 是{blocked}，捕获时按下会先触发它，"
                "这条映射不会生效。仍然绑到它上面？",
            ):
                return
            new_category, new_name = self._split_source(new_source)
            target = (
                mode.mouse_buttons
                if new_category == "mouse"
                else mode.keyboard_buttons
            )
            if new_name in target and not messagebox.askyesno(
                "键位已被占用",
                f"{display_key(new_source)} 已经绑定了「{describe_action(target[new_name])}」，"
                "用当前动作覆盖它？",
            ):
                return
            value = store.pop(name)
            target[new_name] = value
            self._rebuild_mapper()
            self._persist()
            mapping_ui.refresh_mapping_list(self)
            self._append_log(
                f"映射已改键：{display_key(source)} → {display_key(new_source)}"
            )

        KeyCaptureDialog(self.root, on_captured)

    def _stick_source_keys(self, mode=None) -> list[str]:
        """当前模式里被左摇杆方向占用掉的键。"""
        sticks = (mode or self._mode_cfg()).keyboard_sticks
        return [str(key).lower() for keys in sticks.values() for key in keys]

    def _binding_sources(self, mode=None) -> list[str]:
        """当前模式里已经被映射占用的键（鼠标统一带 mouse_ 前缀）。"""
        target = mode or self._mode_cfg()
        sources = [str(key).lower() for key in target.keyboard_buttons]
        sources += [f"mouse_{str(name).lower()}" for name in target.mouse_buttons]
        return sources

    def _hotkey_reason(self, source: str) -> str:
        """映射唯一硬禁的键：捕获热键。捕获中按它只会开关捕获，永远轮不到映射。"""
        if str(source or "").strip().lower() == self._config.hotkey:
            return "捕获热键"
        return ""

    def _mapping_key_conflict(self, source: str) -> str:
        """映射来源键的「软冲突」：允许绑，但捕获时会先被别的功能吃掉。

        只查模式切换键和扳机调参键——它们在输入层被优先处理，映射永远不触发，
        所以绑之前问一句。方向键不在此列：一个键同时走路和按键是正常玩法。
        """
        return config.key_conflict(
            source,
            mode_switch=self._config.mode_switch,
            trigger_keys=config.trigger_adjust_keys(self._config),
        )

    def _global_key_conflict(
        self,
        source: str,
        *,
        ignore_mode_switch: str = "",
        ignore_trigger: str = "",
    ) -> str:
        """改调参键 / 切换键时用：比映射更严，已经映射出去的键也算冲突。"""
        return config.key_conflict(
            source,
            hotkey=self._config.hotkey,
            mode_switch=self._config.mode_switch,
            trigger_keys=config.trigger_adjust_keys(self._config),
            stick_keys=self._stick_source_keys(),
            mapping_sources=self._binding_sources(),
            ignore_mode_switch=ignore_mode_switch,
            ignore_trigger=ignore_trigger,
        )

    def _note_stick_share(self, source: str) -> None:
        """同一个键既是方向键又是映射时给条日志：两个动作会同时发生。"""
        if str(source or "").strip().lower() in self._stick_source_keys():
            self._append_log(
                f"{display_key(source)} 同时是左摇杆方向键，捕获时两个动作都会触发"
            )

    def _add_mapping(self) -> None:
        """先弹按键捕获框，识别出键名后再选动作类型。"""

        def on_captured(source: str | None) -> None:
            if not source:
                return
            reason = self._hotkey_reason(source)
            if reason:
                messagebox.showwarning(
                    "这个键不能用",
                    f"{display_key(source)} 是{reason}，换一个键吧。",
                )
                return
            blocked = self._mapping_key_conflict(source)
            if blocked and not messagebox.askyesno(
                "这个键会被抢占",
                f"{display_key(source)} 是{blocked}，捕获时按下会先触发它，"
                "这条映射不会生效。仍然添加？",
            ):
                return
            category, name = self._split_source(source)
            mode = self._mode_cfg()
            target = mode.mouse_buttons if category == "mouse" else mode.keyboard_buttons
            if name in target and not messagebox.askyesno(
                "键位已被占用",
                f"{display_key(source)} 已经绑定了「{describe_action(target[name])}」，"
                "用新动作覆盖它？",
            ):
                return
            self._note_stick_share(source)

            def save(value) -> None:
                if category == "mouse":
                    mode.mouse_buttons[name] = value
                else:
                    mode.keyboard_buttons[name] = value
                self._rebuild_mapper()
                self._persist()
                mapping_ui.refresh_mapping_list(self)

            ActionEditor(self.root, source, "CROSS", save)

        KeyCaptureDialog(self.root, on_captured)

    # ------------------------------------------------------------ 摇杆设置
    def edit_stick_keys(self) -> None:
        StickKeysEditor(
            self.root, dict(self._mode_cfg().keyboard_sticks), self._save_stick_keys
        )

    def _save_stick_keys(self, sticks: dict) -> None:
        self._mode_cfg().keyboard_sticks = sticks
        self._rebuild_mapper()
        self._persist()
        mapping_ui.refresh_stick_keys(self)
        self._append_log("左摇杆方向键已更新")

    def _toggle_mouse_view(self) -> None:
        """鼠标视角总开关：关掉后鼠标不再驱动右摇杆。"""
        enabled = bool(self._mouse_enabled_var.get())
        self._config.mouse.enabled = enabled
        self._append_log("鼠标视角：" + ("开启" if enabled else "关闭"))
        self._commit_sliders()

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self._topmost_var.get()))

    def _toggle_flick(self) -> None:
        """Flick Stick：水平快速甩动触发瞬间转身。"""
        enabled = bool(self._flick_var.get())
        self._config.mouse.flick_enabled = enabled
        self._append_log("Flick Stick：" + ("开启" if enabled else "关闭"))
        self._commit_sliders()

    def _activate_target_window(self) -> None:
        title = self._config.target_window
        if not title:
            return
        found = windows.activate_by_title(title, exclude="XY-CtoPS5")
        self._append_log(
            f"已切换到窗口：{title}" if found else f"未找到窗口：{title}（继续捕获）"
        )

    def refresh_targets(self) -> None:
        """重新枚举当前可见窗口，刷新下拉选项。"""
        titles = [title for _, title in windows.list_windows(exclude="XY-CtoPS5")]
        self._target_box.configure(values=["（不切换）"] + titles)

    def _choose_target(self, title: str) -> None:
        self._config.target_window = "" if title == "（不切换）" else title
        self._persist()
        self._append_log(
            "捕获时切换窗口："
            + (self._config.target_window or "不切换（透明层保持焦点）")
        )

    def _apply_stick_value(self, value: float) -> None:
        self._stick_value_label.configure(text=f"左摇杆幅度 {value:.2f}")

    def _apply_stick_ramp(self, value: float) -> None:
        """左摇杆过渡速度：越大推得越快，0 表示瞬时到位。"""
        ramp = float(value)
        self._config.left_stick.ramp = ramp
        self._stick_ramp_label.configure(text=f"{ramp:.1f}/s")

    def _apply_deadzone(self, value: float) -> None:
        """右摇杆死区：越小越灵敏，0 表示完全不过滤微小位移。"""
        deadzone = max(0.0, min(0.5, float(value)))
        self._config.mouse.deadzone = deadzone
        self._deadzone_label.configure(text=f"死区 {deadzone:.3f}")

    def _apply_sensitivity(self, value: float) -> None:
        """鼠标到摇杆的换算放大倍数，越大视角转得越快。"""
        sensitivity = max(0.2, min(6.0, float(value)))
        self._config.mouse.sensitivity = sensitivity
        self._sens_label.configure(text=f"灵敏度 {sensitivity:.1f}")

    def _apply_slow_sensitivity(self, value: float) -> None:
        """慢转灵敏度：小幅度移动时的倍率，越高越跟手。"""
        slow = max(0.2, min(3.0, float(value)))
        self._config.mouse.slow_sensitivity = slow
        self._slow_sens_label.configure(text=f"慢灵敏 {slow:.2f}")

    def _apply_fast_sensitivity(self, value: float) -> None:
        """快转灵敏度：快速甩动时的倍率，越高转身越快。"""
        fast = max(0.5, min(6.0, float(value)))
        self._config.mouse.fast_sensitivity = fast
        self._fast_sens_label.configure(text=f"快灵敏 {fast:.1f}")

    def _apply_smoothing(self, value: float) -> None:
        """一阶平滑：越大越顺但延迟越高。"""
        smooth = max(0.0, min(0.95, float(value)))
        self._config.mouse.smoothing = smooth
        self._smoothing_label.configure(text=f"平滑 {smooth:.2f}")

    def _choose_curve(self, label: str) -> None:
        """切换响应曲线类型。"""
        curve_map = {
            "线性": "linear",
            "二次": "quadratic",
            "三次": "cubic",
            "幂": "power",
        }
        self._config.mouse.curve_type = curve_map.get(label, "linear")
        self._commit_sliders()

    def _apply_r2(self, value: float) -> None:
        """设定 R2 按下时的输出深度（0~1），不直接发送。"""
        depth = max(0.0, min(1.0, float(value)))
        self._config.r2_depth = depth
        try:
            self._r2_var.set(depth)
        except Exception:  # noqa: BLE001 - 滑条未创建时忽略
            pass
        self._r2_label.configure(text=f"R2 {depth:.1f}")
        if self._bridge is not None:
            self._bridge.set_r2_depth(depth)

    def _apply_l2(self, value: float) -> None:
        """设定 L2 按下时的输出深度（0~1），不直接发送。"""
        depth = max(0.0, min(1.0, float(value)))
        self._config.l2_depth = depth
        try:
            self._l2_var.set(depth)
        except Exception:  # noqa: BLE001 - 滑条未创建时忽略
            pass
        self._l2_label.configure(text=f"L2 {depth:.1f}")
        if self._bridge is not None:
            self._bridge.set_l2_depth(depth)

    def _on_adjust(self, action: str) -> None:
        """调参键回调（跑在监听线程）：只入队，Tk 操作回界面线程做。"""
        self._ui_queue.put(("adjust", action))

    def _apply_adjust(self, action: str) -> None:
        """按绑定的调参键改扳机深度：每按一次 0.1，右上角提示当前值。"""
        target = "r2" if action.startswith("r2") else "l2"
        step = 0.1 if action.endswith("_up") else -0.1
        variable = self._r2_var if target == "r2" else self._l2_var
        try:
            current = float(variable.get())
        except Exception:  # noqa: BLE001 - 控件没建好时按默认满按算
            current = 1.0
        depth = max(0.0, min(1.0, current + step))
        if target == "r2":
            self._apply_r2(depth)
        else:
            self._apply_l2(depth)
        self._overlay.show_notice(f"{target.upper()} {depth:.1f}")
        # 按键改的深度也要落盘，否则重启就回到 1.0
        self._persist()

    def _rebind_trigger(self, action: str) -> None:
        """改调参键：捕获到新键后写进 config.json，并同步给输入层。"""

        def on_captured(name: str | None) -> None:
            if not name:
                return
            reason = self._global_key_conflict(name, ignore_trigger=action)
            if reason:
                messagebox.showwarning(
                    "这个键不能用",
                    f"{display_key(name)} 是{reason}，换一个键吧。",
                )
                return
            setattr(self._config, action, name)
            if self._source is not None:
                self._source.set_trigger_adjust(
                    config.trigger_adjust_keys(self._config), self._on_adjust
                )
            self._persist()
            run_tuning_ui.refresh_trigger_buttons(self)
            self._append_log(
                f"{run_tuning_ui.trigger_label(action)} 调参键：{display_key(name)}"
            )

        KeyCaptureDialog(self.root, on_captured, allow_wheel=True)

    def _commit_sliders(self, _event=None) -> None:
        """滑块松开后才写盘，避免拖动过程中反复 IO 卡顿。"""
        self._persist()

    def create_preset(self) -> None:
        """新建一个空预设：只有一个「默认」模式，映射全空，建完直接切过去。"""
        dialog = ctk.CTkInputDialog(
            text="新预设名称（映射为空，默认只有一个「默认」模式）",
            title="新建预设",
        )
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            name = config.check_preset_name(raw)
        except ValueError as exc:
            messagebox.showwarning("名称不可用", str(exc))
            return
        if config.is_user_preset(name) or name in config.list_presets():
            messagebox.showwarning(
                "预设已存在",
                f"「{name}」已经存在，换个名字吧。\n要复用当前配置可以用「另存为…」。",
            )
            return
        try:
            # 空映射，但沿用当前的热键 / 切换键 / 调参键 / 目标窗口，
            # 否则新建预设会把用户的切换键悄悄换回默认 F9
            path = config.save_preset(
                name, config.new_empty_config(name, self._config)
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("新建失败", str(exc))
            return
        self._refresh_preset_list(select=name)
        self.apply_preset(name)
        self._append_log(f"已新建空预设：{path}")

    def save_as_preset(self) -> None:
        """把当前整套配置（含所有模式）另存为一份预设副本。"""
        dialog = ctk.CTkInputDialog(
            text="预设名称（例如其他游戏名）\n会给当前所有模式单独存一套",
            title="新建 / 另存为预设",
        )
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            name = config.check_preset_name(raw)
        except ValueError as exc:
            messagebox.showwarning("名称不可用", str(exc))
            return
        if config.is_user_preset(name) and not messagebox.askyesno(
            "确认覆盖", f"预设「{name}」已存在，用当前配置覆盖它？"
        ):
            return
        try:
            path = config.save_preset(name, self._config)
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._config.preset = name
        self._refresh_preset_list(select=name)
        self._preset_owner = name
        self._persist()
        self._append_log(f"预设已保存：{path}")

    def remove_preset(self) -> None:
        """删除用户预设文件（内置预设不能删）。"""
        name = self._preset_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "先在上面的下拉框选择要删除的预设")
            return
        if not config.is_user_preset(name):
            messagebox.showinfo(
                "内置预设",
                f"「{name}」是内置预设，不能删除。\n需要改动时可以「另存为」一个新名字。",
            )
            return
        deleting_current = self._config.preset == name
        if not messagebox.askyesno(
            "确认删除",
            f"删除用户预设「{name}」？\n\n只删 presets\\{name}.json"
            + ("，并切换到另一个可用预设。" if deleting_current else "。"),
        ):
            return
        try:
            path = config.delete_preset(name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        if deleting_current:
            # 关键：删的是当前预设时必须真正加载回落的那一套，不能只改名字。
            # 否则旧 modes 会被 _persist 当成新预设的内容写盘，把另一个预设覆盖成空的。
            self._preset_owner = ""
            remaining = [item for item in config.list_presets() if item != name]
            self._refresh_preset_list()
            if remaining:
                self.apply_preset(remaining[0])
            else:
                self._config.preset = ""
                self._persist()
                mapping_ui.refresh_mapping_list(self)
                mapping_ui.refresh_stick_keys(self)
                mapping_ui.refresh_mode_ui(self)
        else:
            self._refresh_preset_list()
        self._append_log(f"预设已删除：{path}")

    def _refresh_preset_list(self, select: str | None = None) -> None:
        """重新读预设目录，刷新下拉选项（新建 / 删除 / 应用后调用）。"""
        self._preset_values = config.list_presets()
        if select:
            self._preset_var.set(select)
        elif self._preset_var.get() not in self._preset_values and self._preset_values:
            self._preset_var.set(self._preset_values[0])
        if getattr(self, "_preset_box", None) is not None:
            self._preset_box.configure(values=self._preset_values)

    def _restore_preset_selection(self) -> None:
        """预设读取失败后，把下拉框拉回实际生效的那个，避免「显示 A 实际 B」。"""
        self._refresh_preset_list()
        if self._config.preset and self._config.preset in self._preset_values:
            self._preset_var.set(self._config.preset)

    def apply_preset(self, name: str | None = None) -> None:
        """应用预设：下拉选中或新建后直接调用，不再需要单独的「应用」按钮。"""
        preset = (name or self._preset_var.get() or "").strip()
        if not preset:
            return
        try:
            raw = config.load_preset(preset)
        except FileNotFoundError as exc:
            messagebox.showerror("错误", str(exc))
            self._restore_preset_selection()
            return
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror(
                "预设读取失败",
                f"预设「{preset}」的文件读不出来：\n{exc}\n\n"
                "它可能被改坏了，可以删掉这个预设文件或换个预设。",
            )
            self._restore_preset_selection()
            return
        built = config.build_config(raw)
        self._config.preset = preset
        self._config.modes = built.modes
        self._config.mode_switch = built.mode_switch
        # 不覆盖 mouse / left_stick：手感参数由 tuning.json 独立管理，
        # 应用预设只换键位映射，用户调好的灵敏度/死区/平滑必须保持不变。
        self._config.current_mode = "default"
        self._edit_mode = "default"
        self._preset_var.set(preset)
        self._preset_owner = preset
        self._rebuild_mapper()
        self._persist()
        mapping_ui.refresh_mapping_list(self)
        mapping_ui.refresh_stick_keys(self)
        mapping_ui.refresh_mode_ui(self)
        self._append_log(f"已应用预设：{preset}")

    def _persist(self) -> None:
        """编辑后立即写盘：config.json 存映射，tuning.json 存摇杆手感参数。

        当前预设如果是用户自己新建的，也同步写回预设文件（内置预设只读，不覆盖），
        这样切换来切换去不会丢掉改过的键位。
        """
        try:
            config.save_config(self._config)
        except OSError as exc:
            self._append_log(f"配置保存失败：{exc}")
        try:
            # 摇杆/鼠标手感单独文件：改动即存，应用预设不覆盖
            config.save_tuning(self._config)
        except OSError as exc:
            self._append_log(f"手感参数保存失败：{exc}")
        if (
            self._config.preset
            and self._config.preset == getattr(self, "_preset_owner", "")
            and config.is_user_preset(self._config.preset)
        ):
            try:
                config.save_preset(self._config.preset, self._config)
            except (OSError, ValueError) as exc:
                self._append_log(f"预设保存失败：{exc}")

    def _rebuild_mapper(self) -> None:
        was_capturing = bool(
            self._source is not None and self._source.capturing and self._source_ready
        )
        # 旧输入对象整套扔掉（钩子 / 热键 / Raw Input 窗口一起释放），再按当前玩法重建。
        # 手柄玩法下 _init_keyboard_side 什么都不做，_source 保持 None。
        self._release_keyboard_side()
        self._mapper = InputMapper(self._config)
        self._mapper.set_left_value(self._config.left_stick.value)
        self._init_keyboard_side()
        if was_capturing and self._source is not None:
            # 捕获中改了映射：重建后必须把捕获接回去，否则覆盖层还开着、
            # 按钮还写着「停止捕获」，实际输入却已经断了。
            self._source.set_capturing(True)
            self._apply_capture_state(True)
            self._append_log("配置已更新，捕获已自动恢复")

    # ------------------------------------------------------------ 杂项
    def _append_log(self, text: str) -> None:
        # Tk 只能在主线程碰；后台线程误调时转回界面线程
        if threading.current_thread() is not threading.main_thread():
            self._ui_queue.put(("log", text))
            return
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text + "\n")
        # 长时间挂着日志会无限变长（内存与滚动都越来越慢），超过上限裁掉最旧的
        lines = int(self._log_text.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self._log_text.delete("1.0", f"{lines - LOG_MAX_LINES + 1}.0")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _poll_events(self) -> None:
        # 每轮最多处理固定条数：万一某个生产者瞬间刷屏，也不能让界面线程
        # 卡在 while True 里几秒（Windows 会直接判定“未响应”）。剩余的下轮再消化。
        for _ in range(100):
            try:
                message = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)
        for _ in range(200):
            try:
                kind, value = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "capture":
                self._apply_capture_state(value)
            elif kind == "probe":
                self._apply_probe_result(value)
            elif kind == "stick":
                self._apply_stick_value(value)
            elif kind == "sticks":
                self._apply_stick_pair(value)
            elif kind == "key":
                self._apply_key_state(value)
            elif kind == "adjust":
                self._apply_adjust(value)
            elif kind == "mode":
                self._edit_mode = value
                self._refresh_mode_ui()
                label = self._mode_label(value)
                self._overlay.set_mode_text(label)
                self._append_log(f"切换到模式：{label}")
            elif kind == "session_lost":
                if self._bridge is not None:
                    self._append_log(
                        "Remote Play 会话已断开（主机端关闭或网络中断），已自动断开"
                    )
                    self._disconnect()
            elif kind == "heartbeat":
                try:
                    self._run_subtitle.configure(text=f"已发送 {value} 帧输入")
                except Exception:  # noqa: BLE001 - 页面没建好时忽略
                    pass
            elif kind == "log":
                self._append_log(value)
        self.root.after(120, self._poll_events)

    def _on_close(self) -> None:
        self._running = False
        # 先取消两个 Tk 定时器（手柄轮询 / Raw Input 消息泵），否则关窗时 Tk 会报
        # invalid command name
        self._stop_controller_poll()
        self._stop_pump_loop()
        try:
            self._overlay.hide()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._controller.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._stop_tick_loop()
            # 键鼠侧整套拆掉（解钩子 / 注销热键 / 销毁 Raw Input 窗口 / 松键）
            self._release_keyboard_side()
            if self._bridge is not None:
                future = asyncio.run_coroutine_threadsafe(self._bridge.close(), self._loop)
                future.result(timeout=5)
        except Exception:  # noqa: BLE001 - 退出路径不再抛错
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()


def main() -> int:
    # 单实例：两个实例会抢同一个手柄的 HID 句柄，还会互相覆盖 config.json。
    # 第二次启动不弹窗，直接把已经在跑的那个窗口切到前台就退出。
    if not windows.acquire_single_instance():
        windows.activate_by_title("XY-CtoPS5")
        return 0
    # 声明 DPI 感知：系统缩放不是 100% 时，DPI-unaware 进程的
    # SetCursorPos 与 GetCursorPos 使用的坐标系不一致，锁回光标后位置
    # 仍会偏移一大截，每帧都被算成巨大位移——表现为视角狂飘。
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:  # noqa: BLE001
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
    # 提高系统定时器精度（默认 15.6ms）：tick 循环要跑 250Hz，
    # 否则鼠标位移被 15ms 采样一次，游戏里会一顿一顿的
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:  # noqa: BLE001 - 提精度失败不影响主流程
        pass
    try:
        ctk.set_default_color_theme("blue")
        root = ctk.CTk()
        Ps5KbmApp(root)
        root.mainloop()
    finally:
        try:
            import ctypes

            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
