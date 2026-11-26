# 视频数据导出（给其他工作流用）

本目录由 `video/export-video-data.mjs` 生成，**只读工程、不改工程**。
工程里任何一处改动后重新导出：

```powershell
cd "E:\Code Project\CtoPS5\video"
node export-video-data.mjs
```

## 四个文件分别是什么

| 文件 | 给谁看 | 内容 |
|---|---|---|
| `video-data.json` | 程序 / AI | 14 段完整数据：起止帧、旁白文案与音频路径、截图与标注框、音效落点、配色、时间规则 |
| `分镜表.md` | 人 | 时间轴表格 + 每段画面动作 + 每个标注框的 0–1 比例坐标 |
| `字幕.srt` | 剪辑软件 | 段级旁白字幕（标准 SRT 时码 `HH:MM:SS,mmm`） |
| `素材清单.md` | 人 | 素材路径/尺寸/时长/文案来源 + 音效落点表 + 配色表 |

## 关键数据在哪（video-data.json）

```
meta            1920×1080 @ 30fps，6232 帧，207.73 秒
scenes[]        index / key / from / to / duration（帧）/ kind / title / subtitle
                screenshot-scan 段还有 image 和 targets[]
                targets[]: { x, y, w, h, head, detail }  ← x/y/w/h 是相对截图的 0–1 比例
assets.images[] file / 绝对路径 / 像素尺寸 / usedBy
assets.voice[]  绝对路径 / 秒 / 帧 / 文案 / 文案出处（哪个 tts 脚本）
sfxTimeline[]   帧 + 文件 + 音量 + 归属段
palette         七个色值；fonts.sans / fonts.mono
timingRules     时长推导规则 + 扫描镜头的时间参数
```

**所有 `absPath` 都是本机绝对路径**，换机器时需要重映射到新的工程目录。

## 换到别的工作流时要注意

**坐标可以直接用**：所有帧坐标都是 1920×1080，与 `raea`、Remotion、AE 的合成坐标一致。
截图窗固定为 `x=520, y=72, w=1120, h=933`（见 `screenshotWindow`）。

**raea 的地板比 Remotion 严**（按本机 AGENTS.md）：

- 文字不许进 16:9 上下 120px 安全区 —— 现有左栏标题从 `y=92` 起，移植时需要整体下移或缩小
- 小字对比度 ≥ 3:1 —— 右栏竖排 HUD（`alpha(CYAN, 0.42)`）在 raea 里会被判低对比
- 末帧才出现的文字不算读到 —— 片尾三行信息在 raea 里要提前落定

**字体**：本机没有 Inter。中文用 `Microsoft YaHei`，西文无衬线用 `Segoe UI`，等宽用 `Cascadia Mono` / `Consolas`。

**时间轴不要手抄**：`duration = 实测旁白帧数 + 余量`，余量在教程段是 33~36 帧。
改了任何一句旁白都要重新测时长再排，否则就会出现「话没说完就切镜头」——
这也是这版视频返工过两次的原因。工程的 `verify-timeline.mjs` 就是干这个的，
移植时建议把同样的校验搬过去。

## 已知缺口

- **`voice/08_controller.mp3` 的原文文案没留档**（当时那次 TTS 的脚本没保存）。
  JSON 里给了 `textSuggested`，是按画面重写的**建议文案，不是原文**。
  要恢复原文只能听音频；要改这句就得重新 TTS 并重排这一段。
- **GTA6 两段的截图是游戏内设置界面**，不是本程序界面；换工作流时这两段按「整图展示」处理即可。

## 源工程在哪

```
E:\Code Project\CtoPS5\video\
  src\ps5\timeline.ts    时间轴（段顺序 / 旁白帧数 / 音频映射）
  src\ps5\Main.tsx       各场景实现（背景 / 开场 / 原理图 / 截图段 / 整图段 / 结尾）
  src\ps5\ScanShot.tsx   截图取景镜头（扫描线 / 取景框 / 编号徽章 / 左栏面板）
  src\ps5\theme.ts       配色与字体
  public\images\         7 张截图
  public\voice\          14 条旁白 mp3
  public\audio\          BGM + 11 个音效
  out\promo.mp4          成片（3 分 27 秒）
```

> 注意：`video/` 目录已被 `.gitignore` 排除，不随仓库上传，换机器需要单独拷贝。
