# 连接逻辑：已配对主机快速连接（2026-11-23）

## 1. 边界：做 / 不做

**做**：

- 连接页拆成两种视图：
  - **完整流程视图**（现状）：填 IP / 扫描局域网 / Account ID + PIN / 配对 / 连接，首次使用走这里；
  - **快捷连接视图**（新增）：已经配对过（`credentials.json` 里存了主机与账号）时，只显示主机身份 + 三个按钮
    「直接连接」「重新检测」「换 ID 连接」（连接后「断开」可用）。
- 启动时**自动检测**当前局域网内有没有**已配对的那台** PS5（按 DDP 的 `host-id` 匹配；
  主机 DHCP 换了 IP 也能通过扫描找回，并把新 IP 写回 `credentials.json`）。
- 检测结果驱动界面：
  - 在线 → 停在快捷视图，点「直接连接」直接建立会话（不用再填任何东西）；
  - 未发现 / 检测异常 / 没有凭据 → 自动回到完整流程视图，顶部说明原因并可「重新检测」；
  - 配对成功后刷新「已配对主机」并自动重新检测。
- 删除 `app.py` 里没有任何调用点的死分支 `_apply_disconnected`。

**不做**：

- 不做 PSN 账号密码 / 网页登录界面（Account ID 仍手填或用 `run.cmd login` 取）。
- 不自动连接：检测到在线也必须由用户点「直接连接」（用户明确要求"一个按钮可以直接连接"）。
- 不做多主机收藏 / 下拉切换列表；换主机走「换 ID 连接」回完整流程。
- 不改 Remote Play 协议、不改 `credentials.json` / `config.json` 的字段格式。
- 不做自动唤醒主机（关机 / 待机时按"未发现"处理）。

## 2. 约束与复用

- **官方 API 优先**：`playdirector.ConsoleController.status()` 已经实现了「先按保存的 IP 探测身份 → 不通时 `scan()`
  按 `host-id` 找回主机 → 用 `migrate_credentials` 迁移凭据」。本功能**直接复用**它，不自己写 DDP 包。
  （依据：`.venv/Lib/site-packages/playdirector/console.py` 第 208-246 行。）
- 复用现有的 asyncio 后台线程与 `_ui_queue`（后台线程不碰 Tk），不新增线程。
- 复用 `ui_widgets` 的按钮 / 卡片 / 字体封装与 `theme.py` 的 token，不新增硬编码颜色与尺寸。
- 测试沿用 `tests/` 的 `unittest` 风格，不引入 pytest。
- 阈值：新文件 ≤300 行；`app.py` 只加编排胶水（目标 +≤80 行），视图与判定拆到新模块。

## 3. 架构：模块、依赖方向、公开接口

```
app.py（编排：何时探测、按钮回调、状态转发）
  ├── connect_ui.py     连接页骨架 + 快捷视图 + 统一渲染入口（只碰 Tk）
  │     ├── connect_full_ui.py  完整流程视图与提示条（只碰 Tk）
  │     └── connect_flow.py     纯逻辑：视图选择 / 按钮可用性 / 文案（无 Tk、无 IO）
  ├── probe.py          探测适配：已配对主机是否在当前局域网（复用 ConsoleController.status）
  │     └── _deps.py    vendor 路径引导（从 bridge.py 抽出，供 probe 复用，消除重复）
  ├── bridge.py         会话与发送（逻辑不变，只改用 _deps）
  └── config.py         凭据读写（不变）
```

依赖方向：`app → {connect_ui, probe, bridge, config}`；`connect_ui → {connect_full_ui, connect_flow, theme, ui_widgets}`；
`connect_full_ui → {connect_flow, theme, ui_widgets}`；`connect_flow` 不依赖任何 IO / Tk；`probe → {playdirector, _deps}`。
无循环依赖，UI 层不反向依赖 app 之外的东西。

**公开接口**：

```python
# connect_flow.py
@dataclass(frozen=True)
class PairedConsole:
    host_id: str; host_name: str; host_ip: str; account_id: str; device_type: str
    @property display_name(self) -> str
    @property type_label(self) -> str

def summarize_credentials(raw: dict | None) -> PairedConsole | None
def initial_view(paired: PairedConsole | None) -> str
def view_for_state(state: str) -> str

@dataclass(frozen=True)
class QuickView:
    title: str; subtitle: str; status_text: str; tone: str
    can_connect: bool; can_disconnect: bool; can_recheck: bool

def describe(paired, state, *, connected=False, connected_host="",
             connecting=False, probe_error="", connect_error="") -> QuickView
def full_notice(paired, state, probe_error="") -> str

# probe.py
@dataclass(frozen=True)
class ProbeResult:
    online: bool; host_id: str; host_ip: str; host_name: str
    device_type: str; ip_changed: bool; credentials: dict; error: str

async def probe_console(credentials: dict, timeout: float = 20.0, controller_factory=None) -> ProbeResult

# connect_ui.py
def build_connect_page(app, parent) -> ctk.CTkFrame
def show_view(app, view: str) -> None
def render(app) -> None
```

## 4. 契约

- **状态常量**：`checking / online / offline / unpaired / error`；视图常量 `quick / full`；语气 `ok / warn / err / dim`。
- **`ProbeResult` 语义**：
  - `online=True`：`host_ip` 是当前可用地址（可能已迁移），`credentials` 是迁移后的凭据副本，`ip_changed` 表示与传入的不同；
  - `online=False, error=""`：局域网内没有该主机（离线）；
  - `online=False, error!="…"`：探测本身出错（超时 / 凭据异常 / 网络异常），`error` 保留原始信息。
- **`summarize_credentials` 契约**：`device_ip` 为空或 `profiles` 为空 → 返回 `None`（视为未配对）；
  `account_id` 优先取 `account_id_input`，缺失时从 `profiles[*].id` 兜底。
- **渲染契约**：`render(app)` 只更新两套视图的文案与按钮状态，**不改变当前显示哪套视图**；
  切视图统一走 `show_view(app, view)`，由 `app` 显式决定，避免状态刷新时把用户"弹"回去。
- **错误分类**：凭据缺失/损坏 → `unpaired`；探测超时或异常 → `error`；`status()` 返回空 → `offline`。

## 5. 数据与状态

- **单一事实来源**：`credentials.json`（`device_ip` / `host_id` / `host_name` / `account_id_input` / `profiles`），
  不新增持久化字段；主机换 IP 时只回写 `device_ip`（并同步 `config.json` 的 `ps5_host` 便于老流程预填）。
- **app 内存状态**：`_paired`、`_probe_state`、`_probe_pending`、`_probe_error`、`_connect_error`、`_connecting`、`_bridge`。
- **状态流转**：

```
启动 ─┬─ 有凭据 → 快捷视图(checking) ─ probe ─┬─ online  → 快捷视图（可「直接连接」）
      │                                        ├─ offline → 完整视图 + 提示 +「重新检测」
      │                                        └─ error   → 完整视图 + 提示 +「重新检测」
      └─ 无凭据 → 完整视图
完整视图配对成功 → 刷新 _paired → 快捷视图(checking) → probe
连接成功 → 快捷视图（已连接，可「断开」）；连接失败 → 快捷视图显示失败原因并允许重试
断开 → 快捷视图（保持上次 online 结论）
```

## 6. 失败与边界

- **探测超时**：`probe_console` 用 `asyncio.wait_for(..., timeout=20)` 兜底（内部 `status()` 最坏 5+3+5 秒），超时按 `error` 处理。
- **凭据损坏 / 缺 `profiles`**：`_read_paired` 捕获 `OSError`/`ValueError` 记日志并当作未配对，界面走完整流程。
- **重复探测**：`_probe_pending` 为真或 `_bridge` 已连接、`_connecting` 进行中时拒绝再次发起。
- **检测中/连接中**：「直接连接」「重新检测」置灰，避免误点。
- **`host-id` 不匹配**（局域网里是**别的** PS5）：按离线处理，回完整流程重新配对（避免用错主机的凭据连接）。
- **关闭窗口时探测未返回**：结果只进 `_ui_queue`，不碰已销毁的 Tk。
- **连接失败**：沿用现有对话框（主机被占用给出专门提示），并在快捷视图显示失败原因。

## 7. 演进与扩展点

- **多主机收藏**：`PairedConsole` 列表化 + 快捷视图下拉；数据放 `config.json` 的 `consoles` 数组（本次不预留字段）。
- **自动唤醒**：`ConsoleController.wake()` 已是官方 API，离线时可加「唤醒主机」按钮。
- **app.py 继续膨胀**：把连接编排整体搬进 `connect_controller.py`；本次已把视图（`connect_ui`）与判定（`connect_flow`）拆出，`app.py` 只剩回调胶水。

## 8. 改动清单：文件 → 动作

| 文件 | 动作 |
|---|---|
| `ps5kbm/_deps.py` | 新增：vendor 路径引导（从 `bridge.py` 抽出） |
| `ps5kbm/probe.py` | 新增：已配对主机在线探测（复用 `ConsoleController.status`） |
| `ps5kbm/connect_flow.py` | 新增：视图选择 / 按钮可用性 / 文案（纯逻辑） |
| `ps5kbm/connect_ui.py` | 新增：连接页骨架、快捷视图、两套视图的统一渲染入口 |
| `ps5kbm/connect_full_ui.py` | 新增：完整流程视图（主机 / 配对 / 连接断开）与提示条 |
| `ps5kbm/bridge.py` | 修改：改用 `_deps.ensure_vendor_path()`，删掉内联路径注入 |
| `ps5kbm/ui_pages.py` | 修改：删除 `build_connect_page`（迁到 `connect_ui.py`） |
| `ps5kbm/app.py` | 修改：连接页改用 `connect_ui`；新增探测/快捷连接/换 ID 编排；删死代码 `_apply_disconnected` |
| `tests/test_connect_flow.py` | 新增：凭据摘要、视图选择、各状态文案与按钮可用性 |
| `tests/test_probe.py` | 新增：在线 / 离线 / 换 IP / 超时 / 异常（用假 controller，不联网） |
| `README.md` | 修改：快速开始与教程补充"第二次启动一键连接" |
| `docs/使用说明.md` | 修改：图形界面一节补充两种视图与检测行为 |
| `docs/features/连接逻辑.md` | 新增：功能开发文档（设计、原理、扩展指南） |
| `docs/images/connect-*.png` | 新增：快捷视图 / 离线回落 / 已连接三张界面截图（功能文档引用） |
| `CHANGELOG.md` | 修改：新增"未发布"记录 |

## 9. 验证：命令 / 测试 / 验收标准

- `python -m unittest discover -s tests -v`：新增两个测试文件全绿，原 `test_mapping.py` 不回归。
- `python -m ps5kbm --help`：CLI 冒烟（确认 `_deps` 抽取没有破坏 `playdirector` 导入）。
- 真实 GUI 验证（本机，用假探测结果驱动三种界面状态并截图）：
  - 有凭据 + 在线 → 快捷视图，按钮可用，文案正确；
  - 有凭据 + 离线 → 自动回落完整视图，顶部提示 + 「重新检测」；
  - 无凭据 → 完整视图（现状）。
- 需要用户实机验证（本机没有 PS5，无法验证真实 DDP）：真实探测耗时、在线直接连接、换 IP 后自动找回。
- **回滚**：改动集中在新模块 + `app.py` 少量胶水，回退本次提交即恢复原连接页。

## 10. 熵账本

**本次偿还的债**：

- 删除 `app.py` 死代码 `_apply_disconnected` 与 `"disconnected"` 队列分支（无任何生产者）。
- `ui_pages.py`（752 行）迁出连接页（-48 行），不再继续膨胀。
- `bridge.py` 的 vendor 路径注入抽到 `_deps.py`，供 `probe.py` 复用，避免第二份拷贝。

**本次新增的债**：

- 「检测」与「真正连接」是两次独立的 DDP 交互，中间隔几秒；主机在检测后关机仍可能连接失败（已有失败提示兜底）。
- 快捷视图与完整视图各有一套「连接/断开」按钮，必须都经 `connect_ui.render()` 同步；漏调会导致按钮状态不一致（已在测试与自查清单里覆盖）。
- `app.py` 仍然偏大（约 1030 行）；下一步若再加连接相关功能，应搬出 `connect_controller.py`。

## 11. 实际结果（执行后回填）

- 已完成：`_deps.py` / `probe.py` / `connect_flow.py` / `connect_ui.py` 新增；`bridge.py`、`ui_pages.py`、`app.py`
  按计划改造；两个测试文件新增；README / 使用说明 / CHANGELOG / 功能文档同步。
- 验证结果：
  - `python -m unittest discover -s tests`：60 个用例全绿（含新增的 29 个）；
  - 界面四态截图（在线 / 离线 / 已连接 / 无凭据）均正常；
  - 用假探测结果驱动真实 `Ps5KbmApp` 跑了 29 项状态流转断言（启动探测 → 离线回落 → 换 ID →
    手动完整流程不被抢回 → 用已配对主机 → 连接失败重试 → 已连接 → 断开复位），全部通过；
  - 用本机真实 `credentials.json` 跑了一次真实应用：探测真的在局域网找到了 `PS5Pro-Yi` 并进入
    快捷视图（证明复用 `ConsoleController.status()` 的检测路径可用）。
- 未验证（本机没有 PS5 会话场景）：真实「直接连接」建立输入通道、PS5 换 IP 后自动找回，
  需要用户实机确认。
- 与计划的偏差：
  - 计划里 `describe()` 只有 `probe_error`，实现中额外区分「检测失败」与「连接失败」两种文案（都走 `error` 语气）。
  - 完整视图顶部除了「重新检测」还加了「用已配对主机」按钮：用户点错「换 ID 连接」时可以一键回快捷视图。
  - 计划外修复：`CTkScrollableFrame` 的滚动条默认长度会把「扫描结果」区撑到 200+，把配对卡片和
    「连接主机」按钮顶出窗口。改为用固定高度容器包住列表区（提示条也做成单行结构），
    完整视图在默认窗口尺寸下已能完整显示所有内容。
- 未验证（本机没有 PS5）：真实 DDP 检测耗时、真实在线一键连接、换 IP 后自动找回，需要实机确认。
