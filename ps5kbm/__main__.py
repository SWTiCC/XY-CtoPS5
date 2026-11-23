"""命令行入口：scan / pair / run / config。

用法：
    python -m ps5kbm scan
    python -m ps5kbm pair --host 192.168.1.50 --account-id <ID> --pin 12345678
    python -m ps5kbm run
    python -m ps5kbm config --init
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from . import __version__, bridge, config
from .bridge import ConsoleError
from .input_source import InputSource
from .mapping import InputMapper

TICK_SECONDS = 1.0 / 250.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ps5kbm",
        description="用键鼠控制 PS5：经 Remote Play 输入通道模拟 DualShock 4",
    )
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    parser.add_argument("--version", action="version", version=f"ps5kbm {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描局域网内的 PS5")
    scan.add_argument("--timeout", type=float, default=3.0)

    pair = sub.add_parser("pair", help="用 PSN Account ID 和 PS5 屏幕 PIN 配对")
    pair.add_argument("--host", required=True, help="PS5 的局域网 IP")
    pair.add_argument("--account-id", required=True, help="PSN Account ID（十进制或 Base64）")
    pair.add_argument("--pin", required=True, help="PS5 远程游玩屏幕上显示的 8 位 PIN")
    pair.add_argument("--out", default=config.DEFAULT_CREDENTIALS_PATH)

    run = sub.add_parser("run", help="连接 PS5 并开始键鼠映射")
    run.add_argument("--config", default=config.DEFAULT_CONFIG_PATH)

    login = sub.add_parser(
        "login", help="用浏览器登录 PSN，取出配对所需的 Account ID"
    )
    login.add_argument("--redirect", default="", help="直接粘贴跳转后的完整 URL")

    test_input = sub.add_parser(
        "test-input", help="测试鼠标位移采集（Raw Input）是否正常"
    )
    test_input.add_argument("--seconds", type=float, default=8.0)

    cfg = sub.add_parser("config", help="生成或查看配置")
    cfg.add_argument("--init", action="store_true", help="生成默认 config.json")
    cfg.add_argument("--print", action="store_true", help="打印合并后的配置")
    cfg.add_argument("--path", default=config.DEFAULT_CONFIG_PATH)
    return parser


async def _cmd_scan(args) -> int:
    devices = await bridge.discover(timeout=args.timeout)
    if not devices:
        print("没有发现 PS5。确认主机已开机、已启用远程游玩、与 PC 在同一网段。")
        return 1
    for row in devices:
        print(
            f"{row.get('host-name') or '?'}\t"
            f"{row.get('host-ip') or '?'}\t"
            f"{row.get('host-type') or '?'}\t"
            f"{row.get('host-id') or '?'}"
        )
    return 0


async def _cmd_pair(args) -> int:
    credentials = await bridge.pair(args.host, args.account_id, args.pin, args.out)
    print(f"配对成功：{credentials.get('host_name') or credentials['device_ip']}")
    print(f"凭据已写入：{args.out}")
    return 0


async def _cmd_login(args) -> int:
    """走 Sony OAuth 拿 PSN Account ID。

    这一步只跟索尼服务器打交道，不碰 PS5；拿到的 ID 再交给 pair。
    """
    from pyremoteplay.oauth import async_get_user_account, get_login_url

    redirect = args.redirect.strip()
    if not redirect:
        print("第 1 步：用浏览器打开下面的地址，登录你的 PSN 账号：")
        print(get_login_url())
        print()
        print("第 2 步：登录后会跳转到 remoteplay.dl.playstation.net 的地址（可能显示空白页）。")
        print("        把浏览器地址栏里的完整 URL 复制下来，粘贴到这里。")
        try:
            redirect = input("redirect URL: ").strip()
        except EOFError:
            print("没有收到 URL，已取消。", file=sys.stderr)
            return 1
    account = await async_get_user_account(redirect)
    if not account or not account.get("user_rpid"):
        print("登录失败：URL 无效、过期，或索尼接口拒绝了请求。", file=sys.stderr)
        return 1
    account_id = account["user_rpid"]
    print()
    print(f"PSN 在线 ID：{account.get('online_id', '?')}")
    print(f"Account ID：{account_id}")
    print()
    print("下一步：在 PS5 上打开 设置 → 系统 → 远程游玩 → 关联设备，拿到 8 位 PIN，然后执行：")
    print(f'  python -m ps5kbm pair --host <PS5的IP> --account-id {account_id} --pin <8位PIN>')
    return 0


def _cmd_test_input(args) -> int:
    """让用户移动鼠标，确认 Raw Input 能读到位移。"""
    from .raw_mouse import RawMouseReader

    total = {"dx": 0, "dy": 0, "events": 0}

    def on_delta(dx: int, dy: int) -> None:
        total["dx"] += dx
        total["dy"] += dy
        total["events"] += 1

    reader = RawMouseReader(on_delta)
    if not reader.start():
        print(f"Raw Input 启动失败：{reader.error}", file=sys.stderr)
        return 1
    print(f"Raw Input 已启动，请在 {args.seconds:g} 秒内移动鼠标……")
    time.sleep(args.seconds)
    reader.stop()
    print(f"收到 {total['events']} 个位移事件，累计 dx={total['dx']} dy={total['dy']}")
    if total["events"] == 0:
        print("没有收到位移：确认鼠标在移动，或该环境不允许 Raw Input。", file=sys.stderr)
        return 1
    print("Raw Input 工作正常。")
    return 0


def _cmd_config(args) -> int:
    if args.init:
        config.save_default_config(args.path)
        print(f"已生成默认配置：{args.path}")
        print("把 ps5_host 改成你的 PS5 地址，或直接用 credentials.json 里记录的地址。")
        return 0
    cfg = config.load_config(args.path)
    if args.print:
        print(
            f"预设={cfg.preset} 热键={cfg.hotkey} 切换模式={cfg.mode_switch.upper()} 鼠标灵敏度={cfg.mouse.sensitivity} "
            f"曲线={cfg.mouse.curve} 死区={cfg.mouse.deadzone}"
        )
        mode = cfg.modes.get(cfg.current_mode) or cfg.modes["default"]
        print(f"模式：{', '.join(cfg.modes)}（当前 {cfg.current_mode}）")
        print(f"键盘按钮映射={mode.keyboard_buttons}")
        print(f"鼠标按钮映射={mode.mouse_buttons}")
        print(f"键盘摇杆映射={mode.keyboard_sticks}")
        return 0
    print("请指定 --init 或 --print")
    return 1


async def _cmd_run(args) -> int:
    cfg = config.load_config(args.config)
    if not os.path.exists(cfg.credentials_path):
        print("还没有配对凭据。先执行：", file=sys.stderr)
        print("  run.cmd scan", file=sys.stderr)
        print("  run.cmd login", file=sys.stderr)
        print("  run.cmd pair --host <PS5的IP> --account-id <ID> --pin <8位PIN>", file=sys.stderr)
        return 1
    credentials = config.load_credentials(cfg.credentials_path)
    mapper = InputMapper(cfg)
    ps5 = bridge.Ps5Bridge(credentials)
    try:
        await ps5.connect()
    except (ConsoleError, OSError, TimeoutError) as exc:
        print(f"连接失败：{exc}", file=sys.stderr)
        print("排查：PS5 已开机、远程游玩已启用、同一网段、凭据未过期。", file=sys.stderr)
        return 1

    source = InputSource(mapper, hotkey=cfg.hotkey)
    source.start()
    print(f"已连接 {ps5.host}。按 {cfg.hotkey.upper()} 切换捕获，{cfg.mode_switch.upper()} 切换模式，Ctrl+C 退出。")
    last = time.perf_counter()
    was_capturing = False
    try:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            now = time.perf_counter()
            dt = now - last
            last = now
            if source.capturing:
                dx, dy = source.poll_mouse_delta()
                if dx or dy:
                    mapper.on_mouse_delta(dx, dy)
            elif was_capturing:
                # 关闭捕获时释放所有按下的按钮，避免主机上卡键
                ps5.send_events(mapper.release_all())
            was_capturing = source.capturing

            result = mapper.tick(dt)
            ps5.set_sticks(result.left, result.right)
            if result.events:
                ps5.send_events(result.events)
    except KeyboardInterrupt:
        print("\n正在退出……")
    finally:
        source.stop()
        await ps5.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    bridge.configure_logging(args.verbose)
    if args.command == "scan":
        return asyncio.run(_cmd_scan(args))
    if args.command == "pair":
        return asyncio.run(_cmd_pair(args))
    if args.command == "login":
        return asyncio.run(_cmd_login(args))
    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    if args.command == "test-input":
        return _cmd_test_input(args)
    return _cmd_config(args)


if __name__ == "__main__":
    raise SystemExit(main())
