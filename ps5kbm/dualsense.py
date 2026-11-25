"""DualSense（PS5 手柄）的 HID 读取与输出。

依赖：PyPI 包 `hidapi`（导入名 `hid`，Cython 版，hidapi 已静态链接，不需要额外 DLL）。

输入报告（hidapi read 返回的字节流）：
- USB：报告 0x01，64 字节；
- 蓝牙：报告 0x31，78 字节，状态从第 2 字节开始（所以下面统一用 `_OFFSET + n`）。

输出报告（写手柄，USB 报告 0x02）：
- byte 1：valid_flag0，bit0|bit1 = 经典马达，bit2 = 右扳机，bit3 = 左扳机；
- byte 2：valid_flag1，bit2 = 灯条，bit4 = 玩家指示灯，bit6 = 效果总功率；
- byte 3：右马达（弱/高频）；byte 4：左马达（强/低频）；
- byte 11..21：右扳机效果块；22..32：左扳机效果块（各 11 字节：模式 + 10 参数）。
- byte 39：ledOption（0x03 = 玩家灯亮度由本包控制 + 不被固件打断）；
  byte 43：玩家灯亮度；byte 44：玩家灯编号；byte 45..47：灯条 RGB。

偏移以 pydualsense 0.7.5 与 SDL 的 DualSense 实现为准（两者一致），
扳机/灯条/马达都已在实机验证过。

线程模型：一个后台线程负责连接/读取，界面与主循环只拿快照；
写操作（震动/扳机效果）加锁，失败只记错误，不影响主流程。
"""

from __future__ import annotations

import logging
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

SONY_VID = 0x054C
# DualSense / DualSense Edge；DualShock 4 先识别但不保证功能
KNOWN_PIDS = {
    0x0CE6: "DualSense",
    0x0DF2: "DualSense Edge",
    0x05C4: "DualShock 4",
    0x09CC: "DualShock 4 v2",
}
GAMEPAD_USAGE_PAGE = 0x01

USB_REPORT_ID = 0x01
BT_REPORT_ID = 0x31

# 输出报告（写手柄）：USB 用 0x02（64 字节），蓝牙用 0x31（78 字节，第 1 字节固定 0x02）。
# 字段偏移以 pydualsense（实测可用实现）为准：USB 与蓝牙相差 1 个字节。
USB_OUTPUT_REPORT_ID = 0x02
BT_OUTPUT_REPORT_ID = 0x31
USB_OUTPUT_LENGTH = 64
BT_OUTPUT_LENGTH = 78

_USB_VALID0 = 1
_USB_VALID1 = 2
_USB_MOTOR_RIGHT = 3
_USB_MOTOR_LEFT = 4
_USB_RIGHT_TRIGGER = 11
_USB_LEFT_TRIGGER = 22

_BT_VALID0 = 2
_BT_VALID1 = 3
_BT_MOTOR_RIGHT = 4
_BT_MOTOR_LEFT = 5
_BT_RIGHT_TRIGGER = 12
_BT_LEFT_TRIGGER = 23

# valid_flag0 的位：经典马达要 0x01+0x02 一起置位；扳机效果左 0x04 / 右 0x08 对应
# pydualsense 注释里的 “0x04 set the right trigger motor / 0x08 set the left trigger motor”
_VALID0_MOTORS = 0x01 | 0x02
# 灯条 / 玩家灯偏移（pydualsense 0.7.5 的输出报告布局；蓝牙整体后移 1 字节）
_USB_LED_OPTION = 39
_USB_LED_BRIGHTNESS = 43
_USB_PLAYER_LEDS = 44
_USB_LIGHTBAR = 45
_BT_LED_OPTION = 40
_BT_LED_BRIGHTNESS = 44
_BT_PLAYER_LEDS = 45
_BT_LIGHTBAR = 46
# valid_flag1：0x04 = 灯条，0x10 = 玩家指示灯
_VALID1_LIGHTBAR = 0x04
_VALID1_PLAYER_LEDS = 0x10
# ledOption：0x01 玩家灯亮度由本包控制，0x02 不被打断
_LED_OPTION_BOTH = 0x03
# 玩家灯编号（PlayerID 枚举：1~4 号，0 表示全亮）
PLAYER_LED_VALUES = {0: 31, 1: 4, 2: 10, 3: 21, 4: 27}

_VALID0_RIGHT_TRIGGER = 0x04
_VALID0_LEFT_TRIGGER = 0x08

# 扳机效果模式字节（来自 ExtendInput TriggerEffectGenerator，MIT）
TRIGGER_MODE_OFF = 0x05
TRIGGER_MODE_FEEDBACK = 0x21  # 阻力（官方）
TRIGGER_MODE_WEAPON = 0x25  # 开枪（官方）
TRIGGER_MODE_VIBRATION = 0x26  # 震动（官方）
TRIGGER_MODE_BOW = 0x22  # 拉弓（固件里残留，非官方）
TRIGGER_MODE_GALLOPING = 0x23
TRIGGER_MODE_MACHINE = 0x27

# 陀螺仪原始值 → rad/s：DualSense 陀螺仪量程 ±2000°/s、16 位有符号，
# 即 32768 单位对应 2000°/s（实测静止读数约 0，快速转身读数 ~2500 也吻合）。
# 之前的 1024 单位/rad/s 是错的（陀螺仪读数会小 60 倍）。
GYRO_RAW_TO_RAD = (2000.0 / 32768.0) * (3.141592653589793 / 180.0)
# 加速度：8192 单位 = 1g（实测平放/持握时读数约 8192）。
ACCEL_RAW_TO_G = 1.0 / 8192.0

# 按下判定阈值：扳机模拟量超过它才算"按下"（对应按钮位）
TRIGGER_PRESS_THRESHOLD = 0.05

# 输入报告里各字段相对 `_OFFSET` 的偏移
_IN_LX = 1
_IN_LY = 2
_IN_RX = 3
_IN_RY = 4
_IN_L2 = 5
_IN_R2 = 6
_IN_SEQ = 7
_IN_BTN0 = 8
_IN_BTN1 = 9
_IN_BTN2 = 10
_IN_GYRO = 16
_IN_ACCEL = 22
_IN_BATTERY = 53

# 十字键 nibble → 按钮名（0 上、2 右、4 下、6 左，8 = 松开，其余是斜向）
_DPAD = {
    0: {"UP"},
    1: {"UP", "RIGHT"},
    2: {"RIGHT"},
    3: {"DOWN", "RIGHT"},
    4: {"DOWN"},
    5: {"DOWN", "LEFT"},
    6: {"LEFT"},
    7: {"UP", "LEFT"},
    8: set(),
}


@dataclass(frozen=True)
class DeviceInfo:
    path: bytes
    vendor_id: int
    product_id: int
    product: str
    usage_page: int = 0

    @property
    def label(self) -> str:
        name = KNOWN_PIDS.get(self.product_id)
        if name:
            return name
        return self.product or f"{self.vendor_id:04X}:{self.product_id:04X}"


@dataclass
class ControllerState:
    """一帧手柄状态。摇杆 -1..1（y 正 = 下），扳机 0..1。"""

    device: str = ""
    transport: str = "unknown"  # usb | bt
    buttons: set[str] = field(default_factory=set)
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    l2: float = 0.0
    r2: float = 0.0
    gyro: tuple[float, float, float] = (0.0, 0.0, 0.0)
    accel: tuple[float, float, float] = (0.0, 0.0, 0.0)
    battery: int | None = None
    charging: bool = False


def _normalize_stick(raw: int) -> float:
    """0..255 → -1..1（128 为居中）。"""
    return max(-1.0, min(1.0, (int(raw) - 128) / 127.0))


def _parse_buttons(btn0: int, btn1: int, btn2: int, l2: float, r2: float) -> set[str]:
    # DualSense 的按钮字节和 DS4 相反：高 4 位是面键，低 4 位是十字键
    # （0=上 … 7=左上，8=松开），照 pydualsense 的位定义。
    pressed: set[str] = set()
    if btn0 & 0x10:
        pressed.add("SQUARE")
    if btn0 & 0x20:
        pressed.add("CROSS")
    if btn0 & 0x40:
        pressed.add("CIRCLE")
    if btn0 & 0x80:
        pressed.add("TRIANGLE")
    pressed |= _DPAD.get(btn0 & 0x0F, set())

    if btn1 & 0x01:
        pressed.add("L1")
    if btn1 & 0x02:
        pressed.add("R1")
    if btn1 & 0x04:
        pressed.add("L2")
    if btn1 & 0x08:
        pressed.add("R2")
    if btn1 & 0x10:
        pressed.add("SHARE")
    if btn1 & 0x20:
        pressed.add("OPTIONS")
    if btn1 & 0x40:
        pressed.add("L3")
    if btn1 & 0x80:
        pressed.add("R3")

    if btn2 & 0x01:
        pressed.add("PS")
    if btn2 & 0x02:
        pressed.add("TOUCHPAD")
    if btn2 & 0x04:
        pressed.add("MUTE")

    # 扳机模拟量到了就补上（有些游戏/系统只认数字位）
    if l2 >= TRIGGER_PRESS_THRESHOLD:
        pressed.add("L2")
    if r2 >= TRIGGER_PRESS_THRESHOLD:
        pressed.add("R2")
    return pressed


def parse_report(data: bytes | list[int], device: str = "") -> ControllerState | None:
    """解析一帧输入报告；不是已知报告返回 None。纯函数，方便单测。"""
    raw = bytes(data)
    if not raw:
        return None
    report_id = raw[0]
    if report_id == USB_REPORT_ID:
        offset = 0
        transport = "usb"
    elif report_id == BT_REPORT_ID:
        offset = 1
        transport = "bt"
    else:
        return None
    need = offset + _IN_BATTERY + 1
    if len(raw) < need:
        return None

    l2 = raw[offset + _IN_L2] / 255.0
    r2 = raw[offset + _IN_R2] / 255.0
    gx, gy, gz = struct.unpack_from("<hhh", raw, offset + _IN_GYRO)
    ax, ay, az = struct.unpack_from("<hhh", raw, offset + _IN_ACCEL)
    battery_byte = raw[offset + _IN_BATTERY]
    level = (battery_byte & 0x0F) * 10
    charging = ((battery_byte >> 4) & 0x0F) in (1, 2)

    return ControllerState(
        device=device,
        transport=transport,
        buttons=_parse_buttons(
            raw[offset + _IN_BTN0], raw[offset + _IN_BTN1], raw[offset + _IN_BTN2], l2, r2
        ),
        lx=_normalize_stick(raw[offset + _IN_LX]),
        ly=_normalize_stick(raw[offset + _IN_LY]),
        rx=_normalize_stick(raw[offset + _IN_RX]),
        ry=_normalize_stick(raw[offset + _IN_RY]),
        l2=l2,
        r2=r2,
        gyro=(gx * GYRO_RAW_TO_RAD, gy * GYRO_RAW_TO_RAD, gz * GYRO_RAW_TO_RAD),
        accel=(ax * ACCEL_RAW_TO_G, ay * ACCEL_RAW_TO_G, az * ACCEL_RAW_TO_G),
        battery=min(100, level) if battery_byte else None,
        charging=charging,
    )


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def trigger_effect_off() -> bytes:
    """关掉扳机效果（把扳机恢复成中性）。"""
    return bytes([TRIGGER_MODE_OFF] + [0] * 10)


def trigger_effect_feedback(position: int = 6, strength: int = 6) -> bytes:
    """官方「阻力」效果：拉过 position 之后开始有阻力，强度 1~8。"""
    position = _clamp_int(position, 0, 9)
    strength = _clamp_int(strength, 1, 8)
    force_value = (strength - 1) & 0x07
    active = 0
    force = 0
    for zone in range(position, 10):
        active |= 1 << zone
        force |= force_value << (3 * zone)
    block = [
        TRIGGER_MODE_FEEDBACK,
        active & 0xFF,
        (active >> 8) & 0xFF,
        force & 0xFF,
        (force >> 8) & 0xFF,
        (force >> 16) & 0xFF,
        (force >> 24) & 0xFF,
        0,
        0,
        0,
        0,
    ]
    return bytes(block)


def trigger_effect_weapon(start: int = 2, end: int = 7, strength: int = 6) -> bytes:
    """官方「开枪」效果：start 到 end 之间顶住，模拟扳机段落。"""
    start = _clamp_int(start, 2, 7)
    end = _clamp_int(end, start + 1, 8)
    strength = _clamp_int(strength, 1, 8)
    zones = (1 << start) | (1 << end)
    return bytes(
        [
            TRIGGER_MODE_WEAPON,
            zones & 0xFF,
            (zones >> 8) & 0xFF,
            strength - 1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


def trigger_effect_vibration(
    position: int = 5, amplitude: int = 6, frequency: int = 30
) -> bytes:
    """官方「震动」效果：扳机在 position 之后按 frequency 抖动。"""
    position = _clamp_int(position, 0, 9)
    amplitude = _clamp_int(amplitude, 1, 8)
    frequency = _clamp_int(frequency, 1, 255)
    value = (amplitude - 1) & 0x07
    active = 0
    amps = 0
    for zone in range(position, 10):
        active |= 1 << zone
        amps |= value << (3 * zone)
    return bytes(
        [
            TRIGGER_MODE_VIBRATION,
            active & 0xFF,
            (active >> 8) & 0xFF,
            amps & 0xFF,
            (amps >> 8) & 0xFF,
            (amps >> 16) & 0xFF,
            (amps >> 24) & 0xFF,
            0,
            0,
            frequency,
            0,
        ]
    )


def trigger_effect_bow(
    start: int = 2, end: int = 7, strength: int = 5, snap: int = 4
) -> bytes:
    """「拉弓」效果（固件残留，非官方）：越拉越紧，到 end 弹回。"""
    start = _clamp_int(start, 0, 8)
    end = _clamp_int(end, start + 1, 8)
    strength = _clamp_int(strength, 1, 8)
    snap = _clamp_int(snap, 1, 8)
    zones = (1 << start) | (1 << end)
    force = ((strength - 1) & 0x07) | (((snap - 1) & 0x07) << 3)
    return bytes(
        [
            TRIGGER_MODE_BOW,
            zones & 0xFF,
            (zones >> 8) & 0xFF,
            force & 0xFF,
            (force >> 8) & 0xFF,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


# 界面上的可选效果：名字 → 生成函数（关闭单独处理）
TRIGGER_EFFECTS = {
    "阻力": trigger_effect_feedback,
    "开枪": trigger_effect_weapon,
    "震动": trigger_effect_vibration,
    "拉弓": trigger_effect_bow,
}


def effect_bytes(name: str) -> bytes:
    """按界面名字取效果字节；未知名字返回关闭。"""
    factory = TRIGGER_EFFECTS.get(str(name or "").strip())
    return factory() if factory else trigger_effect_off()


BT_CRC_SEED = 0xEADA2D49


def bt_crc(report: bytes) -> int:
    """蓝牙输出报告的 CRC（前 74 字节，种子 0xEADA2D49，写入最后 4 字节）。"""
    return zlib.crc32(bytes(report[:74]), BT_CRC_SEED)


def list_devices() -> list[DeviceInfo]:
    """枚举 Sony 手柄（只看游戏手柄接口，过滤掉音频/触摸板接口）。"""
    try:
        import hid
    except ImportError:
        return []
    result: list[DeviceInfo] = []
    for item in hid.enumerate():
        if item.get("vendor_id") != SONY_VID:
            continue
        if item.get("product_id") not in KNOWN_PIDS:
            continue
        usage_page = int(item.get("usage_page") or 0)
        if usage_page and usage_page != GAMEPAD_USAGE_PAGE:
            continue
        result.append(
            DeviceInfo(
                path=item["path"],
                vendor_id=item["vendor_id"],
                product_id=item["product_id"],
                product=item.get("product_string") or "",
                usage_page=usage_page,
            )
        )
    return result


class DualSenseReader:
    """后台线程：连接手柄、持续读报告、提供快照与输出（震动/扳机效果）。

    内部持有线程对象而不是自己继承 Thread：玩法隔离要求「切走手柄玩法时把读取线程
    停掉、HID 句柄关掉，切回来再起」，而 Thread 对象不能重复 start()。
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state: ControllerState | None = None
        self._device = None
        self._info: DeviceInfo | None = None
        self._running = False
        self._error = ""
        self._last_report = 0.0
        self._motors = (0, 0)  # (left, right) 最近一次写入的马达值
        # 输出报告可能从反馈线程写、读线程读，hidapi 的句柄不能并发用
        self._write_lock = threading.Lock()
        # 输出报告按连接方式（USB 0x02 / 蓝牙 0x31）选布局，收到第一帧后确定
        self._transport = "usb"
        self._haptics_mode = False  # True = 走 USB 音频触觉，不再发经典马达

    # ------------------------------------------------------------ 生命周期
    def start_reader(self) -> None:
        """启动读取线程；已在跑则什么都不做，stop() 之后可以再次启动。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            thread = threading.Thread(
                target=self._run_loop, daemon=True, name="dualsense"
            )
            self._thread = thread
        thread.start()

    def stop(self) -> None:
        """停线程并关 HID 句柄（完全释放；下次 start_reader 会重新开）。"""
        with self._lock:
            self._running = False
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._close()

    def is_alive(self) -> bool:
        with self._lock:
            thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def _run_loop(self) -> None:
        while self._running:
            if self._device is None:
                if not self._try_open():
                    time.sleep(0.5)
                    continue
            try:
                data = self._device.read(128, 200)
            except Exception as exc:  # noqa: BLE001 - 拔线/驱动异常都当断连处理
                self._error = f"读取失败：{exc}"
                _LOGGER.info("DualSense 读取中断：%s", exc)
                self._close()
                continue
            if not data:
                # 读超时：超过 1 秒没有输入报告就当断连（手柄休眠/拔线）
                if self._state is not None and time.monotonic() - self._last_report > 1.0:
                    self._error = "超过 1 秒没有数据"
                    self._close()
                continue
            state = parse_report(data, self._info.label if self._info else "")
            if state is None:
                continue
            with self._lock:
                # 连接方式以打开时的设备路径为准（Windows 蓝牙会把报告 ID 去掉，
                # 单看报告字节会把蓝牙误判成 USB，导致输出报告用错格式）
                state.transport = self._transport
                self._state = state
                self._last_report = time.monotonic()
                self._error = ""

    # ------------------------------------------------------------ 查询
    @property
    def connected(self) -> bool:
        with self._lock:
            return self._state is not None

    @property
    def device_label(self) -> str:
        with self._lock:
            return self._info.label if self._info else ""

    @property
    def transport(self) -> str:
        with self._lock:
            return self._transport

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def snapshot(self) -> ControllerState | None:
        with self._lock:
            return self._state

    # ------------------------------------------------------------ 输出
    def _new_output_report(self) -> tuple[bytearray, dict]:
        """按当前连接方式准备输出报告，返回 (报告, 字段偏移表)。

        和 pydualsense 一致：每份报告都带上马达字段（valid0 置 0x01|0x02 并写当前值），
        否则只改扳机/灯条的报告会让手柄把马达状态当成未指定而提前停下。
        """
        with self._lock:
            transport = self._transport
            motors = self._motors
        if transport == "bt":
            report = bytearray(BT_OUTPUT_LENGTH)
            report[0] = BT_OUTPUT_REPORT_ID
            report[1] = 0x02  # 蓝牙输出报告固定前缀
            layout = {
                "valid0": _BT_VALID0,
                "valid1": _BT_VALID1,
                "intensity": 38,
                "led_option": _BT_LED_OPTION,
                "led_brightness": _BT_LED_BRIGHTNESS,
                "player_leds": _BT_PLAYER_LEDS,
                "lightbar": _BT_LIGHTBAR,
                "motor_right": _BT_MOTOR_RIGHT,
                "motor_left": _BT_MOTOR_LEFT,
                "right_trigger": _BT_RIGHT_TRIGGER,
                "left_trigger": _BT_LEFT_TRIGGER,
                # 音频/触觉相关（USB 偏移 +1）
                "volume_headphone": 6,
                "volume_speaker": 7,
                "volume_mic": 8,
                "audio_control1": 9,
                "mute_light_mode": 10,
                "power_save_mute": 11,
                "haptic_lowpass": 41,
            }
        else:
            report = bytearray(USB_OUTPUT_LENGTH)
            report[0] = USB_OUTPUT_REPORT_ID
            layout = {
                "valid0": _USB_VALID0,
                "valid1": _USB_VALID1,
                "intensity": 37,
                "led_option": _USB_LED_OPTION,
                "led_brightness": _USB_LED_BRIGHTNESS,
                "player_leds": _USB_PLAYER_LEDS,
                "lightbar": _USB_LIGHTBAR,
                "motor_right": _USB_MOTOR_RIGHT,
                "motor_left": _USB_MOTOR_LEFT,
                "right_trigger": _USB_RIGHT_TRIGGER,
                "left_trigger": _USB_LEFT_TRIGGER,
                # 音频/触觉相关（dualsense-controller 的 output.rs 字节表）
                "volume_headphone": 5,
                "volume_speaker": 6,
                "volume_mic": 7,
                "audio_control1": 8,
                "mute_light_mode": 9,
                "power_save_mute": 10,
                "haptic_lowpass": 40,
            }
        # 触觉模式下不能带马达使能位：USB 音频触觉和经典马达是互斥的两条路，
        # 只要报告里置了 0x01|0x02，手柄就会切到「兼容震动」，音频触觉随即静音。
        if not self._haptics_mode:
            report[layout["valid0"]] |= _VALID0_MOTORS
            report[layout["motor_left"]] = motors[0]
            report[layout["motor_right"]] = motors[1]
        return report, layout

    def set_haptics_mode(self, enabled: bool) -> None:
        """USB 原生触觉启用时，关掉经典马达通道（两者互斥，见 _new_output_report）。

        进入触觉模式时顺带补发一帧「打开音频通路」——这样键鼠玩法下完全不碰手柄，
        只有真的要用触觉时才写这几帧（音量/静音位）。
        """
        with self._lock:
            if self._haptics_mode == enabled:
                return
            self._haptics_mode = enabled
            transport = self._transport
        _LOGGER.info("手柄输出模式：%s", "音频触觉（不发经典马达）" if enabled else "经典马达")
        if enabled and transport == "usb":
            self.unlock_audio()

    @property
    def haptics_mode(self) -> bool:
        with self._lock:
            return self._haptics_mode

    def rumble(self, low: float, high: float, force: bool = False) -> bool:
        """震动：low=强/低频马达，high=弱/高频马达，0..1。

        触觉模式下默认不发（会静音音频触觉）；`force=True` 用于「试震动」按钮，
        写完由调用方重新发一帧 unlock_audio() 把音频触觉恢复回来。
        """
        if self._haptics_mode and not force:
            return False
        low_byte = max(0, min(255, int(round(float(low) * 255))))
        high_byte = max(0, min(255, int(round(float(high) * 255))))
        report, layout = self._new_output_report()
        report[layout["valid0"]] |= _VALID0_MOTORS
        report[layout["motor_right"]] = high_byte
        report[layout["motor_left"]] = low_byte
        with self._lock:
            self._motors = (low_byte, high_byte)
        return self._write(report)

    def set_lightbar(self, rgb: bytes, player: int | None = None) -> bool:
        """把主机下发的灯条颜色写到手柄（可选同时设置玩家灯编号）。

        协议细节来自 pydualsense：valid_flag1 的 0x04 表示本包改灯条、
        0x10 表示本包改玩家指示灯；ledOption 置 0x03（不被打断），
        灯条 RGB 在 USB 的 [45:48] / 蓝牙的 [46:49]。
        """
        if len(rgb) != 3:
            return False
        report, layout = self._new_output_report()
        report[layout["valid1"]] |= _VALID1_LIGHTBAR
        report[layout["led_option"]] = _LED_OPTION_BOTH
        report[layout["led_brightness"]] = 0x00
        block = layout["lightbar"]
        report[block : block + 3] = rgb
        if player is not None:
            value = PLAYER_LED_VALUES.get(int(player))
            if value is not None:
                report[layout["valid1"]] |= _VALID1_PLAYER_LEDS
                report[layout["player_leds"]] = value
        return self._write(report)

    def set_trigger_effects(
        self, left: bytes | None = None, right: bytes | None = None
    ) -> bool:
        """一次写左右两边的扳机效果（各 11 字节：模式 + 参数）。

        照 chiaki / Veyra 的做法：一份报告里同时置左右两个有效位
        （0x04 | 0x08 = 0x0C）并同时写入两块数据。
        之前分两次写，后一次会把前一份报告整体覆盖掉，只有最后一侧生效，
        这也是「L2 松手偶尔不生效」「效果时有时无」的来源。
        传 None 的一侧写入「关闭」效果（0x05），不会留下上一条残留。
        """
        if (left is not None and len(left) != 11) or (
            right is not None and len(right) != 11
        ):
            return False
        report, layout = self._new_output_report()
        report[layout["valid0"]] |= _VALID0_LEFT_TRIGGER | _VALID0_RIGHT_TRIGGER
        # chiaki 的做法：同时置效果功率位（0x40）并给强度字节
        report[layout["valid1"]] |= 0x40
        report[layout["intensity"]] = 0x00
        off = trigger_effect_off()
        left_block = layout["left_trigger"]
        right_block = layout["right_trigger"]
        report[left_block : left_block + 11] = left if left is not None else off
        report[right_block : right_block + 11] = right if right is not None else off
        return self._write(report)

    def set_trigger_effect(self, side: str, effect: bytes) -> bool:
        """只改一侧的扳机效果（本地试效果用），另一侧保持关闭。"""
        right = side.lower() in ("r", "right", "r2")
        if right:
            return self.set_trigger_effects(right=effect)
        return self.set_trigger_effects(left=effect)

    def clear_trigger_effect(self, side: str | None = None) -> bool:
        """关掉扳机效果；不传 side 时两边一起关。"""
        if side is None:
            return self.set_trigger_effects()
        return self.set_trigger_effect(side, trigger_effect_off())

    def unlock_audio(self) -> bool:
        """打开手柄的音频/触觉通路（扬声器音量 + 清静音与省电位）。

        为什么必须有这一步：接在 PC 上时手柄内部这两个寄存器是「音量 0 / 静音」状态，
        Windows 把音频送到那个四声道端点后，手柄照样不出声、触觉执行器也不动
        （实机现象：端点峰值 0.98，手柄毫无反应）。PS5 和 SDL 都会替手柄设一遍。

        字节定义来自 dualsense-controller 的 output.rs：
          report[10] power_save_mute_control：
            0x04 POWER_SAVE_HAPTIC / 0x08 POWER_SAVE_AUDIO
            0x20 MUTE_SPEAKER / 0x80 MUTE_HAPTIC
          report[6] volume_speaker（PS5 约 0x5D~0x64）
        valid_flag0 的 0x10/0x20/0x40/0x80 分别允许耳机/扬声器/麦克风音量与音频控制组1，
        valid_flag1 的 0x02 允许音频静音位生效。

        注意：这一帧**不带马达使能位**（valid0 只写 0xF0），避免顺手把触觉切走。
        """
        report, layout = self._new_output_report()
        report[layout["valid0"]] = 0x10 | 0x20 | 0x40 | 0x80
        report[layout["valid1"]] |= 0x02 | 0x20
        report[layout["motor_left"]] = 0
        report[layout["motor_right"]] = 0
        report[layout["volume_headphone"]] = 0x64
        report[layout["volume_speaker"]] = 0x64
        report[layout["volume_mic"]] = 0x64
        report[layout["audio_control1"]] = 0x0C  # 回声/降噪默认值
        report[layout["mute_light_mode"]] = 0x00
        report[layout["power_save_mute"]] = 0x00  # 清空所有静音 / 省电位
        report[layout["haptic_lowpass"]] = 0x00
        ok = self._write(report)
        if ok:
            _LOGGER.info("已打开手柄音频通路（扬声器音量 100%、清静音与省电位）")
        else:
            _LOGGER.warning("打开手柄音频通路失败")
        return ok

    # ------------------------------------------------------------ 内部实现
    def _try_open(self) -> bool:
        devices = list_devices()
        if not devices:
            with self._lock:
                self._error = "没有检测到手柄"
            return False
        for info in devices:
            try:
                import hid

                device = hid.device()
                device.open_path(info.path)
                device.set_nonblocking(0)
                # 蓝牙 HID 的路径里带 BT HID 服务 UUID；不能用输入报告 ID 判断，
                # Windows 蓝牙会把报告 ID 去掉、看起来和 USB 的 0x01 一样。
                is_bt = b"00001124" in bytes(info.path or b"").lower()
                with self._lock:
                    self._device = device
                    self._info = info
                    self._transport = "bt" if is_bt else "usb"
                    self._error = ""
                    self._last_report = time.monotonic()
                _LOGGER.info("已连接手柄：%s（%s）", info.label, "蓝牙" if is_bt else "USB")
                if is_bt:
                    # 蓝牙刚连上时手柄只发「简单报告」(0x01，没有陀螺仪/电量)，
                    # 先写一帧输出报告，它才会切到 0x31 全量报告。
                    self.rumble(0.0, 0.0)
                return True
            except Exception as exc:  # noqa: BLE001 - 换下一个接口
                with self._lock:
                    self._error = f"打开失败：{exc}"
                continue
        return False

    def _write(self, report: bytearray) -> bool:
        with self._lock:
            device = self._device
        if device is None:
            return False
        # 蓝牙输出报告最后 4 字节是 CRC，不补的话手柄会忽略整包
        if len(report) == BT_OUTPUT_LENGTH:
            report[74:78] = bt_crc(report).to_bytes(4, "little")
        try:
            with self._write_lock:
                device.write(bytes(report))
            return True
        except Exception as exc:  # noqa: BLE001 - 写失败不影响主流程
            _LOGGER.warning("写手柄失败：%s", exc)
            return False

    def _close(self) -> None:
        with self._lock:
            device = self._device
            self._device = None
            self._info = None
            self._state = None
            # 重连后要重新进入触觉模式（重新发解锁帧），所以这里复位
            self._haptics_mode = False
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass
