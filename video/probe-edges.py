"""量出每张截图里「桌面残留 → 窗口」的精确分界，供视频裁剪用。

输出：每张图中间行左右各 60px、中间列上下各 40px 的像素 RGB，
以及判定出的窗口矩形（连续的、方差小的深色区域）。
"""

import os

from PIL import Image

IMG_DIR = r"E:\Code Project\CtoPS5\video\public\images"
TARGETS = [
    "connect-unpaired-v3.png",
    "connect-quick-v3.png",
    "mapping-page-v3.png",
    "run-page-v3.png",
    "controller-page.png",
]


def luminance(px):
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def scan_edge(pixels, label):
    """打印每个位置的亮度，找桌面条带的边界。"""
    vals = [f"{int(luminance(p)):3d}" for p in pixels]
    print(f"    {label}: " + " ".join(vals))


for name in TARGETS:
    path = os.path.join(IMG_DIR, name)
    if not os.path.exists(path):
        print(f"缺失: {name}")
        continue
    im = Image.open(path).convert("RGB")
    w, h = im.size
    print(f"\n=== {name}  {w}x{h} ===")
    mid_y = h // 2
    mid_x = w // 2
    scan_edge([im.getpixel((x, mid_y)) for x in range(0, 60)], "左 x0..59 ")
    scan_edge([im.getpixel((x, mid_y)) for x in range(w - 60, w)], "右 xw-60..")
    scan_edge([im.getpixel((mid_x, y)) for y in range(0, 40)], "上 y0..39 ")
    scan_edge([im.getpixel((mid_x, y)) for y in range(h - 40, h)], "下 yh-40..")
