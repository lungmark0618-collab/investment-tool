"""ntfy.sh push notification integration."""
import json
from pathlib import Path
from typing import Optional
import urllib.request

CONFIG_PATH = Path(__file__).parent.parent / "data" / "config.json"
DEFAULT_SERVER = "https://ntfy.sh"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_topic() -> Optional[str]:
    return (load_config().get("ntfy_topic", "") or "").strip() or None


def set_topic(topic: str):
    cfg = load_config()
    cfg["ntfy_topic"] = topic.strip()
    save_config(cfg)


def get_server() -> str:
    return (load_config().get("ntfy_server", "") or "").strip() or DEFAULT_SERVER


def set_server(server: str):
    cfg = load_config()
    cfg["ntfy_server"] = server.strip() or DEFAULT_SERVER
    save_config(cfg)


def get_scan_times() -> list:
    """Return list of HH:MM strings."""
    cfg = load_config()
    return cfg.get("scan_times") or ["09:00", "13:30", "21:30"]


def set_scan_times(times: list):
    cfg = load_config()
    cfg["scan_times"] = sorted(set(t.strip() for t in times if t.strip()))
    save_config(cfg)


def get_dedup_hours() -> int:
    return int(load_config().get("dedup_hours", 24))


def set_dedup_hours(hours: int):
    cfg = load_config()
    cfg["dedup_hours"] = int(hours)
    save_config(cfg)


def get_signal_filter() -> dict:
    """Which signals to notify on."""
    cfg = load_config().get("signals", {})
    return {
        "add": cfg.get("add", True),
        "reduce": cfg.get("reduce", True),
    }


def set_signal_filter(add: bool, reduce: bool):
    cfg = load_config()
    cfg["signals"] = {"add": bool(add), "reduce": bool(reduce)}
    save_config(cfg)


def send(message: str, topic: Optional[str] = None, title: Optional[str] = None,
         priority: str = "default", tags: Optional[str] = None) -> tuple[bool, str]:
    """
    Send a ntfy.sh push notification.
    Returns (success: bool, detail: str).
    """
    topic = topic or get_topic()
    if not topic:
        return False, "未設定 ntfy 主題（Topic）"

    server = get_server().rstrip("/")
    url = f"{server}/{topic}"

    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if title:
        headers["Title"] = title.encode("utf-8").decode("latin-1", errors="ignore") \
            if all(ord(c) < 256 for c in title) else title
        # ntfy supports UTF-8 in headers if encoded properly; fall back to raw
        try:
            title.encode("ascii")
        except UnicodeEncodeError:
            # encode non-ASCII titles for header transport
            import base64
            headers["Title"] = "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?="
    if priority and priority != "default":
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags

    try:
        data = message.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                return True, "通知已送出"
            return False, f"ntfy 回應狀態：{resp.status}"
    except Exception as e:
        return False, f"發送失敗：{e}"


def build_message(symbol: str, trigger: str, data: dict) -> tuple[str, str]:
    """Build a formatted ntfy message. Returns (title, body)."""
    fund = data.get("fundamental", {})
    risk = data.get("risk", {})
    val = data.get("valuation", {})
    pos = data.get("position", {})
    alloc = data.get("allocation", {})

    price_info = data.get("current_price_str", "")

    title = f"{'🔔 補倉訊號' if trigger == 'add' else '⚠️ 減碼訊號'} — {symbol}"

    lines = []
    if price_info:
        lines.append(f"股價：{price_info}")
    lines += [
        f"基本面：{fund.get('total_score', 'N/A')}/100  {fund.get('grade', '')}",
        f"風險：{risk.get('level', 'N/A')}",
        f"估值：{val.get('status', 'N/A')}",
        f"建議操作：{pos.get('action', 'N/A')}",
    ]
    if alloc.get("invest_amount") is not None:
        lines.append(f"建議投入：NT${alloc['twd_invest']:,.0f}（{alloc['invest_ratio']*100:.0f}%）")
    if pos.get("rules"):
        lines.append("")
        lines.append("觸發條件：")
        for r in pos["rules"][:3]:
            lines.append(f"• {r}")
    return title, "\n".join(lines)
