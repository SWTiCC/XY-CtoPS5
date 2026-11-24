"""v4 重新生成开场旁白：开头只讲定位，不重复原理（原理由 02_diagram 单独讲）。"""

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
        "用键盘鼠标玩 PS5 游戏。XY-CtoPS5，开源免费。两种玩法：键鼠映射，或者 DualSense 手柄直通。",
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
