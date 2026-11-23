# 运行页布局重排 + 0.2.1 打包（2026-11-23）

## 1. 边界：做 / 不做

**做**：

- 重排「运行」页：所有控件一屏放得下，底部日志区不再被挤没，曲线下拉不再被右边缘裁掉。
- 版本号统一为 `0.2.1`：包内 `__version__`、侧栏显示、`--version`、安装包 `AppVersion`、CHANGELOG。
- 重新打包 `dist\XY-CtoPS5`（onedir）、`dist\XY-CtoPS5-Setup.exe`，并刷新桌面快捷方式指向的程序目录 `app\`。

**不做**：

- 不改任何运行逻辑 / 映射逻辑 / 手柄发送逻辑，只动布局与版本号。
- 不把安装位置迁到 `%LOCALAPPDATA%`：现在桌面快捷方式指向 `E:\Code Project\CtoPS5\app\XY-CtoPS5.exe`，
  程序会向上找到项目根的 `credentials.json` 复用配对；换目录会让用户重新配对。
- 不引入滚动画布（整页滚动会与映射页的内嵌滚动列表抢滚轮）。

## 2. 约束与复用

- 复用 `ui_widgets` 的卡片 / 按钮 / 字体封装与 `theme` token；新增 `divider()`、`switch()` 两个通用小组件。
- 控件变量名与回调全部保持不变（`app._apply_*` / `_toggle_*`），app.py 只改一行 `build_run_page` 的引用。
- 阈值：新文件 ≤300 行；`ui_pages.py` 从 699 行降到 297 行（运行页迁出）。

## 3. 架构：模块、依赖方向、公开接口

```
app.py
  └── run_ui.py           运行页骨架：状态区 / 捕获目标 / 底部提示
        └── run_tuning_ui.py  手感调参区：鼠标三列滑条 + 扳机两行
              └── {theme, ui_widgets}
ui_pages.py               顶栏 / 侧栏 / 映射页 / 日志区（运行页已迁出）
```

依赖方向：`run_ui → run_tuning_ui → {theme, ui_widgets}`；无循环。

## 4. 契约

- `run_ui.build_run_page(app, parent)` 创建运行页，仍然负责这些属性：
  `_run_title` / `_run_subtitle` / `_capture_button` / `_topmost_var` / `_stick_value_label` /
  `_input_state_label` / `_stick_state_label` / `_target_var` / `_target_box`。
- `run_tuning_ui.build_mouse_tuning / build_triggers` 负责：
  `_stick_ramp_var/_label`、`_deadzone_*`、`_sens_*`、`_slow_sens_*`、`_fast_sens_*`、`_smoothing_*`、
  `_curve_var`、`_mouse_enabled_var`、`_flick_var`、`_r2_*`、`_l2_*`。
- 所有滑条仍绑定「松开才写盘」(`app._commit_sliders`)。

## 5. 数据与状态

无新增持久化字段；`config.json` / `tuning.json` 格式不变。

## 6. 失败与边界

- 窗口高度不够时由 Tk 自行裁剪，不再出现"页面把日志区挤成 0 高"的情况（页面请求高度从 902 降到 779，
  日志区保留约 3 行可见）；映射页仍是内部列表滚动。
- 松开滑条仍会写盘；测试脚本用 `app._persist = lambda: None` 避免污染用户配置。

## 7. 演进与扩展点

- 再加运行页控件时优先在三列网格里加一格，不新增整行；超过一屏再考虑分栏或整页滚动。
- `divider()` / `switch()` 已进 `ui_widgets`，其他页面可直接复用。

## 8. 改动清单

| 文件 | 动作 |
|---|---|
| `ps5kbm/run_ui.py` | 新增：运行页骨架 |
| `ps5kbm/run_tuning_ui.py` | 新增：手感调参区（鼠标 + 扳机） |
| `ps5kbm/ui_pages.py` | 修改：删除运行页（699 → 297 行） |
| `ps5kbm/ui_widgets.py` | 修改：新增 `divider` / `switch` |
| `ps5kbm/app.py` | 修改：运行页改用 `run_ui` |
| `ps5kbm/__init__.py` | 修改：`__version__ = 0.2.1` |
| `installer.iss` | 修改：`AppVersion 0.2.1` |
| `CHANGELOG.md` / `README.md` | 修改：0.2.1 记录、版本引用 |
| `docs/images/run-page.png` | 新增：运行页截图 |

## 9. 验证

- `python -m unittest discover -s tests` 全绿；`python -m ps5kbm --version` 输出 `ps5kbm 0.2.1`；
- 运行页实测高度 779（旧版 902），日志区可见；
- 冒烟脚本调用运行页全部更新函数（17 项）无缺失控件；
- 打包后启动 `app\XY-CtoPS5.exe`，确认侧栏 `v0.2.1`、运行页布局、连接页功能正常。

## 10. 熵账本

**偿还**：`ui_pages.py` 从 699 行降到 297 行；运行页拆成两个各 ≤300 行的模块；`curve_label` 随运行页迁走，消除重复定义。

**新增**：`ui_widgets` 多了两个小组件（可复用）；运行页仍是固定布局，若再加控件需要重新算高度。

## 11. 实际结果（回填）

- 运行页页面请求高度 902 → 779（物理像素，150% 缩放下），日志区从"被挤没"恢复到约 3 行；
- 滑条改三列网格后曲线下拉不再被右边缘裁掉；
- 版本 0.2.1 统一到 `__version__` / 侧栏 / `--version` / `installer.iss` / CHANGELOG；
- 打包结果：
  - `dist\XY-CtoPS5\XY-CtoPS5.exe`（onedir，21:05）
  - `dist\XY-CtoPS5-Setup.exe`（Inno Setup，ProductVersion 0.2.1，20.4 MB）
  - `app\XY-CtoPS5.exe` 已更新（桌面快捷方式仍指向它，复用项目根 `credentials.json`，不用重新配对）
- 实测：安装版（`app\XY-CtoPS5.exe`）启动后侧栏显示 `v0.2.1`，连接页自动检测到 `PS5Pro-Yi` 在线，
  切到运行页布局正常、日志区可见。
- 未做：没有把程序装到 `%LOCALAPPDATA%\XY-CtoPS5`（会让已有配对失效）；安装包留给新机器/分发用。
