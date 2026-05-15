"""股票名稱搜尋 — 支援英文名 / 代碼 / 部分台股中文名稱對應"""
from typing import List, Dict
import yfinance as yf

# 台股常見公司中文名 → 代碼 fallback（yfinance 中文搜尋不穩）
TW_NAME_ALIAS = {
    "台積電": "2330.TW", "台積": "2330.TW", "tsmc": "2330.TW",
    "聯發科": "2454.TW", "鴻海": "2317.TW", "富邦金": "2881.TW",
    "國泰金": "2882.TW", "中信金": "2891.TW", "兆豐金": "2886.TW",
    "玉山金": "2884.TW", "元大金": "2885.TW", "第一金": "2892.TW",
    "華南金": "2880.TW", "永豐金": "2890.TW", "合庫金": "5880.TW",
    "中華電": "2412.TW", "台達電": "2308.TW", "聯電": "2303.TW",
    "南亞": "1303.TW", "台塑": "1301.TW", "台化": "1326.TW",
    "中鋼": "2002.TW", "長榮": "2603.TW", "陽明": "2609.TW",
    "華航": "2610.TW", "長榮航": "2618.TW",
    "和泰車": "2207.TW", "裕隆": "2201.TW",
    "統一": "1216.TW", "大立光": "3008.TW",
    # ETF
    "元大台灣50": "0050.TW", "0050": "0050.TW",
    "高股息": "0056.TW", "元大高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續": "00878.TW",
    "00919": "00919.TW", "群益台灣精選高息": "00919.TW",
    "00929": "00929.TW", "復華台灣科技優息": "00929.TW",
    "00940": "00940.TW", "元大臺灣價值高息": "00940.TW",
}


def search_stocks(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """
    搜尋股票，回傳：[{symbol, name, exchange}, ...]
    支援：英文名、ticker 代碼、純數字（自動補 .TW）、部分中文公司名
    """
    q = query.strip()
    if not q:
        return []

    results: List[Dict[str, str]] = []
    seen = set()

    def add(sym: str, name: str, exch: str = ""):
        if sym and sym not in seen:
            seen.add(sym)
            results.append({"symbol": sym, "name": name or sym, "exchange": exch})

    # 1) 台股中文名/別名 fallback（先查，命中時直接放最前面）
    q_low = q.lower().strip()
    for alias, sym in TW_NAME_ALIAS.items():
        if alias.lower() == q_low or q_low in alias.lower():
            add(sym, alias, "TAI")

    # 2) yfinance Search（英文 / 代碼）
    try:
        s = yf.Search(q, max_results=limit * 2)
        for quote in s.quotes[:limit * 2]:
            sym = quote.get("symbol", "")
            name = quote.get("shortname") or quote.get("longname") or sym
            exch = quote.get("exchange", "")
            if sym:
                add(sym, name, exch)
            if len(results) >= limit:
                break
    except Exception:
        pass

    # 3) 若輸入是純數字 → 補一個 .TW 推測
    if q.isdigit() and 4 <= len(q) <= 6:
        sym = f"{q}.TW"
        if sym not in seen:
            add(sym, f"台股 {q}", "TAI")

    return results[:limit]
