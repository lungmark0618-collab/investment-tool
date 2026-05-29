import yfinance as yf
import pandas as pd
from typing import Optional, Tuple, Dict, Any


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    # Pure digits → assume Taiwan stock, append .TW
    if "." not in symbol and symbol.isdigit():
        return symbol + ".TW"
    return symbol


def _quote_ok(t: yf.Ticker) -> bool:
    """多重訊號確認標的存在。
    Yahoo 常對雲端/資料中心 IP 限流，使 .info 回空 dict，
    導致 TSLA 這種明明存在的代碼被誤判「找不到」。改用走不同端點的
    fast_info / 一小段 history 當後備，任一成功即視為有效。"""
    try:
        info = t.info
        if info and (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or info.get("navPrice")
        ):
            return True
    except Exception:
        pass
    try:
        fi = t.fast_info
        if fi and fi.get("lastPrice"):
            return True
    except Exception:
        pass
    try:
        h = t.history(period="5d")
        if h is not None and not h.empty:
            return True
    except Exception:
        pass
    return False


def fetch_ticker(symbol: str) -> Tuple[Optional[yf.Ticker], str]:
    """Return (Ticker, used_symbol) or (None, symbol) on failure."""
    raw = symbol.strip().upper()
    candidates = [normalize_symbol(symbol)]
    # 台股純數字：先 .TW（上市），抓不到再試 .TWO（上櫃/OTC）
    if "." not in raw and raw.isdigit():
        two = raw + ".TWO"
        if two not in candidates:
            candidates.append(two)
    if raw not in candidates:
        candidates.append(raw)

    for sym in candidates:
        try:
            t = yf.Ticker(sym)
            if _quote_ok(t):
                return t, sym
        except Exception:
            continue
    return None, symbol


def _ensure_price(info: dict, ticker: yf.Ticker, history: pd.DataFrame) -> dict:
    """info 被限流而缺價時，用 fast_info / history 收盤價補上 currentPrice，
    讓股價、快速下單、估值等下游不至於整片 N/A。"""
    if info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"):
        return info
    try:
        fi = ticker.fast_info
        lp = fi.get("lastPrice") if fi else None
        if lp:
            info["currentPrice"] = float(lp)
            if not info.get("currency"):
                info["currency"] = fi.get("currency", "") or ""
            return info
    except Exception:
        pass
    if history is not None and not history.empty:
        try:
            info["currentPrice"] = float(history["Close"].iloc[-1])
        except Exception:
            pass
    return info


def get_all_data(ticker: yf.Ticker) -> Dict[str, Any]:
    """Fetch all required data from yfinance in one call."""
    try:
        info = dict(ticker.info or {})  # copy 以便在限流時補價格
    except Exception:
        info = {}  # .info 被限流可能直接拋例外，不要讓整個分析掛掉
    try:
        history = ticker.history(period="5y")
    except Exception:
        history = pd.DataFrame()
    info = _ensure_price(info, ticker, history)
    is_etf = info.get("quoteType", "") in ("ETF", "MUTUALFUND")

    if is_etf:
        return {
            "info": info,
            "history": history,
            "income_stmt": pd.DataFrame(),
            "balance_sheet": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
            "is_etf": True,
        }

    try:
        income_stmt = ticker.income_stmt
    except Exception:
        income_stmt = pd.DataFrame()

    try:
        balance_sheet = ticker.balance_sheet
    except Exception:
        balance_sheet = pd.DataFrame()

    try:
        cashflow = ticker.cashflow
    except Exception:
        cashflow = pd.DataFrame()

    return {
        "info": info,
        "history": history,
        "income_stmt": income_stmt,
        "balance_sheet": balance_sheet,
        "cashflow": cashflow,
        "is_etf": False,
    }


def safe_float(val, default=None) -> Optional[float]:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_fx_rate(from_ccy: str, to_ccy: str) -> Optional[float]:
    """
    Return exchange rate: 1 unit of from_ccy = ? to_ccy.
    e.g. get_fx_rate("TWD", "USD") → ~0.031
    """
    if from_ccy == to_ccy:
        return 1.0
    pair = f"{from_ccy}{to_ccy}=X"
    try:
        t = yf.Ticker(pair)
        price = (
            t.info.get("regularMarketPrice")
            or t.info.get("previousClose")
            or t.fast_info.get("lastPrice")
        )
        if price:
            return float(price)
        hist = t.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None
