"""用 Edge TTS 生成教程旁白（连接 / 映射 / 运行）。

Python 进程在当前沙箱下只能写 .venv，所以输出到 .venv/voice/，
再由 PowerShell 复制到 video/public/voice/。
"""

import asyncio
import os

import edge_tts

PROJECT = r"E:\Code Project\CtoPS5"
OUTPUT_DIR = os.path.join(PROJECT, ".venv", "voice")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VOICE = "zh-CN-XiaoxiaoNeural"

LINES = [
    # 连接教程
    ("06_connect.mp3", "第一次使用，进连接页：填 PS5 的局域网 IP，也可以直接点扫描局域网，从列表里选。再填 PSN Account ID 和 PS5 屏幕上显示的八位 PIN，点配对。"),
    ("07_connect2.mp3", "配对成功后，程序会记住这台主机。以后启动时自动检测它是否在线，只要在同一个网络里，点一下直接连接就能建立输入通道，不用再填任何东西。PS5 重启后 IP 变了也没关系，程序会按主机身份自动找回。"),
    # 映射教程
    ("08_mapping.mp3", "映射页负责所有键位。最上面是预设，一套预设就是一套完整的按键方案，选中即生效。一个预设内部可以有多套模式，运行时用一个键循环切换。"),
    ("09_mapping2.mp3", "每一条映射，左边是键，右边是手柄动作。可以改键、编辑、或者删除。除了单按钮，还支持组合键和序列宏。左摇杆的方向键在下面单独编辑，还能绑定幅度切换。所有改动都会即时自动保存。"),
    # 运行教程
    ("10_run.mp3", "进游戏之前来到运行页。连接成功后点开始捕获，或者直接按 F8，键鼠就完全交给 PS5，鼠标指针会隐藏，退出再按一次 F8。"),
    ("11_run2.mp3", "这一屏是手感调节：过渡、死区、灵敏度、慢灵敏、快灵敏、平滑，拖动实时生效，松开自动保存。觉得小移动拖不动，就把反死区调大一点。"),
    ("12_run3.mp3", "扳机深度：R2 和 L2 各有一个滑条，设定按下时输出多深；右边是加深、减浅键，捕获过程中用鼠标滚轮就能调。下面选择捕获时自动切过去的窗口。"),
    ("13_run4.mp3", "全部调好之后，按 F8 开始玩。这一套就是完整的流程，遇到问题可以看 GitHub 上的使用说明和排障文档。"),
]


async def generate() -> None:
    for filename, text in LINES:
        path = os.path.join(OUTPUT_DIR, filename)
        communicate = edge_tts.Communicate(text, VOICE, rate="+0%")
        await communicate.save(path)
        print(f"生成: {filename} ({os.path.getsize(path) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(generate())
