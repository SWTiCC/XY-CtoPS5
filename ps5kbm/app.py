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
import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from . import bridge, config, ui_pages, windows
from . import theme as T
from .input_source import InputSource
from .mapping import InputMapper
from .overlay import CaptureOverlay
from .ui_common import (
    ActionEditor,
    KeyCaptureDialog,
    QueueLogHandler,
    StickKeysEditor,
)

TICK_SECONDS = 1.0 / 250.0


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
        self._state_vars()

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        self._bridge: bridge.Ps5Bridge | None = None
        self._tick_task = None
        self._running = False
        self._devices: list[dict] = []
        self._source_ready = False
        self._page_name = "connect"
        self._logged_keys: set[str] = set()
        self._last_trace = 0.0
        self._overlay = CaptureOverlay(self.root, self._toggle_capture)

        self._build_ui()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Raw Input 窗口消息由主线程排空（子线程收不到 WM_INPUT）。
        # 间隔 8ms：消息泵本身约 10ms 一批，再密只是空转 Tk 定时器。
        self.root.after(8, self._pump_raw_messages)

    def _pump_raw_messages(self) -> None:
        """主线程定时排空 Raw Input 窗口消息（非阻塞）。"""
        try:
            if self._source is not None:
                self._source.pump_mouse_messages()
        except Exception:  # noqa: BLE001 - 消息泵异常不能中断 UI
            pass
        self.root.after(8, self._pump_raw_messages)

    # ------------------------------------------------------------ 初始化
    def _state_vars(self) -> None:
        cfg = self._reload_config()
        # 已配对过的话，直接从 credentials.json 带回 IP 与 Account ID，省得重新翻
        host = cfg.ps5_host
        account_id = cfg.account_id
        if not host or not account_id:
            try:
                credentials = config.load_credentials(cfg.credentials_path)
                host = host or credentials.get("device_ip", "")
                account_id = account_id or credentials.get("account_id_input", "")
            except (OSError, ValueError):
                pass
        self._host_var = tk.StringVar(value=host or "192.168.1.38")
        self._account_var = tk.StringVar(value=account_id)
        self._pin_var = tk.StringVar()
        self._preset_var = tk.StringVar(value=cfg.preset)
        self._preset_values = config.list_presets()

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
        self._source = InputSource(self._mapper, hotkey=self._config.hotkey)
        self._source.set_capture_callback(self._on_capture_changed)
        self._source.set_key_callback(self._on_key_event)
        self._source.set_mode_switch(self._config.mode_switch, self._on_mode_switch)
        self._source.set_scroll_callback(self._on_wheel)
        self._source.set_l2_adjust_callback(self._on_l2_adjust)
        self._source_ready = False
        return self._config

    def _mode_label(self, name: str) -> str:
        mode = self._config.modes.get(name)
        return (mode.label if mode and mode.label else name) if mode else name

    # ------------------------------------------------------------ 模式管理
    def choose_mode(self, label: str) -> None:
        """下拉框选择要编辑的模式。"""
        for name in self._config.modes:
            if self._mode_label(name) == label:
                self._edit_mode = name
                break
        ui_pages.refresh_mapping_list(self)
        ui_pages.refresh_stick_keys(self)

    def add_mode(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="新模式名称（会显示在透明窗口右上角）", title="新建模式"
        )
        label = (dialog.get_input() or "").strip()
        if not label:
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
            self._config.mode_switch = name
            self._source.set_mode_switch(name, self._on_mode_switch)
            self._refresh_mode_ui()
            self._persist()
            self._append_log(f"模式切换键已设为：{name.upper()}")

        KeyCaptureDialog(self.root, on_captured)

    def _refresh_mode_ui(self) -> None:
        ui_pages.refresh_mode_ui(self)
        ui_pages.refresh_mapping_list(self)
        ui_pages.refresh_stick_keys(self)

    def _on_mode_switch(self) -> None:
        """模式切换键：循环切到下一个模式（只在捕获时生效）。"""
        names = list(self._config.modes)
        if len(names) <= 1:
            return
        current = self._mapper.mode
        index = names.index(current) if current in names else 0
        nxt = names[(index + 1) % len(names)]
        if self._mapper.set_mode(nxt):
            self._config.current_mode = nxt
            label = self._mode_label(nxt)
            self._overlay.set_mode_text(label)
            self._ui_queue.put(("mode", nxt))
            self._append_log(f"切换到模式：{label}")

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
            "connect": ui_pages.build_connect_page(self, content),
            "mapping": ui_pages.build_mapping_page(self, content),
            "run": ui_pages.build_run_page(self, content),
        }
        for page in self._pages.values():
            page.pack_forget()

        ui_pages.build_log_panel(self, self.root)
        ui_pages.refresh_mapping_list(self)
        self.show_page("connect")

    def show_page(self, name: str) -> None:
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
        self._capture_button.configure(text="停止捕获" if capturing else "开始捕获")
        self._trace(f"capture = {capturing}")
        if capturing:
            self._logged_keys.clear()
            self._source.lock_cursor()
            self._overlay.set_grab_focus(not bool(self._config.target_window))
            self._overlay.set_mode_text(self._mode_label(self._mapper.mode))
            self._overlay.show()
            if self._config.target_window:
                # 透明层已让出焦点，稍等窗口就绪后把焦点切到目标窗口
                self.root.after(150, self._activate_target_window)
            self._set_pill("捕获中", T.CAPTURE)
            self._set_run_state("捕获中", "键鼠已接管：F8 或按钮可停止", T.CAPTURE)
            listening = "监听正常" if self._source.listening else "监听异常"
            mouse_mode = (
                "鼠标已拦截"
                if self._source.full_capture
                else "鼠标降级（锁光标读位移）"
            )
            self._input_state_label.configure(
                text=f"输入：捕获中 | {listening} | {mouse_mode} | 按 WASD 看这里"
            )
        else:
            self._source.release_cursor()
            self._overlay.hide()
            self._input_state_label.configure(text="输入：未捕获")
            if self._bridge is not None:
                self._set_pill(f"已连接 · {self._bridge.host}", T.OK)
                self._set_run_state("已连接", "点「开始捕获」把键鼠交给 PS5")
            else:
                self._set_pill("未连接", T.TEXT_FAINT)
                self._set_run_state("未连接主机", "先到「连接」页建立会话，再回到这里开始捕获")

    def _apply_disconnected(self) -> None:
        self._bridge = None
        self._connect_button.configure(state="normal")
        self._disconnect_button.configure(state="disabled")
        self._capture_button.configure(state="disabled")
        self._source.release_cursor()
        self._apply_capture_state(False)
        self._set_pill("未连接", T.TEXT_FAINT)
        self._set_run_state("会话已断开", "点「连接主机」重新连接")

    def _apply_key_state(self, name: str) -> None:
        listening = "监听正常" if self._source.listening else "监听异常"
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

    # ------------------------------------------------------------ 连接流程
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
            self._append_log(f"配对成功：{credentials.get('host_name') or credentials['device_ip']}")
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"配对失败：{exc}")

    def _connect(self) -> None:
        if self._bridge is not None:
            return
        self._append_log("正在建立 Remote Play 会话……")
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self._loop)
        future.add_done_callback(lambda fut: self.root.after(0, self._on_connected, fut))

    async def _connect_async(self) -> bridge.Ps5Bridge:
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
        try:
            self._bridge = future.result()
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
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
            return
        self._set_pill(f"已连接 · {self._bridge.host}", T.OK)
        self._set_run_state("已连接", "点「开始捕获」把键鼠交给 PS5")
        self._connect_button.configure(state="disabled")
        self._disconnect_button.configure(state="normal")
        self._capture_button.configure(state="normal")
        if not self._source_ready:
            self._source.start()
            self._source_ready = True
        self._running = True
        self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self._loop)
        self._append_log("输入通道就绪，按 F8 或点按钮开始捕获")

    def _disconnect(self) -> None:
        ps5 = self._bridge
        self._running = False
        self._bridge = None
        self._stop_tick_loop()
        if self._source.capturing:
            self._source.toggle_capture()
        if ps5 is not None:
            # 关闭会话并等它完成，避免 PS5 端留下“另一个会话还连着”的残留
            try:
                future = asyncio.run_coroutine_threadsafe(ps5.close(), self._loop)
                future.result(timeout=8)
            except Exception as exc:  # noqa: BLE001 - 关闭失败不影响本地状态
                self._append_log(f"关闭会话时出错：{exc}")
        self._connect_button.configure(state="normal")
        self._disconnect_button.configure(state="disabled")
        self._capture_button.configure(state="disabled")
        self._apply_capture_state(False)
        self._append_log("已断开")

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
        while self._running:
            await asyncio.sleep(TICK_SECONDS)
            now = time.perf_counter()
            dt = now - last
            last = now
            try:
                if now - last_heartbeat >= 30.0:
                    last_heartbeat = now
                    # 心跳不再写文件（长期运行的热路径日志已移除），
                    # 只在运行页状态栏体现；排查时看 sent_count 即可
                    sent = self._bridge.sent_count if self._bridge else 0
                    self._run_subtitle.configure(text=f"已发送 {sent} 帧输入")
                # 不在循环里检查 connected：pyremoteplay 的 is_running 在心跳
                # 间隙可能短暂为 False，之前据此退出循环会把输入直接停掉。
                if self._bridge is None:
                    self._running = False
                    break
                if self._source.capturing:
                    # 只调用 poll：它读位移后会把光标拉回中心。
                    dx, dy = self._source.poll_mouse_delta()
                    # 无条件喂（含 0）：滑动平均需要每帧一个样本
                    self._mapper.on_mouse_delta(dx, dy)
                    # 每 0.5 秒校正一次按键状态：多路监听偶尔会丢 keyup，
                    # 残留的键会让左摇杆方向错乱（按 A 却向右走）
                    if now - last_key_sync >= 0.5:
                        last_key_sync = now
                        self._mapper.drop_missing(self._source.pressed_keys())
                elif was_capturing:
                    self._source.release_cursor()
                    self._bridge.send_events(self._mapper.release_all())
                was_capturing = self._source.capturing
                result = self._mapper.tick(dt)
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
        state = self._source.toggle_capture()
        self._apply_capture_state(state)

    def _on_capture_changed(self, capturing: bool) -> None:
        self._ui_queue.put(("capture", capturing))

    def _on_key_event(self, name: str) -> None:
        self._ui_queue.put(("key", name))

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
            ui_pages.refresh_mapping_list(self)

        ActionEditor(self.root, source, store[name], save)

    def remove_mapping(self, source: str) -> None:
        category, name = self._split_source(source)
        mode = self._mode_cfg()
        store = mode.mouse_buttons if category == "mouse" else mode.keyboard_buttons
        store.pop(name, None)
        self._rebuild_mapper()
        self._persist()
        ui_pages.refresh_mapping_list(self)

    def _add_mapping(self) -> None:
        """先弹按键捕获框，识别出键名后再选动作类型。"""

        def on_captured(source: str | None) -> None:
            if not source:
                return
            category, name = self._split_source(source)
            mode = self._mode_cfg()

            def save(value) -> None:
                if category == "mouse":
                    mode.mouse_buttons[name] = value
                else:
                    mode.keyboard_buttons[name] = value
                self._rebuild_mapper()
                self._persist()
                ui_pages.refresh_mapping_list(self)

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
        ui_pages.refresh_stick_keys(self)
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
        self._stick_ramp_label.configure(text=f"过渡 {ramp:.1f}/s")

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
        try:
            self._l2_var.set(depth)
        except Exception:  # noqa: BLE001 - 滑条未创建时忽略
            pass
        self._l2_label.configure(text=f"L2 {depth:.1f}")
        if self._bridge is not None:
            self._bridge.set_l2_depth(depth)

    def _on_l2_adjust(self, direction: int) -> None:
        """键盘 - / = 调整 L2 输出深度：每按一次 0.1。"""
        try:
            current = float(self._l2_var.get())
        except Exception:  # noqa: BLE001
            current = 1.0
        depth = max(0.0, min(1.0, current + direction * 0.1))
        self._apply_l2(depth)
        self._overlay.show_notice(f"L2 {depth:.1f}")

    def _on_wheel(self, dy: int) -> None:
        """滚轮调整 R2 输出深度：每格 0.1，右上角显示当前设定值。"""
        try:
            current = float(self._r2_var.get())
        except Exception:  # noqa: BLE001
            current = 1.0
        depth = max(0.0, min(1.0, current + dy * 0.1))
        self._apply_r2(depth)
        self._overlay.show_notice(f"R2 {depth:.1f}")

    def _send_trigger(self) -> None:
        """扳机深度变化后强制发一帧，让 PS5 立刻收到。"""
        if self._bridge is None:
            return
        try:
            self._bridge.force_send_sticks()
        except Exception:  # noqa: BLE001 - 发送失败不影响 UI
            pass

    def _commit_sliders(self, _event=None) -> None:
        """滑块松开后才写盘，避免拖动过程中反复 IO 卡顿。"""
        self._persist()

    def save_as_preset(self) -> None:
        """把当前映射回写成预设文件，覆盖用户目录里的同名预设。"""
        name = self._preset_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "先在上面的下拉框选择要覆盖的预设名")
            return
        if not messagebox.askyesno(
            "确认覆盖",
            f"用当前映射覆盖预设「{name}」？\n\n以后点「应用预设」会加载这一套。",
        ):
            return
        try:
            path = config.save_preset(name, self._config)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._preset_values = config.list_presets()
        self._preset_box.configure(values=self._preset_values)
        self._append_log(f"预设已更新：{path}")

    def _apply_preset(self) -> None:
        preset = self._preset_var.get()
        try:
            raw = config.load_preset(preset)
        except FileNotFoundError as exc:
            messagebox.showerror("错误", str(exc))
            return
        built = config.build_config(raw)
        self._config.preset = preset
        self._config.modes = built.modes
        self._config.mode_switch = built.mode_switch
        # 不覆盖 mouse / left_stick：手感参数由 tuning.json 独立管理，
        # 应用预设只换键位映射，用户调好的灵敏度/死区/平滑必须保持不变。
        self._config.current_mode = "default"
        self._edit_mode = "default"
        self._rebuild_mapper()
        self._persist()
        ui_pages.refresh_mapping_list(self)
        ui_pages.refresh_stick_keys(self)
        ui_pages.refresh_mode_ui(self)
        self._append_log(f"已应用预设：{preset}")

    def _persist(self) -> None:
        """编辑后立即写盘：config.json 存映射，tuning.json 存摇杆手感参数。"""
        try:
            config.save_config(self._config)
        except OSError as exc:
            self._append_log(f"配置保存失败：{exc}")
        try:
            # 摇杆/鼠标手感单独文件：改动即存，应用预设不覆盖
            config.save_tuning(self._config)
        except OSError as exc:
            self._append_log(f"手感参数保存失败：{exc}")

    def _save_config(self) -> None:
        self._config.current_mode = self._mapper.mode
        self._persist()
        self._rebuild_mapper()
        self._append_log("配置已保存到 config.json")

    def _rebuild_mapper(self) -> None:
        was_capturing = self._source.capturing and self._source_ready
        if self._source_ready:
            self._source.stop()
        self._mapper = InputMapper(self._config)
        self._mapper.set_left_value(self._config.left_stick.value)
        self._source = InputSource(self._mapper, hotkey=self._config.hotkey)
        self._source.set_capture_callback(self._on_capture_changed)
        self._source.set_key_callback(self._on_key_event)
        self._source.set_mode_switch(self._config.mode_switch, self._on_mode_switch)
        self._source.set_scroll_callback(self._on_wheel)
        self._source.set_l2_adjust_callback(self._on_l2_adjust)
        self._source_ready = False
        if self._bridge is not None:
            self._source.start()
            self._source_ready = True
        if was_capturing:
            self._append_log("配置已更新，重新开始捕获后生效")

    # ------------------------------------------------------------ 杂项
    def _append_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                self._append_log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                kind, value = self._ui_queue.get_nowait()
                if kind == "capture":
                    self._apply_capture_state(value)
                elif kind == "disconnected":
                    self._apply_disconnected()
                elif kind == "stick":
                    self._apply_stick_value(value)
                elif kind == "sticks":
                    self._apply_stick_pair(value)
                elif kind == "key":
                    self._apply_key_state(value)
                elif kind == "mode":
                    self._edit_mode = value
                    self._refresh_mode_ui()
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def _on_close(self) -> None:
        self._running = False
        try:
            self._overlay.hide()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._stop_tick_loop()
            if self._source_ready:
                if self._source.capturing:
                    self._source.toggle_capture()
                self._source.stop()
            if self._bridge is not None:
                future = asyncio.run_coroutine_threadsafe(self._bridge.close(), self._loop)
                future.result(timeout=5)
        except Exception:  # noqa: BLE001 - 退出路径不再抛错
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()


def main() -> int:
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
