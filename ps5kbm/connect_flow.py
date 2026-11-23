"""连接页的纯逻辑：显示哪套视图、按钮是否可用、状态文案。

只做判断与拼文案，不 import tkinter、不碰网络与文件，所以可以直接单测。
界面层（connect_ui.py）只按这里给出的结论摆放控件，业务编排在 app.py。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 视图
VIEW_QUICK = "quick"  # 已配对：主机身份 + 直接连接 / 换 ID 连接
VIEW_FULL = "full"  # 首次使用：扫描 / 配对 / 连接完整流程

# ---------------------------------------------------------------- 检测状态
STATE_CHECKING = "checking"  # 正在检测局域网
STATE_ONLINE = "online"  # 已配对主机在线，可直接连接
STATE_OFFLINE = "offline"  # 局域网里没找到已配对主机
STATE_UNPAIRED = "unpaired"  # 没有保存的配对凭据
STATE_ERROR = "error"  # 检测本身出错（超时 / 网络异常）

# 语气：界面层负责映射成 theme 里的颜色
TONE_OK = "ok"
TONE_WARN = "warn"
TONE_ERR = "err"
TONE_DIM = "dim"


@dataclass(frozen=True)
class PairedConsole:
    """从 credentials.json 提炼出的「已配对主机」摘要。"""

    host_id: str = ""
    host_name: str = ""
    host_ip: str = ""
    account_id: str = ""
    device_type: str = "PS5"

    @property
    def display_name(self) -> str:
        """界面标题：优先主机名，其次 IP。"""
        return self.host_name.strip() or self.host_ip.strip() or "已配对主机"

    @property
    def type_label(self) -> str:
        return (self.device_type or "PS5").upper()


@dataclass(frozen=True)
class QuickView:
    """快捷视图要显示的内容与按钮可用性。"""

    title: str
    subtitle: str
    status_text: str
    tone: str
    can_connect: bool
    can_disconnect: bool
    can_recheck: bool


def _account_from_profiles(profiles: object) -> str:
    """凭据里的账号兜底：取第一个 profile 的 id（Base64 Account ID）。"""
    if not isinstance(profiles, dict):
        return ""
    for row in profiles.values():
        if isinstance(row, dict) and row.get("id"):
            return str(row["id"])
    return ""


def summarize_credentials(raw: dict | None) -> PairedConsole | None:
    """凭据字典 → 摘要；缺主机地址或缺注册档时返回 None（视为未配对）。

    `profiles` 是真正能建立会话的注册信息，只有 `device_ip` 而没 `profiles`
    的旧文件没法连接，所以这里一并要求存在。
    """
    if not isinstance(raw, dict):
        return None
    host_ip = str(raw.get("device_ip") or "").strip()
    profiles = raw.get("profiles")
    if not host_ip or not isinstance(profiles, dict) or not profiles:
        return None
    account_id = str(raw.get("account_id_input") or "").strip()
    return PairedConsole(
        host_id=str(raw.get("host_id") or ""),
        host_name=str(raw.get("host_name") or ""),
        host_ip=host_ip,
        account_id=account_id or _account_from_profiles(profiles),
        device_type=str(raw.get("device_type") or "PS5"),
    )


def initial_view(paired: PairedConsole | None) -> str:
    """启动时的初始视图：有钱（已配对）走快捷，没有走完整流程。"""
    return VIEW_QUICK if paired is not None else VIEW_FULL


def view_for_state(state: str) -> str:
    """检测结果对应的视图：检测中 / 在线留在快捷；其余回完整流程。"""
    return VIEW_QUICK if state in (STATE_CHECKING, STATE_ONLINE) else VIEW_FULL


def _subtitle(paired: PairedConsole) -> str:
    parts = [paired.type_label, paired.host_ip]
    if paired.account_id:
        parts.append(f"账号 {paired.account_id}")
    return " · ".join(part for part in parts if part)


def describe(
    paired: PairedConsole | None,
    state: str,
    *,
    connected: bool = False,
    connected_host: str = "",
    connecting: bool = False,
    probe_error: str = "",
    connect_error: str = "",
) -> QuickView:
    """快捷视图的文案与按钮状态。

    判定顺序有讲究：正在连接 / 已连接优先于历史检测结论，
    因为这两个状态决定用户此刻能点哪个按钮。
    """
    console = paired or PairedConsole()
    title = console.display_name
    subtitle = _subtitle(console) if paired is not None else "还没有配对的 PS5"

    if connecting:
        return QuickView(
            title, subtitle, "正在建立 Remote Play 会话……", TONE_WARN,
            can_connect=False, can_disconnect=False, can_recheck=False,
        )
    if connected:
        address = connected_host or console.host_ip
        return QuickView(
            title, subtitle, f"已连接 · {address}", TONE_OK,
            can_connect=False, can_disconnect=True, can_recheck=False,
        )
    if connect_error:
        return QuickView(
            title, subtitle, f"连接失败：{connect_error}", TONE_ERR,
            can_connect=True, can_disconnect=False, can_recheck=True,
        )
    if state == STATE_ERROR:
        detail = probe_error or "未知错误"
        # 检测失败不代表主机连不上（超时、本地端口被占用等都会走到这里），
        # 所以照样允许直接连接，别把用户堵在门口。
        return QuickView(
            title, subtitle, f"检测失败：{detail}（仍可尝试直接连接）", TONE_ERR,
            can_connect=True, can_disconnect=False, can_recheck=True,
        )
    if state == STATE_CHECKING:
        return QuickView(
            title, subtitle, "正在检测局域网里的已配对主机……", TONE_DIM,
            can_connect=False, can_disconnect=False, can_recheck=False,
        )
    if state == STATE_ONLINE:
        return QuickView(
            title, subtitle, "已配对主机在线，可直接连接", TONE_OK,
            can_connect=True, can_disconnect=False, can_recheck=True,
        )
    # 离线 / 未配对：都不允许直接连接
    return QuickView(
        title, subtitle, "未在当前局域网发现该主机", TONE_WARN,
        can_connect=False, can_disconnect=False, can_recheck=True,
    )


def full_notice(paired: PairedConsole | None, state: str, probe_error: str = "") -> str:
    """完整流程视图顶部的提示语；空字符串表示不显示提示卡。"""
    if paired is None:
        return ""
    name = paired.display_name
    if state == STATE_ERROR:
        detail = probe_error or "未知错误"
        return (
            f"检测已配对主机「{name}」时出错：{detail}。"
            "点「重新检测」重试，或走下面的流程重新配对。"
        )
    if state == STATE_OFFLINE:
        return (
            f"没找到已配对主机「{name}」（上次 {paired.host_ip}）。"
            "确认 PS5 已开机、远程游玩已启用、与 PC 同网段，再点「重新检测」或走下面的流程。"
        )
    if state == STATE_ONLINE:
        return f"已配对主机「{name}」在线，可直接连接；想换主机请走下面的流程重新配对。"
    if state == STATE_CHECKING:
        return f"正在检测已配对主机「{name}」……"
    return ""
