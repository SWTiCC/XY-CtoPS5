# 手柄页（DualSense 直通 + 陀螺仪 + 震动/自适应扳机）实施计划（2026-11-24）

## 1. 边界：做 / 不做

**做**（合进现有 CtoPS5，新增「手柄」页）：

- 手柄检测：插入/拔出、USB/蓝牙、电量、设备名，页面实时显示；
- **手柄直通**：把 DualSense 的按键 / 双摇杆 / 双扳机按 Remote Play 协议发给 PS5；
- **陀螺仪 → 右摇杆**：按住 L2 启用（可配），松手归零，灵敏度 / 死区 / 平滑 / 反 Y 可调，带校准；
- **震动转发**：主机下发 → 本地 DualSense；
- **自适应扳机转发**：主机下发 → 本地 DualSense（先验证协议里有没有）；
- 配置持久化、日志、打包（沿用现有流程）。

**不做**：

- 不改键鼠映射的行为（手柄模式与键鼠模式**互斥**，页面里切换；混合输入后续再评估）；
- 不内置视频推流（画面仍走采集卡）；
- 不支持 PS4 / DualShock 4 的完整特性（能识别但只做基础按键透传，P2）；
- 不做多手柄（P2）。

**明确不承诺（先验证再定）**：自适应扳机和 HD 触觉能否 100% 还原。协议里有没有、能还原到什么程度，要靠 S2/S4 验证。

## 2. 约束与复用

- **读手柄用 hidapi（PyPI 包名 `hidapi`，导入名 `hid`）**，不用 SDL2：
  装好后是 Cython 扩展 `hid.cp312-win_amd64.pyd`，**hidapi 已静态链接**，
  打包时不需要额外 DLL，也不需要系统装驱动；
  既能读输入报告（陀螺仪/摇杆/按键），也能写输出报告（震动、自适应扳机效果），
  这正是 DS4Windows / DSX 的做法；SDL2 对 DualSense 的自适应扳机支持不完整。
  （注意：PyPI 上另有一个纯 Python 的 `hid` 包，会和这个冲突，**只能装 `hidapi`**。）
- **协议层照旧**：`playdirector` / `pyremoteplay` 的 `ConsoleController`，
  复用 CtoPS5 已修的补丁（16 位计数溢出、L2/R2 模拟量深度）。
- **映射层纯函数**：陀螺仪换算、死区、平滑写成 `gyro.py`，单测覆盖，不碰 Tk/HID。
- 页面沿用 `theme.py` / `ui_widgets.py`，与连接/映射/运行页同一套视觉。

## 3. 架构

```
手柄页 controller_ui.py（只摆控件）
        │ 回调
app.py 编排：模式下选择、参数、日志
   ├── 输入：dualsense.py（hid 读）→ ControllerState
   │         └─ gyro.py（纯函数：角速度 → 右摇杆贡献）
   ├── 发送：bridge.Ps5Bridge（现有）← 手柄状态 / 键鼠映射（二选一）
   └── 反馈：bridge 收到 RUMBLE/TRIGGER 包 → dualsense.py 写输出报告
```

- `dualsense.py`：设备枚举、打开、读输入报告（USB `0x01` / 蓝牙 `0x31`）、
  解析按键/摇杆/扳机/陀螺仪/加速度/电量、写输出报告（震动 `0x02`，蓝牙 `0x31` + 序号）。
- `ControllerState`（dataclass）：`buttons:set[str]`、`lx/ly/rx/ry`、`l2/r2`、`gyro:(x,y,z)`、`battery`。
- `gyro.py`：`GyroMapper`（bias、死区、平滑、灵敏度、反 Y）→ `(x, y)` 贡献值，纯函数。
- `app`：新增 `_controller_mode`（`keyboard` / `controller`）与 `_gyro_mapper`；
  tick 循环里：手柄模式 → 用 ControllerState + 陀螺仪合成摇杆与按键事件；否则走现有 mapper。
- 震动/扳机反馈：`bridge` 收包处新增回调（先加日志验证），再接到 `dualsense.write_output`。

## 4. 契约

```python
@dataclass
class ControllerState:
    name: str
    transport: str          # "usb" | "bt"
    buttons: set[str]       # "cross","circle","square","triangle","l1","r1","l2","r2","l3","r3",
                            # "up","down","left","right","options","share","ps","touchpad"
    lx: float; ly: float    # -1..1
    rx: float; ry: float    # -1..1
    l2: float; r2: float    # 0..1（模拟量）
    gyro: tuple[float, float, float]    # rad/s，x/y/z
    accel: tuple[float, float, float]
    battery: int | None     # 0..100
```

```python
class DualSense:
    @staticmethod
    def list_devices() -> list[DeviceInfo]
    def open(self, info) -> None
    def read(self, timeout_ms=0) -> ControllerState | None
    def close(self) -> None
    def set_rumble(self, low: float, high: float) -> None      # 0..1
    def set_trigger_effect(self, side: str, effect: dict) -> None   # P1
```

配置新增：

```json
"controller": {
  "mode": "keyboard",           // keyboard | controller
  "gyro": {
    "enabled": true,
    "activation": "l2",         // l2 | l1 | always
    "sensitivity_x": 1.0,
    "sensitivity_y": 1.0,
    "deadzone": 0.02,
    "smoothing": 0.3,
    "invert_y": false
  },
  "rumble": { "enabled": true, "gain": 1.0 },
  "triggers": { "adaptive": false }
}
```

## 5. 数据与状态

- 单一事实来源：手柄状态只由 `dualsense.read()` 产生；页面显示只读。
- 模式互斥：切到「手柄」模式时停用键鼠映射（`InputSource` 仍运行但映射不参与发送），
  反之亦然；切换时先释放所有已按下的按钮（避免卡键）。
- 陀螺仪校准值随配置持久化；启动时自动校准 1 秒，用户可手动重校。

## 6. 失败与边界

- 手柄未连接：页面显示「未检测到手柄」，不阻塞键鼠模式；
- 读到无效/超时：跳过该帧，连续 1 秒无数据判为断连 → 界面提示 + 退出手柄模式；
- 手柄拔出：释放所有按键、右摇杆归零，再切回键鼠模式；
- 协议里没有震动/扳机数据：界面明确显示「当前主机未下发震动/扳机效果」，不做假实现；
- 蓝牙输出报告需要序号（`0x31` 报告带 seq），USB 用 `0x02`，两条路径都要测；
- 权限/占用：若 Steam 抢手柄（Steam Input），页面提示关闭 Steam 的手柄接管。

## 7. 演进

- P2：键鼠 + 手柄混合输入（需要按钮级引用计数）；
- P2：多手柄 / DualShock 4 / 手柄按键自定义映射；
- P2：陀螺仪直控模式（位移→偏转）与曲线调节；
- P3：手机陀螺仪作为输入源（UDP）。

## 8. 改动清单

| 文件 | 动作 |
|---|---|
| `ps5kbm/dualsense.py` | 新增：hid 枚举/读写/解析 |
| `ps5kbm/gyro.py` | 新增：陀螺仪 → 摇杆纯函数 + 校准 |
| `ps5kbm/controller_ui.py` | 新增：手柄页（状态/参数/校准/日志） |
| `ps5kbm/app.py` | 新增页面、模式切换、tick 合成、反馈回调 |
| `ps5kbm/ui_pages.py` | 侧栏加「手柄」入口 |
| `ps5kbm/config.py` | 新增 `controller` 配置段与默认值 |
| `ps5kbm/bridge.py` | 收包处暴露震动/扳机回调（先日志） |
| `tests/test_gyro.py` | 新增：陀螺仪换算/死区/平滑单测 |
| `tests/test_config.py` | 新增：controller 配置读写 |
| `build-exe.ps1` / `requirements.txt` | 加 `hid` 依赖与 `hidapi.dll` 打包 |
| `docs/使用说明.md` / `CHANGELOG.md` | 同步 |

## 9. 验证

**S1（先做）**：插入 DualSense（USB），跑检测脚本，确认能读到陀螺仪与按键；
**S2**：在 `bridge` 收包处打日志，确认流里有没有震动/扳机包；
**S3**：写输出报告让手柄震动；
**S4**：自适应扳机效果写入手柄；
**S5**：端到端延迟。

**验收**（M1/M2）：
- 手柄页能检测到插入/拔出，显示 USB/蓝牙与电量；
- 手柄模式下按键/摇杆/扳机在 PS5 上正确；
- 按住 L2 转动手柄，右摇杆有响应，松手归零；
- 手柄静止 10 分钟右摇杆输出 <0.02；
- 键鼠模式不受影响（回归现有 95 个单测 + 手动冒烟）。

## 10. 熵账本

- **新增依赖**：`hid`（hidapi）——新依赖需要写进 README 与打包脚本；
- **新增跨模块耦合**：`app` 现在同时持有键鼠 InputSource 与手柄 DualSense，
  用「模式互斥」限制耦合面；混合输入留给 P2，避免一上来就做引用计数；
- **协议补丁**：震动/扳机若需要解析新包，补丁集中在 `bridge.py` 一个函数里，写清启用与移除条件；
- **硬件依赖**：所有手柄相关验证必须有真机；没有手柄时只能写到接口层并标未验证。

## 11. 实施状态（2026-11-24）

已完成（代码层，117 个单测全绿）：

- `ps5kbm/dualsense.py`：hidapi 枚举 / 打开 / 读取 / 解析（USB 0x01、蓝牙 0x31），
  震动输出（USB 0x02，偏移按 Linux 内核 `hid-playstation.c`），扳机效果写入接口（待验证）；
- `ps5kbm/gyro.py`：角速度 → 右摇杆纯函数（死区 / 灵敏度 / 平滑 / 反 X / 反 Y / 校准）；
- `ps5kbm/controller_ui.py`：手柄页（连接状态、输入模式、陀螺仪参数、校准、震动/扳机开关），
  截图见 `docs/images/controller-page.png`；
- `app.py`：手柄页注册、模式切换、tick 循环手柄分支、按键 diff 转发、扳机模拟量、
  陀螺仪合成、断开 / 切换时释放输入、校准采样（主线程 `after` 轮询）；
- `config.py`：`controller` 配置段、默认值、往返读写、非法值回落；
- 侧栏加「手柄」入口；`requirements.txt` / `install.ps1` 加 `hidapi`。

待真机验证（S1 / S3 / S4）：

- HID 输入报告的字节位置与陀螺仪量纲（`GYRO_RAW_TO_RAD`）；
- 震动输出报告的 valid_flag0 / 马达字节（未在真机确认）；
- 陀螺仪三轴符号（页面有反 X / 反 Y 兜底）；
- Remote Play 流里有没有震动 / 扳机效果数据（S2）；有的话接到 `app._on_rumble` 与扳机效果写入。

尚未做：

- 打包（等真机验证后出 0.3.0）；
- 自适应扳机效果解包（依赖 S2 / S4 结论）；
- 键鼠 + 手柄混合输入（P2）。

## 12. 回家后的验证清单（按顺序）

**2026-11-24 实机（蓝牙）已验证：**

- [x] 连接识别：蓝牙 / 电量 90% / 充电状态正确；
- [x] 按键位：✕ ○ □ △ L1 R1 十字键 L3 R3 分享 选项 PS 触摸板全部正确
      （修了 DS5 面键/十字键位序、十字键低 4 位）；
- [x] 震动：蓝牙 `0x31` + CRC 输出报告，手柄有震动；
- [x] 自适应扳机：R2 阻力效果实机确认有顶手感（蓝牙输出与 CRC 正确）；
- [x] 陀螺仪量纲：±2000°/s、16 位有符号（`GYRO_RAW_TO_RAD` 已改为 2000/32768·π/180）；
      加速度 8192 = 1g；
- [x] 陀螺仪方向：向右转 yaw 为负、抬头 pitch 为正，当前取负号的映射方向正确；
- [x] 蓝牙完整报告：刚连接时只发 `0x01` 简单报告（无陀螺仪/电量），
      写一帧输出报告后切到 `0x31` 全量报告（已在连接时自动发送）；
- [x] 传输判断：按设备路径里的 BT HID UUID 判断，不再依赖报告 ID。

**还没做：**

- [ ] 抓包诊断（S2）：确认主机下发的震动 / 自适应扳机数据走哪条通道；
- [ ] 键鼠 + 手柄混合输入（P2）；
- [ ] 打包 0.3.0。

### 剩余步骤

1. **震动 / 扳机**：UE 已确认；进游戏后如果主机下发的震动没有转发，按第 2 步抓包；
2. **抓包诊断**：手柄页打开开关 → 连 PS5 玩一局有自适应扳机的游戏（1~2 分钟）→ 把日志发我；
   确认数据通道后把 `_on_rumble` 和扳机效果接进去；
3. 以上完成 → 打包 **0.3.0** → 安装。
