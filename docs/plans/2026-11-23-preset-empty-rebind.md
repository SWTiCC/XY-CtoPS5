# 0.2.3：空预设 + 切换即应用 + 映射改键（2026-11-23）

## 1. 边界：做 / 不做

**做**：

- **新建预设**：新建的预设映射为空，默认带且仅带一个「默认」模式；点「新建预设」输入名字即创建并切换过去。
- **切换预设即应用**：去掉「应用」按钮，预设下拉选中哪个就立即套用哪个。
- **编辑映射改键**：映射列表每行加「改键」，可以把某条映射的来源键（例如 E）重新捕获成任意键盘 / 鼠标键。
- 用户自己新建的预设，编辑后自动写回预设文件（内置 gta6 不覆盖）；保留「另存为…」用于把当前配置复制成新预设。

**不做**：

- 不改映射动作类型（单按钮 / 组合 / 序列 / 摇杆幅度）的结构。
- 不做预设导入导出、重命名。
- 不允许把映射改键到捕获热键 / 模式切换键 / 扳机调参键（这些键会被输入层优先拦截）。

## 2. 约束与复用

- 复用 `KeyCaptureDialog`（改键）、`config.save_preset` / `check_preset_name` / `is_user_preset`；
- 新建空预设用 `config.new_empty_config()`，写盘仍走 `preset_to_dict`，文件格式不变；
- 约定：`_persist()` 在保存 `config.json` 时顺带把当前配置写回**当前用户预设**（`is_user_preset` 为真时）。

## 3. 架构与接口

```
config.new_empty_config(name) -> AppConfig   # 只有 default 模式、映射全空
app.create_preset()        # 输入名字 → 写预设文件 → 刷新列表 → 应用
app.apply_preset(name)     # 下拉选中即调用；写 config.json 并刷新映射 / 模式 UI
app.rebind_mapping(source) # 捕获新来源键 → 冲突确认 / 保留键校验 → 搬移映射
app._persist()             # 额外自动保存当前用户预设
mapping_ui                 # 工具栏按钮与列表行（新建预设 / 另存为 / 删除 / 改键）
```

## 4. 契约

- `new_empty_config(name)`：`modes == {"default": ModeConfig(label="默认")}`，三组映射均为空 dict；
  其余字段用 `AppConfig` 默认值（手感参数不会被应用预设覆盖）。
- `rebind_mapping`：同类别内同名键 → 询问是否覆盖；跨键盘/鼠标表时从原表删除；
  目标是 hotkey / mode_switch / 四个调参键时拒绝并提示。
- 下拉切换：`CTkComboBox(command=apply_preset)`，不再有单独的「应用」按钮。

## 5. 数据与状态

- `config.json` 照旧是当前工作状态；用户预设文件随编辑自动更新；
- 内置预设（`ps5kbm/presets`）永远只读；删除当前用户预设时回落到其他可用预设（上一版已有）。

## 6. 失败与边界

- 新建时名字已存在 → 拒绝（避免空预设覆盖已有内容），提示换个名字；
- 改键时按 Esc 取消 → 不动；捕获到同一键 → 不动；
- 改键覆盖已有键位 → 弹窗确认后覆盖；
- `_persist` 写预设失败（只读目录等）→ 记日志，不影响 config.json 保存。

## 7. 演进

- 预设导入 / 导出、重命名可复用 `check_preset_name` 与文件层；
- 改键后续可扩展成"按住某键时临时改键"。

## 8. 改动清单

| 文件 | 动作 |
|---|---|
| `ps5kbm/config.py` | 新增 `new_empty_config()` |
| `ps5kbm/app.py` | `create_preset` / `apply_preset` 改造 / `rebind_mapping` / `_reserved_key_reason` / `_persist` 自动存用户预设 |
| `ps5kbm/mapping_ui.py` | 工具栏：新建预设、去掉应用；列表行加「改键」 |
| `tests/test_config.py` | 新增空预设结构测试 |
| `README.md` / `docs/使用说明.md` / `CHANGELOG.md` / `installer.iss` / `__init__.py` | 同步 0.2.3 |

## 9. 验证

- 单测全绿；源运行冒烟：新建空预设 → 下拉自动应用 → 添加映射 → 改键 → 切换预设再切回；
- 安装版截图确认映射页与版本号。

## 10. 熵账本

**偿还**：`_apply_preset` 改名为对外可直接调用的 `apply_preset(name)` 并去掉 UI 里的冗余「应用」步骤；
预设保存逻辑收敛到 `_persist` 一处。

**新增**：用户预设会自动随编辑写盘（删预设前程序会提示），需要文档说明。

## 11. 实际结果（回填）

- 「应用」按钮已去掉，预设下拉选中即调用 `apply_preset(name)`；
- 「新建预设」创建空预设（仅默认模式、三组映射为空），建完直接切换；
- 「另存为…」保留为复制当前配置；用户预设编辑后自动写回文件，切换预设来回不丢键位；
- 映射列表每行新增「改键」，支持键盘↔鼠标跨表搬移、占用键覆盖确认、全局热键/模式切换键/调参键拒绝；
- 验证：79 个单测全绿；17 项预设/改键联动冒烟全通过；
- 打包：0.2.3 的 `dist\XY-CtoPS5`、`dist\XY-CtoPS5-Setup.exe`（ProductVersion 0.2.3）与 `app\` 已更新，
  安装版实测侧栏 `v0.2.3`、映射页「新建预设 / 另存为… / 删除」与列表「改键」按钮正常。
