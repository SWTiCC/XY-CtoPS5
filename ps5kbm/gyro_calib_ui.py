"""陀螺仪校准对话框（游戏式引导：放稳 → 倒计时 → 采样 → 结果）。

采样在主线程用 after 轮询手柄快照，不碰后台线程；
校准结果交给 app.apply_gyro_bias 保存，界面逻辑保持在这里。
"""

from __future__ import annotations

import math

import tkinter as tk

import customtkinter as ctk

from . import gyro as gyro_mod
from . import theme as T

# 采样参数：3 秒、20Hz；抖动超过这个值（rad/s）就判失败，提示放稳重来
SAMPLE_SECONDS = 3.0
SAMPLE_INTERVAL_MS = 50
STABILITY_LIMIT = 0.08  # 超过它算"在动"，进度回落
ACCEL_TOLERANCE = 0.12
STILL_LIMIT = 0.02  # 低于它算"放稳了"，开始累计稳定时间
WINDOW_SAMPLES = int(SAMPLE_SECONDS * 1000 / SAMPLE_INTERVAL_MS)
SAMPLE_COUNT = WINDOW_SAMPLES


class GyroCalibDialog(ctk.CTkToplevel):
    """模态校准窗口。打开后不阻塞主循环。"""

    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        self._samples: list[tuple[float, float, float]] = []
        self._sampling = False
        self._mode = "bias"
        self._stable_time = 0.0
        self._countdown = 0
        self._job: str | None = None
        # 校准完成后自动关窗的定时器
        self._close_job: str | None = None
        self._accel_warned = False

        self.title("陀螺仪校准")
        self.resizable(False, False)
        self.configure(fg_color=T.BG)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        self._build()
        self._center()
        self.after(80, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001 - 窗口还没显示好时忽略
            pass

    # ------------------------------------------------------------ 界面
    def _build(self) -> None:
        wrap = ctk.CTkFrame(self, fg_color=T.BG)
        wrap.pack(fill="both", expand=True, padx=T.S6, pady=T.S6)

        ctk.CTkLabel(
            wrap, text="陀螺仪校准", font=ctk.CTkFont(size=20, weight="bold"), text_color=T.TEXT
        ).pack(anchor="w")
        ctk.CTkLabel(
            wrap,
            text="把手柄平放在桌面（或拿稳），灯条朝向自己。\n点「开始校准」后保持静止 3 秒。",
            font=ctk.CTkFont(size=T.SM),
            text_color=T.TEXT_DIM,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(T.S2, T.S3))

        self._status = ctk.CTkLabel(
            wrap,
            text="准备就绪",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=T.TEXT,
            anchor="center",
        )
        self._status.pack(fill="x", pady=(T.S3, T.S2))

        self._progress = ctk.CTkProgressBar(
            wrap,
            height=8,
            corner_radius=4,
            progress_color=T.ACCENT,
            fg_color=T.SURFACE_HOVER,
        )
        self._progress.set(0.0)
        self._progress.pack(fill="x", pady=(0, T.S3))

        self._detail = ctk.CTkLabel(
            wrap,
            text="",
            font=ctk.CTkFont(size=T.SM),
            text_color=T.TEXT_FAINT,
            anchor="w",
            justify="left",
        )
        self._detail.pack(fill="x")

        self._result = ctk.CTkLabel(
            wrap,
            text="",
            font=ctk.CTkFont(size=T.XS, family=T.FONT_MONO),
            text_color=T.TEXT_FAINT,
            anchor="w",
            justify="left",
        )
        self._result.pack(fill="x", pady=(T.S1, T.S3))

        buttons = ctk.CTkFrame(wrap, fg_color="transparent")
        buttons.pack(fill="x", side="bottom")
        self._cancel_button = ctk.CTkButton(
            buttons,
            text="关闭",
            command=self._close,
            width=90,
            height=34,
            corner_radius=T.R_SM,
            fg_color=T.SURFACE_HOVER,
            hover_color=T.BORDER,
            text_color=T.TEXT,
            font=ctk.CTkFont(size=T.SM),
        )
        self._cancel_button.pack(side="right")
        self._action_button = ctk.CTkButton(
            buttons,
            text="重新校准",
            command=self.start_monitor,
            width=120,
            height=34,
            corner_radius=T.R_SM,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=T.SM, weight="bold"),
        )
        self._action_button.pack(side="right", padx=T.S2)

    def _center(self) -> None:
        import re

        self.update_idletasks()
        # CTk 的 geometry() 用逻辑像素，且会把逻辑尺寸再乘缩放；
        # 主窗口的 geometry() 也是逻辑值，直接在这套坐标系里算居中。
        match = re.match(
            r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.app.root.geometry()
        )
        if match:
            root_w, root_h, root_x, root_y = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
        else:
            root_w, root_h, root_x, root_y = 940, 760, 0, 0
        width = max(self.winfo_reqwidth(), 420)
        height = max(min(self.winfo_reqheight(), 420), 340)
        x = root_x + (root_w - width) // 2
        y = root_y + (root_h - height) // 2
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    # ------------------------------------------------------------ 零偏（自动）
    def start_monitor(self) -> None:
        """打开后自动进入：检测到手柄且静止够久就自动完成，不用点「开始」。"""
        self._mode = "bias"
        self._samples = []
        self._stable_time = 0.0
        self._progress.set(0.0)
        self._status.configure(text="等待手柄…", text_color=T.TEXT_DIM)
        self._detail.configure(text="把手柄平放在桌面，保持静止（会自动开始）")
        self._result.configure(text="")
        self._action_button.configure(
            text="重新校准", command=self.start_monitor, state="normal"
        )
        self._tick_monitor()

    def _tick_monitor(self) -> None:
        if self._mode != "bias":
            return
        state = self.app._controller.snapshot()
        if state is None:
            self._status.configure(text="等待手柄连接", text_color=T.WARN)
            self._detail.configure(text="插上 USB 或配对蓝牙后会自动开始")
            self._progress.set(0.0)
        else:
            # 参考实现的做法：除了陀螺仪静止，还要求加速度≈1g（真的平放没动），
            # 否则手虽然在晃但角速度小的时候会被误判成“稳住了”。
            # 防御：如果加速度模长根本不在物理范围内（说明该手柄的加速度刻度
            # 和我们的换算不一致），就跳过这项检查，绝不能让校准卡死。
            accel = getattr(state, "accel", None)
            if accel:
                magnitude = math.sqrt(sum(value * value for value in accel))
                if 0.3 <= magnitude <= 3.0:
                    if abs(magnitude - 1.0) > ACCEL_TOLERANCE:
                        self._samples.clear()
                        self._stable_time = 0.0
                        self._status.configure(text="手柄没放平或还在动", text_color=T.WARN)
                        self._detail.configure(
                            text=f"重力 {magnitude:.2f}g（需要 ≈1.00g）· 平放在桌面保持静止"
                        )
                        self._progress.set(0.0)
                        self._job = self.after(SAMPLE_INTERVAL_MS, self._tick_monitor)
                        return
                elif not self._accel_warned:
                    self._accel_warned = True
                    self.app._append_log(
                        f"加速度读数 {magnitude:.2f}g 不在合理范围，本次校准只按陀螺仪判断静止"
                    )
            self._samples.append(tuple(state.gyro))
            if len(self._samples) > WINDOW_SAMPLES:
                self._samples.pop(0)
            spread = (
                gyro_mod.bias_spread(self._samples)
                if len(self._samples) >= WINDOW_SAMPLES // 2
                else 99.0
            )
            step = SAMPLE_INTERVAL_MS / 1000.0
            if spread <= STILL_LIMIT:
                self._stable_time = min(SAMPLE_SECONDS, self._stable_time + step)
            else:
                # 动了就退一点，避免“抖一下就攒满”
                self._stable_time = max(0.0, self._stable_time - step * 2)
            self._progress.set(min(1.0, self._stable_time / SAMPLE_SECONDS))
            if spread <= STILL_LIMIT:
                text, color = "很好，保持住…", T.OK
            elif spread <= STABILITY_LIMIT:
                text, color = "再稳一点…", T.WARN
            else:
                text, color = "手柄在动", T.ERR
            self._status.configure(text=text, text_color=color)
            self._detail.configure(
                text=(
                    f"抖动 {spread:.3f} rad/s · 已稳定 "
                    f"{self._stable_time:.1f} / {SAMPLE_SECONDS:.0f} 秒"
                )
            )
            if self._stable_time >= SAMPLE_SECONDS:
                self._finish_bias()
                return
        self._job = self.after(SAMPLE_INTERVAL_MS, self._tick_monitor)

    def _finish_bias(self) -> None:
        self._job = None
        samples = self._samples[-SAMPLE_COUNT:]
        self._samples = []
        if len(samples) < 10:
            self.start_monitor()
            return
        spread = gyro_mod.bias_spread(samples)
        bias = gyro_mod.calibrate_bias_robust(samples)
        self.app.apply_gyro_bias(bias)
        quality = "优" if spread < 0.008 else ("良" if spread < 0.02 else "一般")
        self._progress.set(1.0)
        self._status.configure(text=f"校准完成 · 质量 {quality}", text_color=T.OK)
        self._detail.configure(text="已保存，重启后依然生效。")
        self._result.configure(
            text=(
                f"零偏  x={bias[0]:+.4f}  y={bias[1]:+.4f}  z={bias[2]:+.4f} rad/s\n"
                f"抖动  {spread:.4f} rad/s（越小越稳）"
            ),
            text_color=T.TEXT_FAINT,
        )
        self._action_button.configure(text="重新校准", command=self.start_monitor)
        # 让用户看一眼结果，然后自动关闭（不用再点按钮）
        self._close_job = self.after(1200, self._close)

    def _close(self) -> None:
        global _dialog
        for job in (self._job, self._close_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:  # noqa: BLE001
                    pass
        self._job = None
        self._close_job = None
        self._sampling = False
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001
            pass
        _dialog = None
        self.destroy()


_dialog: GyroCalibDialog | None = None


def open_dialog(app) -> GyroCalibDialog:
    """打开（或聚焦）校准窗口；同一时间只保留一个。"""
    global _dialog
    try:
        if _dialog is not None and _dialog.winfo_exists():
            _dialog.lift()
            _dialog.focus_force()
            return _dialog
    except Exception:  # noqa: BLE001 - 窗口已销毁
        _dialog = None
    _dialog = GyroCalibDialog(app)
    _dialog.start_monitor()
    return _dialog
