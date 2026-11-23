"""重新生成 run 场景旁白：强调先选捕获窗口、再开始捕获。"""

import asyncio
import os

import edge_tts

PROJECT = r"E:\Code Project\CtoPS5"
OUTPUT_DIR = os.path.join(PROJECT, ".venv", "voice")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VOICE = "zh-CN-XiaoxiaoNeural"

LINES = [
    (
        "10_run.mp3",
        "进游戏之前来到运行页。注意顺序：先在下面选好捕获时要切到的窗口，再点开始捕获，或者直接按 F8。这样捕获一开始，画面窗口就会置顶，键鼠也完全交给 PS5。",
    ),
    (
        "12_run3.mp3",
        "扳机深度：R2 和 L2 各有一个滑条，设定按下时输出多深；右边是加深、减浅键，捕获过程中用鼠标滚轮就能调。",
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
