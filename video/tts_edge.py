"""用 Edge TTS 神经网络语音生成视频旁白。

注意：Python 进程在当前沙箱下只能写 .venv 目录，
所以先输出到 .venv/voice/，再由 PowerShell 复制到 video/public/voice/。
"""

import asyncio
import os

import edge_tts

PROJECT = r"E:\Code Project\CtoPS5"
OUTPUT_DIR = os.path.join(PROJECT, ".venv", "voice")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 女声 XiaoxiaoNeural 自然清晰，适合技术介绍
VOICE = "zh-CN-XiaoxiaoNeural"

LINES = [
    ("01_intro.mp3", "PS5 不支持键盘鼠标？用采集卡看画面，用远程游玩通道发输入。"),
    ("02_diagram.mp3", "画面走采集卡的 HDMI 环出，几乎没有延迟；输入走远程游玩的输入通道，把键鼠伪装成一个虚拟手柄。"),
    ("03_mouse.mp3", "鼠标到右摇杆的手感，照着业界成熟方案做：Raw Input 读设备报文，反死区解决小移动拖不动，两段灵敏度兼顾瞄准和转身，还有 Flick Stick 快速转身。"),
    ("04_features.mp3", "支持多套按键映射，一个键循环切换；左右扳机可以设定按压深度；所有参数实时调，改完就保存。"),
    ("05_outro.mp3", "开源免费，在 GitHub 搜索 XY-CtoPS5。发行版只需一个安装程序。"),
]


async def generate() -> None:
    for filename, text in LINES:
        path = os.path.join(OUTPUT_DIR, filename)
        communicate = edge_tts.Communicate(text, VOICE, rate="+0%")
        await communicate.save(path)
        print(f"生成: {filename} ({os.path.getsize(path) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(generate())
