"""DualSense（PS5 手柄）的 HID 读取与输出。

依赖：PyPI 包 `hidapi`（导入名 `hid`，Cython 版，hidapi 已静态链接，不需要额外 DLL）。

输入报告（hidapi read 返回的字节流）：
- USB：报告 0x01，64 字节；
- 蓝牙：报告 0x31，78 字节，状态从第 2 字节开始（所以下面统一用 `_OFFSET + n`）。

输出报告（写手柄，USB 报告 0x02）：
- byte 1：valid_flag0，bit0 = 兼容震动（COMPATIBLE_VIBRATION）；
- byte 2：valid_flag1（灯条/麦克风 LED 等，这里不用）；
- byte 3：右马达（弱/高频）；byte 4：左马达（强/低频）；
- byte 11..21：右扳机效果块；22..32：左扳机效果块（各 11 字节，自适应扳机用）。
  偏移来自 Linux 内核 `hid-playstation.c` 的 `dualsense_output_report_common`；
  扳机效果的使能位还没有真机验证，见 docs/plans/2026-11-24-controller-page.md。

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


class DualSenseReader(threading.Thread):
    """后台线程：连接手柄、持续读报告、提供快照与输出（震动/扳机效果）。"""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="dualsense")
        self._lock = threading.RLock()
        self._state: ControllerState | None = None
        self._device = None
        self._info: DeviceInfo | None = None
        self._running = False
        self._error = ""
        self._last_report = 0.0
        # 输出报告可能从反馈线程写、读线程读，hidapi 的句柄不能并发用
        self._write_lock = threading.Lock()
        # 输出报告按连接方式（USB 0x02 / 蓝牙 0x31）选布局，收到第一帧后确定
        self._transport = "usb"

    # ------------------------------------------------------------ 生命周期
    def start_reader(self) -> None:
        if self.is_alive():
            return
        self._running = True
        self.start()

    def stop(self) -> None:
        self._running = False
        if self.is_alive():
            self.join(timeout=1.0)
        self._close()

    def run(self) -> None:
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
        """按当前连接方式准备输出报告，返回 (报告, 字段偏移表)。"""
        with self._lock:
            transport = self._transport
        if transport == "bt":
            report = bytearray(BT_OUTPUT_LENGTH)
            report[0] = BT_OUTPUT_REPORT_ID
            report[1] = 0x02  # 蓝牙输出报告固定前缀
            layout = {
                "valid0": _BT_VALID0,
                "valid1": _BT_VALID1,
                "intensity": 38,
                "motor_right": _BT_MOTOR_RIGHT,
                "motor_left": _BT_MOTOR_LEFT,
                "right_trigger": _BT_RIGHT_TRIGGER,
                "left_trigger": _BT_LEFT_TRIGGER,
            }
        else:
            report = bytearray(USB_OUTPUT_LENGTH)
            report[0] = USB_OUTPUT_REPORT_ID
            layout = {
                "valid0": _USB_VALID0,
                "valid1": _USB_VALID1,
                "intensity": 37,
                "motor_right": _USB_MOTOR_RIGHT,
                "motor_left": _USB_MOTOR_LEFT,
                "right_trigger": _USB_RIGHT_TRIGGER,
                "left_trigger": _USB_LEFT_TRIGGER,
            }
        return report, layout

    def rumble(self, low: float, high: float) -> bool:
        """震动：low=强/低频马达，high=弱/高频马达，0..1。"""
        low_byte = max(0, min(255, int(round(float(low) * 255))))
        high_byte = max(0, min(255, int(round(float(high) * 255))))
        report, layout = self._new_output_report()
        report[layout["valid0"]] |= _VALID0_MOTORS
        report[layout["motor_right"]] = high_byte
        report[layout["motor_left"]] = low_byte
        return self._write(report)

    def set_trigger_effect(self, side: str, effect: bytes) -> bool:
        """写自适应扳机效果块（11 字节：模式 + 参数）。

        效果字节由 `trigger_effect_*` / `effect_bytes` 生成；
        主机下发的效果怎么解包还没验证（计划 S4），这里先把写入通道打通。
        """
        if len(effect) != 11:
            return False
        right = side.lower() in ("r", "right", "r2")
        report, layout = self._new_output_report()
        report[layout["valid0"]] |= _VALID0_RIGHT_TRIGGER if right else _VALID0_LEFT_TRIGGER
        # chiaki 的做法：同时置效果功率位（0x40）并给强度字节，
        # 否则部分游戏的效果（比如油门/刹车阻尼）不生效
        report[layout["valid1"]] |= 0x40
        report[layout["intensity"]] = 0x00
        block = layout["right_trigger"] if right else layout["left_trigger"]
        report[block : block + 11] = effect
        return self._write(report)

    def clear_trigger_effect(self, side: str) -> bool:
        """把某一边的扳机效果关掉。"""
        return self.set_trigger_effect(side, trigger_effect_off())

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
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass
