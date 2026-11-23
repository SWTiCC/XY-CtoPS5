# 使用问题全量修复（0.2.5，2026-11-23）

> 本轮不升版本号：用户要求「还是 0.2.5，全修复」。修复后重新打包，版本仍是 0.2.5。

## 1. 边界：做 / 不做

**做**：体检脚本复现出的 13 类使用问题（A1-A5 / B1-B6 / C1-C2 / D1-D6）全部修掉。

**不做**：
- 不改连接协议、不改 pyremoteplay 适配层（B5 里的 9303 端口冲突只在界面上给出口，不重写 DDP）；
- 不改映射语义（组合键/序列/stick 动作的解析规则不动）；
- 不动预设文件格式的必要字段（只新增 tuning 字段，旧文件仍可读）；
- 不新增第三方依赖。

## 2. 约束与复用

- 现有分层：`config`（数据/契约）→ `input_source`（输入）→ `app`（编排）→ `*_ui`（只摆控件）。
- 冲突判定是纯逻辑，**放 config.py 做成纯函数**，才能进单元测试；app.py 只负责取参数与弹窗。
- 原子写盘复用同一段 `_write_json`，四处写盘点（config / tuning / preset / credentials）都改走它。
- 对话框、间距、颜色沿用 `theme.py` / `ui_widgets.py`，不新增样式常量。

## 3. 架构：模块、依赖方向、公开接口

| 模块 | 本轮职责 | 新增公开接口 |
| --- | --- | --- |
| `config.py` | 校验/写盘/预设构造 | `key_conflict(...)`、`new_empty_config(name, base=None)`、`TRIGGER_LABELS` |
| `input_source.py` | 捕获态与调参/切模式的生效范围 | `set_capturing(value)` |
| `app.py` | 编排、冲突提示、非阻塞断开 | 无（内部方法） |
| `connect_flow.py` | 状态 → 按钮可用性 | 无（`describe` 语义调整） |
| `*_ui.py` | 显示键名字、深度初值、多键编辑 | 无 |

依赖方向不变：UI → app → config/input_source，**config 不 import UI**。

## 4. 契约

### `config.key_conflict`
```python
def key_conflict(
    name: str,
    *,
    hotkey: str = "",
    mode_switch: str = "",
    trigger_keys: dict[str, str] | None = None,
    stick_keys: Iterable[str] = (),
    mapping_sources: Iterable[str] = (),
    ignore_mode_switch: str = "",
    ignore_trigger: str = "",
) -> str:
    """返回该键被占用的中文原因；可用时返回空串。"""
```
判定顺序固定：捕获热键 → 模式切换键 → 扳机调参键 → 左摇杆方向键 → 已映射按键。

### `config.new_empty_config(name, base=None)`
- `modes` 只有一个 `default`，三组映射为空（契约不变）；
- 传 `base` 时继承**非映射**设置：hotkey / mode_switch / target_window /
  mouse / left_stick / r2_depth / l2_depth（新建预设不再把切换键重置成 F9；
  鼠标手感本来就存在 tuning 里，这里保持常量语义）。

### 扳机深度落盘
- `AppConfig` 新增 `r2_depth: float = 1.0`、`l2_depth: float = 1.0`；
- `tuning.json` 顶层写 `r2_depth` / `l2_depth`（与 mouse/left_stick 同级）；
- `load_config` 里 tuning 覆盖规则同 mouse/left_stick。

## 5. 数据与状态

- 捕获状态单一来源是 `InputSource._capturing`；界面只呈现，不再自行推导。
- 断开连接后 `InputSource` 停止（释放 F8 全局热键与钩子），重连时由 `_on_connected` 重新 start。
- 断开改为异步：`_disconnect` 立即更新界面，关闭会话丢给事件循环；`_connect_async`
  在建立新会话前等待 `_closing` 归零，避免两条会话打架。

## 6. 失败与边界

- `config.json` 解析失败：备份成 `config.json.broken`，按预设启动，日志里说明。
- 预设文件解析失败：弹窗说明并恢复下拉框，界面不留「显示 A 实际 B」的状态。
- 写盘一律 `tmp + os.replace`，避免断电/崩溃留下半截 JSON。
- 捕获时改映射会重建 InputSource：重建后若原本在捕获，**恢复捕获**而不是静默关掉。
- 所有跨线程回调（调参键、切模式键）只入队，Tk 操作回到主线程。

## 7. 演进与扩展点

- 冲突规则集中在 `key_conflict`，以后新增「占用型按键」（比如新的全局键）只改这一处；
- 按键占用项通过参数传入，不硬编码在提示文案里；
- 预设新增字段沿用 `build_config` 的「缺失用默认」策略，老文件继续可读。

## 8. 改动清单：文件 → 动作

| 文件 | 动作 |
| --- | --- |
| `ps5kbm/config.py` | `_write_json` 原子写；`load_config` 坏文件兜底；`new_empty_config(name, base)`；新增 `key_conflict`、`TRIGGER_LABELS`；r2/l2 深度字段与 tuning 读写 |
| `ps5kbm/input_source.py` | 调参键/切换键仅在捕获时生效；新增 `set_capturing` |
| `ps5kbm/app.py` | A1/A2 添加映射校验；A3 断开即停 InputSource + 捕获守卫；A4 调参入队；A5 连接时下发深度；B1 模式重名禁止 + 旧数据消歧；B3 display_key；B4 改键冲突校验；B6 异步断开；C2 预设读失败兜底；D1 minsize；D2 只在捕获时切模式；D3 删死代码；D4 日志裁剪；重建映射后恢复捕获 |
| `ps5kbm/mapping_ui.py` | 切换键按钮用 `display_key` |
| `ps5kbm/run_tuning_ui.py` | 深度初值取配置、标签取 `config.TRIGGER_LABELS` |
| `ps5kbm/ui_common.py` | 方向键编辑器支持多键（逗号分隔，显示全部） |
| `ps5kbm/connect_flow.py` | 检测出错时允许「直接连接」 |
| `ps5kbm/connect_full_ui.py` | 检测中禁用「重新检测」 |
| `ps5kbm/bridge.py` | 无需改动 |
| `tests/test_config.py` | 新增 key_conflict / new_empty_config(base) / 坏配置兜底 / 原子写 / 深度落盘用例 |
| `tests/_tmp/audit_*.py` | 改为验证修复后的行为（回归脚本） |
| `CHANGELOG.md` / `docs/使用说明.md` / `docs/features/*` | 同步行为变化 |

## 9. 验证：命令 / 测试 / 验收标准

- `python -m unittest discover -s tests` 全绿（现有 79 + 新增）；
- `tests/_tmp/audit_ui.py`、`audit_ui2.py`、`audit_layout.py` 全部断言按「已修」通过；
- 真机启动 exe：连接页 / 映射页 / 运行页截图无裁切；F8 在未连接时不再进捕获；
- 打包 `dist\XY-CtoPS5.exe` 与 `dist\XY-CtoPS5-Setup.exe` 仍为 0.2.5，安装到 `app\` 并启动验证。

## 10. 熵账本

**本次偿还**：
- `_send_trigger` 死代码删除；
- 冲突规则从 app.py 里散落的字符串判断收敛成 `config.key_conflict` 一个纯函数；
- 四处重复的「open + json.dump」收敛成 `_write_json`。

**本次新增**：
- `InputSource.set_capturing`、`_closing` 标志：各自只有一处使用，但都属于「状态纠正」的必要出口，已在注释里写明用途；
- `key_conflict` 参数略多（6 个关键字参数），后续如果再加占用类型，改成 dataclass 传参。

**遗留**：
- 探测/连接衔接的本地 9303 端口冲突没有根治（属 pyremoteplay 内部），本轮只保证界面不因此堵死；
- 真机手感（摇杆曲线、扳机深度实际效果）需上台机确认，脚本无法覆盖。

## 11. 实施结果（回填）

13 类问题全部修复，与计划一致；实施过程中有 4 处计划外但必要的补充：

1. **`_apply_capture_state` 增加"输入层对齐"一行**（`self._source.set_capturing(capturing)`）：
   界面状态是唯一事实来源，任何路径进来都让输入层跟随。否则从「重建映射后恢复捕获」这条路径进去，
   界面显示捕获中、输入层却没捕获（正好是本次要修的那类脱节）。
2. **`InputSource.stop()` 顺手把捕获态归零**：断开后停监听时必须一起清，否则 `capturing` 会留着。
3. **`_lock_min_window_size` 改传逻辑尺寸**：CTk 的 `minsize()` 会再乘一次窗口缩放，
   传 `winfo_width()`（物理像素）会把最小尺寸撑到 1.5 倍、窗口反而变大。实测 2115×1710 → 1410×1140。
4. **新增 `tests/manual/verify_ui_fixes.py`**：42 项断言在临时目录里驱动真实界面逐条验证修复，
   原有三个一次性体检脚本没有纳入仓库（都在 gitignore 的 `tests/_tmp` 里）。

验证结果：
- `python -m unittest discover -s tests`：**95 项全绿**（原 79 + 新增 16）；
- `tests/manual/verify_ui_fixes.py`：**42/42 通过**；
- 源运行实测（截图 + 真实按键）：连接页一键连接、映射页「切换键 鼠标侧键2」、
  运行页扳机键显示「↑ 滚轮上 / ↓ 滚轮下 / ↑ = / ↓ -」且 R2/L2 深度来自配置、
  在添加映射弹窗里按 F8 弹出「F8 是捕获热键，换一个键吧」；
- 打包版本仍为 0.2.5，重新生成了 onedir 程序与安装包并安装到 `app\`。

遗留（同上）：9303 端口冲突未根治；摇杆手感与扳机实际效果需真机确认。

## 12. 用户反馈后的规则调整（同日）

体检版把「保留键」全硬拦了，实际用起来收得太紧。按用户反馈改成：

- **唯一硬禁：捕获热键 F8**（捕获中按它只会开关捕获）；
- **同一个键盘键可以承担多件事**：W 既是左摇杆↑方向键、又绑一条 PS5 按钮是允许的，
  两个动作都会触发（方向键表与按键表本来就是两套并行逻辑），只在日志里说明一句；
- **模式切换键 / 扳机调参键**这类会被输入层优先吃掉的键：允许绑，但先问一句
  "捕获时按下会先触发它，这条映射不会生效。仍然添加？"，确认后照常写入；
- **键盘键重复（已经绑过别的动作）**：保留原来的"用新动作覆盖它？"确认。

代码落点：`app._hotkey_reason()`（硬禁）与 `app._mapping_key_conflict()`（软冲突）替代原来的
`_reserved_key_reason()`；`config.key_conflict()` 本身不变（改切换键 / 调参键时仍用它做反向校验）。
回归脚本相应改为 45 项断言，全部通过。
