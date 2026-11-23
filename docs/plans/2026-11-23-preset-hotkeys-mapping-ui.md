# 0.2.2：扳机调参键自定义 + 预设新建 + 映射页美化（2026-11-23）

## 1. 边界：做 / 不做

**做**：

- **扳机调参键自定义**：现在 `R2` 用鼠标滚轮上下、`L2` 用 `-` / `=` 调深度，这四个键改为可配置，
  当前值作为默认值；运行页每行扳机旁边直接显示当前键，点一下就重新捕获。
- **预设可以新建**：映射页的「预设」是**整套配置**（里面含默认 / 驾驶等所有模式）。
  现有 UI 只能覆盖下拉里已有的名字，新增「另存为…（新建预设）」和「删除预设」。
- **映射页 UI 调整 + 映射列表美化**：工具栏收进卡片，列表每行改成圆角行 + 键名 chip + 动作 chip，
  鼠标来源用强调色区分，删除按钮做成小 ×。

**不做**：

- 不改映射引擎（mapping.py）、不改手柄发送逻辑。
- 不做预设导入/导出文件选择器（仍写在 `presets\<名字>.json`）。
- 不做「预设只包含某个模式」的拆分（用户明确要的是整套预设）。

## 2. 约束与复用

- 复用 `KeyCaptureDialog`（键盘 + 鼠标键），新增 `allow_wheel=True` 后可捕获 `wheel_up/wheel_down`；
- 复用 `config.save_preset`（已能写整套 modes），只补 `delete_preset` / 名字校验 / 是否用户预设；
- 复用 `ui_widgets` 的卡片、按钮、`divider`、`switch` 与 theme token；
- 阈值：新/改文件都 ≤300 行；核心逻辑（键位匹配、预设校验）纯函数可单测。

## 3. 架构：模块、依赖方向、公开接口

```
config.py         AppConfig 新增 4 个调参键字段；trigger_adjust_keys() / check_preset_name() / delete_preset()
input_source.py   set_trigger_adjust(keys, callback)；adjust_action_for(keys, name) 纯函数；滚轮 / 键盘 / 鼠标键统一入口
app.py            _on_adjust() / _rebind_trigger_key() / save_as_preset(新建) / delete_preset()
ui_common.py      KeyCaptureDialog(allow_wheel=...) + 标点键 keysym 映射
run_tuning_ui.py  扳机行改为「滑条 + 加减键按钮」
ui_pages.py       映射页工具栏卡片化 + 映射列表行美化
```

依赖方向不变：`ui_* → {config 只读, theme, ui_widgets}`；`input_source` 不依赖 UI；无循环。

## 4. 契约

- `config.AppConfig` 新增：`r2_up="wheel_up"`、`r2_down="wheel_down"`、`l2_up="="`、`l2_down="-"`；
  `config.trigger_adjust_keys(cfg) -> dict[str, str]`（空值回落默认）。
- `input_source.adjust_action_for(keys, name) -> str`：键名（含 `wheel_up/wheel_down`、`mouse_x1`）→
  `r2_up/r2_down/l2_up/l2_down` 或空串；`+` 视为 `=` 的别名。
- `config.check_preset_name(raw) -> str`：去空格、拒绝空名与 `\/:*?"<>|`，非法抛 `ValueError`（中文提示）。
- `config.is_user_preset(name) -> bool` / `delete_preset(name) -> str`（只删用户目录里的预设）。
- 映射列表行：`_mapping_row(app, source, value)`，`source` 形如 `space` / `mouse_x1`。

## 5. 数据与状态

- `config.json` 新增 4 个字段；旧配置缺字段时用默认值，无需迁移。
- 预设文件结构不变（`preset_to_dict` 不写入这 4 个键，保持预设只管键位）。
- 运行页 `app._trigger_buttons` 保存 4 个改键按钮，改键后同步按钮文字。

## 6. 失败与边界

- 调参键与映射键冲突：调参键优先（与现在 `-`/`=` 的行为一致）。
- 改键捕获到空（Esc 取消）→ 不改；重复绑定同一个键 → 允许，先匹配到哪个就哪个（按 r2_up→r2_down→l2_up→l2_down 顺序）。
- 预设名重复 → 询问是否覆盖；删除内置预设 → 拒绝并提示「只能删用户预设」。
- 新建预设时不复制 `credentials.json` 等无关文件，只写 `presets\<名字>.json`。

## 7. 演进与扩展点

- 预设后续可加「导入 / 导出到文件」「复制预设」；`check_preset_name` 与文件层已就位。
- 调参键表以后若要扩到摇杆幅度等，复用 `adjust_action_for` 的映射表结构即可。

## 8. 改动清单

| 文件 | 动作 |
|---|---|
| `ps5kbm/config.py` | 新增 4 个调参键字段、`trigger_adjust_keys`、`check_preset_name`、`is_user_preset`、`delete_preset` |
| `ps5kbm/input_source.py` | 新增 `adjust_action_for` 纯函数、`set_trigger_adjust`；键盘 / 滚轮 / 鼠标键统一走它 |
| `ps5kbm/app.py` | 调参键处理与改键、预设另存为 / 删除、映射列表条数 |
| `ps5kbm/keys.py` | 新增 `display_key()`（`wheel_up` → 滚轮上等） |
| `ps5kbm/ui_common.py` | `KeyCaptureDialog(allow_wheel)`、标点键 keysym、`format_source_key()` |
| `ps5kbm/run_tuning_ui.py` | 扳机行改为「滑条 + 加/减键按钮」 |
| `ps5kbm/mapping_ui.py` | 新增：映射页（预设 / 模式工具栏、映射列表行） |
| `ps5kbm/ui_pages.py` | 修改：只保留顶栏 / 侧栏 / 日志区（699 → 105 行） |
| `docs/features/预设与调参键.md` | 新增：功能开发文档 |
| `docs/images/mapping-page.png` / `run-page.png` | 新增 / 更新：安装版截图 |
| `ps5kbm/ui_pages.py` | 映射页工具栏卡片化、列表行美化、条数显示 |
| `tests/test_config.py` | 新增：调参键默认 / 读写、预设名校验、删除用户预设 |
| `tests/test_input_source.py` | 新增：`adjust_action_for` 匹配与 `+` 别名 |
| `README.md` / `docs/使用说明.md` / `CHANGELOG.md` | 同步 |
| `installer.iss` / `ps5kbm/__init__.py` | 版本 0.2.2 |

## 9. 验证

- `python -m unittest discover -s tests` 全绿；
- 源运行：运行页点「+ 滚轮上」改键成键盘键，捕获后按键能调深度；映射页「另存为…」新建「测试预设」，
  下拉出现并可应用、删除；
- 截图确认映射页与运行页视觉；
- 打包 0.2.2 并更新 `app\`，启动安装版确认侧栏版本与功能。

## 10. 熵账本

**偿还**：把散在 `app.py` 的 `_on_wheel` / `_on_l2_adjust` 合并成一个 `_on_adjust`；映射页从 `ui_pages.py` 拆到
`mapping_ui.py`（ui_pages 699 → 105 行）；调参键默认值集中到 `config.TRIGGER_KEY_DEFAULTS`。

**新增**：`adjust_action_for` 的匹配顺序依赖 `_ADJUST_ORDER`（已写成显式顺序）；预设删除没有回收站（用户确认后才删）。

## 11. 实际结果（回填）

- 调参键：默认值与原行为一致（滚轮上/下、`=`/`-`），可改成键盘键 / 鼠标键 / 滚轮；`+` 仍兼容；
- 预设：映射页新增「另存为…」「删除」，「应用」保持不变；删掉正在使用的预设后启动不再报错；
- 映射页：预设与模式收进一张卡，列表改成圆角行 + 键名 chip + 动作描述（鼠标来源用强调色）+ 编辑 / ×，
  底部显示条数；映射页高度 778（与运行页 779 一致，日志区可见）；
- 测试：77 个单测全绿（新增 `test_config.py` / `test_input_source.py`）；13 项联动冒烟全通过；
- 打包：0.2.2 的 `dist\XY-CtoPS5`、`dist\XY-CtoPS5-Setup.exe`（ProductVersion 0.2.2）与 `app\` 已更新，
  安装版实测侧栏 `v0.2.2`、映射页 / 运行页布局正常。
