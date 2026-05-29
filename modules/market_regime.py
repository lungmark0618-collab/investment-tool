"""Module G — 牛熊市判定

用大盤指數 vs MA200、VIX、52 週位置綜合判斷市場狀態，
產出資金配置乘數（逆向：恐慌時加碼、過熱時保留）。
"""
from typing import Optional, Dict, Any
import pandas as pd
from utils.data_fetcher import make_ticker

INDEX_TWII = "^TWII"   # 台灣加權
INDEX_SPX = "^GSPC"    # S&P 500
INDEX_VIX = "^VIX"     # 恐慌指數


def _fetch_index(symbol: str) -> Optional[pd.DataFrame]:
    try:
        t = make_ticker(symbol)
        hist = t.history(period="2y")
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


def _index_metrics(hist: pd.DataFrame) -> Dict[str, float]:
    close = hist["Close"]
    cur = float(close.iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else cur
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else cur
    high52 = float(close.tail(252).max())
    low52 = float(close.tail(252).min())

    return {
        "current": cur,
        "ma50": ma50,
        "ma200": ma200,
        "bias_ma200_pct": (cur - ma200) / ma200 * 100,
        "bias_ma50_pct": (cur - ma50) / ma50 * 100,
        "drawdown_52w_pct": (cur - high52) / high52 * 100,  # 負值 = 從高點下跌
        "position_52w_pct": (cur - low52) / (high52 - low52) * 100 if high52 > low52 else 50,
        "golden_cross": ma50 > ma200,
    }


def _classify_regime(spx: Dict, vix: float, twii: Optional[Dict] = None) -> Dict[str, Any]:
    """綜合判定市場狀態。"""
    spx_above_ma200 = spx["bias_ma200_pct"] > 0
    spx_dd = spx["drawdown_52w_pct"]
    twii_above_ma200 = (twii or {}).get("bias_ma200_pct", 0) > 0

    # 恐慌：VIX > 35 或 SPX 跌幅 > 25%
    if vix > 35 or spx_dd < -25:
        regime = "恐慌"
        budget_mult = 2.0
        color = "#9b59b6"
        desc = "極度悲觀，長線買進良機"
    # 熊市：SPX < MA200 且回跌 > 15% 或 VIX > 28
    elif (not spx_above_ma200 and spx_dd < -15) or vix > 28:
        regime = "熊市"
        budget_mult = 1.5
        color = "#e74c3c"
        desc = "下行趨勢，分批加碼累積"
    # 修正：回跌 5-15% 或 VIX 22-28
    elif spx_dd < -5 or vix > 22:
        regime = "修正"
        budget_mult = 1.2
        color = "#f39c12"
        desc = "短期回檔，可酌量加碼"
    # 過熱：SPX > MA200 15%+ 且 VIX < 15
    elif spx["bias_ma200_pct"] > 15 and vix < 15:
        regime = "過熱"
        budget_mult = 0.6
        color = "#e67e22"
        desc = "估值偏高，保留現金為主"
    # 牛市：SPX > MA200 且 VIX < 20
    elif spx_above_ma200 and vix < 20:
        regime = "牛市"
        budget_mult = 0.8
        color = "#2ecc71"
        desc = "多頭環境，按計畫定投"
    else:
        regime = "中性"
        budget_mult = 1.0
        color = "#3498db"
        desc = "方向未明，維持紀律"

    # 台股與美股分歧時微調
    if twii and (twii_above_ma200 != spx_above_ma200):
        desc += "（台美分歧，留意輪動）"

    return {
        "regime": regime,
        "budget_multiplier": budget_mult,
        "color": color,
        "description": desc,
    }


def analyze() -> Dict[str, Any]:
    """主入口：抓取大盤資料並判定市場狀態。"""
    spx_hist = _fetch_index(INDEX_SPX)
    vix_hist = _fetch_index(INDEX_VIX)
    twii_hist = _fetch_index(INDEX_TWII)

    if spx_hist is None or vix_hist is None:
        return {
            "available": False,
            "error": "無法取得大盤資料（^GSPC / ^VIX）",
        }

    spx = _index_metrics(spx_hist)
    vix_cur = float(vix_hist["Close"].iloc[-1])
    twii = _index_metrics(twii_hist) if twii_hist is not None else None

    classification = _classify_regime(spx, vix_cur, twii)

    return {
        "available": True,
        "spx": spx,
        "twii": twii,
        "vix": vix_cur,
        **classification,
    }
