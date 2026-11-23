"""设计 token：颜色、字号、间距、圆角、字体。

来源：`E:\\Code Project\\Other\\前端设计规范.md` 第 2 章视觉系统。

桌面端映射说明（有意偏离，理由如下）：
- 规范字体白名单（Geist / Manrope / Geist Mono / Poppins）不含中文字形，
  桌面界面改用系统中文界面字体，保证中文可读性；
- 颜色只使用规范给出的暗色背景板 + 一个强调色，不引入渐变；
- 字号 / 间距 / 圆角严格取规范阶梯。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 颜色
BG = "#181818"  # 窗口背景
SURFACE = "#1F1F1F"  # 卡片
SURFACE_HOVER = "#272727"  # 输入框 / 悬浮态
BORDER = "#313131"  # 分隔线、边框
TEXT = "#EDEDED"  # 主文字
TEXT_DIM = "#9B9B9B"  # 次要文字
TEXT_FAINT = "#6E6E6E"  # 弱化说明

ACCENT = "#3B82F6"  # 强调色（按钮背景）
ACCENT_HOVER = "#2E6FDD"
ACCENT_SOFT = "#1D3557"  # 选中态背景

OK = "#22C55E"
WARN = "#F59E0B"
ERR = "#EF4444"
CAPTURE = "#60A5FA"

# ---------------------------------------------------------------- 字号（px）
XS = 12
SM = 14
BASE = 16
LG = 18
XL = 20
XXL = 24
XXXL = 30

# ---------------------------------------------------------------- 间距（px）
S1 = 4
S2 = 8
S3 = 12
S4 = 16
S6 = 24
S8 = 32

# ---------------------------------------------------------------- 圆角（px）
R_XS = 4
R_SM = 6
R_MD = 8
R_LG = 12
R_XL = 16

# ---------------------------------------------------------------- 字体
FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

WINDOW_WIDTH = 940
WINDOW_HEIGHT = 760
SIDEBAR_WIDTH = 188
