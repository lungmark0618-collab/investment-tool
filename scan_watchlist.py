"""自選清單背景掃描腳本

由 Windows 工作排程器定時呼叫。
對每檔自選股票跑完整分析，只在觸發訊號時推播 ntfy 通知。
同一檔股票同一訊號在 dedup_hours 小時內不重複通知。
"""
import sys
import io
import traceback
from datetime import datetime
from pathlib import Path

# 強制 UTF-8 輸出，避免 cp950 編碼錯誤
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))

from utils.data_fetcher import fetch_ticker, get_all_data, get_fx_rate
from utils.notifier import (
    send, build_message, get_topic, get_dedup_hours,
    get_signal_filter,
)
from modules import fundamental, risk, valuation, allocation, position, market_regime
from database.db import (
    get_watchlist, save_analysis,
    was_recently_notified, log_notification,
    get_avg_cost,
)

LOG_PATH = Path(__file__).parent / "data" / "scan.log"


def log(msg: str):
    LOG_PATH.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def analyze_symbol(symbol: str, cost_basis: float = 0.0,
                   monthly_budget_twd: float = 10000.0,
                   market_mult: float = 1.0,
                   market_label: str = None) -> dict:
    """Run full analysis pipeline for one symbol. Returns full result dict."""
    ticker, used_sym = fetch_ticker(symbol)
    if ticker is None:
        return None
    data = get_all_data(ticker)
    info = data["info"]

    fund_result = fundamental.calculate(data)
    risk_result = risk.calculate(data)
    val_result = valuation.calculate(data)

    # FX conversion
    stock_ccy = info.get("currency", "TWD")
    budget_local = monthly_budget_twd
    if stock_ccy not in ("TWD", ""):
        fx = get_fx_rate("TWD", stock_ccy)
        if fx:
            budget_local = monthly_budget_twd * fx

    alloc_result = allocation.calculate(
        monthly_budget=budget_local,
        valuation_status=val_result["status"],
        ma200_bias=val_result.get("ma200_bias"),
        risk_level=risk_result["level"],
        fundamental_score=fund_result["total_score"],
        market_mult=market_mult,
        market_regime=market_label,
    )
    alloc_result["twd_budget"] = monthly_budget_twd
    alloc_result["twd_invest"] = alloc_result["invest_ratio"] * monthly_budget_twd

    cur_price = (info.get("currentPrice") or info.get("regularMarketPrice")
                 or info.get("previousClose") or 0)

    pos_result = position.calculate(
        fundamental_score=fund_result["total_score"],
        risk_level=risk_result["level"],
        valuation_status=val_result["status"],
        ma200_bias=val_result.get("ma200_bias"),
        cost_basis=float(cost_basis) if cost_basis and cost_basis > 0 else None,
        current_price=cur_price if cur_price else None,
    )

    price_str = f"{cur_price:,.2f} {stock_ccy}".strip()

    return {
        "symbol": used_sym,
        "current_price_str": price_str,
        "fundamental": fund_result,
        "risk": risk_result,
        "valuation": val_result,
        "allocation": alloc_result,
        "position": pos_result,
    }


def main():
    log("=" * 60)
    log("開始掃描自選清單")

    topic = get_topic()
    if not topic:
        log("未設定 ntfy topic，結束")
        return 1

    watchlist = get_watchlist()
    if not watchlist:
        log("自選清單為空，結束")
        return 0

    dedup_h = get_dedup_hours()
    signals = get_signal_filter()
    log(f"自選 {len(watchlist)} 檔 / 去重 {dedup_h}h / 訊號 {signals}")

    # 大盤狀態先抓一次
    try:
        regime = market_regime.analyze()
        mkt_mult = regime.get("budget_multiplier", 1.0) if regime.get("available") else 1.0
        mkt_label = regime.get("regime") if regime.get("available") else None
        log(f"市場狀態：{mkt_label} ×{mkt_mult}")
    except Exception as e:
        log(f"取得大盤狀態失敗：{e}")
        mkt_mult, mkt_label = 1.0, None

    triggered_count = 0
    for item in watchlist:
        sym = item["symbol"]
        # 優先用交易紀錄推算的加權平均成本；無紀錄則退回 watchlist.cost_basis
        cost = get_avg_cost(sym) or item.get("cost_basis") or 0.0
        try:
            result = analyze_symbol(sym, cost_basis=cost,
                                    market_mult=mkt_mult, market_label=mkt_label)
            if not result:
                log(f"{sym}：抓取失敗")
                continue

            save_analysis(sym, result)
            pos = result["position"]
            log(f"{sym}：建議={pos.get('action')} add={pos.get('add_triggered')} reduce={pos.get('reduce_triggered')}")

            for trig_key, sig_type, enabled_key in (
                ("add_triggered", "add", "add"),
                ("reduce_triggered", "reduce", "reduce"),
            ):
                if not pos.get(trig_key):
                    continue
                if not signals.get(enabled_key, True):
                    continue
                if was_recently_notified(sym, sig_type, dedup_h):
                    log(f"  {sig_type} 訊號已於 {dedup_h}h 內通知過，跳過")
                    continue

                title, body = build_message(sym, sig_type, result)
                ok, detail = send(
                    body, topic, title=title,
                    priority="high" if sig_type == "reduce" else "default",
                    tags="warning" if sig_type == "reduce" else "bell",
                )
                if ok:
                    log_notification(sym, sig_type)
                    triggered_count += 1
                    log(f"  ✅ 已通知 {sig_type}")
                else:
                    log(f"  ❌ 通知失敗：{detail}")
        except Exception as e:
            log(f"{sym}：例外 {e}")
            log(traceback.format_exc())

    log(f"掃描完成，共發出 {triggered_count} 則通知")
    return 0


if __name__ == "__main__":
    sys.exit(main())
