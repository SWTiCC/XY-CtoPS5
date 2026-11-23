"""临时脚本：生成 ps5kbm.ico 应用图标（用 bundled Python 的 Pillow）。"""

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 深色圆角底
draw.rounded_rectangle((6, 6, SIZE - 6, SIZE - 6), radius=58, fill=(24, 24, 24, 255))
# 蓝色圆角底衬（镜头感的内层）
draw.rounded_rectangle((26, 26, SIZE - 26, SIZE - 26), radius=44, fill=(31, 31, 31, 255))

# 手柄主体
BLUE = (59, 130, 246, 255)
draw.rounded_rectangle((46, 92, SIZE - 46, 178), radius=43, fill=BLUE)
draw.rounded_rectangle((38, 100, 82, 202), radius=22, fill=BLUE)
draw.rounded_rectangle((SIZE - 82, 100, SIZE - 38, 202), radius=22, fill=BLUE)

# 左摇杆
draw.ellipse((74, 112, 118, 156), fill=(237, 237, 237, 255))
draw.ellipse((85, 123, 107, 145), fill=(24, 24, 24, 255))
# 右侧四键
for cx, cy in ((160, 120), (184, 144), (160, 168), (136, 144)):
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(237, 237, 237, 255))

# 底部连笔：一条横线让手柄更像“托着”
draw.rounded_rectangle((104, 196, 152, 202), radius=3, fill=(59, 130, 246, 200))

img.save(
    r"E:\Code Project\Other\ps5-kbm\ps5kbm.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("icon saved")
