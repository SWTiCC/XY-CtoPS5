# XY-CtoPS5

把 PC 的**键盘和鼠标**变成 **PS5 手柄输入**，通过 PS5 Remote Play 的输入通道发送。

配合采集卡（HDMI 环出）看画面，就能用键鼠玩 PS5 主机游戏——画面走采集卡几乎零延迟，输入走 Remote Play 协议模拟成 DualShock 4。

> 本项目最初是为《GTA6》单机战役做的键鼠方案，鼠标→右摇杆的算法参考了业界成熟实现（chiaki / JoyShockMapper / DS4Windows）的公开做法。

---

## 功能特性

### 鼠标 → 右摇杆（核心）

| 特性 | 说明 |
|---|---|
| **Raw Input 设备位移** | 直接读鼠标设备报文，不依赖光标坐标，不受窗口焦点影响 |
| **固定时间窗口换算** | 10ms 窗口累积位移再换算速度，速度稳定不抖 |
| **反死区（Anti-Deadzone）** | 非零输入抬升到阈值以上，解决"小幅移动拖不动"（游戏自身摇杆死区吃小值） |
| **两段灵敏度** | 慢转/快转分别设灵敏度，中间线性过渡（精细瞄准 + 快速转身） |
| **Flick Stick** | 水平快速甩动时摇杆瞬间满偏一小段，模拟瞬间转身（Jibb Smart 方案） |
| **响应曲线** | 线性 / 二次 / 三次 / 幂，四种可选 |
| **输入死区 + 平滑** | 可调，配合使用 |
| **总开关** | 可单独关闭鼠标视角，不影响键盘 |

### 键盘 → 手柄

- 任意键映射任意手柄按钮
- **多模式**：每个模式一套完整映射，一个键循环切换（如"默认 / 驾驶"）
- **左摇杆方向键**：WASD 推摇杆，支持**过渡速度**（短按小幅、长按满幅）
- 组合键（chord）、序列宏（sequence）、摇杆幅度档位

### 其他

- **透明置顶覆盖层**：捕获时抢焦点、隐藏鼠标指针、右上角短暂显示模式名 / 扳机深度
- **扳机深度**：L2 / R2 可设定按压深度（模拟扳机走 Remote Play 的 analog button 事件），鼠标滚轮、键盘 `-` `=`、滑条都能调
- **目标窗口**：开始捕获时自动把焦点切到指定窗口
- **参数独立保存**：摇杆手感参数存 `tuning.json`，应用预设不会覆盖

---

## 环境要求

- Windows 10 / 11
- PS5 已开启：**设置 → 系统 → 远程游玩 → 启用远程游玩**
- Python 3.12（仅源码运行需要）
- 采集卡（推荐，用于看画面；不接也能用但看不到画面）

---

## 快速开始

### 1. 安装依赖（源码运行）

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### 2. 启动

```powershell
# 方式一：直接运行
.venv\Scripts\pythonw.exe launch.pyw

# 方式二：打包成 exe
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
```

### 3. 配对 PS5

1. PS5 上：设置 → 系统 → 远程游玩 → 启用远程游玩，记下 **PIN**（8 位）
2. PS5 的 PSN Account ID（Base64）可在网上查询或通过 PS5 保存的账号信息获取
3. 程序「连接」页填入 PS5 IP、Account ID、PIN → 点配对
4. 配对成功后生成 `credentials.json`，之后无需再配

### 4. 连接并开始

1. 「运行」页点「连接主机」
2. 点「开始捕获」（或按 **F8**）
3. 切到采集卡窗口，用键鼠控制 PS5

---

## 默认按键映射（GTA6）

| 输入 | 动作 | 输入 | 动作 |
|---|---|---|---|
| WASD | 左摇杆 | 鼠标移动 | 右摇杆（视角） |
| 空格 | ✕ CROSS | 鼠标左键 | R2 |
| R | □ SQUARE | 鼠标右键 | L2 |
| Q | R1 | 鼠标中键 | R3 |
| C | ○ CIRCLE | 鼠标侧键 1 | 上 |
| F | △ TRIANGLE | Tab | L1 |
| Shift | L3 | Esc | OPTIONS |
| Ctrl | 十字键右 | M | 触摸板 |
| B | 十字键左 | V | 十字键下 |
| 方向键 | 十字键 | CapsLock | 同时按 L3+R3 |

- **模式切换**：鼠标侧键 2（默认 / 驾驶）
- **驾驶模式**：W/S 变油门刹车（R2/L2），其余同默认

---

## 技术架构

```
输入层 (ps5kbm/input_source.py)
  ├─ Raw Input 鼠标（主线程消息泵）→ 设备相对位移
  ├─ Raw Input / pynput / 低级钩子 键盘（多路去重）
  └─ 光标差值兜底（远程桌面注入场景）

映射层 (ps5kbm/mapping.py) —— 纯逻辑，无 IO，可单测
  ├─ 鼠标：窗口累积 → 两段灵敏度 → 曲线 → 死区 → 反死区 → Flick Stick
  ├─ 键盘：按键状态 → 摇杆/按钮/组合/序列/幅度档位
  └─ 多模式：每个模式一套解析后的映射

发送层 (ps5kbm/bridge.py)
  ├─ playdirector / pyremoteplay 建立 Remote Play 会话（仅输入通道）
  ├─ 摇杆状态包 60Hz 发送（含 16 位序列号回绕补丁）
  └─ 按钮事件 / 扳机模拟量事件（analog button 0x86/0x87）

界面层 (ps5kbm/app.py + ui_pages.py + ui_common.py)
  ├─ 连接 / 映射 / 运行三页（customtkinter）
  ├─ 透明覆盖层（抢焦点、隐藏光标、提示）
  └─ 参数滑条（死区/灵敏度/两段/平滑/过渡/扳机深度）
```

### 关键技术点

- **Raw Input 必须在主线程建窗并跑消息泵**：子线程收不到 `WM_INPUT`（实测）
- **`WM_INPUT` 的 `lParam` 是 `HRAWINPUT` 句柄**（不是 `wParam`）
- **`RAWINPUT` 的 union 需按最大成员分配**，否则 `GetRawInputData` 返回 0
- **pyremoteplay 的反馈包只有摇杆**：扳机深度走 analog button 事件（0x86/0x87）
- **pyremoteplay 后台线程跨线程发 UDP 会崩**（Windows Proactor）：停用它，改由事件循环发送
- **sequence 16 位溢出**：发送几分钟后会抛 struct.error，按 16 位回绕
- **远程桌面注入不产生 WM_INPUT**：用光标位置差值兜底

---

## 项目结构

```
ps5-kbm/
├─ ps5kbm/                  # 主包
│  ├─ app.py                # 图形界面主逻辑
│  ├─ bridge.py             # Remote Play 会话与输入发送
│  ├─ config.py             # 配置模型与读写
│  ├─ input_source.py       # 输入采集（Raw Input / pynput / 钩子）
│  ├─ mapping.py            # 键鼠 → 手柄映射引擎（纯逻辑）
│  ├─ raw_mouse.py          # Raw Input 鼠标
│  ├─ raw_keyboard.py       # Raw Input 键盘
│  ├─ win_hooks.py          # Win32 低级钩子
│  ├─ global_hotkey.py      # 全局热键
│  ├─ windows.py            # 窗口枚举与激活
│  ├─ ui_pages.py           # 页面构建
│  ├─ ui_common.py          # 通用控件
│  ├─ theme.py              # 设计 token
│  ├─ keys.py               # 键名转换
│  ├─ overlay.py            # 覆盖层
│  └─ presets/              # 内置预设（默认键位 + 手感）
├─ tests/                   # 单元测试（映射引擎）
├─ vendor/                  # netifaces 兼容层
├─ launch.pyw               # 无控制台入口
├─ install.ps1              # 依赖安装
├─ build-exe.ps1            # 打包脚本
└─ requirements.txt
```

---

## 构建

```powershell
# 安装依赖
powershell -ExecutionPolicy Bypass -File .\install.ps1

# 打包 exe（onedir）
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1

# 产物
dist\XY-CtoPS5\XY-CtoPS5.exe
```

---

## 限制说明

- **PS5 锁 30fps 的游戏**（如 GTA6），视角每秒只更新 30 次，鼠标手感有天花板
- **PS5 同一时间只允许一个 Remote Play 会话**：不要同时开官方 PS Remote Play 客户端
- **远程桌面（ToDesk 等）**：绝对坐标模式会撞屏幕边缘，建议改相对/游戏鼠标模式
- 扳机深度依赖 **analog button 事件**，个别游戏可能不识别
- **仅供单人/单机游戏使用**，在线竞技使用本工具可能违反服务条款

---

## 许可证

**GPL-3.0**。

本项目依赖 [pyremoteplay](https://github.com/ktnrg45/pyremoteplay) / playdirector（GPL-3.0），因此整体以 GPL-3.0 发布。完整文本见 <https://www.gnu.org/licenses/gpl-3.0.txt>。

## 免责声明

本项目仅用于个人学习与单机游戏体验。使用它连接到 PS5 需要你自己拥有该主机。因使用本工具导致的任何账号风险、违反服务条款的后果，由使用者自行承担。
