"""按用户确认的文案重新生成旁白（开场 / 玩法选择 / GTA6 设置两段）。"""

import asyncio
import os

import edge_tts

PROJECT = r"E:\Code Project\CtoPS5"
OUTPUT_DIR = os.path.join(PROJECT, ".venv", "voice")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VOICE = "zh-CN-XiaoxiaoNeural"

LINES = [
    (
        "01_intro.mp3",
        "PS5 映射键盘鼠标。这套开源方案把画面和输入拆成两路：画面走采集卡 HDMI 环出，输入走 Remote Play 通道，把键鼠伪装成手柄。现在新增 DualSense 直接接到电脑，可以用陀螺仪和自适应扳机。",
    ),
    (
        "03_modes.mp3",
        "打开程序第一件事，在连接页顶部选玩法。键盘：用键盘鼠标玩；手柄：把 DualSense 用 USB 或蓝牙接到电脑直通。注意连接之后需要更改则先断开再更改。",
    ),
    (
        "12_gta6_1.mp3",
        "GTA6 游戏内设置，瞄准与视角灵敏度，按这张图调整即可。",
    ),
    (
        "13_gta6_2.mp3",
        "战斗设置同样按图调整。用鼠标精确瞄准，不需要辅助瞄准。",
    ),
]


async def generate() -> None:
    for filename, text in LINES:
        path = os.path.join(OUTPUT_DIR, filename)
        communicate = edge_tts.Communicate(text, VOICE, rate="+0%")
        await communicate.save(path)
        print(f"生成: {filename} ({os.path.getsize(path) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(generate())
