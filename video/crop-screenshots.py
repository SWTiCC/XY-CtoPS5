"""把 UI 截图裁到「纯窗口矩形」：去掉四周露出的桌面/阴影条带。

上一步 probe-edges.py 实测出的边界（原图像素坐标，left/upper/right/lower）：
- connect-unpaired-v3 / mapping-page-v3 / run-page-v3：左 10 · 上 2 · 右 1419 · 下 1173
- connect-quick-v3：左 0 · 上 0 · 右 1408 · 下 1171
- controller-page：左 0 · 上 2 · 右 1390 · 下 1187

Python 进程只能写 .venv，所以先输出到 .venv/cropped/，再由 PowerShell 复制。
"""

import os

from PIL import Image

SRC_DIR = r"E:\Code Project\CtoPS5\video\public\images"
OUT_DIR = r"E:\Code Project\CtoPS5\.venv\cropped"

# 文件名 → (left, upper, right, lower)，None 表示取整张
CROPS = {
    "connect-unpaired-v3.png": (10, 2, 1419, 1173),
    "connect-quick-v3.png": None,
    "mapping-page-v3.png": (10, 2, 1419, 1173),
    "run-page-v3.png": (10, 2, 1419, 1173),
    "controller-page.png": (0, 2, 1390, 1187),
}


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, box in CROPS.items():
        src = os.path.join(SRC_DIR, name)
        if not os.path.exists(src):
            print(f"缺失: {name}")
            continue
        im = Image.open(src).convert("RGB")
        out = im if box is None else im.crop(box)
        dst = os.path.join(OUT_DIR, name)
        out.save(dst, "PNG", optimize=True)
        print(f"{name}: {im.size[0]}x{im.size[1]} -> {out.size[0]}x{out.size[1]}")


if __name__ == "__main__":
    main()
